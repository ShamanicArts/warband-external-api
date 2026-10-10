# Living evidence report

This is the index for the final test/live/video handoff. It is intentionally not
marked complete while major dialogue, faction-runtime, packaging and acceptance
work remains. A command acknowledgement is never listed as outcome proof unless
separate engine facts support it.

| Area | Highest current evidence | Tests / raw proof | Honest boundary |
|---|---|---|---|
| Native menu actions and recruitment | visually verified | `test_agentic_adapters.py`, `evidence/native-actions/` | selection attempts still rely on Native conditions |
| Battle formation orders | engine observed + visual | `bridge/test_battle_control.py`, `evidence/battle-orders/` | no battle-success claim |
| NPC movement/combat adapters | engine observed + visual | `bridge/test_scene_control.py`, `evidence/scene-control/` | player held attack remains ineffective |
| Faction diplomacy / NPC party travel | engine observed + visual | `bridge/test_world_control.py`, `evidence/campaign-world/` | unrestricted player travel remains open |
| Goods trade | engine observed + visual | `bridge/test_market_control.py`, `evidence/goods-trade/` | bounded proven transaction forms only |
| World encounters and departures | engine observed + visual | bridge control tests, `evidence/world-encounters/`, `evidence/*-departure/` | setup and consequences are separated |
| Original Native dialogue entries | engine observed + visual | dialogue parser/bridge tests, `evidence/native-dialogue/` | remote original-choice execution remains open |
| Semantic contracts / roles / leases | structural | `test_agentic_contracts.py`, `test_agentic_capabilities.py`, `test_agentic_authority.py` | runtime kernel, not a new game capability |
| Durable semantic events | bridge simulated + live migration | `test_agentic_events.py`, `evidence/semantic-events/` | remaining domain result tables are not migrated |
| Host voice | live provider synthesis | voice tests, `evidence/voice/` | host playback and dialogue wiring not yet exercised |
| Restricted agent interface | agent usable (fixture only) | `test_agentic_usability.py`, `evidence/agent-usability/` | simulated action; not live party control |
| Constrained session/API | bridge simulated | `test_agentic_agent_api.py`, `docs/constrained-agent-api.md` | production bridge application and restart outcome recovery pending |
| GPU-safe live test harness | physical-GPU probe + live private launcher capture | `test_gpu_safe_runner.py`, `test_warband_gpu_supervisor.py`, `evidence/runtime/gpu-probe.json`, `evidence/runtime/gpu-safety-validation.json` | launcher capture is safe; unattended Play and game-process GPU proof remain open |

## Video ledger

No final evidence clips have been recorded yet. At final acceptance, short clips
must be captured from the isolated Warband runtime for interactions where motion,
UI state or event sequence matters: dialogue turns, NPC control/release, faction
orders and consequences, trade, travel/encounters, restart recovery where visible,
and the integrated voice/dialogue demonstration. Structured JSON/SQLite/test proof
remains primary for policy filtering, idempotency and persistence.

Each final clip entry must include the recorded action, before/after state, raw
artifact links, introducing Jujutsu change ID, capture method and any setup done by
CUA. Videos must not imply that CUA performed the claimed agentic mechanic.

The retired Xvfb evidence is not acceptable final footage because Warband used
llvmpipe. New clips must come from the bounded Gamescope harness and must include
game-process hardware proof; a hardware-rendered compositor around a launcher is
not sufficient.
