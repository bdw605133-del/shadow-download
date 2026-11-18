"""Configuration for SHADOW DOWNLOAD.

All sensitive values come from environment variables (or a local .env file).
No secret is hard-coded in source control.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE, # comments). Environment wins."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def _secret_key() -> str:
    """Use env secret, otherwise persist a generated one locally."""
    configured = os.getenv("SHADOW_SECRET_KEY")
    if configured:
        return configured
    key_file = _resolve("data/secret_key")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.is_file():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return generated


STORAGE_ROOT = _resolve(os.getenv("SHADOW_STORAGE_PATH", "storage"))
RELEASE_STORAGE = STORAGE_ROOT / "releases"
STAGING_STORAGE = STORAGE_ROOT / "staging"
DB_PATH = _resolve(os.getenv("SHADOW_DB_PATH", "data/shadow_download.db"))

for _directory in (DB_PATH.parent, RELEASE_STORAGE, STAGING_STORAGE):
    _directory.mkdir(parents=True, exist_ok=True)


class BaseConfig:
    SECRET_KEY = _secret_key()
    DB_PATH = DB_PATH
    STORAGE_ROOT = STORAGE_ROOT
    RELEASE_STORAGE = RELEASE_STORAGE
    STAGING_STORAGE = STAGING_STORAGE

    SITE_NAME = "SHADOW DOWNLOAD"
    PRODUCT_NAME = "SHADOW MODEL"
    BASE_URL = os.getenv("SHADOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    MAX_CONTENT_LENGTH = _int("SHADOW_MAX_UPLOAD_MB", 2048) * 1024 * 1024
    MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024

    SESSION_COOKIE_NAME = "shadow_admin"
    VISITOR_COOKIE_NAME = "shadow_visitor"
    SESSION_IDLE_MINUTES = _int("SHADOW_SESSION_IDLE_MINUTES", 120)
    SESSION_MAX_HOURS = _int("SHADOW_SESSION_MAX_HOURS", 12)
    COOKIE_SECURE = _bool("SHADOW_COOKIE_SECURE", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    FORCE_HTTPS = _bool("SHADOW_FORCE_HTTPS", False)
    TRUSTED_PROXY_COUNT = _int("SHADOW_TRUSTED_PROXY_COUNT", 0)

    # Used only when freezing the public pages into a static GitHub Pages site.
    STATIC_EXPORT = _bool("SHADOW_STATIC_EXPORT", False)
    STATIC_RELEASE_URL_TEMPLATE = os.getenv("SHADOW_STATIC_RELEASE_URL_TEMPLATE", "").strip()

    # Google Search Console ownership token (value only, not the full tag).
    GOOGLE_SITE_VERIFICATION = os.getenv("SHADOW_GOOGLE_VERIFICATION", "").strip()

    LOGIN_MAX_ATTEMPTS = _int("SHADOW_LOGIN_MAX_ATTEMPTS", 10)
    LOGIN_WINDOW_MINUTES = _int("SHADOW_LOGIN_WINDOW_MINUTES", 15)

    DEBUG = False
    TESTING = False


class DevelopmentConfig(BaseConfig):
    DEBUG = _bool("SHADOW_DEBUG", False)


class ProductionConfig(BaseConfig):
    DEBUG = False


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    SESSION_COOKIE_NAME = "shadow_admin_test"
    VISITOR_COOKIE_NAME = "shadow_visitor_test"
    SECRET_KEY = "testing-only-secret-key"
    DB_PATH = PROJECT_ROOT / "data" / "shadow_download_test.db"
    STORAGE_ROOT = PROJECT_ROOT / "storage" / "test"
    RELEASE_STORAGE = STORAGE_ROOT / "releases"
    STAGING_STORAGE = STORAGE_ROOT / "staging"
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024


def config_for(name: str | None = None) -> type[BaseConfig]:
    return {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }.get((name or os.getenv("SHADOW_ENV", "production")).lower(), ProductionConfig)
