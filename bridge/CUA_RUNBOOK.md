# Off-screen Warband through CUA

This is a real Native Warband instance, not the old ExternalAPI mod bridge.
All screenshots, mouse input and keyboard input go through `cua-driver-main`.
No `hyprctl`, `xdotool`, or separate input injector is used.

Verified on 2026-10-09: launcher dropdown opened, Native selected using Up/Return,
game launched, tutorial selected and loaded, and Escape opened the in-game pause
menu. All verified through CUA screenshots. Left paused in the tutorial, with
audio enabled as requested. Mute through the game's Options UI when requested.
Single Escape taps initially missed; a later retry sequence opened the menu.
Movement, combat, campaign control and NPC conversations are not yet verified.

## Running session

- X11 display: `:97` (Xvfb, 1600×900, TCP disabled).
- CUA socket: `/tmp/shuvcode/warband-cua/driver.sock`.
- CUA session label: `warband-isolated`.
- Separate copied Proton prefix: `/tmp/shuvcode/warband-cua/compatdata`.
- Process supervision: tmux session `warband-external-api`, windows `x11`,
  `wm`, `cua`, and `game`. `steam` is the earlier desktop launch; don't stop it
  just to stop the isolated session.
- Openbox was extracted locally under `/tmp/shuvcode/warband-cua/wm` from the
  signed Arch package. No system package installation was performed.

`delivery_mode:"foreground"` means foreground **inside :97**, not on the user's
Hyprland desktop. Background synthetic events were ineffective in the original
XWayland session. This is an isolated-runtime workaround, not a CUA source fix.

## Observe and act

```bash
cua-driver-main call list_windows '{"session":"warband-isolated"}' \
  --socket /tmp/shuvcode/warband-cua/driver.sock
```

Use the returned live PID and window ID; launcher, intro and game windows have
different IDs. Capture each target before acting:

```bash
cua-driver-main call get_window_state \
  '{"pid":PID,"window_id":XID,"session":"warband-isolated","include_accessibility_tree":false,"screenshot_out_file":"/tmp/shuvcode/warband-cua/current.png"}' \
  --socket /tmp/shuvcode/warband-cua/driver.sock

cua-driver-main call click \
  '{"pid":PID,"window_id":XID,"session":"warband-isolated","x":X,"y":Y,"delivery_mode":"foreground"}' \
  --socket /tmp/shuvcode/warband-cua/driver.sock

cua-driver-main call press_key \
  '{"pid":PID,"window_id":XID,"session":"warband-isolated","key":"Escape","delivery_mode":"foreground"}' \
  --socket /tmp/shuvcode/warband-cua/driver.sock
```

Replace placeholders with actual numbers. Coordinates are from the returned
screenshot, which may be scaled. Verify effects with another capture, not just
the action's success message. Dropdown popups may refuse foreground activation;
the module dropdown worked with Up/Return targeting the launcher instead.

## Tested startup commands

Run each long-lived command in its own existing tmux window using `send-keys`.
Do not start duplicate X servers, daemons or game instances.

```bash
/home/shamanic/.cache/manifold/toolchains/xvfb/usr/bin/Xvfb :97 \
  -screen 0 1600x900x24 -nolisten tcp -noreset -ac

env -u WAYLAND_DISPLAY DISPLAY=:97 \
  LD_LIBRARY_PATH=/tmp/shuvcode/warband-cua/wm/usr/lib \
  XDG_DATA_DIRS=/tmp/shuvcode/warband-cua/wm/usr/share:/usr/share \
  /tmp/shuvcode/warband-cua/wm/usr/bin/openbox \
  --config-file /tmp/shuvcode/warband-cua/wm/etc/xdg/openbox/rc.xml

env -u WAYLAND_DISPLAY -u CUA_DRIVER_RS_ENABLE_WAYLAND \
  DISPLAY=:97 XDG_SESSION_TYPE=x11 cua-driver-main serve \
  --socket /tmp/shuvcode/warband-cua/driver.sock \
  --pid-file /tmp/shuvcode/warband-cua/driver.pid --no-overlay

# Working directory: Steam's MountBlade Warband installation.
env -u WAYLAND_DISPLAY DISPLAY=:97 WINE_FULLSCREEN_FSR=0 \
  WINE_DISABLE_FULLSCREEN_HACK=1 PROTON_LOG=1 \
  PROTON_LOG_DIR=/tmp/shuvcode/warband-cua \
  SteamAppId=48700 SteamGameId=48700 \
  STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/shamanic/.local/share/Steam \
  STEAM_COMPAT_DATA_PATH=/tmp/shuvcode/warband-cua/compatdata \
  "/home/shamanic/.local/share/Steam/steamapps/common/Proton 9.0 (Beta)/proton" \
  runinprefix mb_warband.exe
```

The prefix copy needs `pfx`, `version`, `tracked_files`, and `config_info` from
the original compatdata directory, not just `pfx`. It is temporary and is not
guaranteed to survive reboot or temporary-file cleanup. Never point cleanup or
prefix experiments at the working Steam/Pendor prefix.

This display uses software OpenGL rendering in the tested launch. Gameplay
performance and GPU acceleration are not established by launcher input success.
The X server uses local access without an Xauthority cookie (`-ac`); TCP is
disabled, but other local users could access it. This is not a security sandbox.
