# Community profiles

The interface stays inside each tool: **AntiMicroX → Community profiles** and
**ReShade → Community presets** (also available from a configured ReShade game).
There is no additional shared entry in the Toolbox main menu.

A single schema-1 JSON catalogue on the repository's `community-presets` branch
contains both file types. Files are downloaded directly from GitHub's raw URLs;
no API key, contributor token, paid host or database server is required. This
uses no per-file REST API calls. Limits still apply to the GitHub service.

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

Sharing prepares a ZIP and a companion text file in `exports/community/`, with
a GitHub issue URL and no automatic upload. Authors enter public metadata and
review it before creating the package. AntiMicroX controller identities are
removed from the copy; originals are unchanged. ReShade export uses the
existing manager to synchronize and export the game's preset before packaging.

Maintainers review the issue and can validate/promote the ZIP locally with
`community_profiles.py approve submission.zip --catalog-root <checkout>`.
Only expected archive members are read, never extracted. This writes a profile
and manifest entry locally; publishing still requires a normal Git commit.

To move the catalogue to another public GitHub repository, create
`config/community-source.json` with `repository` in `owner/name` form and `ref`
set to a branch/tag name without slashes. The same catalogue schema and folder
layout are required. A cache from another source is never reused.

The automated tests simulate catalogue networking, exports, review/import,
hash/content/path rejection, cache fallback, preservation of local edits,
menu routing, Pad2Key restoration and ReShade preset backup/application. Real
controller and game behavior must still be checked on Batocera.
