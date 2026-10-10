# Installer-generated module boot acceptance

Accepted on 2026-10-10 from a fresh `warband-kit-install apply` output built from
the user's installed Native module. The temporary module folder was
`WarbandAgenticAcceptance`; `selected-module-launcher.webp` independently shows
that exact folder selected before CUA issued the background Play action.

The bounded hidden-workspace runner then captured a non-black loading frame and,
after a 30-second guarded hold, the fully loaded Warband main menu. The final
frame's mean luminance was 0.421459 against the 0.08 rejection threshold. User
focus was the same BB window before and after, and the Hyprland event log has no
Warband activation.

`hardware-renderer-proof.json` binds rendering to Warband PID 653565. Its AMD DRM
gfx counter advanced by 4,517,369 ns on `/dev/dri/renderD129`; no `llvmpipe`,
`softpipe`, `lavapipe` or `swrast` marker appeared. The transient service consumed
47.346 CPU seconds over 59.309 seconds wall time and peaked at 1.3 GB, within its
200% CPU and 2 GB memory caps. The command exited zero and left no Warband window,
process or transient unit.

Artifacts:

- `selected-module-launcher.webp`: exact installer-generated module selection;
- `loading-frame.webp`: first accepted rendered game frame;
- `main-menu.webp`: post-acceptance final frame after the guarded hold;
- `session.json`: lifecycle, focus, capture and cleanup state;
- `hardware-renderer-proof.json`: process-bound AMD DRM evidence;
- `cua-play.json`: background launcher action receipt;
- `cua-game-capture.json` and `cua-final-capture.json`: visual receipts;
- `hyprland-events.log`: hidden-workspace/focus chronology.

This proves fresh generated-module boot, not semantic runtime connectivity. The
generated host remained `waiting-for-game` because Warband does not poll from its
main-menu presentation. A later bounded exploratory background click highlighted
a menu item but did not activate it, so no tutorial, bridge telemetry or agent
interaction is claimed. The isolated prefix's prior `WarbandMCP` selection was
restored, the exact host window was stopped, and temporary module/private outputs
were moved to trash after evidence was retained.
