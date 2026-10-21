# Ultimate Wine Toolbox for Batocera

[English](README.md) | [Français](README.fr.md)

**Ultimate Wine Toolbox** is a Wine / Proton / UMU toolbox designed for Batocera.

Created by **Thomsonito**.

**Stable version: [v0.6.4](https://github.com/Thomson67/ultimate-wine-toolbox/releases/tag/v0.6.4).** WSquashFS updates are validated; WSquashFS creation remains in beta.

## Features

- French / English interface
- UMU Runner Toolbox integration
- Wine Runner Starter Pack, with a list of installed and missing runners
- classic Wine runner management
- classic GE-Proton support, including 11.x (Batocera v44 recommended)
- MangoHud global and per-game management
- DXVK / VKD3D-Proton / DXVK-NVAPI bundles, Batocera 40–43 / 43.1 models and global or per-game selection
- NVAPI version filtering based on known DXVK requirements
- per-game ReShade: installation, toggling, presets, effect templates and API hints
- AntiMicroX: controller profiles, in-game editing, Pad2Key conversion and game assignments
- community catalogue: download, share and moderate AntiMicroX profiles and ReShade presets
- Wine bottle maintenance and orphan detection
- runner and DXVK / VKD3D diagnostics
- `.wine` / `.wsquashfs` squash and unsquash tools
- guided WSquashFS creation (beta) and existing-archive updates, game testing and operation resume
- external saves through `SAVEDIR` / `SAVEFILES` and additional Winetricks components during creation
- Windows game removal
- safe `batocera.conf` analysis, cleanup, organization and restore
- additive Windows configuration export / import between Batocera machines
- automatic backups before destructive `batocera.conf` operations
- native Batocera Ports launcher and Pad2Key support
- update checks at startup and from the toolbox menu

## New in v0.6.4

- Fixed a second Toolbox opening after closing the return screen on older EmulationStation versions, including Batocera 43.1/Xorg.
- Shared protection for WSquashFS, ReShade and AntiMicroX returns.
- AntiMicroX acknowledges the finished-session screen before display while keeping manual recovery available.

[v0.6.4 release notes](release-notes/v0.6.4.md) · [Release history](https://github.com/Thomson67/ultimate-wine-toolbox/releases)

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

Stable builds can be updated from the toolbox or with the installation command above.

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

## In-app documentation

The main **Documentation** menu groups WSquashFS creation and update guides, Wine prefix templates, MangoHud, DXVK/VKD3D and ReShade. Guides are available offline in French and English in a scrolling reader. The templates guide explains their purpose, location and expected format.

## Create a WSquashFS (beta)

The guided workflow prepares a Wine prefix and selects the executable **before the first launch**, then lets you test the game, controller and saves. On return, **Review / change the game executable** can correct the launch choice. After a failure, **Install additional Winetricks** adds components to the working prefix with the selected runner before another test.

For saves, choose a folder (`SAVEDIR`), individual files inside the game directory (`SAVEFILES`), or registry saving. Create an actual save during the test to help detection. Created/modified files are suggested but unchecked: logs and settings may appear too. One `SAVEFILES` selection uses one folder; selected files are copied to Batocera saves and removed from the prefix before compression. Batocera recreates their links at launch without moving the game directory.

Compression, integrity checks and pending-operation resume are part of the workflow. After compression, run or skip the final quick check; Cancel preserves the prefix and does not replace an existing archive. Native `SAVEDIR` support requires **Batocera v42 or later**; an optional experimental compatibility patch is available for v41; full integrity checks require unsquashfs `-pf` support. Creation is based on **DreamerCG**’s script.

## Update a WSquashFS

In WSquashFS Management, Update follows Create. Select a Wine-prefix archive and a directory containing the updated game files directly. The source directory is moved into the existing game directory identified from `autorun.cmd` (often `drive_c/game`) of a separate test prefix. `.pc` archives without a Wine prefix are not supported.

The first test keeps the archive's existing launch command; executable selection is no longer a mandatory step before this test. Check launch, controller input, loading progress and saving again. On return, **Review / change the game executable** lets you correct it and retest. The original runner and game options are copied; testing uses a separate save copy except for shared-root links described below. Then confirm previous save rules or select another location through detection or the graphical browser.

After compression, choose to run or skip the full integrity check before replacement. Checking is offered first; Cancel preserves the working prefix and the original archive. At completion, choose backup and replacement of the old archive or direct replacement. Original saves and changes to `batocera.conf` remain backed up. Compression failure leaves original saves in place. Resume pending updates from the menu. Temporary test saves are removed automatically after successful completion and retained on failure or while pending; deleting the working prefix is optional at completion.

After successful replacement, bottles associated with the archive are cleaned so the next launch uses the updated files and settings. This prevents stale configurations such as an older MangoHud setup from surviving the update.

Allow space for extraction, test saves and the new archive. Native `SAVEDIR=` support requires Batocera v42 or newer. For v41 only, WSquashFS Management offers an experimental boot service with launcher backup and restoration. Enable or disable it from the Toolbox; v40 and .pc launches are not covered.

Updates retain the launch command from `autorun.cmd`, restoring original `start.bat` scripts at the same relative locations in the replacement folder. Another executable can be selected after the test. Without `SAVEDIR=`, existing links to `/userdata/saves/windows` or its subdirectories are detected, restored in the updated game and offered by default. A link to the shared save root keeps its exact original target throughout testing and in the final archive, without an extra prompt or batch changes; this case uses existing saves directly. On return, keep the links or choose another location.

Before the move, the old game directory is renamed `<name>.bak`. The updated directory retains the original name; the source directory disappears from its former location. The `.bak` remains until the game launch is validated, then is removed before recompression. Save links inside the old game directory are restored at the same locations. The move requires the same filesystem and never falls back to an implicit copy. Keeping existing save rules no longer requires an additional confirmation.

The test prefix keeps the exact archive name, replacing `.wsquashfs` with `.wine`, including bracket tags. An existing `.wine` directory triggers replace, choose another name, or quit. WSquashFS ES settings take priority; if it has no game-specific settings, existing Wine settings are reused. `batocera.conf` is backed up before changes. A directory containing the updated source cannot be removed; choose another prefix name instead.

## DXVK, VKD3D-Proton and NVAPI

**DXVK** translates DirectX 9/10/11 to Vulkan; **VKD3D-Proton** does the same for DirectX 12. Bundles let you choose these components separately from the runner, globally or for an individual game. Per-game selection keeps a compatible combination without imposing the same versions on the entire collection.

**DXVK-NVAPI** provides compatibility with NVIDIA functions used by some games. Available versions are filtered by known DXVK requirements, and known VKD3D limitations are reported. The driver, hardware and runner still matter; NVAPI does not give a GTX the hardware features of an RTX.

A newer version is not guaranteed to work better with an older runner. If changing a bundle breaks a game, test Batocera's default components or an older combination. **Vanilla-Proton-9.0-4 with recent VKD3D** caused DirectX 12 crashes during testing.

### Batocera graphics models

In the DXVK / VKD3D manager, **Install a Batocera model** offers the official combinations from Batocera 40, 41, 42 and 43 / 43.1. Versions are pinned, archives are verified with SHA-256, and provenance is recorded in `model.json`. The catalog is stored in `toolbox/data/batocera-dxvk-models.json`.

After installation, select the model globally or per game. NVAPI remains controlled through game settings. Models do not replace your runner, drivers or Batocera configuration: recent VKD3D versions may crash DirectX 12 games with Vanilla-Proton-9.0-4. Models 40 to 42 let you test older graphics components.

## Per-game ReShade

Open **Tools and compatibility → ReShade**, select a game, then **Install / change version and shaders**. Select the actual `.exe` (for some Unreal games, inside `Binaries/Win64`), the game's API **before** DXVK/VKD3D translation, the ReShade version and shader packs. Executable headers determine 32/64-bit architecture. Downloads are on demand; the Starter Pack is unchanged.

Launch from EmulationStation and press **Home** to open ReShade. New profiles skip the tutorial and use **End** to toggle effects; existing customized profiles are preserved. No effect is forced on first launch: enable the effects you want in ReShade. The Toolbox can import a preset `.ini`; its shaders must be available in your selected packs. This uses official Windows ReShade inside Wine/Proton.

- Offered formats: `.wine`, `.pc`, `.wsquashfs`; DirectX 9/10/11/12 and OpenGL. Native Vulkan is outside this integration's scope.
- Launch a `.pc` game once with the selected runner to initialize its bottle before enabling.
- For `.wsquashfs`, managed files go into the bottle's writable layer. The archive stays intact, and ReShade is reapplied when the bottle is recreated.
- Per-game presets/settings are stored under `/userdata/system/ultimate-wine-toolbox/reshade/profiles`. The menu shows the directory. Settings are collected when the game closes and survive runner changes.
- **Disable** restores replaced files. **Uninstall for this game** removes its configuration but retains its preset. Close the game before changing anything. Recognized bundled installations have a separate enable/disable menu. Remove one through its original manager before replacing it with a toolbox installation.
- Shared runner files are not changed. If another tool changed a managed DLL, restoration stops and keeps the backup instead of overwriting that change.
- Logs: `/userdata/system/logs/ultimate-wine-toolbox/reshade-install-*.log` and `reshade-game-event.log`. Required shared libraries/shaders are exposed to UMU while retaining MangoHud settings.
- Batocera does not need `git` or `file`: private adapters download GitHub shader snapshots and read Windows PE headers when these tools are absent. Local shader edits are preserved during updates. The ReShade installer is extracted directly with Python, even if an incomplete system `7z` is present. No system tools are installed.

The backend uses unmodified **[ReShadeLinux 1.3.5](https://github.com/asafelobotomy/reshadelinux/tree/v1.3.5)** by asafelobotomy, continuing kevinlekiller's work; it is downloaded from a pinned revision, verified with SHA-256, and retains its GPL-2.0-or-later license. **[ReShade](https://reshade.me/)** is by crosire and its contributors. Shader pack authors are shown in the picker. Actual rendering compatibility depends on the game and runner; initial Batocera/Wayland and UMU play tests are still required.

### Lists, presets, templates and API hints

- The merged **Games with ReShade** list reads managed configurations and the bundled-installation index directly, without scanning the full collection. **All games** retains the fast batch lookup; search accepts part of the name.
- Preset import/export uses **YAD**, including an overwrite confirmation. A path prompt is available without YAD. Close the game before export; its latest preset is collected. The exported `.ini` does not include shader packs: install matching packs on the destination game.
- Templates install packs **directly without a checklist**. **Retro**: ReShade, SweetFX, Legacy Effects (HQ4X), CRT-Royale, RSRetroArch, Crop and Resize, guest(r) (2D-Scaler / 2D-Scaler-level2), plus **4xBRZ**, **5xBR NoBlend** and **AnomalousPixelBlending (APB)**. Effects process the game's final image; settings depend on its original resolution and the desired appearance. **Thomson selection**: ReShade, SweetFX, Legacy Effects, Fubax, qUINT, prod80, AstrayFX, iMMERSE. **Custom selection** opens the checklist; **Reuse current packs** preserves the game's pack selection. Effects are not enabled all at once: import a preset or choose effects in ReShade.

The retro supplement includes `5XBR_NoBlend.fx` and downloads only `4xBRZ.fx` and `AnomalousPixelBlending.fx` from fixed revisions verified with SHA-256. Sources and authors are recorded in `toolbox/data/reshade-extra-shaders.json`; embedded notices are preserved. **spiderh's 4xBRZ port**, based on Libretro, is obtained from its GShade mirror without installing GShade. **APB**, by RdenBlaauwen, is downloaded directly from its repository. **spiderh's 5xBR NoBlend port** is bundled with its source and GPL-2.0-or-later license. HQ4X and guest(r) shaders remain supplied by their respective packs.

In the overlay, look for **xBRZ4x**, **xBR5x_NoBlend**, **HQ4X**, **TWO_D_SCALER**, **TWO_D_SCALER_LEVEL2** or **AnomalousPixelBlending**. For 4xBRZ, its author recommends setting `Strength` to the image height divided by its original height (for example 1080 / 240 = 4.5). 5xBR NoBlend starts with `Strength` set to 1.5. Test these alternatives on 2D games; compare results before combining multiple smoothing filters.
- PE imports and graphical DLL references provide API hints after executable selection. Adjacent `UnityPlayer.dll` is checked when its import is found. Reads are bounded to 16 MiB per file, including WSquashFS files; the archive is not fully extracted. Dynamic loading, engines and wrappers may make detection incomplete. Confirm the choice.
- **PCGamingWiki** lookup is optional and runs only for the selected game: choose the correct page before reading supported APIs. Listing games makes no network requests. The site may block automated access (403 observed); local/manual selection remains available. Listed supported APIs do not establish the active renderer. Native Vulkan and DirectX 8 or earlier remain outside this direct integration.

Inside **Install / change version and shaders**, after executable selection, the API selector offers **Detect the API by launching the game**. Launch runs through EmulationStation; reach the menu or gameplay, then quit normally. After showing the result, the toolbox resumes at API selection for the same executable. It observes Windows DLLs in the game's Wine and UMU prefixes. WSquashFS archives, autorun files and launch variables remain unchanged. Linux Vulkan libraries are not interpreted as evidence of native Vulkan.

Observations supplement executable hints and require confirmation: multiple APIs, wrappers and an existing ReShade installation can affect results. Unknown results keep manual selection available. Observation ends when the game returns, or after one hour without closing the game. The last report is kept per game: rerun it after changing the runner, game version or renderer. Reopening the toolbox also lets you review an interrupted request.

PCGamingWiki searches start with a title stripped of runner annotations and rank matches by similarity. The closest title is offered first; editions and sequels are never selected silently.

**Find / refresh ReShade bundled with games** identifies usual proxy DLL names using ReShade injector metadata. The first scan may take time. Positive and negative archive results are indexed; unchanged archives are not reread. Opening a game also checks for an existing installation. Ordinary lists never inspect archives.

DLLs present only in `drive_c/ProgramData/ReShade` are global resources and do not establish a game installation. Unreadable archives are reported with their reason in `reshade-discovery.log` without cancelling discovery of other games.

Disabling a bundled installation journals and backs up the original proxy DLL, then prevents loading it from the game folder. WSquashFS uses an OverlayFS whiteout in the per-game bottle without changing the archive. Wine/DXVK keeps using its regular system library. Enabling restores the exact DLL or removes its whiteout. **Restore original management** releases toolbox control. Presets, shaders and autorun remain unchanged; the setting is reapplied on subsequent launches and recreated bottles.

Nonstandard DLL names/loaders are listed without automatic control. WSquashFS masking requires Batocera's OverlayFS launcher and whiteout creation on the bottle filesystem; failure preserves the existing DLL. DLLs changed by another tool are never overwritten during recovery: the journal is retained and an error reported. Toolbox removal restores bundled installations it controlled.

## .NET workflow (experimental)

**Tools and compatibility → Winetricks / Wine Mono / .NET** also works outside archive creation. Select a `.wine`, `.pc` or `.wsquashfs` game, then install common Winetricks components or choose from the complete `list-all` catalogue, or open the Wine Mono / .NET diagnostic, installation and snapshot restoration menu. The configured per-game runner is suggested; another runner can be selected before installation. Changes go directly into `.wine` prefixes; `.pc` and `.wsquashfs` use the runner’s persistent bottle. The original archive stays unchanged, no full game extraction is needed, and deleting the bottle removes these components. Launch `.pc` games once with the chosen runner first. A pending archive build is preserved.

The test workflow distinguishes shared Batocera/runner Wine Mono from prefix installations, supports a verified latest stable Mono MSI or replacement with Microsoft .NET Framework 4.8, and backs up the working prefix before changing it. The game directory is excluded from the backup. Mixed or unidentified .NET states are refused. See the new offline .NET guide; validate installation and a second game launch before archive finalization.

.NET test installations now use local staging outside the ROM directory, preserve TKG link metadata and offer snapshot recovery after incomplete attempts. Real installer compatibility still requires Batocera validation.
