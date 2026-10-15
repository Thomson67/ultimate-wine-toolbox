# AntiMicroX — experimental native integration

This branch is a test build, not a validated Batocera release.

## Runtime and menus

AntiMicroX 3.6.1 is an explicit opt-in download from the official project. The
normal x86_64 AppImage is selected; the debug asset is excluded. Installation
extracts it without FUSE and checks AppRun, the Qt xcb plugin and their loader
dependencies before replacing the previous extraction. Updating the Toolbox
also refreshes the wrapper of an already downloaded AppImage, without another
download. An old download is extracted at its next launch.

The official AppImage inspected for this integration contains Qt6 with the xcb
platform plugin only. Its interface runs through X11/XWayland, including on
labwc. Input generation still uses `--eventgen uinput`. This does not require
modifying Batocera's system files. `/dev/uinput` must exist and be writable.

The wrapper discards host Qt/plugin and loader overrides, uses the bundled
plugin directory, preserves DISPLAY and defaults to `:0` when unset. A different
X server or a missing dependency can still prevent startup; menus now expose
errors instead of reporting an unverified successful launch.

1. Open **Outils et compatibilité / Tools and compatibility → AntiMicroX**.
2. Install AntiMicroX if not already downloaded.
3. Open the profile editor, save an `.amgp` under `/userdata`, then close it.
4. Assign the profile to a selected `.wine` or `.wsquashfs` game with the file
   picker (text path fallback when Yad is absent).
5. Launch that game from EmulationStation, then close it and check the log.

The editor runs in the foreground, with no tray and no success popup obscuring
its window. Editor failures include the exit code and log excerpt. Controller
listing and the version diagnostic have timeouts. Editor and game hooks use
the same managed runtime, not a different system binary.

## Profiles and lifecycle

Associations remain in `config/antimicrox-games.tsv`. Profiles stay at their
chosen locations under `/userdata`, outside the Wine prefix. This configuration
is local: sharing a WSquashFS does **not** yet include its mapping. Reassign the
profile after a game is renamed or compressed to a different ROM path.

The Windows `gameStart` hook starts the assigned profile. `gameStop` stops only
the matching managed session, verifying PID/start time and command line. The
mapping child must not inherit the hook lock. A new Windows game cleans up any
previous managed mapping, even if the new game has no profile. An unrelated
AntiMicroX instance is not killed or reconfigured; starting a mapping/editor is
refused while one is running. Runtime settings are isolated and reset per game
so another game's profiles cannot auto-load. Uninstallation stops the managed
session and removes its hook.

A missed `gameStop` may leave the mapping running until the next Windows game
or uninstallation; there is no independent crash watchdog yet. Launcher-only
mode, title-based profile switching and the WSquashFS post-launch configuration
shortcut are not implemented in this branch.

## Logs and validation

- Installation: `/tmp/uwt-amx-install.log`
- Editor: `/userdata/system/logs/ultimate-wine-toolbox/antimicrox-editor.log`
- Game lifecycle: `/userdata/system/logs/ultimate-wine-toolbox/antimicrox.log`

Automated checks cover asset selection, inherited Qt settings, extraction of an
old download, editor failure reporting, associations, and start/stop locking
with simulated device/process data. The official AppImage was downloaded and
extracted for inspection. These checks do not validate real display, controller
or uinput behavior.

On Batocera, validate the diagnostic version, editor display, DualSense listing,
profile save/reopen, keyboard/mouse events and dead zones, then game start/stop
for both `.wine` and `.wsquashfs` (including UMU). Confirm that mapping stops
at exit and does not carry over to a game without a profile. Also check startup
failure logs and an already-running independent AntiMicroX instance.
