# Development

## Environment

Use Python 3.11 or newer. QGIS integration tests must run in a Python
environment with QGIS, NumPy, and a compatible FastNSA runtime available.
Packaging tests use only Python's standard library.

## Build a Plugin ZIP

Choose a tested FastNSA wheel matching the version in `runtime-lock.json`
and the packaging host's operating system and CPU architecture. Wheels can be
obtained from the FastNSA build artifacts or a published package release.

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

## Candidate Automation

The GitHub Actions workflow runs packaging tests on pushes and pull requests.
Candidate builds are enabled only when the repository Actions variable
`FASTNSA_RUNTIME_PUBLISHED` is set to `true`. Before enabling it, verify the
package ownership and availability of the pinned FastNSA version on PyPI.
If wheels are hosted elsewhere, configure and verify that download source
before enabling candidate builds.

Candidate builds run on Linux and Windows. Isolated runtime validation does
not replace manual QGIS acceptance. See [Dependencies](DEPENDENCIES.md) for
runtime requirements and distribution restrictions.
