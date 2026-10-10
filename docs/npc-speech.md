# Constrained NPC speech and voice

`NativeNpcSpeechApplication` is a provider-neutral reference path for a model or
script controlling one NPC's utterance. It uses the real Warband one-turn
dialogue UI seam and can hand an observed utterance to the existing host voice
service.

The built-in `native-npc-dialogue` kind adds a persistent, host-fed conversation
loop around that same engine-observed response path. `native-npc-speech` remains
the unconstrained one-shot variant.

## Host lifecycle

```python
from bridge.native_npc_speech_app import NativeNpcSpeechApplication
from warband_agentic import VoiceDelivery, make_agent_server

application = NativeNpcSpeechApplication(
    store,
    "npc:trainer:scene-42",
    agent_id=7,
    event_log=semantic_event_log,
)

refresh_job = application.queue_observation_refresh()
# Drive Warband until the scene census command is acknowledged and complete.
turn = application.session.turn()

# Expose application.session through make_agent_server, or use it in-process.
# After an accepted utterance is observed in Warband:
speech = application.voice_request(
    "agent-request-id",
    "trainer.default",
    delivery=VoiceDelivery.PLAY_HOST,
)
voice_service.speak(speech)
```

Voice can instead remain synthesis-only or be sent through the authenticated
voice HTTP API. The voice profile is selected by trusted host policy, not by a
provider voice ID supplied to the game-facing agent.

Packaged hosts expose the same evidence-gated handoff without exposing the
application object:

```http
POST /v1/host/sessions/village-elder/voice-requests
Authorization: Bearer <operator-token>
Content-Type: application/json

{"action_request_id":"npc-turn:12","profile_id":"elder.calm","delivery":"play-host","speed":1.0}
```

The returned JSON is the exact provider-neutral request accepted by
`POST /v1/voice/speech`. The two services keep separate tokens and lifecycle
truth; callers may choose synthesis-only or host playback. A host-config v2
deployment can instead call `/voice-dispatches` at the same session path to have
the application host perform that authenticated relay and return the validated
terminal voice outcome.

For hands-free dialogue, an NPC session may declare a trusted host policy:

```json
{
  "automatic_voice": {
    "profile_id": "elder.calm",
    "delivery": "play-host",
    "speed": 1.0
  }
}
```

This requires the host-config v2 `voice` service. The profile, delivery and speed
come from configuration, never from the NPC agent. After Warband emits the
matching dialogue event and the action outcome is reconciled, the host queues one
asynchronous voice request correlated to that action. Repeated outcome polls do
not replay it. Queue, HTTP, synthesis or playback failure is reported only in
host diagnostics and cannot downgrade, promote or block the game outcome.

With a `SemanticEventLog`, restart recovery restores the exact action outcome and
private bridge command correlation without replay. A later Warband dialogue event
can still promote the recovered action to observed, and `voice_request()` can
recover the original bounded text from the durable bridge command.

## Persistent player-to-NPC loop

Configure a session with `"kind": "native-npc-dialogue"` and the same bounded
`agent_id` setting. After its normal scene-agent refresh completes, a trusted
local UI, speech-to-text adapter or test harness submits the player's line through
the authenticated operator listener:

```http
POST /v1/host/sessions/village-elder/utterances
Authorization: Bearer <operator-token>
Content-Type: application/json

{"utterance_id":"player-turn:12","text":"What happened to the caravan?"}
```

The NPC agent's next observation contains `dialogue.pending_utterance` and up to
eight completed player/NPC turn pairs in `memory.conversation`. No response
affordance exists without a pending player line, and only one response may be in
flight. A matching Warband dialogue event commits the response, after which the
next player line can be accepted.

A definitive rejected response keeps the player line pending and issues a fresh
response affordance, including after restart. Expired or interrupted responses
are not automatically retried because late engine evidence may still prove that
the original line appeared.

Player and observed NPC utterances are written to the semantic event log with
source-level idempotency. Restart reconstructs completed memory and an unresolved
turn without replaying speech. Utterance IDs reject conflicting reuse, player
text is limited to 500 printable characters, NPC text remains limited to 200,
and one session is capped at 64 player/NPC turns.

## Trust and evidence boundary

- A fresh engine census must contain the configured living, non-player agent in
  the current scene and mission session.
- The agent receives self-scoped facts and one `dialogue.speak` capability. It
  cannot choose another agent, lease, operation, scene or session.
- Text is limited to 1–200 printable characters and rejects protocol delimiters,
  braces, newlines and controls.
- The utterance is consequential because it is player-visible and cannot be
  retracted. It has no direct mechanical consequence.
- Queue insertion and command acknowledgement do not prove display. A matching
  Warband dialogue event is required for engine-observed evidence.
- A `SpeechRequest` can only be produced after that observed game outcome. Voice
  synthesis/playback success or failure never changes the dialogue outcome.

Every NPC response still uses the existing one-turn custom speech path with a
fixed Native return choice. The persistent loop does not yet provide an in-game
text-entry UI, speech recognition, remote execution of original Native choices,
NPC-to-NPC dialogue, long-term character memory or packaged-host proposal routes.
The separate [mechanical-proposal broker](mechanical-proposals.md) now provides
the exact-affordance and participant-acceptance core, but is not yet wired into
this application. Automatic voice begins only when an observed outcome is reconciled;
the host does not independently poll unreconciled agent actions. Its semantic
event outbox restores unfinished requests after application-host restart using
the same request ID. The current voice service's idempotency cache is not durable,
so simultaneous failure of both services during uncertain playback can replay
audio and is not described as audible exactly-once delivery.
