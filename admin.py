"""Administrator-only release and content management."""

from __future__ import annotations

import json
import re
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from db import audit, get_content, get_db, set_content, transaction, utc_now
from repositories import all_releases, get_release, screenshots_for
from security import (
    clear_session_cookie,
    create_session,
    destroy_session,
    hash_password,
    login_lock_remaining,
    record_login_attempt,
    require_admin,
    require_csrf,
    safe_next,
    set_session_cookie,
    too_many_requests,
    verify_password,
)
from storage import (
    StorageError,
    delete_file,
    delete_release_directory,
    save_installer,
    save_screenshot,
    verify_release,
)

admin = Blueprint("admin", __name__, url_prefix="/admin")

VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONTENT_JSON_KEYS = ("features", "faq", "install_steps", "system_requirements")


def _admin_id() -> int | None:
    session = getattr(g, "admin_session", None)
    return session["admin_id"] if session else None


def _audit(action: str, target: str = "", detail: str = "") -> None:
    audit(get_db(), action, target, detail, _admin_id())


def _form_data() -> dict[str, str]:
    keys = (
        "version", "title", "channel", "release_date", "notes",
        "min_windows", "max_windows", "architecture", "requirements",
    )
    return {key: (request.form.get(key) or "").strip() for key in keys}


def _validate_release(data: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if not VERSION_RE.fullmatch(data["version"]):
        errors.append("Version must use letters, numbers, dots, dashes or underscores (max 64 characters).")
    if not 2 <= len(data["title"]) <= 120:
        errors.append("Title must be between 2 and 120 characters.")
    if data["channel"] not in {"stable", "beta"}:
        errors.append("Choose a valid release channel.")
    if not DATE_RE.fullmatch(data["release_date"]):
        errors.append("Release date must be YYYY-MM-DD.")
    else:
        try:
            datetime.strptime(data["release_date"], "%Y-%m-%d")
        except ValueError:
            errors.append("Release date is not a real calendar date.")
    if len(data["notes"]) < 10:
        errors.append("Release notes must contain at least 10 characters.")
    if len(data["requirements"]) < 10:
        errors.append("System requirements must contain at least 10 characters.")
    if not data["min_windows"]:
        errors.append("Specify the minimum supported Windows version.")
    if data["architecture"] not in {"x64", "x86", "arm64"}:
        errors.append("Choose a valid architecture.")
    return errors


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@admin.route("/login", methods=["GET", "POST"])
def login():
    if getattr(g, "admin_session", None) is not None:
        return redirect(url_for("admin.dashboard"))
    if request.method == "GET":
        return render_template("admin/login.html", csrf_token=g.visitor_csrf, next=safe_next(request.args.get("next")))

    require_csrf()
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not _credentials_shape_ok(username, password):
        record_login_attempt(username, False)
        flash("Invalid username or password.", "error")
        return render_template("admin/login.html", csrf_token=g.visitor_csrf, next=safe_next(request.form.get("next"))), 401

    lock = login_lock_remaining(username)
    if lock:
        return too_many_requests(lock)

    connection = get_db()
    row = connection.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
    # Always perform a scrypt verification to avoid username enumeration timing.
    stored = row["password_hash"] if row else "$scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + ("A" * 88) + "=="
    valid = verify_password(stored, password) and row is not None
    if not valid:
        record_login_attempt(username, False)
        flash("Invalid username or password.", "error")
        return render_template("admin/login.html", csrf_token=g.visitor_csrf, next=safe_next(request.form.get("next"))), 401

    record_login_attempt(username, True)
    token, csrf = create_session(row["id"])
    connection.execute("UPDATE admins SET last_login_at = ? WHERE id = ?", (utc_now(), row["id"]))
    _audit("admin.login", username, "Successful administrator sign-in")
    connection.commit()
    response = make_response(redirect(safe_next(request.form.get("next"))))
    set_session_cookie(response, token)
    response.delete_cookie(current_app.config["VISITOR_COOKIE_NAME"], path="/")
    return response


def _credentials_shape_ok(username: str, password: str) -> bool:
    from security import USERNAME_RE

    return bool(USERNAME_RE.fullmatch(username)) and 1 <= len(password) <= 256


@admin.route("/logout", methods=["POST"])
@require_admin
def logout():
    require_csrf()
    destroy_session()
    _audit("admin.logout", g.admin_session["username"], "Administrator signed out")
    response = make_response(redirect(url_for("admin.login")))
    clear_session_cookie(response)
    flash("You have been signed out.", "success")
    return response


@admin.route("/change-password", methods=["GET", "POST"])
@require_admin
def change_password():
    if request.method == "GET":
        return render_template("admin/change_password.html", csrf_token=g.admin_session["csrf_token"])
    require_csrf()
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    connection = get_db()
    row = connection.execute(
        "SELECT password_hash FROM admins WHERE id = ?", (g.admin_session["admin_id"],)
    ).fetchone()
    errors = []
    if not verify_password(row["password_hash"], current):
        errors.append("Current password is incorrect.")
    if len(new) < 12:
        errors.append("New password must be at least 12 characters long.")
    if new != confirm:
        errors.append("New passwords do not match.")
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("admin/change_password.html", csrf_token=g.admin_session["csrf_token"]), 400
    connection.execute(
        "UPDATE admins SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (hash_password(new), g.admin_session["admin_id"]),
    )
    _audit("admin.password_changed", g.admin_session["username"], "Administrator password updated")
    connection.commit()
    flash("Password updated.", "success")
    return redirect(url_for("admin.dashboard"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@admin.route("/")
def index():
    return redirect(url_for("admin.dashboard"))


@admin.route("/dashboard")
@require_admin
def dashboard():
    connection = get_db()
    releases = all_releases(include_unpublished=True)
    stats = {
        "total": len(releases),
        "published": sum(1 for item in releases if item["published"]),
        "verified": sum(1 for item in releases if item["verified"]),
        "downloads": sum(int(item["download_count"] or 0) for item in releases),
    }
    recent = connection.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 8"
    ).fetchall()
    return render_template(
        "admin/dashboard.html",
        releases=releases,
        stats=stats,
        recent=recent,
        csrf_token=g.admin_session["csrf_token"],
    )


@admin.route("/releases/new", methods=["GET", "POST"])
@require_admin
def new_release():
    if request.method == "GET":
        return render_template(
            "admin/release_form.html",
            release=None,
            data=None,
            csrf_token=g.admin_session["csrf_token"],
        )
    return _save_release(None)


@admin.route("/releases/<int:release_id>/edit", methods=["GET", "POST"])
@require_admin
def edit_release(release_id: int):
    release = get_release(release_id)
    if release is None:
        flash("Release not found.", "error")
        return redirect(url_for("admin.dashboard"))
    if request.method == "GET":
        return render_template(
            "admin/release_form.html",
            release=release,
            data=dict(release),
            screenshots=screenshots_for(release_id),
            csrf_token=g.admin_session["csrf_token"],
        )
    return _save_release(release)


def _save_release(release):
    require_csrf()
    data = _form_data()
    errors = _validate_release(data)
    connection = get_db()
    duplicate = connection.execute(
        "SELECT id FROM releases WHERE version = ? AND id != ?",
        (data["version"], release["id"] if release else -1),
    ).fetchone()
    if duplicate:
        errors.append("A release with this version already exists.")

    installer = request.files.get("installer")
    if release is None and (not installer or not installer.filename):
        errors.append("An installer file is required for a new release.")
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template(
            "admin/release_form.html",
            release=release,
            data=data,
            screenshots=screenshots_for(release["id"]) if release else [],
            csrf_token=g.admin_session["csrf_token"],
        ), 400

    upload_info = {}
    if installer and installer.filename:
        try:
            upload_info = save_installer(installer, data["version"])
        except StorageError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.edit_release", release_id=release["id"]) if release else url_for("admin.new_release"))

    manifest = request.files.get("manifest")
    if manifest and manifest.filename:
        if not manifest.filename.lower().endswith(".json"):
            flash("Build manifest must be a .json file.", "error")
        else:
            try:
                payload = json.loads(manifest.read().decode("utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("required_files"), list):
                    raise ValueError("Missing required_files list.")
                from storage import release_directory

                (release_directory(data["version"], create=True) / "manifest.json").write_text(
                    json.dumps(payload, indent=2), encoding="utf-8"
                )
            except (ValueError, UnicodeDecodeError, OSError) as exc:
                flash(f"Build manifest was rejected: {exc}", "error")

    now = utc_now()
    with transaction(connection):
        if release is None:
            cursor = connection.execute(
                "INSERT INTO releases (version, title, channel, release_date, notes, installer_name, "
                "installer_path, file_size, sha256, min_windows, max_windows, architecture, requirements, "
                "published, verified, created_at, updated_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)",
                (
                    data["version"], data["title"], data["channel"], data["release_date"], data["notes"],
                    upload_info.get("installer_name", ""), upload_info.get("installer_path"),
                    upload_info.get("file_size"), upload_info.get("sha256"), data["min_windows"],
                    data["max_windows"], data["architecture"], data["requirements"], now, now, _admin_id(),
                ),
            )
            release_id = cursor.lastrowid
        else:
            release_id = release["id"]
            values = [
                data["version"], data["title"], data["channel"], data["release_date"], data["notes"],
                data["min_windows"], data["max_windows"], data["architecture"], data["requirements"], now,
            ]
            if upload_info:
                connection.execute(
                    "UPDATE releases SET installer_name=?, installer_path=?, file_size=?, sha256=?, "
                    "verified=0, verified_at=NULL, published=0 WHERE id=?",
                    (
                        upload_info["installer_name"], upload_info["installer_path"],
                        upload_info["file_size"], upload_info["sha256"], release_id,
                    ),
                )
            values.append(release_id)
            connection.execute(
                "UPDATE releases SET version=?, title=?, channel=?, release_date=?, notes=?, "
                "min_windows=?, max_windows=?, architecture=?, requirements=?, updated_at=? WHERE id=?",
                values,
            )
        _audit("release.saved", data["version"], "Release metadata saved", _admin_id())

    screenshots = request.files.getlist("screenshots")
    if screenshots and any(item.filename for item in screenshots):
        existing = len(screenshots_for(release_id))
        for offset, screenshot in enumerate([item for item in screenshots if item.filename]):
            if existing + offset >= 8:
                flash("A release can have at most 8 screenshots.", "warning")
                break
            try:
                stored = save_screenshot(screenshot, data["version"], existing + offset + 1)
                connection.execute(
                    "INSERT INTO screenshots (release_id, file_path, mime_type, alt_text, sort_order, uploaded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        release_id, stored["file_path"], stored["mime_type"],
                        (request.form.get("screenshot_alt") or "SHADOW MODEL application screenshot").strip()[:200],
                        existing + offset, utc_now(),
                    ),
                )
            except StorageError as exc:
                flash(str(exc), "error")
        connection.commit()

    flash("Release saved. Verify it before publishing.", "success")
    return redirect(url_for("admin.edit_release", release_id=release_id))


@admin.route("/releases/<int:release_id>/verify", methods=["POST"])
@require_admin
def verify(release_id: int):
    require_csrf()
    release = get_release(release_id)
    if release is None:
        flash("Release not found.", "error")
        return redirect(url_for("admin.dashboard"))
    ok, errors, warnings = verify_release(release)
    connection = get_db()
    connection.execute(
        "UPDATE releases SET verified = ?, verified_at = ?, published = CASE WHEN ? = 0 THEN 0 ELSE published END "
        "WHERE id = ?",
        (int(ok), utc_now() if ok else None, int(ok), release_id),
    )
    _audit("release.verified" if ok else "release.verify_failed", release["version"], "; ".join(errors))
    connection.commit()
    if ok:
        flash("Release verified. Required files and checksums match.", "success")
    else:
        for error in errors:
            flash(error, "error")
    for warning in warnings:
        flash(warning, "warning")
    return redirect(url_for("admin.edit_release", release_id=release_id))


@admin.route("/releases/<int:release_id>/publish", methods=["POST"])
@require_admin
def publish(release_id: int):
    require_csrf()
    release = get_release(release_id)
    if release is None:
        flash("Release not found.", "error")
        return redirect(url_for("admin.dashboard"))
    ok, errors, _warnings = verify_release(release)
    if not ok or not release["verified"]:
        for error in errors:
            flash(error, "error")
        flash("This release must pass verification before it can be published.", "error")
        return redirect(url_for("admin.edit_release", release_id=release_id))
    connection = get_db()
    connection.execute("UPDATE releases SET published = 1, updated_at = ? WHERE id = ?", (utc_now(), release_id))
    _audit("release.published", release["version"], "Release published")
    connection.commit()
    flash("Release is now publicly visible.", "success")
    return redirect(url_for("admin.dashboard"))


@admin.route("/releases/<int:release_id>/unpublish", methods=["POST"])
@require_admin
def unpublish(release_id: int):
    require_csrf()
    release = get_release(release_id)
    if release is None:
        flash("Release not found.", "error")
        return redirect(url_for("admin.dashboard"))
    connection = get_db()
    connection.execute("UPDATE releases SET published = 0, updated_at = ? WHERE id = ?", (utc_now(), release_id))
    _audit("release.unpublished", release["version"], "Release unpublished")
    connection.commit()
    flash("Release has been unpublished.", "success")
    return redirect(url_for("admin.dashboard"))


@admin.route("/releases/<int:release_id>/delete", methods=["POST"])
@require_admin
def delete(release_id: int):
    require_csrf()
    release = get_release(release_id)
    if release is None:
        flash("Release not found.", "error")
        return redirect(url_for("admin.dashboard"))
    if request.form.get("confirm") != release["version"]:
        flash("Deletion cancelled: the version confirmation did not match.", "error")
        return redirect(url_for("admin.edit_release", release_id=release_id))
    delete_release_directory(release["version"])
    connection = get_db()
    connection.execute("DELETE FROM screenshots WHERE release_id = ?", (release_id,))
    connection.execute("DELETE FROM releases WHERE id = ?", (release_id,))
    _audit("release.deleted", release["version"], "Release and stored installer deleted")
    connection.commit()
    flash("Release deleted.", "success")
    return redirect(url_for("admin.dashboard"))


@admin.route("/screenshots/<int:screenshot_id>/delete", methods=["POST"])
@require_admin
def delete_screenshot(screenshot_id: int):
    require_csrf()
    connection = get_db()
    row = connection.execute("SELECT * FROM screenshots WHERE id = ?", (screenshot_id,)).fetchone()
    if row:
        delete_file(row["file_path"])
        connection.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))
        _audit("screenshot.deleted", str(screenshot_id), "Screenshot removed")
        connection.commit()
        flash("Screenshot removed.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


# ---------------------------------------------------------------------------
# Content and audit
# ---------------------------------------------------------------------------
@admin.route("/content", methods=["GET", "POST"])
@require_admin
def content():
    connection = get_db()
    if request.method == "GET":
        values = {key: get_content(connection, key, "") for key in
                  ("hero_headline", "hero_description", "app_description", "support_url", "source_url", *CONTENT_JSON_KEYS)}
        return render_template(
            "admin/content.html",
            values=values,
            json_text={key: json.dumps(values[key], ensure_ascii=False, indent=2) for key in CONTENT_JSON_KEYS},
            csrf_token=g.admin_session["csrf_token"],
        )
    require_csrf()
    text_fields = ("hero_headline", "hero_description", "app_description", "support_url", "source_url")
    for key in text_fields:
        value = (request.form.get(key) or "").strip()
        if len(value) > 2000:
            flash(f"{key} is too long.", "error")
            return redirect(url_for("admin.content"))
        set_content(connection, key, value)
    for key in CONTENT_JSON_KEYS:
        raw = request.form.get(key) or "[]"
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("must be a JSON list")
            set_content(connection, key, parsed)
        except ValueError as exc:
            flash(f"{key} was not saved: {exc}", "error")
            connection.commit()
            return redirect(url_for("admin.content"))
    _audit("content.updated", "site_content", "Homepage content updated")
    connection.commit()
    flash("Site content updated.", "success")
    return redirect(url_for("admin.content"))


@admin.route("/audit")
@require_admin
def audit_log():
    rows = get_db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("admin/audit.html", rows=rows, csrf_token=g.admin_session["csrf_token"])
