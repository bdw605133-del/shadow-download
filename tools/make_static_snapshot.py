"""Export only public site data for the free static GitHub Pages build.

Never writes admin accounts, sessions, login attempts, audit rows or secrets.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from db import connect_db  # noqa: E402
from storage import StorageError, resolve_inside  # noqa: E402

OUTPUT_DIR = ROOT / "public_static"
DATA_FILE = OUTPUT_DIR / "data.json"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"

RELEASE_FIELDS = (
    "id", "version", "title", "channel", "release_date", "notes",
    "installer_name", "installer_path", "file_size", "sha256",
    "min_windows", "max_windows", "architecture", "requirements",
    "published", "verified", "verified_at", "created_at", "updated_at",
)
SCREENSHOT_FIELDS = (
    "id", "release_id", "file_path", "mime_type", "alt_text",
    "sort_order", "uploaded_at",
)


def main() -> int:
    connection = connect_db(config.DB_PATH)
    try:
        releases = [
            {field: row[field] for field in RELEASE_FIELDS}
            for row in connection.execute(
                "SELECT * FROM releases WHERE published = 1 AND verified = 1 "
                "ORDER BY release_date DESC, id DESC"
            )
        ]
        screenshots = [
            {field: row[field] for field in SCREENSHOT_FIELDS}
            for row in connection.execute(
                "SELECT * FROM screenshots ORDER BY release_id, sort_order, id"
            )
        ]
        content = {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT key, value FROM site_content")
        }
    finally:
        connection.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(
            {"releases": releases, "screenshots": screenshots, "site_content": content},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if SCREENSHOT_DIR.exists():
        shutil.rmtree(SCREENSHOT_DIR)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for shot in screenshots:
        try:
            source = resolve_inside(config.RELEASE_STORAGE, shot["file_path"])
        except StorageError:
            print(f"Skipping unsafe screenshot path: {shot['file_path']}", file=sys.stderr)
            continue
        if source.is_file():
            shutil.copy2(source, SCREENSHOT_DIR / source.name)

    print(f"Wrote {DATA_FILE.relative_to(ROOT)} ({len(releases)} releases, {len(screenshots)} screenshots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
