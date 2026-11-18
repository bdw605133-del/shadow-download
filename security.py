"""Authentication, session, CSRF and response-hardening helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Response,
    abort,
    current_app,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session as flask_session,
    url_for,
)

from db import audit, get_db, utc_now

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DK_LEN = 64

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


# ---------------------------------------------------------------------------
# Password / token primitives
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DK_LEN,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password(stored: str, password: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(hash_b64)),
        )
        return hmac.compare_digest(derived, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def _pepper() -> bytes:
    return current_app.config["SECRET_KEY"].encode("utf-8")


def hash_token(token: str) -> str:
    return hmac.new(_pepper(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_ip(ip: str) -> str:
    return hmac.new(_pepper(), ip.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def new_token() -> str:
    return secrets.token_urlsafe(32)


def client_ip() -> str:
    trusted = current_app.config.get("TRUSTED_PROXY_COUNT", 0)
    if trusted and request.headers.get("X-Forwarded-For"):
        parts = [part.strip() for part in request.headers["X-Forwarded-For"].split(",")]
        candidate = parts[-trusted] if len(parts) >= trusted else parts[0]
        if candidate:
            return candidate
    return request.remote_addr or "0.0.0.0"


def safe_next(target: str | None, fallback: str = "/admin/dashboard") -> str:
    if not target:
        return fallback
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return fallback
    return target


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def create_session(admin_id: int) -> tuple[str, str]:
    """Create a session and revoke older sessions for the same admin."""
    connection = get_db()
    token = new_token()
    csrf = new_token()
    now = datetime.now(timezone.utc)
    idle = current_app.config["SESSION_IDLE_MINUTES"]
    max_hours = current_app.config["SESSION_MAX_HOURS"]
    expires = now + timedelta(hours=max_hours)
    connection.execute(
        "DELETE FROM admin_sessions WHERE admin_id = ? AND expires_at < ?",
        (admin_id, utc_now()),
    )
    connection.execute(
        "INSERT INTO admin_sessions "
        "(admin_id, token_hash, csrf_token, created_at, expires_at, last_seen_at, ip_hash, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            admin_id,
            hash_token(token),
            csrf,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            expires.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            hash_ip(client_ip()),
            (request.user_agent.string or "")[:500],
        ),
    )
    connection.commit()
    return token, csrf


def load_session():
    token = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
    if not token:
        return None
    connection = get_db()
    row = connection.execute(
        "SELECT s.*, a.username, a.display_name, a.must_change_password "
        "FROM admin_sessions s JOIN admins a ON a.id = s.admin_id "
        "WHERE s.token_hash = ?",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    try:
        if _parse_ts(row["expires_at"]) <= now:
            raise ValueError
        idle_limit = timedelta(minutes=current_app.config["SESSION_IDLE_MINUTES"])
        if _parse_ts(row["last_seen_at"]) + idle_limit <= now:
            raise ValueError
    except ValueError:
        connection.execute("DELETE FROM admin_sessions WHERE id = ?", (row["id"],))
        connection.commit()
        return None
    connection.execute(
        "UPDATE admin_sessions SET last_seen_at = ? WHERE id = ?", (utc_now(), row["id"])
    )
    connection.commit()
    return row


def destroy_session() -> None:
    token = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
    if token:
        connection = get_db()
        connection.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (hash_token(token),))
        connection.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        current_app.config["SESSION_COOKIE_NAME"],
        token,
        max_age=int(timedelta(hours=current_app.config["SESSION_MAX_HOURS"]).total_seconds()),
        httponly=True,
        secure=current_app.config["COOKIE_SECURE"],
        samesite="Lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        current_app.config["SESSION_COOKIE_NAME"],
        path="/",
        httponly=True,
        secure=current_app.config["COOKIE_SECURE"],
        samesite="Lax",
    )


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def visitor_csrf() -> str:
    if not hasattr(g, "visitor_csrf"):
        g.visitor_csrf = new_token()
        g.set_visitor_cookie = True
    return g.visitor_csrf


def current_csrf() -> str:
    if getattr(g, "admin_session", None) is not None:
        return g.admin_session["csrf_token"]
    return visitor_csrf()


def csrf_valid(token: str | None) -> bool:
    expected = current_csrf()
    return bool(token) and hmac.compare_digest(str(token), expected)


def require_csrf() -> None:
    if not csrf_valid(request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")):
        abort(400, description="Invalid security token. Please reload the page and try again.")


# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------
def login_lock_remaining(username: str) -> int:
    connection = get_db()
    window = (datetime.now(timezone.utc) - timedelta(minutes=current_app.config["LOGIN_WINDOW_MINUTES"])).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    ip_hash = hash_ip(client_ip())
    row = connection.execute(
        "SELECT "
        "SUM(CASE WHEN ip_hash = ? AND successful = 0 THEN 1 ELSE 0 END) AS by_ip, "
        "SUM(CASE WHEN ip_hash = ? AND username = ? AND successful = 0 THEN 1 ELSE 0 END) AS by_user "
        "FROM login_attempts WHERE created_at >= ?",
        (ip_hash, ip_hash, username, window),
    ).fetchone()
    by_ip = row["by_ip"] or 0
    by_user = row["by_user"] or 0
    max_attempts = current_app.config["LOGIN_MAX_ATTEMPTS"]
    if by_user >= max_attempts or by_ip >= max_attempts * 3:
        return current_app.config["LOGIN_WINDOW_MINUTES"]
    return 0


def record_login_attempt(username: str, successful: bool) -> None:
    connection = get_db()
    connection.execute(
        "INSERT INTO login_attempts (username, ip_hash, successful, created_at) VALUES (?, ?, ?, ?)",
        (username[:64], hash_ip(client_ip()), int(successful), utc_now()),
    )
    connection.commit()


def too_many_requests(seconds: int) -> Response:
    response = make_response(
        render_template("errors/429.html", retry_seconds=seconds), 429
    )
    response.headers["Retry-After"] = str(seconds * 60)
    return response


# ---------------------------------------------------------------------------
# Decorators / request hooks
# ---------------------------------------------------------------------------
def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        admin_session = getattr(g, "admin_session", None)
        if admin_session is None:
            return redirect(url_for("admin.login", next=safe_next(request.full_path.rstrip("?"))))
        if admin_session["must_change_password"] and request.endpoint != "admin.change_password":
            return redirect(url_for("admin.change_password"))
        return view(*args, **kwargs)

    return wrapped


def install_security_hooks(app) -> None:
    @app.before_request
    def _load_admin_session():
        if app.config.get("FORCE_HTTPS") and not request.is_secure and not app.config.get("TESTING"):
            return redirect(request.url.replace("http://", "https://", 1), code=308)
        g.admin_session = None
        if request.cookies.get(app.config["SESSION_COOKIE_NAME"]):
            g.admin_session = load_session()
        cookie_token = request.cookies.get(app.config["VISITOR_COOKIE_NAME"])
        if cookie_token and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", cookie_token):
            g.visitor_csrf = cookie_token
            g.set_visitor_cookie = False
        else:
            g.visitor_csrf = new_token()
            g.set_visitor_cookie = True

    @app.after_request
    def _apply_security_headers(response: Response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        if getattr(g, "set_visitor_cookie", False):
            response.set_cookie(
                app.config["VISITOR_COOKIE_NAME"],
                g.visitor_csrf,
                httponly=True,
                secure=app.config["COOKIE_SECURE"],
                samesite="Lax",
                path="/",
                max_age=60 * 60 * 8,
            )
        if request.path.startswith("/admin") and not request.path.startswith("/admin/static"):
            response.headers["Cache-Control"] = "no-store, private"
        return response
