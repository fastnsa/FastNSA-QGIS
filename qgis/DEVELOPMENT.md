# Development

## Environment

Use Python 3.11 or newer. QGIS integration tests must run in a Python
environment with QGIS, NumPy, and a compatible FastNSA runtime available.
Packaging tests use only Python's standard library.

## Build a Plugin ZIP

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

Do not use those source-testing overrides for clean-profile ZIP acceptance.
Install only the built ZIP in a new QGIS profile for GUI validation.

## Build and Release Automation

The GitHub Actions workflow runs packaging tests and Linux/Windows package
builds on pushes and pull requests. It downloads FastNSA from PyPI using
`--require-hashes`; the packager independently rechecks the selected wheel.
There is no `FASTNSA_RUNTIME_PUBLISHED` variable or external secret to configure.

The release workflow reuses these checks. A manual run only assembles a release
bundle; a matching version-tag push also creates a draft GitHub Release. See
[Releasing](RELEASING.md) for repository setup, validation, and publication steps.
