RELEASING
=========

Release pipeline
----------------

Releases are fully automated via GitHub Actions. No local tagging or script execution is needed.

1. Go to **Actions → Release → Run workflow**.
2. Choose `major`, `minor`, or `patch`.
3. The workflow:
   - Bumps `VERSION` on a `release/vX.Y.Z` branch,
   - Opens a PR to `main` titled `Release: bump to vX.Y.Z`,
   - Enables auto-merge (squash) on that PR.
4. CI runs automatically on the PR. The CI job is a required check that gates the merge.
5. Once CI is green, GitHub auto-merges the PR.
6. The `Tag and publish` workflow fires on merge:
   - Verifies the tag does not already exist,
   - Creates and pushes the annotated tag `vX.Y.Z`,
   - Builds and pushes `ghcr.io/<owner>/rm-manager:X.Y.Z`,
   - Also pushes `:latest` unless the version contains a `-` prerelease suffix.

Prerelease images
-----------------

For a prerelease, edit `VERSION` manually (e.g. `1.7.0-rc.1`), commit it on a `release/`
branch, open a PR, and merge. The `Tag and publish` workflow will create the tag and push
the versioned image but will **not** update `:latest`.

Publishing release notes
------------------------

After the tag is created, create a GitHub Release from the tag via the UI or:

```bash
gh release create vX.Y.Z --generate-notes
```

Versioning
----------

Follow SemVer (`vMAJOR.MINOR.PATCH`):
- **MAJOR**: breaking changes.
- **MINOR**: new backwards-compatible features.
- **PATCH**: bug fixes.

The `VERSION` file at repo root is the single source of truth. The release workflow
reads it after merge to determine the tag; do not rely on git tags alone.

Required GitHub settings
------------------------

These must be configured once in the repository UI before the release pipeline works.

**Settings → General → Pull Requests**
- Allow auto-merge: enabled

**Settings → Branches → Branch protection rule for `main`**
- Require a pull request before merging
- Require status checks to pass before merging
  - Add the CI job as a required check. The check name follows the format
    `<workflow name> / <job name>` as shown in the Actions run UI (e.g. `CI / test`).
- Require branches to be up to date before merging
- Do not allow bypassing the above settings

**Settings → Actions → General → Workflow permissions**
- Read and write permissions
- Allow GitHub Actions to create and approve pull requests

Troubleshooting
---------------

- **Auto-merge did not trigger**: confirm that auto-merge is enabled in Settings → General
  → Pull Requests, and that the CI job appears as a required status check in the branch
  protection rule for `main`.
- **Tag already exists**: the `Tag and publish` workflow will fail with a clear error. Delete
  the remote tag (`git push origin :vX.Y.Z`) before re-running, or cut a new version.
- **Docker push fails**: verify that `packages: write` is granted and that the organization
  allows Actions to publish packages.
