# Release process

Ultimate Wine Toolbox uses the following release convention:

- integration development versions: `X.Y.Z-devN` on `test`
- topic branches may retain a stable baseline while testing a scoped patch installer
- stable versions: `X.Y.Z` on `main`
- GitHub release tags: `vX.Y.Z`

## Normal release workflow

1. Develop on `test` or a topic branch, validate it, and integrate the intended changes into `test`.
2. Set `VERSION` to the final stable version (for example `0.1.1`).
3. Merge `test` into `main`.
4. GitHub Actions automatically:
   - validates the shell/Python sources;
   - builds `Ultimate-Wine-Toolbox-vX.Y.Z.zip`;
   - generates `Ultimate-Wine-Toolbox-vX.Y.Z.zip.sha256`;
   - creates the `vX.Y.Z` GitHub Release, or refreshes its assets if it already exists.

No ZIP or checksum needs to be created manually. The workflow also runs on
README/release-note changes pushed to `main` and can replace assets for the
current version: prepare the intended new VERSION and matching release notes
before promoting branch-only features. Publish new features under a new version rather than retroactively changing
the scope of an existing release.

## Documentation and validation before promotion

- Review all eight `toolbox/docs/fr/*.txt` and `toolbox/docs/en/*.txt` topics,
  both root README files, and relevant technical/community guides.
- Keep menu paths, file locations, limits and examples consistent with the code.
  Distinguish local ZIP transfer from a moderated community submission.
- Record what was actually checked on hardware separately from simulated tests.
  Preserve historical release notes instead of rewriting their feature scope.
- Run the shell/Python checks and relevant tests used by the release workflow.
  For a scoped installer, verify upgrade from the previous published source,
  repeated installation, copied runtime/hook files and restoration.
- Keep topic-branch docs and any standalone test installer in that branch until
  promotion is requested. Updating them alone does not create a stable release.

## Development installation

To install the current `test` branch on Batocera:

```bash
curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/test/install.sh | WT_INSTALL_CHANNEL=test bash
```

The normal public installation command always installs the latest stable GitHub Release:

```bash
curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/main/install.sh | bash
```

## Update assets

Stable releases must contain both:

```text
Ultimate-Wine-Toolbox-vX.Y.Z.zip
Ultimate-Wine-Toolbox-vX.Y.Z.zip.sha256
```

The Toolbox updater requires the SHA-256 asset and refuses an update when verification fails or the checksum is missing.
