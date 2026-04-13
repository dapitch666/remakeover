RELEASING
=========

Overview
--------
Quick procedure for tagging, publishing the Docker image via GitHub Actions, and versioning best practices.

Tagging and pushing
-------------------

Create an annotated tag locally and push it:

```bash
# create an annotated tag
git tag -a v0.6.0 -m "Release v0.6.0"
# push the tag to origin
git push origin v0.6.0
```

Pushing the tag will trigger the `Build and publish Docker image` workflow, which:
- determines the version (tag name without the `v` prefix),
- builds the image via `docker/build-push-action`,
- pushes `ghcr.io/<OWNER>/rm-manager:<version>` and `...:latest`.

The workflow can also be triggered manually from GitHub Actions (`workflow_dispatch`) with an optional version override.

Keeping `VERSION`
-----------------

- The `VERSION` file is for local use only. The workflow derives the version from the Git tag.
- Optional: update `VERSION` before tagging for consistency:

```bash
echo "0.6.0" > VERSION
git add VERSION
git commit -m "Bump VERSION to 0.6.0"
git tag -a v0.6.0 -m "Release v0.6.0"
git push origin main --follow-tags
```

Publishing release notes
------------------------

- After pushing the tag, create a Release on GitHub (UI) or via `gh` to add notes/CHANGELOG.

Recommended publishing rules
-----------------------------

- Use SemVer (`vMAJOR.MINOR.PATCH`).
- Publish Docker images only for release tags (`v*`).
- Keep `latest` pointing to the last stable release.
- A separate CI workflow (`.github/workflows/ci.yml`) runs on every push/PR and executes the tests without pushing any Docker image.

Quick troubleshooting
---------------------

- Check Actions → Runs to view workflow logs.
- Verify that `packages: write` is granted (workflow permissions) and that the organization allows Actions to publish packages.
- If the push to GHCR fails, consider using a temporary PAT (`write:packages`) to isolate the issue.

FAQ
---

- Q: “Do I need to update `VERSION`?” — Not strictly necessary if you tag, but helpful for local consistency.
- Q: “Can I build from `main`?” — Yes, but keep nightly builds and releases separate (tag → publish).

Versioning & CHANGELOG
-----------------------

- **SemVer**: follow `MAJOR.MINOR.PATCH`.
  - **MAJOR**: breaking changes.
  - **MINOR**: new backwards-compatible features.
  - **PATCH**: bug fixes and small corrections.

- **Pre-releases**: use suffixes `-rc.N`, `-beta.N` (e.g. `v1.2.0-rc.1`). Decide whether to publish images for these tags.

- **CHANGELOG**: maintain `CHANGELOG.md` or generate it automatically via:
  - `Release Drafter` (drafts release notes from PRs),
  - `semantic-release` (generates changelog and publishes automatically, based on Conventional Commits),
  - custom scripts (collects PR titles/labels).

- **Recommended procedure**:
  1. Update `CHANGELOG.md` and `VERSION` (optional).
  2. Commit + annotated tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
  3. `git push origin vX.Y.Z` → Actions publishes the image.

- **Publishing policy**:
  - Publish only for official tags.
  - Do not rewrite public tags (prefer a new version instead).
  - For testing, use `snapshot-YYYYMMDD` tags rather than reusing `latest`.

- **Automation**:
  - Integrate `Release Drafter` for automatic Release drafts.
  - Option: `semantic-release` to automate bump/versioning/changelog (requires Conventional Commits discipline).

Example commands
----------------

```bash
# Use the provided script (recommended)
./scripts/bump_version.sh minor --commit --push

# OR manually
echo "1.2.3" > VERSION
git add VERSION CHANGELOG.md
git commit -m "Release: bump to 1.2.3"
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
```

The `bump_version.sh` script accepts `major`, `minor`, or `patch` and automatically handles updating `VERSION`, committing, creating an annotated tag, and pushing (`--commit`, `--push`).
