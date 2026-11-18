#!/usr/bin/env python3
"""Independent pre-publication verification for SHADOW MODEL installers.

Usage:
    python tools/verify_release.py dist/release/SHADOW-MODEL-1.0.0-setup.exe

Exits 0 only when every check passes. The output is JSON so it can be used in CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from release_format import (  # noqa: E402
    MAGIC,
    ReleaseFormatError,
    is_distributable,
    iter_payload,
)


def verify(installer: Path, manifest: Path, expected_version: str | None, expected_sha256: str | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    if not installer.is_file():
        return {"ok": False, "errors": [f"Installer not found: {installer}"], "checks": {}}

    header = installer.open("rb").read(2)
    checks["windows_pe_header"] = header == b"MZ"
    if not checks["windows_pe_header"]:
        errors.append("Installer is not a Windows PE executable.")

    actual_hash = hashlib.sha256()
    with open(installer, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            actual_hash.update(chunk)
    installer_hash = actual_hash.hexdigest()

    payload: dict[str, tuple[int, str]] = {}
    try:
        for name, size, digest in iter_payload(installer):
            payload[name.replace("\\", "/").lower()] = (size, digest)
        checks["payload_readable"] = True
    except (ReleaseFormatError, OSError) as exc:
        payload = {}
        checks["payload_readable"] = False
        errors.append(f"Payload could not be read: {exc}")

    checks["no_private_or_dev_files"] = all(is_distributable(name) for name in payload)
    if not checks["no_private_or_dev_files"]:
        errors.append("Payload contains development, temporary or user-data files.")

    data: dict = {}
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            checks["manifest_present"] = isinstance(data, dict)
        except (ValueError, OSError) as exc:
            checks["manifest_present"] = False
            errors.append(f"Manifest is invalid: {exc}")
    else:
        checks["manifest_present"] = False
        errors.append(f"Manifest not found: {manifest}")

    if checks.get("manifest_present"):
        manifest_version = data.get("version")
        checks["version_matches"] = not expected_version or manifest_version == expected_version
        if not checks["version_matches"]:
            errors.append(f"Manifest version {manifest_version!r} does not match {expected_version!r}.")

        declared = data.get("installer", {})
        declared_hash = str(declared.get("sha256", "")).lower()
        checks["checksum_matches_manifest"] = declared_hash == installer_hash
        if not checks["checksum_matches_manifest"]:
            errors.append("Installer SHA-256 does not match the manifest.")

        if expected_sha256:
            checks["checksum_matches_expected"] = installer_hash == expected_sha256.lower()
            if not checks["checksum_matches_expected"]:
                errors.append("Installer SHA-256 does not match the expected value.")

        required = data.get("required_files")
        checks["required_files_listed"] = isinstance(required, list) and bool(required)
        if not checks["required_files_listed"]:
            errors.append("Manifest has no required_files list.")
        else:
            problems = []
            for item in required:
                if not isinstance(item, dict) or not item.get("path"):
                    problems.append("invalid manifest entry")
                    continue
                relative = str(item["path"]).replace("\\", "/").lower()
                if relative not in payload:
                    problems.append(f"missing: {relative}")
                elif item.get("sha256") and str(item["sha256"]).lower() != payload[relative][1]:
                    problems.append(f"checksum mismatch: {relative}")
            checks["required_files_match"] = not problems
            if problems:
                errors.append("Required file problems: " + "; ".join(problems[:10]))

        critical = data.get("critical_files", [])
        checks["critical_files_present"] = all(str(item).lower() in payload for item in critical)
        if not checks["critical_files_present"]:
            errors.append("One or more critical application/runtime files are missing.")

        licenses = data.get("licenses", [])
        license_paths = [str(item.get("path")) for item in licenses if isinstance(item, dict)]
        checks["licenses_included"] = all(path.lower() in payload for path in license_paths)
        if not checks["licenses_included"]:
            errors.append("A license notice referenced by the manifest is missing from the installer.")

        smoke = data.get("smoke_test", {})
        checks["smoke_test_passed"] = bool(smoke.get("passed"))
        if not checks["smoke_test_passed"]:
            errors.append("No passing smoke test is recorded. The build cannot be labelled stable.")

    if installer.stat().st_size >= 64:
        with open(installer, "rb") as handle:
            handle.seek(-64, 2)
            checks["footer_present"] = MAGIC in handle.read()
    else:
        checks["footer_present"] = False
    if not checks["footer_present"]:
        errors.append("SHADOW payload footer not found.")

    return {
        "ok": not errors,
        "installer": str(installer),
        "size": installer.stat().st_size,
        "sha256": installer_hash,
        "embedded_files": len(payload),
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a SHADOW MODEL installer before publication.")
    parser.add_argument("installer", type=Path)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--version", default=None)
    parser.add_argument("--expected-sha256", default=None)
    args = parser.parse_args()

    manifest = args.manifest or args.installer.parent / "manifest.json"
    report = verify(args.installer, manifest, args.version, args.expected_sha256)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
