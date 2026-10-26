# FastNSA QGIS Plugin

QGIS integration for nearest-edge preprocessing, network density, network
K-function, and spatiotemporal network K-function.

- [Installation and user guide](qgis/README.md)
- [Chinese introduction](qgis/README_ZH.md)
- [Detailed documentation](qgis/docs/index.md)
- [Dependencies](qgis/DEPENDENCIES.md)
- [License](LICENSE)
- [Source repository](https://github.com/fastnsa/FastNSA-QGIS)
- [Issue tracker](https://github.com/fastnsa/FastNSA-QGIS/issues)

## Runtime Boundary

This repository does not duplicate the FastNSA C++ or Python package sources.
`runtime-lock.json` pins the FastNSA version used to build plugin archives.
Publish that runtime first. The generated packaging workflow downloads its
platform wheel from PyPI only after the repository Actions variable
`FASTNSA_RUNTIME_PUBLISHED` is set to `true`. Verify package ownership, version,
and wheel provenance first. If the runtime is distributed elsewhere, configure
that wheel source before enabling candidate builds. Source-packaging tests run
without this opt-in.

```bash
python -m unittest discover -s tests/packaging -t . -v
python -m pip download --only-binary=:all: --no-deps --dest wheelhouse fastnsa==0.2.0
python qgis/package_plugin.py --wheel wheelhouse/<platform-wheel>.whl --output-dir dist
python qgis/validate_package.py dist/<plugin-archive>.zip
```

Use the wheel matching the packaging host. ZIPs include a lightweight runtime
and native dependencies; end users do not need a source checkout. To test the
plugin source in a QGIS environment, install that wheel into `cache/runtime`
with `pip install --target cache/runtime <wheel>` and set `FASTNSA_PYTHON_ROOT`
to its absolute path and `PYTHONPATH` to this repository's `qgis/` plus QGIS's
Python paths. Then run `python -m unittest discover -s tests/qgis -t . -v`.
Do not use these development overrides for clean-profile ZIP acceptance.

The source-packaging tests need only Python's standard library. QGIS tests
need an actual QGIS environment and the pinned runtime; they do not import
tests or sources from the Python package repository.

Before public release, replace draft/private links, review the icon and
notices, archive wheel hashes, and verify the final ZIP on supported hosts.
`EXPORT_PROVENANCE.json` records the source snapshot and file hashes, not
approval to publish. Windows/Linux candidate packaging does not imply macOS
QGIS support.

The self-contained ZIP is for project-controlled distribution. The
[official QGIS plugin repository](https://plugins.qgis.org/docs/publish/)
prohibits bundled binaries; a binary-free variant with external runtime
dependency handling is not implemented yet.
