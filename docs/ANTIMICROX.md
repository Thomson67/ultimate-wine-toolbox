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

The editor runs in the foreground with no success popup obscuring its window.
It must not use `--no-tray`: AntiMicroX 3.6.1 accepts Settings by unconditionally
calling `populateTrayIcon()`, which dereferences the null tray menu in this mode.
The reported Batocera stack (`QMenu::clear`, AppRun offset `0x19456b`) matches
that call. The editor now initializes its tray menu; hidden game mapping still
uses `--hidden --no-tray`. Use Application → Quit if a saved close-to-tray
preference hides the editor instead of exiting. Editor failures include the exit code and log excerpt. The editor window is enlarged
to 1600×900 where the monitor permits it, with a margin on smaller displays;
larger saved sizes are retained if they fit. Only Qt geometry keys are changed.
Info logging is enabled for the editor and the previous editor
log is preserved as `antimicrox-editor.previous.log`. The window sizing and
Settings OK workaround have been confirmed on the user’s Batocera session. Controller
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

## Configure and test in game (experimental)

Choose **Configurer et tester en jeu / Configure and test in game**, select a
`.wine`, `.pc` or `.wsquashfs`, then choose the assigned profile, an existing
profile, or a new one. New profiles are stored in `config/antimicrox-profiles`
with a game name and path hash, outside the prefix. An existing unassociated
profile at that path is reused, never overwritten with an empty profile.

The Toolbox closes its terminal and launches the game through EmulationStation.
Its Windows game hook starts one visible AntiMicroX editing instance with that
profile, uinput, isolated settings and the enlarged window. The editor does not
use `--no-tray`, avoiding the Settings OK crash.

Use **Alt+Tab** on the keyboard or **Hotkey + bottom face button** (DualSense
Cross / Xbox A) on Batocera player 1's controller. Release the combination after
each switch. A temporary per-ROM evmapy rule sends Alt+Tab independently of the
profile being edited. The physical bottom button is `b` in Batocera's internal
mapping. Existing per-ROM actions for the same combination are saved and
replaced for this test. Global actions and other games are not modified.

The shortcut lives in `.wine/padto.keys` or `.pc/padto.keys` for directory games,
and `<game>.wsquashfs.keys` alongside compressed games. No archive is rewritten.
Original file contents and mode are saved before insertion. Normal completion
or a failed launch restores them. Concurrent edits are preserved by removing
only the owned action and restoring a displaced action if no newer rule has
replaced it. Malformed concurrent edits stop cleanup and retain the original
in `state/antimicrox-live.json` for recovery. An interrupted session is recovered
when the Toolbox or AntiMicroX menu is next opened; do not manually delete that state file.
Uninstallation also restores the temporary keys before removing the Toolbox.

Edits apply in memory while AntiMicroX runs. **Click Save in AntiMicroX before
quitting the game**, using the loaded profile path. The game-stop hook ends the
managed editor. The Toolbox then restores the shortcut and returns to the
AntiMicroX menu, where the user can associate the profile for normal launches,
retry the editing session or return without enabling it. Closing the editor
early does not close the game; quit the game normally to complete the session.

A launched editing session does not automatically change the normal game
association. WSquashFS creation/update and ReShade diagnostic return paths are
kept separate. The `port-launch.log` records launch/resume activity; editing
sessions use the regular `antimicrox.log`.

Automated tests exercise transactions, restoration, existing/concurrent rules,
compressed and directory ROMs, visible hook arguments and return dispatch.
Real Alt+Tab focus, player 1 hotkey handling, full-screen Wine/UMU and possible
simultaneous button actions remain to be validated on Batocera. Alt+Tab cycles
compositor windows; games with additional launcher windows may expose those too.

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
