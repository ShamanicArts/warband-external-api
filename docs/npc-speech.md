# Constrained NPC speech and voice

`NativeNpcSpeechApplication` is a provider-neutral reference path for a model or
script controlling one NPC's utterance. It uses the real Warband one-turn
dialogue UI seam and can hand an observed utterance to the existing host voice
service.

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

With a `SemanticEventLog`, restart recovery restores the exact action outcome and
private bridge command correlation without replay. A later Warband dialogue event
can still promote the recovered action to observed, and `voice_request()` can
recover the original bounded text from the durable bridge command.

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

This is the existing one-turn custom speech path with a fixed Native return
choice. It is not arbitrary player free text, a persistent conversation loop,
remote execution of original Native choices, NPC-to-NPC dialogue, memory, or a
mechanical-proposal system.
