"""Tool-disabled OpenCode adapter for one constrained faction decision."""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

TASK_SCHEMA = "warband.agentic/provider-decision-task/v1"
RESULT_SCHEMA = "warband.agentic/subprocess-provider-result/v1"
_MAX_TASK_BYTES = 256 * 1024
_MAX_PROVIDER_BYTES = 2 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_TEXT = re.compile(r"[^\r\n\x00]{1,200}")


class AdapterError(RuntimeError):
    """A sanitized provider-wrapper failure safe to report on stderr."""


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise AdapterError(f"{label} fields do not match")


def _safe_text(value, label):
    if (
        not isinstance(value, str)
        or not _SAFE_TEXT.fullmatch(value)
        or not value.strip()
    ):
        raise AdapterError(f"{label} is invalid")
    return value


def _bounded_integer(value, label, *, minimum=0, maximum=1_000_000_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise AdapterError(f"{label} is invalid")
    return value


def load_task(stream, *, assignment_provider):
    encoded = stream.read(_MAX_TASK_BYTES + 1)
    if len(encoded) > _MAX_TASK_BYTES:
        raise AdapterError("task exceeds the input limit")
    try:
        value = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError("task is not valid JSON") from exc
    _exact(
        value,
        (
            "schema",
            "task_id",
            "batch_id",
            "epoch_id",
            "faction_id",
            "turn_set_sha256",
            "turn",
            "assignment",
            "budget",
        ),
        "task",
    )
    if value["schema"] != TASK_SCHEMA:
        raise AdapterError("task schema is unsupported")
    for field in ("task_id", "batch_id", "epoch_id"):
        _safe_text(value[field], field)
    _bounded_integer(value["faction_id"], "faction_id", maximum=999_999)
    if not isinstance(value["turn_set_sha256"], str) or not _SHA256.fullmatch(
        value["turn_set_sha256"]
    ):
        raise AdapterError("turn-set digest is invalid")
    if not isinstance(value["turn"], dict):
        raise AdapterError("turn is invalid")

    assignment = value["assignment"]
    _exact(assignment, ("provider", "model", "settings"), "assignment")
    if assignment["provider"] != assignment_provider:
        raise AdapterError("assignment provider does not match this adapter")
    _safe_text(assignment["model"], "model")
    settings = assignment["settings"]
    if not isinstance(settings, dict) or not set(settings).issubset({"variant"}):
        raise AdapterError("assignment settings are not supported")
    if "variant" in settings:
        _safe_text(settings["variant"], "variant")

    budget = value["budget"]
    _exact(
        budget,
        (
            "max_input_tokens",
            "max_output_tokens",
            "timeout_ms",
            "max_cost_microusd",
        ),
        "budget",
    )
    _bounded_integer(
        budget["max_input_tokens"], "input-token budget", minimum=1, maximum=1_000_000
    )
    _bounded_integer(
        budget["max_output_tokens"],
        "output-token budget",
        minimum=1,
        maximum=1_000_000,
    )
    _bounded_integer(
        budget["timeout_ms"], "timeout budget", minimum=1, maximum=3_600_000
    )
    if budget["max_cost_microusd"] is not None:
        _bounded_integer(
            budget["max_cost_microusd"],
            "cost budget",
            minimum=1,
            maximum=1_000_000_000_000,
        )
    return value


def build_prompt(task):
    compact = json.dumps(task, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return (
        "You are a constrained strategy decision function. Do not call tools, read "
        "files, browse, explain, or use markdown. Return exactly one JSON object with "
        "exactly these fields: request_id, affordance_token, arguments, "
        "expected_revision. request_id must equal the task_id. Choose only an issued "
        "affordance and copy its opaque token, bounded arguments, and the observation "
        "revision exactly. Here is the canonical task JSON:\n" + compact
    )


def _v1_agent_config():
    return {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": "warband-decision",
        "plugin": [],
        "agent": {
            "warband-decision": {
                "description": "Makes one bounded Warband strategy decision",
                "mode": "primary",
                "prompt": (
                    "Make exactly one decision from the supplied JSON. Never call "
                    "a tool. Emit only the requested JSON object."
                ),
                "tools": {"*": False},
            }
        },
    }


def _money_to_microusd(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AdapterError("provider cost receipt is invalid")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise AdapterError("provider cost receipt is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise AdapterError("provider cost receipt is invalid")
    return int((amount * Decimal(1_000_000)).quantize(Decimal(1), ROUND_HALF_UP))


def _token_receipt(value):
    if not isinstance(value, dict):
        raise AdapterError("provider token receipt is invalid")
    for field in ("input", "output"):
        _bounded_integer(value.get(field), "provider token receipt")
    reasoning = value.get("reasoning", 0)
    _bounded_integer(reasoning, "provider reasoning receipt")
    cache = value.get("cache", {})
    if not isinstance(cache, dict):
        raise AdapterError("provider cache receipt is invalid")
    cache_read = cache.get("read", 0)
    cache_write = cache.get("write", 0)
    _bounded_integer(cache_read, "provider cache receipt")
    _bounded_integer(cache_write, "provider cache receipt")
    return value["input"] + cache_read + cache_write, value["output"] + reasoning


def _parse_response_text(text, task):
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise AdapterError("provider response is not one JSON object")
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        response = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AdapterError("provider response is not valid JSON") from exc
    _exact(
        response,
        ("request_id", "affordance_token", "arguments", "expected_revision"),
        "provider response",
    )
    if response["request_id"] != task["task_id"]:
        raise AdapterError("provider response belongs to another task")
    _safe_text(response["affordance_token"], "affordance token")
    if not isinstance(response["arguments"], dict):
        raise AdapterError("provider response arguments are invalid")
    _bounded_integer(
        response["expected_revision"], "expected revision", maximum=2**63 - 1
    )
    context = task["turn"].get("observation", {}).get("context", {})
    revision = context.get("revision")
    if type(revision) is int and response["expected_revision"] != revision:
        raise AdapterError("provider response revision is stale")
    affordances = task["turn"].get("affordances")
    if isinstance(affordances, list):
        tokens = {
            item.get("token")
            for item in affordances
            if isinstance(item, dict) and isinstance(item.get("token"), str)
        }
        if tokens and response["affordance_token"] not in tokens:
            raise AdapterError("provider response uses an unknown affordance")
    return response


def parse_events(encoded, task):
    text_parts = []
    completed_text_parts = []
    input_tokens = 0
    output_tokens = 0
    cost_microusd = 0
    usage_count = 0
    for raw_line in encoded.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise AdapterError("provider emitted invalid event JSON") from exc
        if not isinstance(event, dict):
            raise AdapterError("provider emitted an invalid event")
        event_type = event.get("type")
        part = event.get("part")
        if event_type == "text" and isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        data = event.get("data")
        if event_type == "session.text.ended" and isinstance(data, dict):
            text = data.get("text")
            if isinstance(text, str):
                completed_text_parts.append(text)
        usage_container = None
        if event_type in ("step_finish", "step-finish") and isinstance(part, dict):
            usage_container = part
        elif event_type == "session.step.ended" and isinstance(data, dict):
            usage_container = data
        if usage_container is not None:
            tokens = usage_container.get("tokens")
            cost = usage_container.get("cost")
            received_input, received_output = _token_receipt(tokens)
            input_tokens += received_input
            output_tokens += received_output
            cost_microusd += _money_to_microusd(cost)
            usage_count += 1
    decision_parts = completed_text_parts or text_parts
    if not decision_parts:
        raise AdapterError("provider emitted no decision text")
    if usage_count == 0:
        raise AdapterError("provider emitted no usage receipt")
    response = _parse_response_text("".join(decision_parts), task)
    return {
        "schema": RESULT_SCHEMA,
        "response": response,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_microusd": cost_microusd,
        },
    }


def _model_ref(assignment):
    provider_id, separator, model_id = assignment["model"].partition("/")
    if not separator or not provider_id or not model_id:
        raise AdapterError("v2 model must use provider/model format")
    value = {"providerID": provider_id, "id": model_id}
    variant = assignment["settings"].get("variant")
    if variant is not None:
        value["variant"] = variant
    return value


def _run_process(argv, *, cwd, environment):
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                cwd=cwd,
                env=environment,
                shell=False,
            )
            return_code = process.wait()
        except OSError as exc:
            raise AdapterError("OpenCode process could not start") from exc
        size = os.fstat(output.fileno()).st_size
        if size > _MAX_PROVIDER_BYTES:
            raise AdapterError("OpenCode output exceeded its limit")
        if return_code != 0:
            raise AdapterError("OpenCode process returned a non-zero status")
        output.seek(0)
        return output.read()


def _api_call(executable, operation, data, *, params=None, cwd, environment):
    argv = [str(executable), "api", operation]
    for key, value in (params or {}).items():
        argv.extend(("--param", f"{key}={value}"))
    if data is not None:
        argv.extend(
            ("--data", json.dumps(data, allow_nan=False, separators=(",", ":")))
        )
    encoded = _run_process(argv, cwd=cwd, environment=environment)
    if not encoded.strip():
        return None
    try:
        return json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError("OpenCode emitted invalid command JSON") from exc


def _envelope_data(value, label):
    if not isinstance(value, dict) or "data" not in value:
        raise AdapterError(f"OpenCode {label} envelope is invalid")
    return value["data"]


def parse_v2_context(value, task):
    messages = _envelope_data(value, "context")
    if not isinstance(messages, list):
        raise AdapterError("OpenCode context is invalid")
    assistants = [
        item
        for item in messages
        if isinstance(item, dict) and item.get("type") == "assistant"
    ]
    if not assistants:
        raise AdapterError("OpenCode emitted no assistant decision")
    assistant = assistants[-1]
    content = assistant.get("content")
    if not isinstance(content, list):
        raise AdapterError("OpenCode assistant content is invalid")
    if any(isinstance(item, dict) and item.get("type") == "tool" for item in content):
        raise AdapterError("OpenCode attempted a tool call")
    text_parts = [
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    if not text_parts:
        raise AdapterError("OpenCode emitted no decision text")
    input_tokens, output_tokens = _token_receipt(assistant.get("tokens"))
    cost = assistant.get("cost")
    return {
        "schema": RESULT_SCHEMA,
        "response": _parse_response_text("".join(text_parts), task),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_microusd": None if cost is None else _money_to_microusd(cost),
        },
    }


def _best_effort_api(executable, operation, data, *, params=None, cwd, environment):
    try:
        _api_call(
            executable,
            operation,
            data,
            params=params,
            cwd=cwd,
            environment=environment,
        )
    except AdapterError:
        pass


def _run_v2(task, executable, directory, environment):
    session_id = None
    finished = False
    create = {
        "title": "Warband decision " + task["task_id"],
        "agent": "plan",
        "model": _model_ref(task["assignment"]),
        "location": {"directory": directory},
        "metadata": {"warband_task_id": task["task_id"]},
        "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
    }
    try:
        created = _envelope_data(
            _api_call(
                executable,
                "session.create",
                create,
                cwd=directory,
                environment=environment,
            ),
            "session-create",
        )
        if not isinstance(created, dict):
            raise AdapterError("OpenCode session-create result is invalid")
        session_id = _safe_text(created.get("id"), "OpenCode session ID")
        _api_call(
            executable,
            "session.prompt",
            {"text": build_prompt(task)},
            params={"sessionID": session_id},
            cwd=directory,
            environment=environment,
        )
        _api_call(
            executable,
            "session.wait",
            None,
            params={"sessionID": session_id},
            cwd=directory,
            environment=environment,
        )
        finished = True
        context = _api_call(
            executable,
            "session.context",
            None,
            params={"sessionID": session_id},
            cwd=directory,
            environment=environment,
        )
        return parse_v2_context(context, task)
    finally:
        if session_id is not None:
            if not finished:
                _best_effort_api(
                    executable,
                    "session.interrupt",
                    None,
                    params={"sessionID": session_id},
                    cwd=directory,
                    environment=environment,
                )
            _best_effort_api(
                executable,
                "session.remove",
                None,
                params={"sessionID": session_id},
                cwd=directory,
                environment=environment,
            )


def _run_v1(task, executable, directory, environment):
    config = _v1_agent_config()
    environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(
        config, separators=(",", ":"), sort_keys=True
    )
    Path(directory, "opencode.json").write_text(
        json.dumps(config, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    assignment = task["assignment"]
    argv = [
        str(executable),
        "--pure",
        "run",
        "--format",
        "json",
        "--agent",
        "warband-decision",
        "--model",
        assignment["model"],
        "--dir",
        directory,
    ]
    variant = assignment["settings"].get("variant")
    if variant is not None:
        argv.extend(("--variant", variant))
    argv.append(build_prompt(task))
    encoded = _run_process(argv, cwd=directory, environment=environment)
    try:
        return parse_events(encoded.decode("utf-8"), task)
    except UnicodeDecodeError as exc:
        raise AdapterError("OpenCode emitted non-UTF-8 output") from exc


def run_task(task, *, executable, dialect):
    executable_path = Path(executable).resolve()
    if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
        raise AdapterError("OpenCode executable is unavailable")
    child_environment = dict(os.environ)
    child_environment.update(
        {
            "OPENCODE_AUTO_SHARE": "false",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_PRUNE": "true",
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX": str(
                task["budget"]["max_output_tokens"]
            ),
        }
    )
    with tempfile.TemporaryDirectory(prefix="warband-provider-") as directory:
        if dialect == "v2":
            return _run_v2(task, executable_path, directory, child_environment)
        return _run_v1(task, executable_path, directory, child_environment)


def _parser():
    parser = argparse.ArgumentParser(
        description="Translate one Warband provider task through headless OpenCode"
    )
    parser.add_argument("--executable", required=True)
    parser.add_argument("--assignment-provider", default="opencode")
    parser.add_argument("--dialect", choices=("v2", "v1"), default="v2")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def cancel(_signum, _frame):
        raise AdapterError("adapter was cancelled")

    signal.signal(signal.SIGTERM, cancel)
    try:
        try:
            provider = _safe_text(args.assignment_provider, "assignment provider")
            task = load_task(sys.stdin.buffer, assignment_provider=provider)
            result = run_task(task, executable=args.executable, dialect=args.dialect)
        except (AdapterError, OSError, TypeError, ValueError) as exc:
            detail = (
                str(exc) if isinstance(exc, AdapterError) else "internal adapter error"
            )
            print(f"OpenCode adapter failed: {detail}", file=sys.stderr)
            return 1
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
    json.dump(
        result,
        sys.stdout,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
