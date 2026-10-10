---
type: spec
status: draft
summary: Architecture and delivery contract for the Warband Agentic Modding Kit.
note_created: 2026-10-10
updated: 2026-10-10
---

# Warband Agentic Modding Kit

Status: **Draft**

Authors: Lucas (product direction), Codex (initial synthesis)
Purpose: define the durable architecture that turns the existing Warband MCP
integration into a releasable, provider-neutral agentic modding and scripting kit.

This document is intentionally broader than the current revision-15 Native
dialogue work. `MCP.md` remains the authority for observed capabilities and live
evidence; `IMPLEMENTATION.md` remains the running implementation/evidence map.
This spec defines where those increments are converging.

## 1. Vision and positioning

Warband should become an agent-native simulation and modding environment. Agents
must be able to observe bounded game state, discover actions they are currently
allowed to take, perform real game-backed actions, and observe their actual
consequences. The same substrate should support:

- full developer/operator control through MCP;
- constrained player-adjacent, NPC, party and faction agents;
- dynamic dialogue and optional voice applications;
- reproducible game-mechanics testing;
- multi-agent campaign experiments and faction benchmarks;
- third-party mods that expose additional mechanics without reimplementing the
  transport, persistence, authority or lifecycle machinery.

The kit is not an embedded chatbot and does not select an LLM provider. Dialogue,
voice, memory, faction policy and benchmark runners are consumers of the kit.

## 2. Core design principles

Priority order is significant.

1. **Game truth over agent narration.** An action is successful only when the
   game executes it and its required outcome evidence is observed.
2. **Real mechanics before state editing.** Normal-rule actions call Native or
   mod-authored mechanics. Administrative and debug interventions are separately
   named, authorized and reported.
3. **Least authority and legitimate perception.** An agent sees and controls only
   the actor, party, faction or test scope assigned to it.
4. **Affordances over guessed commands.** Context-scoped action descriptions are
   issued by the runtime and expire with the state that made them valid.
5. **Provider neutrality.** The runtime never assumes a particular model, memory
   service, speech engine or orchestration framework.
6. **Vanilla-safe by default.** The supported baseline uses compiled Warband game
   scripts plus authenticated loopback transport, not memory injection or desktop
   input masquerading as game control.
7. **Failure is data.** Rejections, interruptions, stale state and negative live
   experiments are preserved and cannot be promoted into capability claims.
8. **Mod authors should not handle protocol internals.** Registers, reserved troop
   slots, callback encoding and persistence belong behind the SDK boundary.
9. **MCP is an adapter.** The semantic runtime must also support restricted agent
   APIs, benchmark runners and future local transports.
10. **Evidence levels stay distinct.** Structural tests, bridge simulations,
    engine acknowledgements, engine facts and independent visual evidence are
    reported separately.

## 3. Product boundary

### 3.1 Pick: a kit with reference applications

**Pick:** ship a runtime, an extension SDK, adapters, reference applications and
a benchmark harness.

Why not:

- **One monolithic AI-NPC mod:** couples the infrastructure to one experience and
  one provider.
- **A flat collection of MCP tools:** becomes hard to secure, compose and explain
  as coverage grows.
- **A generic arbitrary-script endpoint:** destroys auditability and least
  authority.

### 3.2 Deliverables

1. **Agentic Runtime** — state, identities, roles, affordances, actions, outcomes,
   events, leases, persistence and recovery.
2. **Warband Extension SDK** — declarative registration and compiled adapters for
   explicit game-backed observations and actions.
3. **Protocol adapters** — full MCP, constrained MCP, and a stable local API for
   applications and benchmark runners.
4. **Reference applications** — Native dialogue, host-side voice, faction control
   and scenario testing.
5. **Benchmark suite** — seeded campaigns, standardized role views, decision
   epochs, scoring, transcripts and replay metadata.

## 4. Architecture at a glance

```text
Agent / test runner / dialogue app / voice app
                    |
       MCP, constrained MCP, local SDK/API
                    |
          Semantic Agentic Runtime
   identity | perception | affordances | actions
    leases  | outcomes   | events      | replay
                    |
         Capability and backend registry
                    |
     Vanilla compiled-script backend (default)
                    |
             Mount & Blade: Warband
```

An optional extended engine backend may be added later (§14, Q4), but must not
weaken the vanilla-safe contract or silently change how a capability is executed.

## 5. Semantic data model

### 5.1 Pick: versioned envelopes with stable IDs

**Pick:** all semantic messages use versioned envelopes and explicit identity,
context, game revision, provenance and evidence fields.

Why not:

- **Expose raw bridge dictionaries:** leaks transport accidents into every client.
- **Use display names as identity:** names are mutable, localized and ambiguous.
- **Infer current context from old Native globals:** existing live work proves
  those values are not authoritative context.

Core concepts:

- `ActorRef`: stable runtime identity plus game entity kind/ID.
- `RoleGrant`: actor/faction/test authority and perception policy.
- `ContextRef`: campaign, menu, trade, mission, dialogue or presentation session.
- `ObservationEnvelope`: bounded facts observed at a game revision.
- `Affordance`: an available action, parameters, risk, authority and expiry.
- `ActionSubmission`: selected affordance token plus arguments and expected
  revision.
- `ActionOutcome`: dispatch state, engine result, resulting facts and evidence.
- `GameEvent`: durable ordered change with cause, subject, scope and game time.
- `ControlLease`: exclusive or shared control of an actor/domain for a duration.

Every fact records whether it is engine-observed, definition metadata, inferred,
or application memory. Inference and model-authored memory are never game truth.

## 6. Observation and perception

### 6.1 Pick: policy-filtered observations

**Pick:** produce canonical internal observations, then filter them through the
active role's perception policy before delivery.

Why not:

- **Give every agent world census:** invalidates NPC/faction experiments and leaks
  hidden information.
- **Implement a separate exporter for every model:** duplicates game integration
  and produces inconsistent truth.

Initial policies:

- `observer.readonly`: explicitly selected datasets, no actions.
- `player.strategic`: player-visible campaign/menu/dialogue information.
- `npc.self`: the NPC, its scene/party, relationships and legitimately known
  events.
- `party.commander`: owned party, members, route, nearby threats and orders.
- `faction.sovereign`: faction resources, known settlements, controlled parties,
  diplomacy and reports.
- `test.director`: explicitly omniscient test state and administrative setup.
- `operator.full`: complete MCP development surface.

Policy output must state omitted/unknown data instead of fabricating defaults.

## 7. Affordances and actions

### 7.1 Pick: server-issued expiring affordance tokens

**Pick:** clients normally act through short-lived affordances generated for an
actor and context. Full operator MCP may retain typed direct tools for diagnosis.

Why not:

- **Let restricted agents submit operation names and IDs directly:** encourages
  guessed IDs and stale-context actions.
- **Let language-model text directly mutate mechanics:** confuses role-play with
  authorization and game truth.

An affordance contains:

- stable capability name and human description;
- actor, targets and authority class;
- typed parameter schema and bounded choices;
- context/session and expected game revision;
- expiry conditions;
- reversibility and consequence warning;
- required outcome/evidence contract.

The runtime resolves the token to a statically registered handler. The game
backend repeats context and argument validation immediately before mutation.

### 7.2 Mechanical proposals from dialogue

Generated dialogue may propose an intent such as recruitment, payment, travel or
diplomacy. The application must resolve it against current affordances and obtain
any required participant acceptance. Free text is never treated as execution.

The implemented core broker now binds an opaque proposal option to one exact
current affordance, delays proposal creation until the source dialogue is
engine-observed, records independent participant decisions and refuses stale
execution. The NPC application and packaged host expose the option through the
current speech affordance and provide trusted loopback listing, decision and
execution routes. Lifecycle snapshots are durable, while restart converts
unfinished authority to stale rather than rebinding it. Participant-specific
authentication and live consequence evidence remain application work.

## 8. Authority, control leases and multi-agent arbitration

### 8.1 Pick: explicit grants plus leases

**Pick:** roles grant possible authority; leases grant current control over an
actor, party, faction or subsystem.

Why not:

- **A global `world_control` boolean as the final model:** cannot distinguish NPC,
  faction, benchmark and administrative authority.
- **First request wins:** makes multi-agent runs nondeterministic and unsafe.

Rules:

- Actor/body control is exclusive unless a capability explicitly supports shared
  participation.
- Strategic faction control and subordinate party control may be hierarchical.
- Native AI resumes when an actor lease expires or is explicitly released.
- The test director may suspend roles only in an explicitly administrative
  scenario.
- Conflicting actions are rejected with the owning lease and expiry, not queued
  indefinitely.

## 9. Events, consistency and recovery

### 9.1 Pick: durable ordered event log

**Pick:** persist semantic events with a monotonically increasing runtime sequence,
game time, context, subjects, causative command and evidence source.

Why not:

- **Snapshots only:** agents cannot reliably attribute consequences or recover
  after disconnection.
- **Model-generated summaries as the log:** summaries lose mechanical facts and
  cannot support replay or benchmarks.

Actions use optimistic concurrency against an observation revision. Multi-step
exports identify whether they are atomic, page-consistent or independently timed.
Restart semantics retain the current conservative rule: uncertain mutations are
not replayed automatically. Late game acknowledgements may reconcile an
interrupted action, but clients must inspect outcomes before retrying.

## 10. Extension SDK

### 10.1 Pick: declarative capability definitions compiled into explicit handlers

**Pick:** expose a Python authoring API and build manifest that register capability
metadata alongside bounded compiled game operations.

Why not:

- **Ask authors to patch `game_receive_url_response` manually:** creates opcode,
  register and lifecycle collisions.
- **Runtime arbitrary bytecode:** unsafe and incompatible with capability review.
- **Require a bespoke MCP tool for every extension:** binds mods to one client
  protocol.

Each extension declares:

- identity, semantic version and compatibility requirements;
- observations/events supplied;
- actions, schemas, authority and valid contexts;
- compiled handler or reviewed Native/mod-script adapter;
- reserved storage/register requirements;
- outcome decoding and evidence expectations;
- whether the operation is normal, administrative or debug.

The builder detects conflicting IDs, slots, globals and patch seams before writing
output. Generated capability catalogs drive runtime discovery and adapter docs.

## 11. Dialogue and memory reference application

The reference application demonstrates the kit without becoming its core.

Required primitives:

- start and observe original game conversations;
- export current participants and original available choices;
- execute a session-scoped original choice;
- inject an explicitly agent-authored utterance through a registered dialogue
  extension;
- observe turn advancement and closure;
- associate character, faction, relationship, quest and recent-world context;
- allow agent-initiated and later NPC-to-NPC/group conversations;
- store provider-neutral application memory separately from game facts;
- convert proposed mechanical consequences into affordances (§7.2).

Original Native choice execution is the current implementation frontier. The
existing one-turn custom `npc_say` path and original Native entry remain distinct.

## 12. Voice interface

### 12.1 Pick: pluggable host-side voice service

**Pick:** define a provider-neutral local voice API. Audio may play through the
user's computer; in-game audio injection is optional and deferred.

Why not:

- **Bake one TTS engine into the mod:** blocks local/provider experimentation and
  complicates distribution.
- **Require Warband sound-resource injection for MVP:** unnecessary for an
  immersive working experience and materially harder to package.

The implemented first interface accepts:

- utterance ID and text;
- a public speaker/voice profile ID;
- delivery (`synthesize-only` or `play-host`), speed and output format;
- an optional correlation ID for dialogue/application events.

It emits ordered lifecycle events (`queued`, `synthesizing`, `ready`, `playing`,
`played`, `synthesis-failed`, `playback-failed`) and timing metadata. The current
adapter returns bounded WAV bytes retained in memory; a separate player optionally
owns host playback. Voice failure must never block or falsify the underlying
dialogue turn. Priority, interruption, style/emotion hints, spatial metadata and
durable artifact recovery are future protocol extensions, not current claims.

Credentials and provider configuration stay outside the game module and evidence
artifacts. The first adapter uses the user's loopback OpenAI-compatible Kokoro
`/v1/audio/speech` endpoint and optional PipeWire playback. The HTTP facade is
bearer-authenticated and refuses non-loopback binds. The packaged host can relay
an engine-observed dialogue utterance through a separately authenticated loopback
voice service, either by explicit trusted request or an asynchronous per-session
policy. Automatic delivery is deduplicated after outcome reconciliation, and
audio is not part of game truth.

## 13. Faction agents and benchmark harness

### 13.1 Pick: synchronized strategic decision epochs

**Pick:** pause at a campaign epoch, produce role-filtered faction observations,
collect bounded orders under equal budgets, commit non-conflicting actions, advance
a fixed amount of game time, then record outcomes.

Why not:

- **Let model response latency control game time:** gives faster providers a
  mechanical advantage.
- **Give every faction omniscient state:** measures hidden-information use rather
  than strategy.
- **Score a single campaign:** Warband simulation is stochastic.

The benchmark runner records:

- starting module/save hashes and scenario seed;
- model/provider/settings, budgets and timeouts;
- exact filtered observations and affordances;
- decisions, invalid/rejected actions and costs;
- resulting game events and periodic checkpoints;
- territory, settlement value, military strength, casualties, treasury,
  diplomacy, survival and scenario-specific objectives;
- enough metadata to replay decisions even when simulation timing is not bitwise
  deterministic.

Suites compare Native AI baselines, the same model across all factions, different
models per faction, and hierarchical faction-plus-lord agents. External model
testing requires a user-visible heads-up naming models, scope, expected cost/time
and evaluation before launch.

## 14. Backends and compatibility

### 14.1 Pick: vanilla-safe baseline with explicit backend identity

**Pick:** keep the current compiled-script/loopback HTTP backend as the required
baseline. Every capability reports its backend and evidence level.

Why not:

- **Replace it with memory injection:** abandons portability, auditability and the
  existing product value.
- **Use desktop automation as an invisible fallback:** makes mechanical claims
  untrustworthy.

CUA remains separate launch and visual-validation infrastructure unless a future
application explicitly requests desktop control and reports it as such. A future
WSE2/native backend may fill proven engine gaps, but capabilities must not silently
change backend or semantics.

Initial compatibility target is Warband 1.174 with a fresh Native-derived module.
Other mods require explicit seam/catalog compatibility work; Pendor remains out of
scope until separately authorized and must not be modified during Native work.

## 15. Testing and evidence

Every capability progresses through named levels:

1. `declared` — schema and handler registered.
2. `structural` — generated bytecode/parser and validation tests pass.
3. `bridge-simulated` — transport, persistence and malformed input are tested.
4. `engine-acknowledged` — actual game executed or rejected the command.
5. `engine-observed` — required resulting facts were independently read back.
6. `visually-verified` — separate capture confirms player-visible behavior where
   relevant.
7. `agent-usable` — one or more announced external agents successfully discover
   and use it without hidden operator knowledge.

Tests and docs must state the highest achieved level and known untested branches.
Model-based usability tests are investigation/review, not delegated code-writing.

## 16. Packaging, security and distribution

- Never distribute installed Native assets, compiled modules containing private
  tokens, saves or local credentials.
- Generate an isolated module from a user-owned Native installation.
- Bind plaintext game transport to loopback only.
- Separate build secrets from distributable catalogs/manifests.
- Provide diagnostics for module identity, integration revision, bridge identity,
  protocol version and extension compatibility.
- Package runtime, builder/SDK, schemas, MCP adapter and examples independently
  enough that applications do not import internal bridge classes.
- Add migration policy for protocol, database and extension schema versions.
- License original project code and documentation under MIT while preserving
  explicit third-party content and dependency boundaries.

## 17. Dependencies and licensing

| Dependency/input | Version | License/status | Verdict |
|---|---:|---|---|
| Python | >=3.11 | PSF | clean |
| MCP Python SDK | >=1.26,<2 | MIT | clean |
| Jujutsu | development-only | Apache-2.0/MIT | clean |
| Warband Native compiled files | user installation | proprietary game content | never redistribute |
| TaleWorlds ModSys definitions/reference | pinned 1.171 mirror | verify source terms | pending |
| Local voice provider | user supplied | unknown until adapter review | pending |
| Optional model providers | external services/models | provider-specific | quarantined from core |

The repository's original code and documentation are licensed under MIT. The
top-level `THIRD_PARTY_NOTICES.md` preserves the separate status of game content,
screenshots, external providers and the referenced ModSys definitions. A public
source repository does not by itself claim supported-release acceptance; the
remaining source-reference verdicts and live acceptance gates stay explicit.

## 18. Delivery phases

| Phase | Deliver | Explicitly deferred |
|---|---|---|
| 0. Current frontier | Native dialogue choice discovery/execution with exact session and consequence evidence | generative dialogue UX |
| 1. Semantic kernel | schemas, identities, roles, observations, affordances, outcomes and events over current capabilities | third-party extension stability |
| 2. Restricted agents | perception policies, grants, leases, constrained MCP/local API, agent-usability fixtures | public benchmarks |
| 3. Extension SDK | declarative capability registry, generated catalog, collision/seam checks, example extension | broad non-Native compatibility |
| 4. Dialogue reference | original choices, free-text application, memory boundary, mechanical proposals | group voice polish |
| 5. Voice reference | local provider adapter, host playback and lifecycle events | in-game audio injection |
| 6. Faction runtime | faction observations/actions, subordinate party ownership and synchronized epochs | every political mechanic |
| 7. Test/benchmark suite | seeded scenarios, checkpoints, scoring, transcripts and announced multi-model evaluations | deterministic simulation guarantee |
| 8. Public kit | packaging, migration, security, licensing, tutorials and compatibility matrix | unsupported engine promises |

Each phase extends the same semantic contracts. Shipping a phase does not imply
completion of the full-control backlog in `IMPLEMENTATION.md`.

## 19. Risk register

| Risk | Severity | Mitigation | Owner |
|---|---|---|---|
| Vanilla engine cannot expose a required interaction | high | retain evidence, provide honest unsupported affordance; evaluate explicit optional backend only after proof | Lucas/Codex |
| Builder/callback monolith becomes unmaintainable | high | capability registry, generated dispatch and extension collision checks | Codex |
| Agents exploit omniscient or administrative data | high | role perception policies, authority classes and benchmark audits | Codex |
| Acknowledgement is mistaken for outcome | high | required outcome/evidence contracts and capability levels | Codex |
| Native/mod assets or terms block distribution | high | generate locally, distribute no assets, maintain the third-party/license matrix before release | Lucas |
| Stale actions execute after context transition | high | expiring affordances, expected revisions and game-side session guards | Codex |
| Multi-agent races produce unfair benchmarks | medium | leases, synchronized epochs and deterministic arbitration rules | Codex |
| Voice/provider latency stalls gameplay | medium | asynchronous lifecycle, interruption policy and text-first fallback | Codex |
| Model benchmark cost becomes uncontrolled | medium | explicit pre-launch notice, budgets, dry runs and recorded costs | Lucas/Codex |
| Documentation overclaims broad capability | medium | generated capability matrix plus evidence levels | Codex |

## 20. Non-goals

- Human-equivalent twitch player control is not a release prerequisite.
- The core does not contain an LLM, prompt framework, memory policy or TTS model.
- The vanilla backend does not expose arbitrary bytecode, save editing or memory
  injection.
- A successful queue insertion or acknowledgement is never benchmark success.
- The kit does not promise compatibility with every total-conversion mod without
  explicit adaptation.
- Public release does not include Native assets, private tokens, test saves or
  copyrighted voice models.

## 21. Open questions

- **Q2 — Public name:** retain `Warband External API`, or release as `Warband
  Agentic Kit`/another name?
- **Q4 — Extended backend:** should WSE2/native extension support be an explicit
  post-vanilla target, or remain outside the initial kit?
- **Q5 — Local application API:** JSON-RPC, HTTP/WebSocket, or a Python-first SDK
  backed by the semantic schemas?
- **Q6 — Save/checkpoint policy:** which game-supported save operations are safe
  enough for automated scenario branching without blind save mutation?
- **Q7 — Faction perception:** which Native facts count as legitimate sovereign
  knowledge versus reports delayed by time/distance?
- **Q8 — First public milestone:** semantic kernel developer preview, dialogue
  demo, or faction benchmark preview?

## 22. Success criteria

The kit is ready for an initial public developer release when:

- a fresh Native installation can be transformed reproducibly without modifying
  Native or distributing its assets;
- applications consume versioned semantic contracts rather than bridge internals;
- at least one restricted NPC/party/faction role can discover and execute scoped
  affordances while denied operator-only actions and hidden facts;
- original dialogue choice execution and one provider-neutral generated dialogue
  path are demonstrated with mechanical outcome boundaries;
- a local voice adapter can speak dialogue through host playback without coupling
  dialogue correctness to audio success;
- one seeded faction scenario can run through synchronized decision epochs and
  produce a complete decision/event/cost transcript;
- capability discovery reports evidence level and limitations accurately;
- restart, stale context and interrupted-action recovery are documented and tested;
- a collated evidence report maps every material claim to tests, retained raw
  artifacts, its introducing revision and honest limitations, with short video
  clips for visually meaningful game interactions;
- licensing, packaging and secret-handling blockers are resolved.

## 23. Implementation kickoff checklist

- [x] Establish durable BB goal and model-testing notification rule.
- [x] Preserve current Jujutsu slice for Native dialogue-choice investigation.
- [x] Draft target architecture and product boundary.
- [x] Parse current Native conversation entries into a reviewed structural model.
- [x] Add catalog-validated durable evidence for engine-committed Native entries
      (live NPC-line/player-choice delivery and bridge-restart recovery verified).
- [ ] Determine the exact engine path, if any, for advancing a player dialogue
      choice without desktop input.
- [x] Define semantic schema package independently of HTTP/MCP representations.
- [x] Wrap two existing vertical paths as prototypes: engine/campaign observation
      and a session-scoped Native menu action.
- [x] Add role/grant and evidence-level capability discovery.
- [x] Define the versioned semantic event-log schema and migrate terminal commands
      plus committed Native dialogue history without upgrading legacy evidence.
- [ ] Migrate or explicitly retire the remaining domain-specific legacy result
      tables after defining their semantic event/outcome mappings.
- [x] Inspect the local voice system and implement its first adapter against §12
      (authenticated HTTP round trip and real Kokoro WAV synthesis verified;
      host playback available but deliberately not exercised during proof).
- [x] Build a deterministic restricted-agent usability fixture before launching
      announced external models; Luna, Muse and Grok passed the original run,
      and a corrective Pi/OpenCode Go run proved DeepSeek V4.1 Flash was also
      available and passed the revision-recovery fixture.
- [x] Add a Python-first constrained session and authenticated loopback API that
      keeps identity/lease/handler bindings private and filters session events.
- [x] Add explicit trusted Python extension registration with versioned
      declarations, collision checks, settings/ownership validation, scoped
      backend operations, host integration and exact-ID installed entry-point
      loading, plus exact module/host extension-version checks and bounded
      declarative generated ModSys handlers. Automatic loading, arbitrary handler
      composition and resource allocation remain open.
- [x] Add evidence-gated, scenario-defined faction metrics/scoring, a canonical
      multi-epoch run report, a fixed-clock paged campaign metric collector and a
      restart-safe non-blocking baseline-to-report orchestration harness. Live
      acceptance, game-save/process recovery and non-OpenCode provider wrappers
      remain open; equal-budget task/report-audit contracts, a bounded subprocess
      adapter, a tool-denied OpenCode v1/v2 wrapper, restart-safe runner API,
      preflight-gated live CLI and a check-only versioned benchmark plan are
      implemented.
- [ ] Complete the collated test/live/video evidence report before final handoff.
- [x] License the original project under MIT and document third-party boundaries;
      dependency/source attribution remains part of release review.
