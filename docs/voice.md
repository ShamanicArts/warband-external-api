# Host voice API

Voice is an optional host-side application service. It is not game truth and does
not block, advance or roll back a dialogue turn. The initial concrete adapter uses
the user's local OpenAI-compatible Kokoro service; audio can remain synthesized or
play through the computer's PipeWire output. In-game audio injection is deferred.

## Start

1. Copy `config/voice.example.json` to a private local configuration and edit the
   named profiles. Agents see profile IDs, display names, locale and tags; they do
   not see provider voice IDs or adapter configuration.
2. Put a random token of at least 32 characters in a private token file.
3. Start the service:

```bash
uv run python -m warband_agentic.voice_server \
  --config /path/to/voice.json \
  --token-file /path/to/voice.token
```

The service binds only to `127.0.0.1:8870`. Kokoro must be reachable on the
configured loopback endpoint. `playback: "pipewire"` enables host playback;
`"disabled"` permits synthesis-only requests.

## API

All routes require `Authorization: Bearer <token>`.

- `GET /v1/voice/profiles` — safe named profiles.
- `POST /v1/voice/speech` — synthesize and optionally play.
- `GET /v1/voice/requests/{request_id}` — idempotent outcome lookup.
- `GET /v1/voice/events?after={sequence}` — lifecycle cursor.
- `GET /v1/voice/audio/{audio_id}` — bounded in-memory audio artifact.

Example request body:

```json
{
  "request_id": "speech:dialogue-event:42",
  "text": "Good day, sir.",
  "profile_id": "elder.calm",
  "delivery": "play-host",
  "speed": 1.0,
  "output_format": "wav",
  "correlation_id": "dialogue-event:42"
}
```

The request ID is idempotent within the running service. Reusing one with different
input is rejected rather than returning the wrong line's outcome. Synthesis and
playback failures are explicit `synthesis-failed` / `playback-failed` outcomes; a
playback failure can still retain successfully synthesized audio. Neither failure
changes the correlated game event. Concurrent duplicate request IDs synthesize
exactly once. Artifacts are memory-only and oldest-first bounded.

This is currently a synchronous service call: a speech POST returns after
synthesis and any requested host playback complete. Priority, interruption,
spatial rendering, dialogue-event wiring and restart recovery are not implemented.
