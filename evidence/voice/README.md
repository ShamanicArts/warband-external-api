# Host voice evidence

`live-kokoro-http.json` records the live authenticated API round trip through the
local Kokoro adapter. The outcome, event cursor and retained audio were retrieved
through separate routes. Delivery was deliberately synthesis-only, so this proves
real WAV generation and retrieval but not audible PipeWire playback.

`automatic-host-relay-simulation.json` records the deterministic two-service
acceptance exercised by `test_agent_host.py`: a protocol-2 Store reports an NPC
dialogue event, outcome reconciliation queues one configured `play-host` request,
the authenticated voice service returns `played`, and a repeated outcome lookup
does not replay it. The bridge/game side and audio player are test doubles; this
is not live Warband or audible PipeWire evidence.
