"""Read helpers shared by public pages and the admin dashboard."""

from __future__ import annotations

import re
from datetime import datetime

from db import get_db


def all_releases(include_unpublished: bool = False) -> list:
    where = "" if include_unpublished else "WHERE r.published = 1 AND r.verified = 1"
    return get_db().execute(
        f"SELECT r.* FROM releases r {where} "
        "ORDER BY r.release_date DESC, r.id DESC"
    ).fetchall()


def latest_release() -> object | None:
    return get_db().execute(
        "SELECT * FROM releases WHERE published = 1 AND verified = 1 AND channel = 'stable' "
        "ORDER BY release_date DESC, id DESC LIMIT 1"
    ).fetchone()


def get_release(release_id: int) -> object | None:
    return get_db().execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()


def get_release_by_version(version: str) -> object | None:
    return get_db().execute("SELECT * FROM releases WHERE version = ?", (version,)).fetchone()


def screenshots_for(release_id: int | None) -> list:
    if release_id is None:
        return []
    return get_db().execute(
        "SELECT * FROM screenshots WHERE release_id = ? ORDER BY sort_order, id", (release_id,)
    ).fetchall()


def release_notes_lines(notes: str) -> list[str]:
    return [line.strip() for line in (notes or "").splitlines() if line.strip()]


def format_bytes(value: int | None) -> str:
    if not value:
        return "—"
    units = ["B", "KB", "MB", "GB"]
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} GB"


def format_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        return value


def version_sort_key(version: str) -> tuple:
    parts = re.split(r"[.\-+]", version)
    return tuple(int(part) if part.isdigit() else part for part in parts)
