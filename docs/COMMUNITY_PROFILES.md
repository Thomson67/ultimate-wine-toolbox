# Community profiles

The interface stays inside each tool: **AntiMicroX → Community profiles** and
**ReShade → Community presets** (also available from a configured ReShade game).
There is no additional shared entry in the Toolbox main menu.

A single schema-1 JSON catalogue in `Thomson67/ultimate-wine-toolbox-community`
(branch `main`) contains both file types. Downloads use GitHub raw URLs directly;
no account or API key is required for readers. The Cloudflare Worker only handles
submissions and moderation. Each tool keeps its own community menu.

Service deployment instructions, schema, sources and a ready-to-paste bundle:
https://github.com/Thomson67/ultimate-wine-toolbox-community/blob/main/service/INSTALLATION_FR.md

## Read and import

First browsing downloads the catalogue; subsequent browsing/search uses the
local cache in `state/community/catalog.json`. Refresh is explicit. A failed or
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

ReShade must already be configured for the game. Applying an imported preset
first exports the previous preset to `exports/community-backups/`, then uses
the existing ReShade import mechanism. Shader packs are not installed
automatically by this menu. Dependencies are displayed before download.

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

Sharing creates a local ZIP in `exports/community/`, removes controller identities
from the exported copy, then sends the profile and public metadata over HTTPS after
explicit confirmation. No GitHub account is needed. ReShade uses the existing
manager to synchronize and export the preset first. Direct sharing accepts 64 KiB
profiles. The original file is unchanged. Failed or uncertain sends keep the ZIP;
“Retry a saved package” resubmits its same identifier and checksum. A successful
response writes a local `.receipt.json`. No automatic resend happens at startup.

The private D1 queue is visible only after validator login. Each tool's validator
menu shows only its own type and displays all mappings or the full preset. Approval
publishes both profile and manifest in one non-forced Git commit; rejection publishes
nothing. Authors' nicknames are self-declared. The service forbids `execute` and
`loadprofile`, but keyboard macros still require human review.

The validator key is a generated 256-bit random secret entered through a password
prompt, never a command argument. Its SHA-256 verifier and the repository-scoped
GitHub token live only in Cloudflare secrets. A hashed random session token lives
in D1; its client copy is mode 0600 in `state/community/validator-session.json`,
expires after 30 minutes and is revoked/deleted when leaving moderation. Login
tracing is disabled. The key is never saved by the Toolbox. Do not substitute a
human-chosen password for the generated random key.

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
