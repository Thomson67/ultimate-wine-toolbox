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

The wrapper also registers the missing `QXmlStreamReader*` Qt6 type before
AntiMicroX starts. Without this upstream 3.6.1 workaround, profile loading can
report `Cannot queue arguments` and `Could not open mutex_read_config`, leaving
a running mapper with no loaded actions. The checked, process-local library
and its rebuildable source are in `toolbox/compat/antimicrox`. A native queued
XML regression test passes against the official bundled Qt libraries; actual
mapping on Batocera remains to be confirmed. Existing profiles are preserved.

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

**Gérer les jeux avec un profil associé / Manage games with assigned profiles**
lists only assigned games, including stale associations whose ROM or profile is
missing. Each game shows full ROM/profile paths and offers profile details
(all sets and mappings, keyboard combinations, mouse movement/clicks,
timed sequences, set changes and advanced slot fields), editing the assigned profile,
editing/testing it in game, replacing it and removing its assignment. Shared
profiles are identified before editing. Removal keeps the `.amgp` file and
other games' assignments, and takes effect on the next game launch. Missing
games remain removable, but cannot be launched from this menu.

Profile information uses a vertically scrollable, wrapped text viewer. Common
Qt key codes are decoded to names; unfamiliar/native codes remain visible
instead of being omitted. Reporting never executes profile commands.

Standard `gamecontroller` profiles display Xbox / PlayStation labels (A / Cross,
LB / L1, LS click / L3, LT / L2, etc.) with the AntiMicroX button number retained
in brackets. Left/right sticks and the D-pad are named explicitly. Generic raw
`joystick` profiles keep numeric button labels because their physical order is
device-specific. Stick directions use AntiMicroX's clockwise 1–8 enum; D-pad
directions use SDL hat bitmasks. Trigger labels support modern indices 5/6 and
legacy indices 1/2. Custom button names remain visible.

**Supprimer un profil / Delete a profile** is available both in the main
AntiMicroX menu and for an assigned game. It lists managed profiles, including
unassigned ones, plus associated external profiles under `/userdata`; a file
picker can select another `.amgp`. Confirmation shows the selected file and its
assigned games. Deletion removes the file and all its assignments, preserving
other profiles. A running mapper blocks deletion. The file is staged on its
own filesystem and restored if the configuration write fails. Associations are
locked during updates; a changed file or TSV invalidates an earlier confirmation.

Yad starts in `config/antimicrox-profiles/`, preselecting the current profile
when it is in that folder. Manual path entry uses the same starting directory.

## Pad2Key conversion

**Convertir un Pad2Key en profil AntiMicroX / Convert Pad2Key to an AntiMicroX
profile** accepts a selected Windows game's `.wsquashfs.keys` or `.wine/padto.keys`
(`.pc` also supported), or a manually selected `.keys` file. A preview reports
converted actions and everything requiring manual editing before creating a new
profile under `config/antimicrox-profiles/`. Existing profiles are never overwritten.
The original file stays unchanged during conversion. Converted mappings can be
viewed, edited, enabled or enabled and tested with the existing live workflow.

This first version converts player-one keyboard targets (including simultaneous
key combinations), mouse clicks, sticks used as a mouse, D-pad directions, stick
directions and triggers. `mode: any` trigger alternatives are supported. Physical
button naming follows Batocera's SNES convention: `b` becomes Xbox A / PS Cross,
`a` becomes B / Circle, `y` becomes X / Square and `x` becomes Y / Triangle.
`pageup` and `pagedown` become LB/L1 and RB/R1. Supported native Linux key codes
preserve right-side modifiers and keypad identity with AntiMicroX's native-key
prefix; these profiles use the managed uinput event generator.

Hotkey + one button chords (`mode: all`) use a second set while Hotkey is held,
with a reverse while-held association back to the normal set. The conversion
reads Batocera's user/system `es_input.cfg`: a shared Hotkey uses its configured
logical button, while a standalone Hotkey maps to SDL Guide. If configurations
use different Hotkey buttons, the menu asks which controller configuration to
use. Missing, ambiguous, axis/hat Hotkeys and Start-as-Hotkey are not guessed.
Like evmapy, the shifted set retains the button's ordinary output in addition
to its chord output. Other ordinary mappings are copied, except plain Start:
**Hotkey + Start gets no mapping unless that exact chord is explicitly defined
in the source file.** Batocera's own quit shortcut remains available otherwise.
The preview reports the selected modifier and set behavior. Reconvert if the
controller's Hotkey assignment changes.

Held/delayed triggers, other multi-button chords and sequences, shell commands, unknown
inputs/targets and other players are explicitly reported rather than guessed.
Commands from a `.keys` file are never executed. Unsupported actions are not
added partially. Mouse sensitivity and deadzones may need adjustment in the
editor because evmapy and AntiMicroX have different motion handling. Only the
selected file is analyzed; global Pad2Key files are not silently imported.

Enabling a converted profile backs up the game's original `.keys` contents and
mode in `state/antimicrox-pad2key-backups.json`. Player-one actions are replaced
with empty-target overrides, which emit no input and shadow identical triggers
in Batocera's merged global mappings. Other players' original Pad2Key actions
remain intact; this does not introduce separate AntiMicroX profile routing for
multiple controllers. The conversion menu explicitly targets player one.

Removing the AntiMicroX assignment or deleting the assigned converted profile
restores the original Pad2Key bytes and mode (or removes the temporary override
if no original existed). Switching AntiMicroX profiles keeps the original backup
until the association is removed. Live configuration temporarily adds its shortcut
to the suspended file and restores that file when the session ends. Uninstall
restores Pad2Key backups before deleting Toolbox state. External edits to a
suspended file are never overwritten: the operation fails and retains its backup.
Source changes after preview/creation are detected before conversion/activation.

Automated fixtures reproduce the two supplied examples: Max Payne converts
21/21 actions and Gobliins 6 converts 6/6. Tests cover button conventions, function
keys, mouse directions/clicks, unsupported actions, round-trip restoration,
profile deletion, failure rollback, global trigger shadowing and live-launch
handoff. Converted mappings and mouse feel still require Batocera gameplay tests.

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

The Toolbox closes its terminal and starts a detached observer with inherited
file descriptors closed. Its Ports launcher exits before the observer requests
the game through EmulationStation. The observer waits for the Ports session to
be released and confirms the exact ROM `path` returned by `/runningGame`;
HTTP 200 alone is not a successful launch. An already-active requested game is
observed without a duplicate launch. Another active game is not interrupted.
This fixes the reported black screen where ES still ran the Toolbox port and
the old monitor mistook that port for the game while waiting for itself to exit.
The actual display/input handoff remains to be retested on Batocera.
Its Windows game hook starts one visible AntiMicroX editing instance with that
profile, uinput, isolated settings and the enlarged window. The editor does not
use `--no-tray`, avoiding the Settings OK crash.

At startup, the live focus observer waits for a stable Wine XWayland window,
checks that ES runs the requested ROM, and asks the window manager to bring
that window forward once. AntiMicroX remains open for Alt+Tab. After game focus
is confirmed, a six-second passive banner explains Alt+Tab and the selected
controller shortcut, in the Toolbox's language. No confirmation is needed.
The initial wait is bounded to 120 seconds and activation is requested only
once; unrelated foreground applications are not raised over. If activation is
ignored, no banner is shown over the editor. Later switches remain manual.
The startup banner uses a non-interactive GTK layer-shell overlay on Wayland
(keyboard mode NONE, no exclusive zone, pointer/touch pass-through). On X11 it
uses an override-redirect popup that does not accept focus. If the safe Wayland
overlay is unavailable, the banner is skipped instead of using a normal window.
The earlier `batocera-flash-screen` startup banner could activate a GTK window;
Max Payne reported `DIERR_NOTACQUIRED` at that point. The user confirmed the passive replacement resolves this startup crash on
Batocera/labwc. The previously validated short
focus-recovery banner on later editor-to-game returns is unchanged.

Use **Alt+Tab** on the keyboard or **Hotkey + R1/RB** on Batocera player 1's
controller. If this chord is used by the profile, the session tries Hotkey +
Select instead. A button that itself acts as Hotkey is excluded. If both are
occupied, the session uses keyboard Alt+Tab only; it never chooses Hotkey +
Start. The pre-launch notice and in-game banner show the chosen shortcut.
Release the combination after each switch. A temporary per-ROM evmapy rule sends
Alt+Tab independently of AntiMicroX. Source conversion metadata, profile set
mappings and existing per-ROM actions are checked for conflicts before preparing
the session. Profiles are not rewritten. Ordinary button outputs may still fire
alongside the temporary shortcut, as they do with evmapy. Do not assign the
reserved shortcut while editing; restart the session after such a change.
Older sessions retain their recorded action for recovery; the original
Hotkey + bottom-button rule is also recognized for backward-compatible cleanup.
Global actions and other games are not modified.

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
On the reported Batocera session, Wine required a second round trip before
accepting input after Alt+Tab. Opening and closing Batocera's GTK information
popup restored input. Live sessions now launch a detached XWayland activation
observer: after a stable transition from the managed editor to a Wine X11
window, it confirms ES still runs the same ROM and invokes the tested
`batocera-flash-screen` popup for 0.3 seconds (small “Retour au jeu” banner).
It never sends F2 or gameplay keys. Other applications, initial game launch,
normal profile playback and the popup's own return do not trigger a refresh.
The observer exits when the mapping PID, start time or live session changes.
This covers XWayland Wine windows; native winewayland windows are not detected
by this observer. The user has confirmed automatic return recovery and the
creation/editing workflow on the Batocera test session.

Real Alt+Tab focus, player 1 hotkey handling, full-screen Wine/UMU and possible
simultaneous button actions remain to be validated on Batocera. Alt+Tab cycles
compositor windows; games with additional launcher windows may expose those too.

## Logs and validation

- Installation: `/tmp/uwt-amx-install.log`
- Editor: `/userdata/system/logs/ultimate-wine-toolbox/antimicrox-editor.log`
- Game lifecycle: `/userdata/system/logs/ultimate-wine-toolbox/antimicrox.log`
- Detached launch: `/userdata/system/logs/ultimate-wine-toolbox/antimicrox-handoff.log`

After the Toolbox Ports launcher exits, live editing checks ES's in-memory game
list via `GET /systems/{system}/games`. If the game is missing, it requests one
`GET /reloadgames` refresh without confirmation, then waits up to 60 seconds for
the exact ROM path before launching. Games already indexed do not trigger a
refresh. This happens only once ES is idle, to avoid blocking its UI thread on
the running Toolbox. `/launch` alone can return HTTP 200 for an unknown path.
If refresh fails, the live session is restored and its error is reported when
returning to the Toolbox; no repeated refresh or ES restart is attempted.
ES may still display its own prompt if a scraper or hashing job is running.

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
