"""SQLite persistence layer for SHADOW DOWNLOAD.

Release metadata, admin accounts, sessions, content and audit events live here.
Installer binaries never do: they are stored under release storage on disk.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT 'Administrator',
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    ip_hash TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_admin ON admin_sessions(admin_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON admin_sessions(expires_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    successful INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(ip_hash, username, created_at);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'stable' CHECK (channel IN ('stable', 'beta')),
    release_date TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    installer_name TEXT NOT NULL DEFAULT '',
    installer_path TEXT,
    file_size INTEGER,
    sha256 TEXT,
    min_windows TEXT NOT NULL DEFAULT 'Windows 10 (64-bit)',
    max_windows TEXT NOT NULL DEFAULT '',
    architecture TEXT NOT NULL DEFAULT 'x64',
    requirements TEXT NOT NULL DEFAULT '',
    published INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    download_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by INTEGER REFERENCES admins(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_releases_published ON releases(published, verified, release_date);

CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    alt_text TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_content (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    ip_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    ip_hash TEXT,
    created_at TEXT NOT NULL
);
"""

DEFAULT_CONTENT: dict[str, object] = {
    "hero_headline": "MEET SHADOW MODEL",
    "hero_description": (
        "SHADOW MODEL is a private, Windows desktop AI assistant built for chat, "
        "voice, images and documents — with Arabic and English support."
    ),
    "app_description": (
        "A focused desktop experience that keeps your conversations, files and "
        "models close at hand. No browser tab required."
    ),
    "features": [
        {
            "icon": "chat",
            "title": "AI Chat",
            "description": "A native Qt chat workspace with streaming replies, Markdown and code rendering, file attachments and saved conversation history.",
            "note": "",
            "verified": True,
        },
        {
            "icon": "core",
            "title": "Independent SHADOW Model",
            "description": "A first-class, independently trained byte-level BPE Transformer with its own tokenizer, checkpoints, training controls and streaming CPU inference.",
            "note": "Experimental and CPU-first. It is not equivalent to a large cloud model and must be trained before use.",
            "verified": True,
        },
        {
            "icon": "voice",
            "title": "Voice Assistant",
            "description": "Microphone input with whisper.cpp transcription, wake-word detection and offline narration through Windows SAPI voices.",
            "note": "Arabic narration requires an Arabic SAPI voice installed in Windows.",
            "verified": True,
        },
        {
            "icon": "image",
            "title": "Image Understanding",
            "description": "Attach images to a conversation and query vision-capable providers, with OCR text extraction available to local models.",
            "note": "Native SHADOW receives OCR text only. Scene understanding requires a configured vision-capable provider.",
            "verified": True,
        },
        {
            "icon": "document",
            "title": "Document Reading",
            "description": "Read and query PDF, DOCX, XLSX, TXT, CSV and JSON attachments directly inside the chat workspace.",
            "note": "PDF support covers selectable text; scanned PDFs need OCR. Office extraction is a minimal built-in reader.",
            "verified": True,
        },
        {
            "icon": "memory",
            "title": "Conversation Memory",
            "description": "Persistent conversation history plus a separate conversation-memory store that keeps context across turns.",
            "note": "Training data is never collected from conversations.",
            "verified": True,
        },
        {
            "icon": "language",
            "title": "Arabic and English",
            "description": "A bilingual interface with Arabic and English themes, RTL support and lossless UTF-8 handling in the tokenizer.",
            "note": "",
            "verified": True,
        },
        {
            "icon": "desktop",
            "title": "Windows Desktop Application",
            "description": "A native C++17 / Qt 6 x64 application with bundled Qt and VC++ runtimes, local engines and an optional portable model set.",
            "note": "No browser is required for local features.",
            "verified": True,
        },
    ],
    "system_requirements": [
        {"label": "Operating system", "value": "Windows 10 64-bit (version 1903+) or Windows 11"},
        {"label": "Processor", "value": "4 cores (tested target: Intel Core i5-2500)"},
        {"label": "Memory", "value": "8 GB free RAM (16 GB recommended)"},
        {"label": "Graphics", "value": "Not required; the CPU build runs on integrated graphics"},
        {"label": "Disk space", "value": "About 1.5 GB for the app, engines and both models"},
        {"label": "Additional runtime", "value": "Qt 6 and Visual C++ x64 runtimes are bundled in the official installer"},
    ],
    "install_steps": [
        "Download the installer for the latest verified release from the Download page.",
        "Compare the downloaded file's SHA-256 with the checksum shown on the release card.",
        "Run the installer and choose an installation folder, or use the portable folder if supplied.",
        "Launch SHADOW MODEL from the Start Menu or from ShadowAI.exe.",
        "Open Settings → Local AI and select the bundled models, or download models from the Settings page.",
    ],
    "faq": [
        {
            "q": "Is this the official download site?",
            "a": "Yes. SHADOW DOWNLOAD is the dedicated distribution site for the SHADOW MODEL Windows desktop application. It is separate from the AI chat website.",
        },
        {
            "q": "Is there a verified release available?",
            "a": "Only releases that have been built, checksummed and verified are published here. If the Download page says no release is available, do not trust installers from other sources.",
        },
        {
            "q": "How do I verify the installer?",
            "a": "Open PowerShell in the download folder and run: Get-FileHash .\\<installer-name> -Algorithm SHA256. Compare the result with the checksum published on the Download page.",
        },
        {
            "q": "Does SHADOW MODEL need an internet connection?",
            "a": "Local chat, voice transcription, document reading and the native SHADOW model work offline. Cloud providers and model downloads require internet access and your own credentials.",
        },
        {
            "q": "Which Windows versions are supported?",
            "a": "Windows 10 64-bit (1903+) and Windows 11. The supported range for each build is listed on its release card.",
        },
        {
            "q": "Where can I report a problem?",
            "a": "Use the official support link in the footer. Include your Windows version, the release version and the SHA-256 of the file you downloaded.",
        },
    ],
    "support_url": "",
    "source_url": "",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect_db(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_db(path: str | Path, *, seed_content: bool = True) -> None:
    connection = connect_db(path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        if seed_content:
            now = utc_now()
            for key, value in DEFAULT_CONTENT.items():
                connection.execute(
                    "INSERT OR IGNORE INTO site_content (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value, ensure_ascii=False), now),
                )
        connection.commit()
    finally:
        connection.close()


def get_db() -> sqlite3.Connection:
    from flask import current_app, g

    if "db" not in g:
        g.db = connect_db(current_app.config["DB_PATH"])
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    from flask import g

    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection):
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def get_content(connection: sqlite3.Connection, key: str, default=None):
    row = connection.execute(
        "SELECT value FROM site_content WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return DEFAULT_CONTENT.get(key, default)
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return default


def set_content(connection: sqlite3.Connection, key: str, value) -> None:
    connection.execute(
        "INSERT INTO site_content (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), utc_now()),
    )


def audit(
    connection: sqlite3.Connection,
    action: str,
    target: str = "",
    detail: str = "",
    admin_id: int | None = None,
    ip_hash: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO audit_log (admin_id, action, target, detail, ip_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (admin_id, action, target, detail[:2000], ip_hash, utc_now()),
    )
