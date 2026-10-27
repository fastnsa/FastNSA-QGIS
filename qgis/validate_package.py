"""Validate a plugin ZIP and smoke-test its runtime without QGIS or source paths."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


SMOKE_TEST = r'''
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import fastnsa
import numpy as np
from fastnsa.bindings import capi
from fastnsa.runtime import NativeNetwork, NativePointSet
from fastnsa.stats.k_function import network_k_function, spatiotemporal_network_k_function
from fastnsa.stats.network_kde import network_kde

if Path(fastnsa.__file__).resolve().parent != root / "fastnsa":
    raise RuntimeError("FastNSA was not imported from the candidate ZIP.")
if not Path(capi.lib._name).resolve().is_relative_to(root):
    raise RuntimeError("The native library was not loaded from the candidate ZIP.")
with NativeNetwork(
    edges=np.array([[0, 1, 100.0]], dtype=np.float64),
    offsets=np.array([0, 1, 2], dtype=np.int32),
    indices=np.array([0, 0], dtype=np.int32),
    coordinates=np.array([[0.0, 0.0], [100.0, 0.0]]),
    geometry_offsets=np.array([0, 2], dtype=np.int32),
) as network:
    with NativePointSet.map_xy(
        network, [10.0, 40.0, 80.0], [1.0, -1.0, 2.0], times=[0.0, 1.0, 3.0]
    ) as points:
        np.testing.assert_array_equal(points.edge_ids_array(), [0, 0, 0])
        np.testing.assert_allclose(points.offsets_array(), [10.0, 40.0, 80.0])
        result = network_k_function(
            network=network, points=points, r_values=[10.0, 50.0],
            simulations=1, random_state=1234,
        )
        if not np.isfinite(result.k_obs).all():
            raise RuntimeError("Network K-function produced non-finite values.")
        result = spatiotemporal_network_k_function(
            network=network, points=points, s_values=[0.0, 50.0],
            t_values=[0.0, 2.0], simulations=0,
        )
        if not np.isfinite(result.k_obs).all():
            raise RuntimeError("ST K-function produced non-finite values.")
        densities = []
        for method in ("ADA", "LION"):
            result = network_kde(
                network=network, points=points, bandwidth=40.0,
                lixel_length=20.0, method=method,
            )
            if not np.isfinite(result.density).all() or (result.density < 0).any():
                raise RuntimeError("NKDV produced invalid density values.")
            densities.append(result.density)
        np.testing.assert_allclose(densities[0], densities[1], rtol=1e-10, atol=1e-10)
print(json.dumps({
    "native_abi": capi.NATIVE_ABI_VERSION,
    "python_version": sys.version.split()[0],
    "numpy_version": np.__version__,
    "runtime_smoke_test": "passed",
    "qgis_gui_acceptance": "pending",
}))
'''


def validate_archive(archive_path: Path) -> dict:
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    expected = archive_path.with_suffix(".zip.sha256").read_text(encoding="ascii").split()[0]
    if checksum != expected:
        raise ValueError("Candidate ZIP checksum does not match its SHA-256 sidecar.")

    with tempfile.TemporaryDirectory(prefix="fastnsa-candidate-check-") as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or "\\" in name
                        or not path.parts or path.parts[0] != "fastnsa_qgis"):
                    raise ValueError(f"Unexpected plugin ZIP member: {name}")
                if any(part in {".git", "__pycache__"} for part in path.parts):
                    raise ValueError(f"Development files in candidate ZIP: {name}")
            archive.extractall(staging)
        plugin = staging / "fastnsa_qgis"
        config = configparser.ConfigParser()
        config.read(plugin / "metadata.txt", encoding="utf-8")
        build_info = json.loads((plugin / "build-info.json").read_text(encoding="utf-8"))
        if config.get("general", "version") != build_info["plugin_version"]:
            raise ValueError("Plugin metadata and build-info versions do not match.")
        environment = os.environ.copy()
        for key in ("PYTHONPATH", "FASTNSA_LIBRARY_PATH", "FASTNSA_PYTHON_ROOT"):
            environment.pop(key, None)
        result = subprocess.run(
            [sys.executable, "-I", "-c", SMOKE_TEST, str(plugin)],
            cwd=staging, env=environment, text=True, capture_output=True, timeout=120,
        )
        if result.returncode:
            raise RuntimeError(f"Isolated runtime smoke test failed:\n{result.stdout}\n{result.stderr}")
        report = {
            **build_info, "archive": archive_path.name, "archive_sha256": checksum,
            **json.loads(result.stdout.strip().splitlines()[-1]),
        }
        if build_info.get("runtime_lock_verified") and report["native_abi"] != build_info["runtime_abi"]:
            raise ValueError("Bundled native ABI does not match the runtime lock.")
    archive_path.with_suffix(".validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", type=Path, nargs="+")
    arguments = parser.parse_args()
    for archive in arguments.archives:
        print(json.dumps(validate_archive(archive), indent=2))


if __name__ == "__main__":
    main()
