"""Freeze the public SHADOW DOWNLOAD pages into a GitHub Pages static site.

Required environment:
  SHADOW_PUBLIC_BASE_URL              e.g. https://owner.github.io/repo/
  SHADOW_STATIC_RELEASE_URL_TEMPLATE  e.g. https://github.com/owner/repo/releases/download/v{version}/{filename}

The installer itself is NOT copied into the site. It must be uploaded to a
GitHub Release so the generated links are real, public HTTPS downloads.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SNAPSHOT_FILE = ROOT / "public_static" / "data.json"
SCREENSHOT_SOURCE = ROOT / "public_static" / "screenshots"
SITE_DIR = ROOT / "site"

ROUTES = (
    ("index.html", "/"),
    ("download/index.html", "/download"),
    ("features/index.html", "/features"),
    ("release-notes/index.html", "/release-notes"),
    ("system-requirements/index.html", "/system-requirements"),
    ("installation/index.html", "/installation"),
    ("faq/index.html", "/faq"),
    ("robots.txt", "/robots.txt"),
    ("sitemap.xml", "/sitemap.xml"),
)


def _validate(value: str, name: str) -> None:
    if not value:
        raise RuntimeError(f"{name} is required")
    for marker in ("<", ">", "CHANGE_ME", "example.com", "YOUR_", "OWNER", "REPO"):
        if marker in value:
            raise RuntimeError(f"{name} still contains a placeholder: {marker}")


def _base_url_parts(base_url: str) -> tuple[str, str]:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("SHADOW_PUBLIC_BASE_URL must be a full https:// URL")
    return base_url.rstrip("/"), parsed.path.rstrip("/")


def _rewrite_paths(base_path: str) -> None:
    """Prefix root-relative links for GitHub Pages project sites."""
    if not base_path:
        return
    prefix = f"{base_path}/"
    for target in SITE_DIR.rglob("*.html"):
        text = target.read_text(encoding="utf-8")
        for attribute in ("href", "src", "action"):
            text = text.replace(f'{attribute}="/', f'{attribute}="{prefix}')
        target.write_text(text, encoding="utf-8")

    robots = SITE_DIR / "robots.txt"
    if robots.is_file():
        lines = []
        for line in robots.read_text(encoding="utf-8").splitlines():
            if line.startswith(("Allow: /", "Disallow: /")):
                verb, value = line.split(": ", 1)
                line = f"{verb}: {prefix}{value.lstrip('/')}"
            lines.append(line)
        robots.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_database(path: Path, snapshot: dict) -> None:
    from db import SCHEMA

    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        columns = (
            "id", "version", "title", "channel", "release_date", "notes",
            "installer_name", "installer_path", "file_size", "sha256",
            "min_windows", "max_windows", "architecture", "requirements",
            "published", "verified", "verified_at", "created_at", "updated_at",
        )
        connection.executemany(
            f"INSERT INTO releases ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [tuple(release.get(column) for column in columns) for release in snapshot["releases"]],
        )
        shot_columns = (
            "id", "release_id", "file_path", "mime_type", "alt_text",
            "sort_order", "uploaded_at",
        )
        connection.executemany(
            f"INSERT INTO screenshots ({', '.join(shot_columns)}) VALUES ({', '.join('?' for _ in shot_columns)})",
            [tuple(shot.get(column) for column in shot_columns) for shot in snapshot["screenshots"]],
        )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        connection.executemany(
            "INSERT OR REPLACE INTO site_content (key, value, updated_at) VALUES (?, ?, ?)",
            [(key, json.dumps(value, ensure_ascii=False), now) for key, value in snapshot["site_content"].items()],
        )
        connection.commit()
    finally:
        connection.close()


def main() -> int:
    base_url = os.getenv("SHADOW_PUBLIC_BASE_URL", "").strip()
    release_template = os.getenv("SHADOW_STATIC_RELEASE_URL_TEMPLATE", "").strip()
    _validate(base_url, "SHADOW_PUBLIC_BASE_URL")
    _validate(release_template, "SHADOW_STATIC_RELEASE_URL_TEMPLATE")
    if (
        not release_template.startswith("https://")
        or "{version}" not in release_template
        or "{filename}" not in release_template
    ):
        raise RuntimeError(
            "SHADOW_STATIC_RELEASE_URL_TEMPLATE must be an https:// GitHub Releases URL "
            "containing {version} and {filename}"
        )
    if not SNAPSHOT_FILE.is_file():
        raise RuntimeError(f"Missing {SNAPSHOT_FILE}; run tools/make_static_snapshot.py first")

    public_base, base_path = _base_url_parts(base_url)
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as temporary:
        temp_root = Path(temporary)
        db_path = temp_root / "public.db"
        _build_database(db_path, snapshot)

        os.environ["SHADOW_ENV"] = "production"
        os.environ["SHADOW_DB_PATH"] = str(db_path)
        os.environ["SHADOW_STORAGE_PATH"] = str(temp_root / "storage")
        os.environ["SHADOW_BASE_URL"] = public_base
        os.environ["SHADOW_SECRET_KEY"] = "static-export-only-not-a-runtime-secret"
        os.environ["SHADOW_STATIC_EXPORT"] = "1"
        os.environ["SHADOW_STATIC_RELEASE_URL_TEMPLATE"] = release_template

        from app import create_app

        app = create_app("production")
        client = app.test_client()
        client.environ_base["SCRIPT_NAME"] = base_path
        client.environ_base["wsgi.url_scheme"] = "https"

        if SITE_DIR.exists():
            shutil.rmtree(SITE_DIR)
        SITE_DIR.mkdir(parents=True)

        for output, route in ROUTES:
            response = client.get(route)
            if response.status_code != 200:
                raise RuntimeError(f"Failed to render {route}: HTTP {response.status_code}")
            target = SITE_DIR / output
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.data)
            print(f"  {route} -> {target.relative_to(ROOT)}")

        _rewrite_paths(base_path)

        static_target = SITE_DIR / "static"
        shutil.copytree(ROOT / "app" / "static", static_target)
        if SCREENSHOT_SOURCE.is_dir():
            shutil.copytree(SCREENSHOT_SOURCE, static_target / "screenshots", dirs_exist_ok=True)
        (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Static site written to {SITE_DIR.relative_to(ROOT)}")
    print(f"Public base URL: {public_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
