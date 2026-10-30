# Development

## Environment

Use Python 3.11 or newer. QGIS integration tests must run in a Python
environment with QGIS, NumPy, and a compatible FastNSA runtime available.
Packaging tests use only Python's standard library.

## Build a Plugin ZIP

### Source-Only Candidate

Build without a wheel, native library, QGIS, or NumPy:

```bash
python qgis/package_plugin.py --distribution external --output-dir dist/source
python qgis/validate_package.py dist/source/<plugin-archive>.zip
```

This validates archive structure, file names and executable headers, the size
limit, and importing the entry point without FastNSA, NumPy, or QGIS. A
`runtime_smoke_test: not_run_external_dependency` result is deliberately not a
native-runtime pass. To additionally test an installed external runtime:

```bash
python qgis/validate_package.py dist/source/<plugin-archive>.zip \
  --external-runtime-root /path/to/site-packages-or-target-directory
```

The validation interpreter must have NumPy. The validator exercises mapping,
K/ST K-function and ADA/LION using FastNSA outside the plugin archive. This does
not replace clean-profile GUI acceptance or official security/manual approval.

### Self-Contained GitHub Package

Choose the exact published FastNSA wheel listed for the packaging host in
`runtime-lock.json`. Packaging verifies its filename, SHA-256, and metadata
version before extracting any runtime files. Locally rebuilt or modified wheels
are intentionally rejected unless the lock is explicitly updated for testing.

```bash
python qgis/package_plugin.py --wheel /path/to/fastnsa-platform.whl --output-dir dist
python qgis/validate_package.py dist/<plugin-archive>.zip
```

The packager extracts the lightweight runtime and native dependencies into the
plugin ZIP. It also writes SHA-256 and build-information sidecars. The
validator checks archive integrity and runs the bundled runtime in isolation.

The wheel-based command does not require a FastNSA source checkout. The
`--native-library` development mode requires the matching Python sources and
native library, so use `--wheel` when working in this repository alone.

## Security Precheck

Scan the **built source-only ZIP**, not the whole development checkout or a
self-contained ZIP. This includes the exact Python files, metadata, JSON,
and user guides that will be uploaded. The check never imports plugin code.

Install the maintainer tools into a separate virtual environment, not QGIS:

```bash
python3 -m venv /tmp/fastnsa-security-tools
/tmp/fastnsa-security-tools/bin/python -m pip install -r qgis/security-requirements.txt
python3 qgis/package_plugin.py --distribution external --output-dir dist/security-source
/tmp/fastnsa-security-tools/bin/python qgis/scan_package.py \
  dist/security-source/fastnsa_qgis-0.1.1-qgis-repository.zip --output-dir dist/security-reports \
  --expected-source-commit "$(git rev-parse HEAD)"
```

For an uncommitted build, add `--source-commit working-tree` to the packaging
command. For release checks, build from the final committed source instead.
Omit `--expected-source-commit` for a `working-tree` build. On Windows,
provide the full SHA from `git rev-parse HEAD` as the option value.
Use new output directories on a repeat run: neither archives nor reports are
overwritten. On Windows, use the virtual environment's `Scripts/python.exe`.

The report includes the archive SHA-256, source commit, tool versions and
return codes, and full Bandit, detect-secrets, and Flake8 output. Secret
verification via network calls is disabled; all archive files are scanned.
No custom baseline, hidden configuration, inline `nosec`, or inline `noqa`
suppression is used. Other standard tool defaults apply, including built-in
Flake8 style defaults and secret-detection heuristics. Scans do not upload
results anywhere.

CI runs the same precheck on the final `source-dist/*.zip` after structural
validation, using `security-requirements.txt` in the isolated build runner.
The source candidate is uploaded only if the precheck succeeds. Download
`fastnsa-source-security-report` for `summary.json`, including the archive
SHA-256, source commit, findings counts and tool versions. A findings failure
still uploads its summary; an incomplete tool run may have no summary and
must not be treated as a pass. Raw reports stay on the runner, since they
may contain code snippets or potential secrets. Reproduce locally to inspect
them. Reports are separate from installer and GitHub release assets.

The **local** gate fails on any Bandit finding, unreviewed potential secret, Bandit
scan error, or Flake8 `F*`/`E9*` finding. Other Flake8 findings remain visible
warnings. For example, a report with only `E501` long lines is
`passed_with_warnings`, not a claim that strict Flake8 passed. Executable-file
flags also remain warnings. Tool crashes, incomplete output, and timeouts
cannot produce a passing report. Review raw reports before sharing them.

CI supplies `--expected-source-commit "$GITHUB_SHA"` independently of the ZIP.
Only a `Hex High Entropy String` finding on the exact `build-info.json`
`source_commit` field, whose value and finding fingerprint match that full
SHA, is classified as reviewed provenance. A mismatched expected commit
fails the check. Findings elsewhere, other detectors, and other values in
that same file still block the candidate. The raw scan is never filtered;
the summary retains total findings, reviewed provenance locations and
unreviewed findings separately. A reviewed SHA is a visible warning, not
a claim that detect-secrets found nothing.

These checks do not certify dependencies, native libraries, GUI behavior, or
official repository acceptance. The official server may use different tool
versions and rule settings. See its
[security tools](https://plugins.qgis.org/docs/security-scanning/tools) and
[rule reference](https://plugins.qgis.org/docs/security-scanning/rules).

## Run Tests

Run the archive-packaging tests from the repository root:

```bash
python -m unittest discover -s tests/packaging -t . -v
```

For QGIS integration tests, install the matching wheel into a local runtime
directory in the QGIS Python environment:

```bash
python -m pip install --no-deps --target cache/runtime /path/to/fastnsa-platform.whl
```

Set `FASTNSA_PYTHON_ROOT` to the absolute path of `cache/runtime`. Add this
repository's `qgis/` directory and QGIS's own Python paths to `PYTHONPATH`,
then run:

```bash
python -m unittest discover -s tests/qgis -t . -v
```

For explicit source development instead, add `python/` to PYTHONPATH and set
`FASTNSA_DEVELOPMENT_MODE=1`; an intentional `FASTNSA_LIBRARY_PATH` override is
allowed only in an unpackaged development checkout. Published packages do not
search ancestor directories for arbitrary source checkouts or accept a native
library override. Do not remove/reload FastNSA modules to switch native code.

Do not use those source-testing overrides for clean-profile ZIP acceptance.
Install only the built ZIP in a new QGIS profile for GUI validation.

Source-only setup automatically checks the exact versioned user directory
documented in [External Runtime](docs/external-runtime.md). A first activation
can register the provider immediately with **Check again** or **Save and enable**.
Once any FastNSA modules or a native import attempt exist in the process,
switching their location requires restarting QGIS. Unloaded plugin-local
leftovers are reported and skipped, not deleted. Do not work around these guards
by removing modules or unloading libraries.

## Build and Release Automation

The GitHub Actions workflow runs packaging tests and Linux/Windows package
builds on pushes and pull requests. It downloads FastNSA from PyPI using
`--require-hashes`; the packager independently rechecks the selected wheel.
There is no `FASTNSA_RUNTIME_PUBLISHED` variable or external secret to configure.

The release workflow reuses these checks. A manual run only assembles a release
bundle; a matching version-tag push also creates a draft GitHub Release. See
[Releasing](RELEASING.md) for repository setup, validation, and publication steps.

The separately named `fastnsa-official-repository-candidate` artifact is
source-only. The existing GitHub release assembler continues to collect only
the two self-contained platform artifacts, so it cannot accidentally mix the
new candidate into the released installer/checksum set. No official upload is
automated in this branch.
