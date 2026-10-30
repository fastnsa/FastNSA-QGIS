"""Run offline security prechecks on the contents of a source-only plugin ZIP."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib import metadata
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

from package_policy import MAX_SOURCE_ARCHIVE_BYTES, check_source_archive


COMMANDS = {
    "bandit": ["bandit", "--recursive", "fastnsa_qgis", "--ignore-nosec", "--format", "json"],
    "detect-secrets": ["detect_secrets", "scan", "--all-files", "--no-verify", "fastnsa_qgis"],
    "flake8": ["flake8", "--isolated", "--disable-noqa", "--jobs", "1", "fastnsa_qgis"],
}
REPORT_NAMES = {"bandit": "bandit.json", "detect-secrets": "detect-secrets.json", "flake8": "flake8.txt"}


def review_commit_findings(secrets, build_info_text, expected_source_commit):
    """Recognize only the exact, externally trusted provenance field, not other hex strings."""
    if expected_source_commit is None:
        return []
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_source_commit):
        raise ValueError("Expected source commit must be a full Git SHA")
    if json.loads(build_info_text).get("source_commit") != expected_source_commit:
        raise ValueError("Archive source commit does not match the expected source commit")
    filename = "fastnsa_qgis/build-info.json"
    lines = build_info_text.splitlines()
    fingerprint = hashlib.sha1(expected_source_commit.encode("ascii"), usedforsecurity=False).hexdigest()
    reviewed = []
    for row in secrets.get("results", {}).get(filename, []):
        line = row.get("line_number")
        if (row.get("filename") == filename and row.get("type") == "Hex High Entropy String"
                and row.get("hashed_secret") == fingerprint
                and type(line) is int and 1 <= line <= len(lines)
                and re.fullmatch(r'\s*"source_commit"\s*:\s*"' + expected_source_commit
                                 + r'"\s*,?\s*', lines[line - 1])):
            reviewed.append({
                "filename": filename, "line_number": line, "type": row["type"],
                "reason": "Exact provenance SHA matches the externally supplied source commit",
            })
    return reviewed


def summarize(bandit, secrets, lint_text, return_codes, reviewed_commit_findings=()):
    """Keep every finding; warnings are not presented as a clean lint result."""
    if not isinstance(bandit.get("results"), list) or not isinstance(bandit.get("errors"), list):
        raise ValueError("Incomplete Bandit report")
    if bandit.get("metrics", {}).get("_totals", {}).get("loc", 0) <= 0:
        raise ValueError("Bandit did not report scanning Python code")
    if not isinstance(secrets.get("results"), dict) or not secrets.get("plugins_used"):
        raise ValueError("Incomplete detect-secrets report")
    lint_codes = Counter()
    for line in lint_text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r".+:\d+:\d+: ([A-Z]\d+) .+", line)
        if match is None:
            raise ValueError("Unrecognized Flake8 output; inspect flake8.txt")
        lint_codes[match[1]] += 1
    if return_codes["bandit"] == 1 and not (bandit["results"] or bandit["errors"]):
        raise ValueError("Bandit failed without reporting a finding")
    if return_codes["flake8"] == 1 and not lint_codes:
        raise ValueError("Flake8 failed without reporting a finding")
    security_findings = len(bandit["results"])
    secret_findings = sum(len(rows) for rows in secrets["results"].values())
    unreviewed_secrets = secret_findings - len(reviewed_commit_findings)
    if unreviewed_secrets < 0:
        raise ValueError("Reviewed findings exceed the secret scan findings")
    lint_errors = sum(count for code, count in lint_codes.items()
                      if code.startswith(("F", "E9")))
    blockers = security_findings + unreviewed_secrets + lint_errors + len(bandit["errors"])
    return {
        "bandit_findings": security_findings,
        "bandit_errors": len(bandit["errors"]),
        "bandit_by_rule": dict(Counter(row["test_id"] for row in bandit["results"])),
        "potential_secrets": secret_findings,
        "unreviewed_potential_secrets": unreviewed_secrets,
        "reviewed_commit_hash_findings": list(reviewed_commit_findings),
        "flake8_findings": sum(lint_codes.values()),
        "flake8_by_code": dict(sorted(lint_codes.items())),
        "flake8_local_gate_errors": lint_errors,
        "local_gate": "failed" if blockers else "passed",
        "status": ("failed" if blockers else "passed_with_warnings"
                   if lint_codes or reviewed_commit_findings else "passed"),
    }


def scan_archive(archive_path, output_dir, *, expected_source_commit=None):
    """Scan without importing plugin code or performing credential verification."""
    archive_path = Path(archive_path).resolve()
    output_dir = Path(output_dir).absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Refusing to overwrite an existing report directory")
    versions = {name: metadata.version(name) for name in COMMANDS}
    if archive_path.stat().st_size > MAX_SOURCE_ARCHIVE_BYTES:
        raise ValueError("Source archive exceeds the 25 MB package limit")
    with archive_path.open("rb") as stream:
        data = stream.read(MAX_SOURCE_ARCHIVE_BYTES + 1)
    if len(data) > MAX_SOURCE_ARCHIVE_BYTES:
        raise ValueError("Source archive exceeds the 25 MB package limit")
    with tempfile.TemporaryDirectory(prefix="fastnsa-security-") as temporary:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            check_source_archive(archive)
            python_files = sum(name.endswith(".py") for name in archive.namelist())
            if not python_files:
                raise ValueError("No Python files in source archive")
            build_info_text = (archive.read("fastnsa_qgis/build-info.json").decode("utf-8")
                               if "fastnsa_qgis/build-info.json" in archive.namelist() else "{}")
            build_info = json.loads(build_info_text)
            review_commit_findings({}, build_info_text, expected_source_commit)
            executable_files = [info.filename for info in archive.infolist()
                                if not info.is_dir() and (info.external_attr >> 16) & 0o111]
            archive.extractall(temporary)
        output_dir.mkdir(parents=True)
        outputs, return_codes = {}, {}
        for name, arguments in COMMANDS.items():
            result = subprocess.run(
                [sys.executable, "-I", "-m", *arguments], cwd=temporary,
                capture_output=True, text=True, encoding="utf-8", timeout=180,
                check=False,
            )
            (output_dir / REPORT_NAMES[name]).write_text(result.stdout, encoding="utf-8")
            (output_dir / (name + ".stderr.txt")).write_text(result.stderr, encoding="utf-8")
            allowed = {0} if name == "detect-secrets" else {0, 1}
            if result.returncode not in allowed:
                raise ValueError(f"{name} failed to run; inspect its report and stderr")
            outputs[name] = result.stdout
            return_codes[name] = result.returncode
        secrets = json.loads(outputs["detect-secrets"])
        reviewed = review_commit_findings(secrets, build_info_text, expected_source_commit)
        summary = summarize(json.loads(outputs["bandit"]), secrets,
                            outputs["flake8"], return_codes, reviewed)
        if executable_files and summary["status"] == "passed":
            summary["status"] = "passed_with_warnings"
        summary.update({
            "schema_version": 2,
            "scanned_at_utc": datetime.now(timezone.utc).isoformat(),
            "archive": archive_path.name,
            "archive_sha256": hashlib.sha256(data).hexdigest(),
            "archive_source_commit": build_info.get("source_commit"),
            "expected_source_commit": expected_source_commit,
            "python_files": python_files,
            "executable_members": executable_files,
            "tool_versions": versions,
            "tool_return_codes": return_codes,
            "credential_network_verification": False,
            "official_security_scan": "not_run",
            "official_approval": "not_assessed",
            "local_policy": (
                "Any Bandit finding, unreviewed potential secret, Bandit scan error, or Flake8 F*/E9* "
                "finding fails the local gate. Other Flake8 findings and executable-file "
                "flags remain visible warnings. No custom baseline, rule exclusion, or inline "
                "suppression is used; standard tool defaults apply. Only a Hex High Entropy "
                "String on the exact build-info.json source_commit field matching an externally "
                "supplied full Git SHA is reviewed as provenance; raw findings are preserved."
            ),
        })
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source-commit", help="Trusted full Git SHA, supplied outside the ZIP.")
    args = parser.parse_args()
    try:
        summary = scan_archive(args.archive, args.output_dir,
                               expected_source_commit=args.expected_source_commit)
    except (OSError, ValueError, metadata.PackageNotFoundError,
            zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        print(f"Security precheck could not finish: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0 if summary["local_gate"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
