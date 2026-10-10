# Deterministic faction arena

The deterministic faction arena is a model-ready, two-faction acceptance
fixture for the agentic contracts. It lets independent agents make one bounded
strategic decision each from private, role-filtered observations, then resolves
both decisions simultaneously and emits a canonical scored report.

This is not a live Warband run. The arena uses a deterministic simulator so the
same submitted decisions always produce the same state transition. It exercises
the production authority, observation, affordance, synchronized-epoch,
provider-audit and evidence-gated scoring contracts without claiming that the
result happened in the game engine.

## Export private turns

Export the public briefing and both private faction tasks:

```bash
uv run warband-faction-arena export
```

Export only one faction's task for delivery to its assigned model:

```bash
uv run warband-faction-arena export --faction 15
uv run warband-faction-arena export --faction 16
```

Each task contains exact facts about the controlled faction, a coarse inferred
band for the opponent and three exact-session affordances: attack, defend or
recruit. It does not disclose the opponent's exact military strength or private
task. Affordance tokens, required `const` arguments and the current revision are
authoritative; the descriptive capability schema is not a license to invent
other actions.

## Public resolution rules

Both decisions are committed before either is resolved.

- Recruit spends 20 supply and adds 15 military strength before attacks.
- Attack costs the attacker 10 military strength.
- An undefended target loses 20 military strength and one settlement.
- A defended target loses 5 military strength and no settlement.
- Both factions may attack, defend or recruit in the same epoch.

The arena advances the deterministic campaign clock by one hour after resolving
the epoch. Rankings are based on evidence-gated settlement, military-strength
and survival metrics.

## Resolve decisions

Create a JSON object keyed by faction ID. Each value is the bounded response
returned for that faction:

```json
{
  "15": {
    "request_id": "swadia-epoch-1",
    "affordance_token": "<token from faction 15 task>",
    "arguments": {"action": "attack", "target_id": 1},
    "expected_revision": 1
  },
  "16": {
    "request_id": "vaegirs-epoch-1",
    "affordance_token": "<token from faction 16 task>",
    "arguments": {"action": "recruit", "target_id": 600},
    "expected_revision": 1
  }
}
```

Resolve it with:

```bash
uv run warband-faction-arena resolve decisions.json
```

## Bind provider identity and usage

`resolve-providers` accepts a provider-result envelope so the canonical report
records which model controlled each faction, its declared generation settings and
the measured usage receipt:

```json
{
  "15": {
    "assignment": {
      "provider": "example-provider",
      "model": "example-model-a",
      "settings": {"temperature": 0}
    },
    "response": {
      "request_id": "swadia-epoch-1",
      "affordance_token": "<token>",
      "arguments": {"action": "attack", "target_id": 1},
      "expected_revision": 1
    },
    "usage": {
      "input_tokens": 1000,
      "output_tokens": 100,
      "elapsed_ms": 2400,
      "cost_microusd": null
    }
  },
  "16": {
    "assignment": {
      "provider": "example-provider",
      "model": "example-model-b",
      "settings": {"temperature": 0}
    },
    "response": {
      "request_id": "vaegirs-epoch-1",
      "affordance_token": "<token>",
      "arguments": {"action": "defend", "target_id": 1},
      "expected_revision": 1
    },
    "usage": {
      "input_tokens": 1000,
      "output_tokens": 100,
      "elapsed_ms": 2400,
      "cost_microusd": null
    }
  }
}
```

```bash
uv run warband-faction-arena resolve-providers provider-results.json
```

Both assignments are constrained by the same public decision budget: 8,192
input tokens, 512 output tokens and 120 seconds wall time. The audit rejects
missing factions and over-budget usage instead of silently scoring an unequal
run. Freeze model assignments before dispatch with the full benchmark plan and
runner when predeclared assignment enforcement is required.

The current fixture is deliberately one epoch. Persistent campaigns,
cross-epoch memory and a live synchronized Warband run remain later acceptance
work.
