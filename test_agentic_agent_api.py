import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from warband_agentic import (
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    AuthorityClass,
    CapabilityDefinition,
    CapabilityRegistry,
    ConstrainedAgentSession,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    Fact,
    FactSource,
    GameEvent,
    LeaseBook,
    LeaseMode,
    ObservationEnvelope,
    ObservationFilter,
    RiskClass,
    RoleGrant,
    RoleId,
    SemanticEventLog,
    default_perception_policies,
    make_agent_server,
    to_wire,
)


class SessionHarness:
    def __init__(self, database, dispatcher_fails=False):
        self.revision = 7
        self.dispatches = []
        self.controller = ActorRef("controller:faction:1", ActorKind.SYSTEM)
        self.party = ActorRef("party:17", ActorKind.PARTY, 17)
        self.context = lambda: ContextRef(
            ContextKind.CAMPAIGN, "campaign:world", self.revision, None, 101
        )
        self.grant = RoleGrant(
            "private:grant:1",
            RoleId.FACTION_SOVEREIGN,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.PARTY_COMMAND),
            "faction.sovereign",
            ("party.strategy",),
            1000,
            2000,
        )
        self.leases = LeaseBook(lambda: "private:lease:17")
        self.lease = self.leases.acquire(
            self.controller,
            self.party,
            ("party.strategy",),
            LeaseMode.EXCLUSIVE,
            1000,
            2000,
        )
        tokens = iter(f"affordance:{index}" for index in range(20))
        self.registry = CapabilityRegistry(lambda: next(tokens), self.leases.resolve)
        self.registry.register(
            CapabilityDefinition(
                "party.issue-order",
                "Issue a bounded strategic party order",
                "party.strategy",
                AuthorityClass.PARTY_COMMAND,
                (ContextKind.CAMPAIGN,),
                {
                    "type": "object",
                    "properties": {
                        "order": {"type": "string", "enum": ("defend", "raid")}
                    },
                    "required": ("order",),
                    "additionalProperties": False,
                },
                RiskClass.REVERSIBLE,
                True,
                None,
                EvidenceLevel.ENGINE_OBSERVED,
                "private.party-order-handler",
                True,
            )
        )
        filters = ObservationFilter()
        for policy in default_perception_policies():
            filters.register(policy)
        self.log = SemanticEventLog(database)

        def observation():
            return ObservationEnvelope(
                f"canonical:{self.revision}",
                self.controller,
                RoleId.OPERATOR_FULL,
                self.context(),
                (
                    Fact(
                        "faction.name",
                        "Kingdom of Swadia",
                        FactSource.DEFINITION_METADATA,
                        self.revision,
                    ),
                    Fact(
                        "operator.secret",
                        417,
                        FactSource.ENGINE_OBSERVED,
                        self.revision,
                    ),
                ),
                (),
                1100,
            )

        def affordances(registry, grant, observed, now_ms):
            return (
                registry.issue(
                    "party.issue-order",
                    self.controller,
                    (self.party,),
                    observed.context,
                    grant,
                    now_ms,
                    1800,
                    {
                        "type": "object",
                        "properties": {"order": {"type": "string", "const": "defend"}},
                        "required": ("order",),
                        "additionalProperties": False,
                    },
                ),
            )

        def dispatch(validated):
            self.dispatches.append(validated)
            if dispatcher_fails:
                raise RuntimeError("backend disconnected")
            return ActionOutcome(
                validated.submission.action_id,
                ActionState.OBSERVED,
                validated.affordance.context,
                self.revision + 1,
                {"result": 0},
                (
                    Fact(
                        "parties.17.order",
                        "defend",
                        FactSource.ENGINE_OBSERVED,
                        self.revision + 1,
                    ),
                ),
                (
                    Evidence(
                        EvidenceLevel.ENGINE_OBSERVED,
                        "Warband party getter",
                        "Party order read back as defend",
                    ),
                ),
                None,
                1300,
            )

        self.session = ConstrainedAgentSession(
            "session:faction:1",
            self.grant,
            self.registry,
            filters,
            observation,
            affordances,
            dispatch,
            lambda affordance: self.lease.lease_id,
            self.log,
            clock_ms=lambda: 1200,
            action_id_factory=lambda request_id: f"action:{request_id}",
        )

    def request(self, request_id="request:1", token="affordance:0", revision=7):
        return {
            "request_id": request_id,
            "affordance_token": token,
            "arguments": {"order": "defend"},
            "expected_revision": revision,
        }

    def close(self):
        self.log.close()


class ConstrainedAgentSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.harness = SessionHarness(Path(self.temp.name) / "events.sqlite3")

    def tearDown(self):
        self.harness.close()
        self.temp.cleanup()

    def test_turn_filters_perception_and_hides_server_bindings(self):
        turn = self.harness.session.turn()
        repeated = self.harness.session.turn()
        self.assertIs(turn, repeated)
        wire = to_wire(turn)
        encoded = json.dumps(wire)
        self.assertEqual(wire["observation"]["role"], "faction.sovereign")
        self.assertIn("operator", wire["observation"]["omitted"])
        self.assertNotIn("operator.secret", encoded)
        self.assertNotIn("private.party-order-handler", encoded)
        manifest = json.dumps(self.harness.session.manifest())
        self.assertNotIn("private:grant", manifest)
        self.assertNotIn("private:lease", manifest)
        self.assertIn("turn.observation.context.revision", manifest)

    def test_trusted_application_can_invalidate_a_cached_turn(self):
        first = self.harness.session.turn()
        self.harness.session.invalidate_turn()
        refreshed = self.harness.session.turn()

        self.assertIsNot(first, refreshed)
        self.assertEqual(first.observation.context, refreshed.observation.context)
        self.assertNotEqual(first.affordances[0].token, refreshed.affordances[0].token)

    def test_manifest_explains_submission_binding_and_affordance_time(self):
        submission = self.harness.session.manifest()["submission"]
        self.assertEqual(
            submission["request_id"],
            {
                "type": "client_chosen_idempotency_key",
                "constraints": "1-200 printable characters",
                "retry_rule": (
                    "reuse only for an identical submission; use a new value "
                    "for changed intent"
                ),
                "example": "decision:epoch-12:party-17",
            },
        )
        self.assertEqual(
            submission["authorization"],
            {
                "source": "turn.affordances[]",
                "capabilities": (
                    "descriptive schemas only; capability presence does not "
                    "authorize an action"
                ),
            },
        )
        self.assertEqual(
            submission["arguments"],
            {
                "schema_source": "turn.affordances[].parameters",
                "required_properties_source": (
                    "turn.affordances[].parameters.required"
                ),
                "const_properties": "submit_the_exact_value",
            },
        )
        self.assertEqual(
            submission["affordance_time"],
            {
                "fields": ["issued_at_ms", "expires_at_ms"],
                "unit": "milliseconds",
                "clock": "session_runtime_clock",
                "client_rule": (
                    "treat_as_same_session_validity_metadata_and_fetch_a_fresh_"
                    "turn_after_expiry_or_conflict"
                ),
            },
        )

    def test_submission_injects_identity_and_lease_then_records_event(self):
        self.harness.session.turn()
        outcome = self.harness.session.submit(self.harness.request())
        self.assertIs(outcome.state, ActionState.OBSERVED)
        validated = self.harness.dispatches[0]
        self.assertEqual(validated.submission.actor, self.harness.controller)
        self.assertEqual(validated.submission.lease_id, "private:lease:17")
        self.assertEqual(self.harness.session.outcome("request:1"), outcome)
        page = self.harness.session.events()
        self.assertEqual(
            [event.event_type for event in page.events], ["action.observed"]
        )
        self.assertEqual(page.events[0].cause_action_id, "action:request:1")

    def test_request_id_is_idempotent_but_conflicting_reuse_is_rejected(self):
        self.harness.session.turn()
        first = self.harness.session.submit(self.harness.request())
        repeated = self.harness.session.submit(self.harness.request())
        self.assertIs(first, repeated)
        self.assertEqual(len(self.harness.dispatches), 1)
        changed = self.harness.request()
        changed["arguments"] = {"order": "raid"}
        with self.assertRaisesRegex(ValueError, "different input"):
            self.harness.session.submit(changed)

    def test_restart_recovers_lookup_and_idempotency_without_replay(self):
        database = Path(self.temp.name) / "events.sqlite3"
        self.harness.session.turn()
        original = self.harness.session.submit(self.harness.request())
        self.harness.close()
        self.harness = SessionHarness(database)

        self.assertEqual(self.harness.session.outcome("request:1"), original)
        self.assertEqual(self.harness.session.submit(self.harness.request()), original)
        self.assertEqual(self.harness.dispatches, [])
        changed = self.harness.request()
        changed["arguments"] = {"order": "raid"}
        with self.assertRaisesRegex(ValueError, "different input"):
            self.harness.session.submit(changed)
        public_events = json.dumps(to_wire(self.harness.session.events()))
        self.assertNotIn("request_hash", public_events)
        self.assertNotIn("_recovery", public_events)

    def test_old_action_history_blocks_unsafe_post_upgrade_replay(self):
        database = Path(self.temp.name) / "events.sqlite3"
        self.harness.log.append(
            GameEvent(
                0,
                "action.observed",
                self.harness.context(),
                (self.harness.party,),
                {
                    "agent_session_id": "session:faction:1",
                    "request_id": "legacy:1",
                    "capability": "party.issue-order",
                    "engine_result": {"result": 0},
                    "facts": [],
                    "reason": None,
                },
                Evidence(
                    EvidenceLevel.ENGINE_OBSERVED,
                    "older runtime",
                    "Action predates durable request recovery",
                ),
                1300,
                "action:legacy:1",
            ),
            "old-agent-action:1",
        )
        self.harness.close()
        self.harness = SessionHarness(database)
        self.harness.session.turn()

        with self.assertRaisesRegex(ValueError, "cannot be safely replayed"):
            self.harness.session.submit(self.harness.request("legacy:1"))
        with self.assertRaisesRegex(ValueError, "predates durable recovery"):
            self.harness.session.outcome("legacy:1")
        self.assertEqual(self.harness.dispatches, [])

    def test_stale_turn_and_client_owned_identity_fields_are_rejected(self):
        self.harness.session.turn()
        self.harness.revision = 8
        with self.assertRaisesRegex(ValueError, "active turn"):
            self.harness.session.submit(self.harness.request())
        raw = {**self.harness.request(), "actor": "player:0"}
        with self.assertRaisesRegex(ValueError, "fields"):
            self.harness.session.submit(raw)
        self.assertEqual(self.harness.dispatches, [])

    def test_dispatch_failure_becomes_interrupted_outcome(self):
        self.harness.close()
        self.harness = SessionHarness(
            Path(self.temp.name) / "failed.sqlite3", dispatcher_fails=True
        )
        self.harness.session.turn()
        outcome = self.harness.session.submit(self.harness.request())
        self.assertIs(outcome.state, ActionState.INTERRUPTED)
        self.assertIn("backend disconnected", outcome.reason)
        self.assertEqual(
            self.harness.session.events().events[0].event_type,
            "action.interrupted",
        )

    def test_event_cursor_does_not_leak_other_session_events(self):
        foreign = GameEvent(
            0,
            "secret.operator-event",
            self.harness.context(),
            (),
            {"agent_session_id": "session:operator", "secret": 417},
            Evidence(EvidenceLevel.ENGINE_OBSERVED, "engine", "private"),
            1100,
        )
        self.harness.log.append(foreign, "foreign:1")
        self.harness.session.turn()
        self.harness.session.submit(self.harness.request())
        page = self.harness.session.events()
        self.assertEqual(len(page.events), 1)
        self.assertNotIn("secret", json.dumps(to_wire(page)))
        self.assertEqual(page.high_watermark, 2)

    def test_concurrent_duplicate_dispatches_once(self):
        self.harness.session.turn()
        outcomes = []
        threads = [
            threading.Thread(
                target=lambda: outcomes.append(
                    self.harness.session.submit(self.harness.request())
                )
            )
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(outcomes), 4)
        self.assertEqual(len(self.harness.dispatches), 1)


class ConstrainedAgentHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.harness = SessionHarness(Path(self.temp.name) / "events.sqlite3")
        self.token = "a" * 64
        self.server = make_agent_server(self.harness.session, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.harness.close()
        self.temp.cleanup()

    def request(self, path, body=None, token=None):
        request = Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + (token or self.token),
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            finally:
                exc.close()

    def test_authenticated_http_turn_action_lookup_and_event_cursor(self):
        status, manifest = self.request("/v1/agent/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(manifest["role"], "faction.sovereign")
        _, turn = self.request("/v1/agent/turn")
        token = turn["affordances"][0]["token"]
        status, outcome = self.request(
            "/v1/agent/actions",
            self.harness.request(token=token),
        )
        self.assertEqual(status, 200)
        self.assertEqual(outcome["state"], "observed")
        _, lookup = self.request("/v1/agent/actions/" + quote("request:1", safe=""))
        self.assertEqual(lookup, outcome)
        _, events = self.request("/v1/agent/events?after=0&limit=10")
        self.assertEqual(events["events"][0]["event_type"], "action.observed")

    def test_http_auth_conflicts_and_loopback_guards(self):
        status, _ = self.request("/v1/agent/turn", token="wrong")
        self.assertEqual(status, 403)
        self.request("/v1/agent/turn")
        status, body = self.request(
            "/v1/agent/actions",
            self.harness.request(revision=6),
        )
        self.assertEqual(status, 409)
        self.assertIn("stale", body["error"])
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_agent_server(self.harness.session, self.token, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
