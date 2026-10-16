# Community profiles

The interface stays inside each tool: **AntiMicroX → Community profiles** and
**ReShade → Community presets** (also available from a configured ReShade game).
There is no additional shared entry in the Toolbox main menu.

A single schema-1 JSON catalogue in `Thomson67/ultimate-wine-toolbox-community`
(branch `main`) contains both file types. Downloads use GitHub raw URLs directly;
no account or API key is required for readers. The Cloudflare Worker only handles
submissions and moderation. Each tool keeps its own community menu.

The default submission service is `https://uwt-community-api.thomson67.workers.dev`.
After an endpoint rename, a local `config/community-source.json` with an explicit
`api` override must also be updated. Remembered validator access is tied to the
API origin and requires fresh pairing; the master validator key and D1 records
are unchanged. Catalogue downloads continue to use GitHub.

Service deployment instructions, schema, sources and a ready-to-paste bundle:
https://github.com/Thomson67/ultimate-wine-toolbox-community/blob/main/service/INSTALLATION_FR.md

## Read and import

First browsing downloads the catalogue; subsequent browsing/search uses the
local cache in `state/community/catalog.json`. Refresh is explicit and requests a
fresh copy with a unique URL and no-cache headers, bypassing GitHub’s five-minute
cache of branch URLs after publication. Profile URLs remain unchanged. A failed or
invalid refresh does not replace a valid cached catalogue. Profile downloads
require network access and verify the manifest SHA-256 before validation and
installation. Text/control characters, file paths, content types and sizes are
checked. Only declarative `.amgp` SDL GameController profiles and portable
ReShade `.ini` presets are accepted. Commands and external profile loading are
rejected. Personal paths and controller identities are not accepted.

AntiMicroX downloads go into `config/antimicrox-profiles`; ReShade downloads go
into `config/reshade-community-presets`. A changed personal file is preserved
under its existing name and a download creates a separate filename. Import
metadata is stored in `state/community/imports.json`.

After AntiMicroX download, the user can inspect all mappings, edit, assign or
test in game. Hotkey adaptation is manual: the details explicitly show the
expected modifier. Assignment uses the existing reversible Pad2Key suspension
and restoration mechanism, with a working runtime/uinput required. A modified
suspended Pad2Key is still protected; community downloads do not bypass its
recovery checks.

Applying a ReShade preset offers all Windows games in the ES gamelist. A game
without an injector can run the existing installation wizard and continue with
the downloaded preset. The model screen is skipped when a preset is already
selected. The standard model screen also offers a searchable community preset
chooser (with refresh, full details, validation and hash-verified download).

Shader packs are inferred offline from effect sections and `Technique@File.fx`
references, using the pinned official EffectPackages index mapped to the backend's
pack IDs and Toolbox retro extras (`toolbox/data/reshade-effect-index.json`).
TechniqueSorting alone does not pull in inactive effects. Known packs are selected
automatically; unknown effects and ambiguous pack matches require review of a
preselected checklist. No URL from a preset controls a shader download. A preset
contains settings; the backend installs the selected packs and their dependencies.
A graphics-API diagnostic launch retains the selected community preset on resume.

An existing integrated ReShade does not need reinstallation. The Toolbox changes
only ReShade.ini's preset path and a separate UWTCommunityPreset INI next to the
selected existing injector. Its DLLs, shader/texture paths and shader files remain
unchanged. Required shaders must already be present in this case. For wsquashfs,
only Wine OverlayFS upperdirs receive those two INI files; the archive is not
modified. A launch hook reapplies the saved preset when using a new/recreated
runner prefix and saves in-game preset edits at gameStop. Journals/backups precede
writes. The integrated game's menu offers restoration of the previous settings,
refusing to overwrite files subsequently edited by the user. Running games and
unsafe file links are refused.

Managed ReShade imports first export the previous preset to
`exports/community-backups/`, then use the existing importer. Disabled managed
setups are enabled after confirmed import. Cancelling or failing configuration
does not import the preset. Shader requirements are displayed before download.

## Export and review

Sharing proposes the game name from the profile's association, import/conversion
metadata, internal profile title or filename. Generated hashes, file extensions,
Pad2Key suffixes and known runner/language tags are removed. When available,
the title is matched to ES's current Windows game list. A profile shared by
multiple games requires explicit selection. ReShade uses the selected game,
not the temporary preset export filename.

The user can accept the proposed name or choose another game from the ES
gamelist, with a search option. There is no free-text game-name field in this
sharing step. Manual selection reads `GET /systems/windows/games`; it does
not scan ROM folders. If ES is unavailable, a locally derived proposal can
still be accepted, while manual selection reports the unavailable list.

ReShade sharing lists both Toolbox-managed games and detected integrated installations.
“Scan Windows games” scans the ES Windows game list for integrated ReShade injectors,
including `.wsquashfs` archives. It does not use AntiMicroX associations. The preset
chooser distinguishes presets in the original game/archive from saved presets in
existing Wine runner prefixes and marks the configured active preset when its path
can be resolved inside that source. Archives are listed/read using `unsquashfs`,
without extracting or rewriting the game. Unsupported loader variants can still
share a detected preset. A manual `.ini` choice remains available. Downloaded presets use the existing or new installation workflow described above.

After identifying the game, sharing asks for only three fields: profile/preset
name, public author nickname and description. Versions, compatibility notes and
requirements are not additional form questions; the existing metadata schema
remains compatible, with those optional values empty for new submissions. Mapping
hotkeys and shader pack inference continue to use the profile/preset content.

Sharing creates a local ZIP in `exports/community/<kind>/`, removes controller identities
from the exported copy, then sends the profile and public metadata over HTTPS after
explicit confirmation. No GitHub account is needed. Managed ReShade presets use the existing
manager to synchronize and export first; integrated presets are copied read-only. Direct sharing accepts 64 KiB
profiles. The original file is unchanged. Failed or uncertain sends keep the ZIP and offer
an immediate retry with the same identifier/checksum. The community menus no longer
include a saved-package resend option. A successful response writes a local
`.receipt.json`. No automatic resend happens at startup.

The private D1 queue is visible only after validator login. Each tool's validator
menu shows only its own type and displays all mappings or the full preset. Approval
publishes both profile and manifest in one non-forced Git commit; rejection publishes
nothing. Authors' nicknames are self-declared. The service forbids `execute` and
`loadprofile`, but keyboard macros still require human review.

Validators pair from their PC or phone instead of typing the generated 256-bit key
on Batocera. `/pair` authenticates the validator using that existing key, then requires
inspection and explicit approval of an eight-character, five-minute code displayed by
the Toolbox. The short code cannot retrieve credentials; polling uses a separate random
256-bit device secret. Pairing codes are single-approval and rate-limited. This is a
custom pairing flow, not OAuth or two-factor authentication.

The optional remembered-device grant lasts a fixed 30 days. Its token lives in
`state/community/validator-device.json` (0600) and creates fresh 30-minute sessions.
Only hashes are held server-side. Temporary session copies remain in
`state/community/validator-session.json` (0600), revoked/deleted when leaving moderation.
The master key is never stored by the Toolbox. A paired session can moderate profiles
but cannot authorize other devices or manage device grants. The PC page stores its
session only in memory and never puts the key or tokens in URLs or browser storage.
Revocation from the PC blocks existing device sessions too. “Forget validator access”
revokes that grant and removes the local credentials; a network error requires checking
revocation on the PC. Existing sessions/key login remain compatible after rerunning
the additive D1 schema and deploying the version-2 Worker. Existing proposals are kept.

The first service version caps submissions at five attempts per IP/day, 100/day
in total and 200 pending contributions. A daily Cron deletes expired rate counters,
sessions and submissions after 30 days. Check actual CPU usage on Workers Free
before opening submissions publicly; local tests cannot establish the 10 ms limit.

An offline maintainer fallback remains available:
`community_profiles.py approve submission.zip --catalog-root <checkout>`.
This reads only expected ZIP members without extraction; it does not publish Git.

A custom `config/community-source.json` may specify `repository`, `ref`, and `api`
(an HTTPS origin). Custom catalogue overrides are preserved; they must explicitly
supply their own API to use submissions. Cached catalogues from a different source
and validator sessions from another API are never reused. Existing installations
pointing explicitly at the former `community-presets` branch should update this file.

The automated tests simulate catalogue networking, exports, review/import,
hash/content/path rejection, cache fallback, preservation of local edits,
menu routing, Pad2Key restoration and ReShade preset backup/application. Real
controller and game behavior must still be checked on Batocera.
