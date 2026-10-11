# Ultimate Wine Toolbox for Batocera

[English](README.md) | [Français](README.fr.md)

**Ultimate Wine Toolbox** is a Wine / Proton / UMU toolbox designed for Batocera.

Created by **Thomsonito**.

## Features

- French / English interface
- UMU Runner Toolbox integration
- Wine Runner Starter Pack, with a list of installed and missing runners
- classic Wine runner management
- GE-Proton legacy support for Batocera
- MangoHud global and per-game management
- DXVK / VKD3D bundle management
- global and per-game DXVK selection
- Wine bottle maintenance and orphan detection
- runner and DXVK / VKD3D diagnostics
- `.wine` / `.wsquashfs` squash and unsquash tools
- Windows game removal
- safe `batocera.conf` analysis, cleanup, organization and restore
- additive Windows configuration export / import between Batocera machines
- automatic backups before destructive `batocera.conf` operations
- native Batocera Ports launcher and Pad2Key support

## New in v0.3.0

- **Beta** game updates inside an existing WSquashFS, immediately after Create: reuse the prefix, launcher, game settings and save rules.
- Move the updated game directory, test launch and saves, then recompress with a full integrity check.
- Replace directly or back up the previous archive before replacement.
- Resume or cancel pending operations and clean temporary test saves after success.
- Exclude `autorun.cmd` from executable selection.

The new update feature remains in beta while more games are tested. Other features retain their existing status.

[Full release notes](release-notes/v0.3.0.md)

## New in v0.2.0

- Guided WSquashFS creation with external saves, game testing and automatic resume.
- After a failed creation test, install Winetricks components in the working prefix and optionally retest the game.
- Graphical save-folder selection, inspection and a `user.reg` alternative.
- Archive backup/replacement and renaming, quick/full integrity checks and a built-in guide.
- Minimal, default and detailed MangoHud profiles.
- Optional runner-name migration with reference backups, and uninterrupted multi-runner UMU installation.

Save externalization through `SAVEDIR=` requires **Batocera v42 or later**. Full integrity checks require unsquashfs `-pf` support.

WSquashFS creation is based on **DreamerCG**’s script.

[Full release notes](release-notes/v0.2.0.md)

## Installation

Run as `root` on Batocera.

Quick install:

```bash
curl -fsSL https://bit.ly/ultimate-wine-toolbox | bash
```

Direct GitHub install:

```bash
curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/main/install.sh | bash
```

Installed files are stored under:

```text
/userdata/system/ultimate-wine-toolbox
```

Launch from:

```text
Ports -> Ultimate Wine Toolbox
```

## Safety

Ultimate Wine Toolbox is designed to remain conservative when modifying Batocera data:

- existing runners are not overwritten automatically
- destructive operations require confirmation
- `batocera.conf` is backed up before modification
- stock Batocera `windows.dxvk` and `windows.dxvk_hud` settings are protected
- external/custom DXVK installations are not removed automatically
- symbolic links are not followed during game deletion
- legacy development-build migration preserves user state before removing old paths

## Windows configuration transfer

Windows configuration exports are stored under:

```text
/userdata/system/ultimate-wine-toolbox/exports/windows-config
```

Imports are additive: existing Windows settings on the target machine are kept. If an imported key already exists locally, the local value has priority.

The stock Batocera settings `windows.dxvk` and `windows.dxvk_hud` are intentionally excluded from exports and imports.

## Logs

Port startup log:

```bash
cat /userdata/system/logs/ultimate-wine-toolbox/port-launch.log
```

Latest Toolbox session log:

```bash
cat /userdata/system/logs/ultimate-wine-toolbox/latest.log
```

## Releases

Stable releases are published in the GitHub **Releases** section:

https://github.com/Thomson67/ultimate-wine-toolbox/releases

## Legacy development-name migration

Installing Ultimate Wine Toolbox over an older development build automatically migrates the useful Toolbox state to the new paths and removes the old launcher, hooks and runtime directories only after the migration succeeds.

Wine/UMU runners, games, saves and bottles are preserved.

## Update a WSquashFS (beta)

In WSquashFS Management, Update follows Create. Select a Wine-prefix archive and a directory containing the updated game files directly. The source directory is moved into the existing game directory identified from `autorun.cmd` (often `drive_c/game`) of a separate test prefix. `.pc` archives without a Wine prefix are not supported.

Select the executable and test launch, controller input, loading your progress and saving again. The original runner and game options are copied; testing uses a separate save copy, except links to the shared `/userdata/saves/windows` root, which keep their original target throughout testing and in the final archive without an extra prompt or batch changes. Such links use existing saves directly. On return, confirm the previous save rules or select another location through detection or the graphical browser.

A full integrity check must pass before replacement. At completion, choose backup and replacement of the old archive or direct replacement. Original saves and changes to `batocera.conf` remain backed up. Compression failure leaves original saves in place. Resume pending updates from the menu. Temporary test saves are removed automatically after successful completion and retained on failure or while pending; deleting the working prefix is optional at completion.

Allow space for extraction, test saves and the new archive. `SAVEDIR=` requires Batocera v42 or newer.

Updates first offer the launch command from `autorun.cmd`, restoring original `start.bat` scripts at the same relative locations in the replacement folder. Another executable can be selected. Without `SAVEDIR=`, existing links to `/userdata/saves/windows` or its subdirectories are detected, restored in the updated game and offered by default. A root link uses a separate test view without copying other games' saves. Literal batch references to the save root are adapted for testing and restored afterwards; computed script names are not evaluated. A known progress folder can be copied before testing. On return, keep the links or choose another location.

Before the move, the old game directory is renamed `<name>.bak`. The updated directory retains the original name; the source directory disappears from its former location. The `.bak` remains until the game launch is validated, then is removed before recompression. Save links inside the old game directory are restored at the same locations. The move requires the same filesystem and never falls back to an implicit copy. Keeping existing save rules no longer requires an additional confirmation.

The test prefix keeps the exact archive name, replacing `.wsquashfs` with `.wine`, including bracket tags. An existing `.wine` directory triggers replace, choose another name, or quit. WSquashFS ES settings take priority; if it has no game-specific settings, existing Wine settings are reused. `batocera.conf` is backed up before changes. A directory containing the updated source cannot be removed; choose another prefix name instead.

## Batocera graphics models

In the DXVK / VKD3D manager, **Install a Batocera model** offers the official combinations from Batocera 40, 41, 42 and 43 / 43.1. Versions are pinned, archives are verified with SHA-256, and provenance is recorded in `model.json`. The catalog is stored in `toolbox/data/batocera-dxvk-models.json`.

After installation, select the model globally or per game. NVAPI remains controlled through game settings. Models do not replace your runner, drivers or Batocera configuration: recent VKD3D versions may crash DirectX 12 games with Vanilla-Proton-9.0-4. Models 40 to 42 let you test older graphics components.

WSquashFS creation also supports individual saves inside the game directory (`SAVEFILES`). Create a save during the test, then select created/modified files or use the manual list. Files are unchecked by default: settings and logs may also appear. Select files from one folder at a time; chosen files are copied to Batocera saves and removed from the prefix before compression; Batocera recreates their links at launch without moving the game directory.

## Per-game ReShade (beta)

Open **Graphics settings → ReShade (beta)**, select a game, then **Install / change version and shaders**. Select the actual `.exe` (for some Unreal games, inside `Binaries/Win64`), the game's API **before** DXVK/VKD3D translation, the ReShade version and shader packs. Executable headers determine 32/64-bit architecture. Downloads are on demand; the Starter Pack is unchanged.

Launch from EmulationStation and press **Home** to open ReShade. No effect is forced on first launch: enable the effects you want in ReShade. The Toolbox can import a preset `.ini`; its shaders must be available in your selected packs. This uses official Windows ReShade inside Wine/Proton, rather than a native Linux layer like vkBasalt.

- Offered formats: `.wine`, `.pc`, `.wsquashfs`; DirectX 9/10/11/12 and OpenGL. Native Vulkan is outside this integration's scope.
- Launch a `.pc` game once with the selected runner to initialize its bottle before enabling.
- For `.wsquashfs`, managed files go into the bottle's writable layer. The archive stays intact, and ReShade is reapplied when the bottle is recreated.
- Per-game presets/settings are stored under `/userdata/system/ultimate-wine-toolbox/reshade/profiles`. The menu shows the directory. Settings are collected when the game closes and survive runner changes.
- **Disable** restores replaced files. **Uninstall for this game** removes its configuration but retains its preset. Close the game before changing anything. Remove a pre-existing ReShade installation using its original manager first.
- Shared runner files are not changed. If another tool changed a managed DLL, restoration stops and keeps the backup instead of overwriting that change.
- Logs: `/userdata/system/logs/ultimate-wine-toolbox/reshade-install-*.log` and `reshade-game-event.log`. Required shared libraries/shaders are exposed to UMU while retaining MangoHud settings.
- Batocera does not need `git` or `file`: private adapters download GitHub shader snapshots and read Windows PE headers when these tools are absent. Local shader edits are preserved during updates. The ReShade installer is extracted directly with Python, even if an incomplete system `7z` is present. No system tools are installed.

The backend uses unmodified **[ReShadeLinux 1.3.5](https://github.com/asafelobotomy/reshadelinux/tree/v1.3.5)** by asafelobotomy, continuing kevinlekiller's work; it is downloaded from a pinned revision, verified with SHA-256, and retains its GPL-2.0-or-later license. **[ReShade](https://reshade.me/)** is by crosire and its contributors. Shader pack authors are shown in the picker. Actual rendering compatibility depends on the game and runner; initial Batocera/Wayland and UMU play tests are still required.

### Lists, presets, templates and API hints

- **Enabled** and **Installed** lists read ReShade configurations directly, without scanning the full collection. **All games** retains the fast batch lookup; search accepts part of the name.
- Preset import/export uses **YAD**, including an overwrite confirmation. A path prompt is available without YAD. Close the game before export; its latest preset is collected. The exported `.ini` does not include shader packs: install matching packs on the destination game.
- Templates install packs **directly without a checklist**. **Retro**: ReShade, SweetFX, CRT-Royale, RSRetroArch, Crop and Resize, Bad Upscaling Replacer. **Thomson selection**: ReShade, SweetFX, Legacy Effects, Fubax, qUINT, prod80, AstrayFX, iMMERSE. **Custom selection** opens the checklist; **Reuse current packs** preserves the game's pack selection. Templates do not force effects: import a preset or enable effects in ReShade.
- PE imports and graphical DLL references provide API hints after executable selection. Adjacent `UnityPlayer.dll` is checked when its import is found. Reads are bounded to 16 MiB per file, including WSquashFS files; the archive is not fully extracted. Dynamic loading, engines and wrappers may make detection incomplete. Confirm the choice.
- **PCGamingWiki** lookup is optional and runs only for the selected game: choose the correct page before reading supported APIs. Listing games makes no network requests. The site may block automated access (403 observed); local/manual selection remains available. Listed supported APIs do not establish the active renderer. Native Vulkan and DirectX 8 or earlier remain outside this direct integration.
