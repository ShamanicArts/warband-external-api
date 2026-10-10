# Hidden-workspace hardware-rendering acceptance

Accepted on 2026-10-10 with Warband 1.174, Proton 9.0 Beta, Hyprland 0.56.2,
CUA Driver 0.34.0 and an AMD Radeon RX 6600 XT.

The launcher was created on the inactive named workspace `warband-agent` by a
rule installed before Proton started. The bounded runner automatically selected
only the exact launcher PID in its transient cgroup. CUA used X11 background
delivery to select Play without focusing or exposing that workspace. Hyprland's
event stream contains no Warband activation; the user moved between existing
Chrome and BB windows during the run without the game stealing focus.

`hardware-renderer-proof.json` is kernel DRM evidence, not an inference from an
environment variable. Warband PID 582253 owned AMD render node
`/dev/dri/renderD129`, and its `amdgpu` gfx-engine counter advanced by 4,649,587
ns between guard samples. The owned cgroup was continuously scanned for
`llvmpipe`, `softpipe`, `lavapipe` and `swrast`; none appeared.

The run used the explicit `wined3d` backend because Warband's launcher currently
stalls before creating a window or Vulkan device with DXVK. WineD3D was backed
by the AMD hardware DRM device; it was not software rendering.

Artifacts:

- `game-loading-screen.webp`: CUA capture from the automatically accepted run;
  mean luminance 0.385403 exceeded the 0.08 black-frame rejection threshold.
- `game-main-menu.webp`: CUA capture from the preceding bounded acceptance run.
- `cua-play.json`: exact owned PID/window target and background-delivery receipt.
- `cua-game-capture.json`: game-window capture receipt and luminance gate.
- `hardware-renderer-proof.json`: game-PID AMD gfx-engine advancement.
- `session.json`: renderer, backend, workspace and before/after focus identity.
- `hyprland-events.log`: mapping/focus chronology with no Warband activation.

The transient service enforced `CPUQuota=200%`, `MemoryHigh=1500M`,
`MemoryMax=2G`, `TasksMax=192`, `Nice=10` and `KillMode=control-group`. Observed
peak memory was 702.7 MB, with 15.193 CPU seconds over 29.481 seconds wall time.
The command exited zero after capture. The exact unit stopped all owned Wine
descendants (one stubborn helper required SIGKILL), the rule was removed and the
workspace was destroyed. No Warband process, client or transient unit remained.
