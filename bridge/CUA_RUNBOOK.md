# GPU-safe off-screen Warband through CUA

> **Never launch Warband on Xvfb.** The retired `:97` setup rendered through
> llvmpipe and consumed roughly ten CPU cores. It is incident history, not a
> usable fallback.

The supported test boundary is headless Gamescope pinned to the AMD RX 6600 XT.
Gamescope creates a private Xwayland display, so Warband does not map a window
on the user's Hyprland desktop. A transient user service imposes CPU, memory,
task and wall-clock limits. The runner continuously scans its owned process tree
and logs for `llvmpipe`, `softpipe`, `lavapipe` and `swrast`; any match aborts
the entire owned control group.

Current default limits are:

- `CPUQuota=250%`
- `MemoryHigh=2G`, `MemoryMax=3G`
- `TasksMax=256`
- `Nice=10`
- 15-minute wall-clock limit, with bounded five-second teardown

The unit preserves the caller's working directory and uses
`KillMode=control-group`, so detached Wine, CUA or Gamescope descendants cannot
outlive a completed run.

## Prove the compositor path

This check does not launch Warband:

```bash
nice -n 10 python bridge/gpu_safe_runner.py probe \
  --json-out evidence/runtime/gpu-probe.json
```

The proof must name `AMD Radeon RX 6600 XT (RADV NAVI23)`, establish the
headless backend and start a private Xwayland display. A missing physical device
or any software-renderer marker is a hard failure.

## Observe the launcher safely

Create a fresh log directory and start a bounded launcher-only session:

```bash
run_dir=$(mktemp -d /tmp/warband-gpu-safe.XXXXXX)
nice -n 10 python bridge/gpu_safe_runner.py run \
  --width 800 --height 600 --fps 30 --max-runtime 120 \
  --log-dir "$run_dir" -- \
  python bridge/warband_gpu_supervisor.py --graphics-backend wined3d
```

The supervisor refuses `DISPLAY=:0` and requires the private-display marker set
by the verified runner. It starts CUA against private X11 only: host Wayland is
removed from CUA's environment. Do not enable native Wayland or Gamescope's
`--expose-wayland` for CUA; in testing, screen capture resolved through the host
portal and exposed the real desktop rather than the private Gamescope output.

The CUA socket and session metadata are written inside `run_dir`. While the
bounded session is alive, use its live PID and XID:

```bash
cua-driver-main call list_windows \
  '{"session":"warband-isolated"}' \
  --socket "$run_dir/cua-driver.sock"

cua-driver-main call get_window_state \
  '{"pid":PID,"window_id":XID,"session":"warband-isolated","include_accessibility_tree":false,"screenshot_out_file":"/tmp/warband-launcher.png"}' \
  --socket "$run_dir/cua-driver.sock"
```

CUA has independently captured the 640x480 Warband 1.174 launcher with
`WarbandMCP` selected. The tested Wine launcher exposes no AT-SPI controls, and
pixel/keyboard XTEST delivery through headless Gamescope does not activate Play.
Therefore launcher capture is proven, but unattended transition into the game is
not. Do not report a CUA action acknowledgement as a game transition.

## Require actual game-process GPU rendering

For any future gameplay or evidence run, add:

```bash
--require-hardware-gl --hardware-deadline 45
```

That requirement succeeds only when the actual `mb_warband.exe` process maps
`radeonsi_dri.so`; Gamescope's own Vulkan renderer is not enough. It also fails
closed when the guarded command exits before producing the proof. The current
launcher-only path is expected to return status 70 at this boundary because Play
cannot yet be activated through private CUA.

The supervisor also has a DXVK backend. `--require-dxvk` verifies that the
isolated prefix's 32-bit `d3d9.dll` hash matches Proton's DXVK DLL, that Proton
loads it as native and that Gamescope selected the AMD GPU. The full Proton/DXVK
launch currently does not map the Warband launcher under headless Gamescope, so
it is preflight evidence, not a working interactive path.

Warband 1.174 has no general command-line module/launcher bypass. Static analysis
found only the `-sm` debug/module-system option; a bounded `-m WarbandMCP` run
remained in the launcher. Play changes state within the same process rather than
spawning a second executable.

## Evidence and cleanup

Every live run should retain:

- `gamescope.log` naming the physical AMD renderer;
- `session.json` with private display and lifecycle state;
- the relevant DXVK or WineD3D proof file;
- periodic aggregate CPU/RSS samples;
- a Hyprland event capture showing no Warband/Gamescope desktop focus event;
- CUA before/after captures for any claimed interaction.

After a run, verify that no exact owned process or transient unit remains. Never
kill broad Wine, Steam, Gamescope or CUA process sets because other agents may own
them. If the outer `systemd-run --wait` client is interrupted, resolve the exact
unit from the owned process's `/proc/PID/cgroup` and stop only that unit.

The old Xvfb/Openbox commands, temporary `:97` display and software-rendered
screenshots are deliberately omitted. They proved CUA interaction but not an
acceptable runtime and must not be revived.
