# Hidden-workspace hardware-rendering acceptance

Accepted on 2026-10-10 with Warband 1.174, Proton 9.0 Beta, Hyprland 0.56.2,
CUA Driver 0.34.0 and an AMD Radeon RX 6600 XT.

The launcher was created on the inactive named workspace `warband-agent` by a
rule installed before Proton started. CUA used X11 background delivery to select
Play without focusing or exposing that workspace. The focused window before and
after the run was the same BB window on workspace 11.

`hardware-renderer-proof.json` is kernel DRM evidence, not an inference from an
environment variable. Warband PID 533531 owned AMD render node
`/dev/dri/renderD129`, and its `amdgpu` gfx-engine counter advanced by 5,512,877
ns between guard samples. The owned cgroup was continuously scanned for
`llvmpipe`, `softpipe`, `lavapipe` and `swrast`; none appeared.

The run used the explicit `wined3d` backend because Warband's launcher currently
stalls before creating a window or Vulkan device with DXVK. WineD3D was backed
by the AMD hardware DRM device; it was not software rendering.

Artifacts:

- `game-loading-screen.webp`: CUA capture from the automatically accepted run.
- `game-main-menu.webp`: CUA capture from the preceding bounded acceptance run.
- `hardware-renderer-proof.json`: game-PID AMD gfx-engine advancement.
- `session.json`: renderer, backend, workspace and before/after focus identity.
- `hyprland-events.log`: mapping/focus chronology with no Warband activation.

The transient service enforced `CPUQuota=200%`, `MemoryHigh=1500M`,
`MemoryMax=2G`, `TasksMax=192`, `Nice=10` and `KillMode=control-group`. Observed
peak memory was 1,574,871,040 bytes. The exact unit was stopped after capture;
all owned Wine descendants exited, the rule was removed and the workspace was
destroyed.
