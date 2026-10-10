# Hidden-workspace background-input boundary

Accepted as a negative capability boundary on 2026-10-10 against a fresh
installer-generated `WarbandAgenticSemanticAcceptance` module. Warband ran in
the guarded inactive workspace through WineD3D on the AMD RX 6600 XT. The AMD
DRM gfx counter for the owned game PID advanced by 3,852,391 ns, no software
renderer marker appeared, and the runner retained its 200% CPU / 2 GB memory
limits until teardown.

CUA targeted the exact owned 1600x919 Warband window with background-only X11
delivery. A click at the freshly captured `Play Tutorial` coordinate changed the
text from black to yellow, proving the target and coordinate translation were
correct. Background Enter and background double-click were then acknowledged,
but the post-action frames were byte-identical and the generated host remained
`waiting-for-game`; port 8890 never opened. Warband therefore accepts unfocused
pointer motion/hover but does not activate this custom-drawn menu through the
available unfocused XSendEvent route.

No foreground input was attempted. The Hyprland event log contains no Warband
activation event. The focus identities differ at the beginning and end because
the user changed their own active application during the 148-second run; neither
identity is Warband.

Artifacts:

- `menu-ready.webp`: main menu before the bounded action;
- `play-tutorial-hover.webp`: exact post-click hover state; the Enter,
  double-click and final captures had the same SHA-256 as this frame;
- `background-input-actions.json`: targets, delivery routes and verified
  outcomes;
- `hardware-renderer-proof.json`: process-bound AMD DRM evidence;
- `session.json`: runner lifecycle and cleanup state;
- `hyprland-audit.json`: aggregate compositor audit with zero Warband
  activation or hidden-workspace selection; the raw stream was intentionally
  discarded because it also contained unrelated user and agent window titles.

This does not prove semantic runtime connectivity from a fresh install. It
rules out more blind background clicking as a useful path and preserves the
focus-safety boundary.
