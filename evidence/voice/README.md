# Host voice evidence

`live-kokoro-http.json` records the live authenticated API round trip through the
local Kokoro adapter. The outcome, event cursor and retained audio were retrieved
through separate routes. Delivery was deliberately synthesis-only, so this proves
real WAV generation and retrieval but not audible PipeWire playback.
