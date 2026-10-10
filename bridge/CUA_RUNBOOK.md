# GPU-safe hidden-workspace Warband through CUA

> **Never launch Warband on Xvfb.** The retired `:97` setup rendered through
> llvmpipe and consumed roughly ten CPU cores. It is incident history, not a
> usable fallback.

The preferred interactive boundary is desktop XWayland on an inactive Hyprland
workspace named `warband-agent`. `bridge/warband_desktop_runner.py` installs a
runtime-only named rule before Proton starts. It assigns every
`steam_app_48700` window to that workspace silently, denies initial/activation
focus, and removes the rule during teardown. Normal user launches are
unaffected.

The runner owns Proton in a transient user service and continuously scans the
exact service cgroup and logs for `llvmpipe`, `softpipe`, `lavapipe` and
`swrast`. Any match aborts the owned control group. It also aborts if a Warband
window leaves the agent workspace, becomes active, or makes the workspace
visible.

Current limits are:

- `CPUQuota=200%`
- `MemoryHigh=1500M`, `MemoryMax=2G`
- `TasksMax=192`
- `Nice=10`
- five-minute wall-clock limit and five-second teardown
- `KillMode=control-group`

## Run on the hidden desktop workspace

The currently proven Warband 1.174 path uses WineD3D over AMD's hardware GL
stack. This is not software rendering: acceptance requires live Linux DRM
accounting from the Warband window PID. DXVK remains available as the preferred
backend, but on this installation both tested Proton verbs stall before a
window or Vulkan device is created. A matching DXVK DLL hash alone is not a
working run.

The log directory must not exist before launch:

```bash
run_dir=$(mktemp -u /tmp/warband-desktop-safe.XXXXXX)
python bridge/warband_desktop_runner.py run \
  --graphics-backend wined3d \
  --prefix /tmp/shuvcode/warband-cua/compatdata \
  --auto-play \
  --post-acceptance-seconds 30 \
  --log-dir "$run_dir"
```

The command discovers only the exact `steam_app_48700` launcher PID owned by its
transient cgroup. It captures that window, sends Play through CUA background
delivery, waits for game-PID AMD DRM activity, and captures the resulting game
window. ImageMagick is used to reject technically valid but visually black
transition frames. Once all acceptance gates pass, the runner tears down its
exact cgroup and exits zero.

The CUA session label defaults to a value unique to the outer runner process, so
completed daemon sessions are never accidentally reused. A positive
`--post-acceptance-seconds` keeps every safety guard active for that additional
bounded interval and writes `game-final.png` plus `cua-final-capture.json` before
teardown. `session.json` retains the exact resource limits plus cgroup-v2 CPU
seconds, memory peak and PID peak before the transient unit disappears. Use zero
when the first non-black rendered frame is sufficient.

For manual diagnostics only, omit `--auto-play`, then inspect the launcher in a
second terminal through the existing X11 CUA daemon:

```bash
cua-driver-main call list_windows \
  '{"session":"warband-hidden"}' \
  --socket ~/.cache/cua-driver/cua-driver-x11.sock
```

Capture the exact returned PID/window ID, verify that it belongs to the transient
service, then use a background click on Play. Do not use foreground delivery.
Play is approximately `(150, 212)` in the tested 640x480 launcher, but use a
fresh capture ID.

Success is not the CUA acknowledgement. It requires all of:

- a 1600x919 game window still on `warband-agent`;
- unchanged user focus and no Warband `activewindow` event;
- `hardware-renderer-proof.json` showing that the game PID's `amdgpu`
  gfx-engine counter increased on `/dev/dri/renderD129`;
- no software-renderer marker in the owned cgroup or logs;
- a CUA capture whose mean luminance passes the non-black game-frame gate.

Background input beyond the launcher has an explicit current boundary. A fresh
2026-10-10 run reached the main menu and changed `Play Tutorial` into its yellow
hover state through exact-window background delivery, but background Enter and
double-click produced byte-identical frames and no bridge connection. Do not
repeat blind clicks or escalate to foreground delivery. The retained proof is in
`evidence/runtime/background-input-boundary/`.

The accepted 2026-10-10 artifacts are in
`evidence/runtime/desktop-gpu-safe/`.

## Hardware probe without Warband

This checks the AMD compositor path without launching the game:

```bash
nice -n 10 python bridge/gpu_safe_runner.py probe \
  --json-out evidence/runtime/gpu-probe.json
```

The proof must name `AMD Radeon RX 6600 XT (RADV NAVI23)`, establish the
headless backend and start private Xwayland. A missing physical device or any
software-renderer marker is a hard failure.

## Legacy private-Gamescope diagnostic

Headless Gamescope remains useful for isolated launcher capture, but CUA cannot
activate Play there. It is not the gameplay acceptance route.

```bash
run_dir=$(mktemp -d /tmp/warband-gpu-safe.XXXXXX)
nice -n 10 python bridge/gpu_safe_runner.py run \
  --width 800 --height 600 --fps 30 --max-runtime 120 \
  --log-dir "$run_dir" -- \
  python bridge/warband_gpu_supervisor.py --graphics-backend wined3d
```

The supervisor refuses `DISPLAY=:0` and requires the private-display marker.
It starts its own CUA daemon against private X11. Do not enable native Wayland
or Gamescope's `--expose-wayland`; testing showed portal capture could expose
the host desktop.

Warband 1.174 has no general command-line launcher bypass. Static analysis found
only the `-sm` debug/module-system option; `-m WarbandMCP` remained in the
launcher. Play changes state within the same process.

## Evidence and cleanup

Retain the session lifecycle, hardware proof, Hyprland event log, aggregate
CPU/RSS samples and CUA captures for every claimed interaction. After a run,
verify that no exact owned process or transient unit remains. Never kill broad
Wine, Steam, Gamescope or CUA process sets because other agents may own them.
If the outer waiter is interrupted, resolve and stop only its exact transient
unit.

The old Xvfb/Openbox commands and software-rendered screenshots are deliberately
omitted. They proved interaction but not an acceptable runtime and must not be
revived.
