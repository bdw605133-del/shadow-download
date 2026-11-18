#!/usr/bin/env python3
"""Stage or publish a verified SHADOW MODEL release in the website database.

The release is only made public when --publish is supplied and the installer
passes full verification (including a recorded smoke test).

Usage:
    python tools/publish_release.py --version 1.0.0 \
        --installer dist/release/SHADOW-MODEL-1.0.0-setup.exe \
        --notes-file release-notes.txt --publish
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from db import audit, connect_db, init_db, utc_now  # noqa: E402
from verify_release import verify  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage or publish a verified release.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--notes-file", type=Path, default=None)
    parser.add_argument("--requirements-file", type=Path, default=None)
    parser.add_argument("--min-windows", default="Windows 10 64-bit (1903+) or Windows 11")
    parser.add_argument("--architecture", default="x64")
    parser.add_argument("--channel", choices=("stable", "beta"), default="stable")
    parser.add_argument("--publish", action="store_true", help="Make the verified release publicly visible")
    args = parser.parse_args()

    installer = args.installer.resolve()
    manifest = (args.manifest or installer.parent / "manifest.json").resolve()
    report = verify(installer, manifest, args.version, None)
    if not report["ok"]:
        print(json.dumps(report, indent=2))
        print("ERROR: release failed verification and was not staged.", file=sys.stderr)
        return 1
    if report["checks"].get("checksum_matches_manifest") is False:
        raise SystemExit("Installer checksum does not match manifest.")

    settings = config.config_for()
    init_db(settings.DB_PATH)
    storage_root = Path(settings.RELEASE_STORAGE)
    version_dir = storage_root / args.version
    version_dir.mkdir(parents=True, exist_ok=True)
    stored_installer = version_dir / installer.name
    if installer.resolve() != stored_installer.resolve():
        shutil.copy2(installer, stored_installer)
    shutil.copy2(manifest, version_dir / "manifest.json")

    notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else f"SHADOW MODEL {args.version} release."
    requirements = args.requirements_file.read_text(encoding="utf-8") if args.requirements_file else (
        "Windows 10 64-bit (1903+) or Windows 11. 8 GB free RAM (16 GB recommended). "
        "About 1.5 GB free disk space. CPU-only inference; no GPU required."
    )
    title = args.title or f"SHADOW MODEL {args.version}"

    connection = connect_db(settings.DB_PATH)
    existing = connection.execute("SELECT id FROM releases WHERE version = ?", (args.version,)).fetchone()
    now = utc_now()
    metadata = (
        title, args.channel, now[:10], notes,
        stored_installer.name, str(stored_installer.relative_to(storage_root)).replace("\\", "/"),
        report["size"], report["sha256"], args.min_windows, "", args.architecture, requirements,
    )
    with connection:
        if existing:
            connection.execute(
                "UPDATE releases SET title=?, channel=?, release_date=?, notes=?, installer_name=?, "
                "installer_path=?, file_size=?, sha256=?, min_windows=?, max_windows=?, architecture=?, "
                "requirements=?, verified=1, verified_at=?, updated_at=?, published=? WHERE id=?",
                (*metadata, now, now, int(args.publish), existing["id"]),
            )
        else:
            connection.execute(
                "INSERT INTO releases (title, channel, release_date, notes, installer_name, installer_path, "
                "file_size, sha256, min_windows, max_windows, architecture, requirements, verified, verified_at, "
                "created_at, updated_at, published, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (*metadata, now, now, now, int(args.publish), args.version),
            )
        audit(
            connection,
            "release.published" if args.publish else "release.staged",
            args.version,
            f"SHA-256 {report['sha256']}",
            None,
            None,
        )
    connection.close()

    print(json.dumps({
        "ok": True,
        "version": args.version,
        "published": bool(args.publish),
        "installer": str(stored_installer),
        "sha256": report["sha256"],
        "size": report["size"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
