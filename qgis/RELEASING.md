# Releasing FastNSA for QGIS

This maintainer guide describes GitHub Releases, not submission to the official
QGIS plugin repository. User-facing installation steps belong in
[Installation](docs/installation.md).

## Source-Only Review Candidate

Version 0.1.1 adds `--distribution external` to the packager and a separate
`fastnsa-official-repository-candidate` CI artifact. This ZIP contains no
FastNSA package, native library, wheel, or compiled cache. Validate it using the
commands in [Development](DEVELOPMENT.md) and test both missing dependencies and
an installed FastNSA 0.3.0 runtime in clean QGIS profiles.

Do not upload a self-contained platform ZIP to the official repository.
Do not assume that excluding binaries guarantees approval: the
[publishing requirements](https://plugins.qgis.org/docs/publish/) allow declared
external dependencies, while the
[approval guidance](https://plugins.qgis.org/docs/approval) has stricter wording
about binaries. Explain the external open-source PyPI runtime to QGIS reviewers
and obtain guidance before submitting. The security scan and manual review are
still required. The candidate is not automatically uploaded or approved.

Before upload, run the [security precheck](DEVELOPMENT.md#security-precheck)
on the final source-only ZIP and keep its checksum-linked report. A local
pass with warnings is not the official scan result or approval. Do not add
blanket scanner exclusions just to make the report appear clean.
CI uploads `fastnsa-official-repository-candidate` only after this precheck
passes. Keep the separate `fastnsa-source-security-report` summary with the
matching ZIP checksum and source commit. Neither artifact is an approval.
CI reviews only the exact provenance SHA supplied independently by GitHub;
it remains visible in the report and does not exempt other secret findings.

Retain the `fastnsa_qgis` plugin ID and use a new version; do not move 0.1.0's
published tag or replace its installers. An old bundled installation must be
removed cleanly before testing the source-only variant. User instructions are
in [External Runtime](docs/external-runtime.md).

## Repository Setup

1. Enable GitHub Actions in **Settings > Actions > General**. If the repository
   has an Actions allowlist, permit `actions/checkout`, `actions/setup-python`,
   `actions/upload-artifact`, and `actions/download-artifact`.
2. Check that organization policies permit the release job's explicit
   `contents: write` permission. Other jobs retain `contents: read`. Do not grant
   blanket write permission to all workflows merely to enable this release.
3. No PyPI account, Trusted Publisher, PAT, repository secret, or GitHub
   Environment is needed. The runtime is downloaded from public PyPI; the draft
   release uses the automatically generated `GITHUB_TOKEN` via `github.token`.
4. The obsolete `FASTNSA_RUNTIME_PUBLISHED` variable may be removed. It is no
   longer consulted because the locked runtime is already published.

An Environment is optional, not a build machine or a dependency environment.
If an additional approval gate is wanted later, configure an Environment first
and explicitly reference it on `github-release` in `release.yml`. Restrict its
deployment rules to **Tag** `v*`, not **Branch** `v*`. Availability of approval
rules in a private repository depends on the GitHub plan. The current workflow
deliberately requires no such environment and only creates a **draft**; manual
publication is the final release gate.

GitHub references: [workflow token permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token),
[reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
and [deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

## Prepare the Source

- Set the stable version in `qgis/fastnsa_qgis/metadata.txt`; set
  `experimental=False` and `deprecated=False`.
- Add `qgis/releases/<version>.md` and update user documentation and the metadata
  changelog. Do not put CI setup or historical candidate debugging in READMEs.
- Update `runtime-lock.json` only after the matching FastNSA version is on PyPI.
  Record each supported wheel's exact filename and SHA-256 from PyPI and the
  expected native ABI. Runtime version and plugin version are independent.
- Run `python -m unittest discover -s tests/packaging -t . -v` and commit/push
  the reviewed changes to `main`.

The packager rejects incorrect wheel filenames, metadata versions, and hashes.
Native-library development builds are marked `runtime_lock_verified: false`
and cannot be used by the release assembler.

## Build and Validate Before Tagging

1. Wait for **QGIS plugin checks and packages** on `main` to pass. It packages
   Linux x86_64 and Windows AMD64 from hash-locked PyPI wheels and runs isolated
   mapping, K/ST K-function, and ADA/LION runtime checks.
2. Run **Prepare FastNSA QGIS release** manually on `main`. Manual runs perform
   preflight, both platform builds, and full artifact assembly, but **never**
   create a GitHub Release, even if a tag is selected in the UI.
3. Download `fastnsa-qgis-release-<version>` from that run and extract the outer
   Actions ZIP. Install only an inner `fastnsa_qgis-<version>-<platform>.zip`.
4. In clean QGIS profiles on Windows and Linux/WSL, check installation, icon,
   four Processing tools, each of the four analysis workflows, background and
   cancellation controls, optional Matplotlib 3D, and startup after a restart.
5. Record the tested commit, archive SHA-256, QGIS/Python/NumPy versions,
   platform, and outcome in the maintainer's acceptance record. A runtime report
   with `qgis_gui_acceptance: pending` is normal: CI does not certify GUI tests
   or silently claim manual acceptance.

There must be no source changes between accepted builds and the release tag.
Tag builds are rebuilt and validated rather than reusing an earlier run's ZIP;
timestamps and source-ref provenance may differ. Smoke-test the final tag-built
ZIPs before making the draft public. Never edit build or validation reports to
make an untested artifact appear accepted.

## Create the Release Draft

After approval of the exact commit, create an annotated tag such as `v0.1.0`
and push that tag. Do not do this during the initial code-preparation step.

The tag must match metadata exactly and its commit must be reachable from
`main`. The workflow only creates releases in `fastnsa/FastNSA-QGIS`. It
rebuilds both archives and verifies versions, source commit, runtime hashes,
ABI, checksums, embedded build information, and runtime reports before drafting.

The public draft contains only four download assets:

- Linux and Windows installable plugin ZIPs;
- the matching per-archive `.zip.sha256` files.

Release notes are used as the page body, not uploaded as another attachment.
The complete verified bundle, including build information, runtime reports,
`manifest.json`, `SHA256SUMS`, and release notes, remains in the Actions artifact
`fastnsa-qgis-release-<version>` for 90 days. Archive that artifact separately
before expiration if long-term maintenance evidence is needed. Do not upload
its aggregate checksum inventory by itself alongside the four public assets:
it also references the maintenance files that are not public attachments.

Local `release_plugin.py verify` requires this full CI bundle, not just the
four public downloads. End users can check each installer with its individual
`.zip.sha256` file. The plugin archive itself also retains `build-info.json`.

After final ZIP smoke tests, review the draft notes and assets, then select
**Publish release**. A draft release is not public; neither are releases in a
private repository. Making the repository public is a separate owner decision.
GitHub's automatic source ZIP is not the installable plugin.

## Failure Handling

Fix failed builds before tagging. Do not change a published runtime wheel,
bypass hash checks, or move an existing release tag. If draft creation fails,
inspect the job before retrying. The workflow does not overwrite an existing
release or upload replacement assets automatically. Existing drafts must be
reviewed explicitly; a partial failure is not permission to replace assets.

The bundle helper only prepares and verifies files. Local inspection is possible
without GitHub credentials:

```bash
python qgis/release_plugin.py preflight
python qgis/release_plugin.py verify --bundle-dir /path/to/extracted-bundle \
  --source-commit <full-commit-sha> --source-ref refs/tags/v0.1.0
```
