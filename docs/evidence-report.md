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
| Host voice | live provider synthesis + two-service relay simulation | voice tests, `test_agent_host.py`, `evidence/voice/` | real PipeWire playback from an engine-observed dialogue turn remains unverified |
| Restricted agent interface | agent usable (fixture only) | `test_agentic_usability.py`, `evidence/agent-usability/` | simulated action; not live party control |
| Constrained session/API | production Store integration + restart simulation | `test_agentic_agent_api.py`, `test_native_menu_agent_app.py`, `test_native_faction_agent_app.py`, `test_native_npc_speech_app.py`, `docs/constrained-agent-api.md` | new records recover without replay; pre-recovery records are quarantined; multi-session hosting and broader domains pending |
| Faction reference application | bridge simulated over live-proven mechanics | `test_native_faction_agent_app.py`, `docs/faction-agent.md`, `evidence/campaign-world/` | new composition not yet live-tested; no live synchronized run or strategic scoring |
| Synchronized faction epoch | bridge simulated + coordinator restart simulation | `test_agentic_benchmark.py`, `test_campaign_epoch_driver.py`, `docs/faction-benchmarks.md` | frozen turns, committed actions and wait/stop commands resume without replay; no game-save recovery, live multi-faction run or external-model run yet |
| Faction scenario scoring/run report | structural | `test_agentic_scoring.py`, `warband_agentic/scoring.py`, `docs/faction-benchmarks.md` | evidence-gated bounded scoring and canonical reports proven; paused live metric collection and external-model run remain open |
| Campaign faction metric collector | bridge simulated | `bridge/test_campaign_metrics.py`, `bridge/campaign_metric_collector.py`, `docs/faction-benchmarks.md` | paged fixed-clock aggregation and drift refusal proven; no live collector run or atomic multi-page engine snapshot claim |
| Faction benchmark orchestration harness | structural composition + restart simulation | `bridge/test_faction_benchmark_harness.py`, `test_agentic_scoring.py`, `bridge/faction_benchmark_harness.py`, `docs/faction-benchmarks.md` | baseline through scored report plus atomic partial-provider receipt recovery proven with real epoch/scoring contracts and fake engine adapters; no live run or game-save/process recovery yet |
| Equal-budget provider decision audit | structural | `test_provider_decision_batch.py`, `warband_agentic/provider_decisions.py`, `test_agentic_scoring.py` | frozen equal caps, usage/cost receipts, timeout/error/no-decision handling and report-v2 binding proven; no concurrent external dispatch or model run yet |
| Subprocess provider adapters | local-process integration | `test_subprocess_provider.py`, `bridge/test_provider_adapter_config.py`, `bridge/test_opencode_provider_adapter.py`, `warband_agentic/subprocess_provider.py`, `bridge/opencode_provider_adapter.py`, `docs/provider-adapters.md` | concurrent dispatch, bounded result parsing, process-tree timeout cleanup, secret-safe config and tool-denied OpenCode v1/v2 translation proven with fake CLIs; no model/provider was invoked, and Cursor lacks usage receipts required by the equal-budget runner |
| Non-blocking benchmark runner | installed CLI structural proof + restart simulation | `bridge/test_benchmark_runner.py`, `bridge/test_benchmark_runtime_cli.py`, `test_benchmark_plan.py`, `bridge/benchmark_runner.py`, `docs/benchmark-runner.md` | validated plan-to-report sequencing, typed refresh waiting, automatic safe-state checkpoints, missing-only provider restart, hash-gated preflight and terminal cleanup proven with fake engine/provider adapters; no live game or external model run |
| Versioned faction benchmark plan | installed CLI structural proof | `test_benchmark_plan.py`, `bridge/benchmark_plan.py`, `config/benchmark.example.json`, `docs/benchmark-plan.md` | host/session/scenario/metric/budget/reproducibility validation and secret-free check output proven without side effects; command does not execute a live run |
| NPC speech application | bridge simulated over visually proven mechanic | `test_native_npc_speech_app.py`, `docs/npc-speech.md`, `evidence/scene-control/` | new composition and integrated voice handoff not yet live-tested; one-turn speech only |
| Persistent NPC dialogue | bridge simulated + durable restart/voice-relay simulation | `test_native_npc_speech_app.py`, `test_agent_host.py`, `docs/npc-speech.md` | bounded host-fed player turns, recovered memory and evidence-gated handoff/dispatch proven; no in-game input UI, policy-triggered dispatch or live integrated run yet |
| Python package, commands and guided installer | installed-wheel + synthetic rollback + real-Native apply/host-check + hardware-rendered generated-module boot | `test_packaging.py`, `test_installer.py`, `bridge/installer.py`, `docs/packaging.md`, `evidence/packaging/`, `evidence/runtime/installer-generated-boot/`, `pyproject.toml` | secret-free plan/receipt, private credentials, generated module/host/voice/MCP configuration, failure rollback and fresh module boot proven; no project license, automatic client registration or live semantic interaction from that fresh install yet |
| Packaged application host | loopback runtime + two-service voice simulation | `test_agent_host.py`, `docs/application-host.md`, `config/agent-host.example.json` | v1/v2 config, one NPC lifecycle/refresh and evidence-gated host playback relay exercised; no live game or multi-session runtime acceptance yet |
| Python extension SDK | installed-style CLI + loopback runtime simulation | `test_agentic_extensions.py`, `test_extension_discovery.py`, `test_agent_host.py`, `test_compiled_extensions.py`, `docs/extension-sdk.md` | explicit registration, exact-ID loading, custom-kind host lifecycle and compiled-operation Store wiring proven; no automatic loading or hot reload |
| Compiled extension operation | structural + bridge simulated | `test_compiled_extensions.py`, `module_system/test_build_mcp_module.py`, `warband_agentic/compiled_extensions.py` | one declaration drives bounded Store validation, opcode-1001 wire encoding and guarded `troop_add_gold` callback generation; no live engine acknowledgement or visual proof yet |
| Module/host extension compatibility | structural + CLI check | `module_system/test_build_mcp_module.py`, `test_agent_host.py`, `mcp-build.json` contract | exact ID/version and full compiled-operation contract mismatch refusal proven before side effects; same-version drift fails closed |
| GPU-safe live test harness | live hidden-workspace game + game-PID kernel DRM proof + luminance-gated initial/final CUA visuals | `test_warband_desktop_runner.py`, `test_gpu_safe_runner.py`, `evidence/runtime/desktop-gpu-safe/`, `evidence/runtime/installer-generated-boot/`, `evidence/runtime/gpu-probe.json` | one bounded command automatically finds its cgroup-owned launcher, issues background Play, rejects black frames, optionally holds guards through final capture, proves AMD hardware rendering and cleans up with no focus theft; DXVK still stalls before mapping |

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
llvmpipe. New clips must come from the bounded hidden-workspace runner and include
game-PID DRM proof; a hardware-rendered compositor around a launcher is not
sufficient. Headless Gamescope remains diagnostic because its private CUA route
cannot activate Play.
