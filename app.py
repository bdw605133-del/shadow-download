"""SHADOW DOWNLOAD — official release and distribution website."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

import config
from admin import admin as admin_blueprint
from db import close_db, get_content, get_db, init_db
from repositories import (
    all_releases,
    format_bytes,
    format_date,
    get_release,
    latest_release,
    release_notes_lines,
    screenshots_for,
)
from security import hash_ip, install_security_hooks, require_admin
from storage import StorageError, resolve_inside

PAGES = {
    "home": ("Home", "/"),
    "download": ("Download", "/download"),
    "features": ("Features", "/features"),
    "release_notes": ("Release Notes", "/release-notes"),
    "system_requirements": ("System Requirements", "/system-requirements"),
    "installation": ("Installation Guide", "/installation"),
    "faq": ("FAQ", "/faq"),
}


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, template_folder="app/templates", static_folder="app/static", static_url_path="/static")
    settings = config.config_for(config_name)
    app.config.from_object(settings)
    app.config["DB_PATH"] = Path(settings.DB_PATH)
    app.config["RELEASE_STORAGE"] = Path(settings.RELEASE_STORAGE)
    app.config["STAGING_STORAGE"] = Path(settings.STAGING_STORAGE)

    init_db(app.config["DB_PATH"])
    app.teardown_appcontext(close_db)
    install_security_hooks(app)
    app.register_blueprint(admin_blueprint)

    register_public_routes(app)
    register_errors(app)
    register_template_helpers(app)
    return app


def _page(app: Flask, endpoint: str, template: str, title: str, description: str):
    @app.route(PAGES[endpoint][1], endpoint=endpoint)
    def view():
        return render_template(template, page_title=title, page_description=description, active=endpoint)

    view.__name__ = endpoint


def register_public_routes(app: Flask) -> None:
    _page(
        app, "home", "home.html", "SHADOW MODEL — Private AI for Windows",
        "Meet SHADOW MODEL: a private Windows desktop AI assistant for chat, voice, images and documents, with Arabic and English support.",
    )
    _page(
        app, "download", "download.html", "Download SHADOW MODEL for Windows",
        "Download the official, verified SHADOW MODEL Windows installer. Check version, file size, release date and SHA-256 checksum.",
    )
    _page(
        app, "features", "features.html", "SHADOW MODEL Features",
        "Explore the implemented features of SHADOW MODEL: AI chat, independent model, voice, image and document handling, memory and bilingual UI.",
    )
    _page(
        app, "release_notes", "release_notes.html", "SHADOW MODEL Release Notes",
        "Read verified release notes and version history for the official SHADOW MODEL Windows application.",
    )
    _page(
        app, "system_requirements", "system_requirements.html", "SHADOW MODEL System Requirements",
        "Check the Windows version, CPU, memory and disk requirements for SHADOW MODEL.",
    )
    _page(
        app, "installation", "installation.html", "Install SHADOW MODEL on Windows",
        "Follow the official installation guide and verify the SHA-256 checksum before running the SHADOW MODEL installer.",
    )
    _page(
        app, "faq", "faq.html", "SHADOW MODEL FAQ",
        "Answers about the official SHADOW MODEL download, verification, offline use and Windows support.",
    )

    @app.get("/download/latest")
    def download_latest():
        release = latest_release()
        if release is None or not release["installer_path"]:
            flash("No verified stable release is available yet. Check back after the next official release.", "error")
            return redirect(url_for("download"))
        return _serve_installer(release)

    @app.get("/download/<int:release_id>/installer")
    def download_release(release_id: int):
        release = get_release(release_id)
        if release is None or not release["published"] or not release["verified"]:
            abort(404)
        return _serve_installer(release)

    @app.get("/media/screenshot/<int:screenshot_id>")
    def screenshot(screenshot_id: int):
        from flask import g

        row = get_db().execute("SELECT * FROM screenshots WHERE id = ?", (screenshot_id,)).fetchone()
        if row is None:
            abort(404)
        release = get_release(row["release_id"])
        if release is None or (not release["published"] and getattr(g, "admin_session", None) is None):
            abort(404)
        try:
            path = resolve_inside(app.config["RELEASE_STORAGE"], row["file_path"])
        except StorageError:
            abort(404)
        if not path.is_file():
            abort(404)
        return send_file(
            path,
            mimetype=row["mime_type"],
            conditional=True,
            max_age=3600,
            etag=True,
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "shadow-download"}, 200

    @app.get("/robots.txt")
    def robots():
        text = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin\n"
            "Disallow: /download/latest\n"
            "Disallow: /media/\n"
            f"Sitemap: {app.config['BASE_URL']}/sitemap.xml\n"
        )
        return make_response(text, 200, {"Content-Type": "text/plain; charset=utf-8"})

    @app.get("/sitemap.xml")
    def sitemap():
        release = latest_release()
        modified = (release["release_date"] if release else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for _endpoint, (_title, path) in PAGES.items():
            lines.append(
                f"<url><loc>{app.config['BASE_URL']}{path}</loc><lastmod>{modified}</lastmod>"
                "<changefreq>weekly</changefreq></url>"
            )
        lines.append("</urlset>")
        return make_response("\n".join(lines), 200, {"Content-Type": "application/xml; charset=utf-8"})

    @app.get("/admin-panel")
    def admin_shortcut():
        return redirect(url_for("admin.dashboard"))


def _serve_installer(release):
    from flask import current_app

    try:
        path = resolve_inside(current_app.config["RELEASE_STORAGE"], release["installer_path"])
    except StorageError:
        return _download_error("The release file path is invalid.", 503)
    if not path.is_file():
        return _download_error("The installer is missing from release storage. Please contact support.", 503)
    if not path.stat().st_size:
        return _download_error("The installer is empty and cannot be served.", 503)

    connection = get_db()
    connection.execute("UPDATE releases SET download_count = download_count + 1 WHERE id = ?", (release["id"],))
    connection.execute(
        "INSERT INTO downloads (release_id, ip_hash, created_at) VALUES (?, ?, ?)",
        (release["id"], hash_ip(request.remote_addr or "0.0.0.0"), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
    )
    connection.commit()

    response = send_file(
        path,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=release["installer_name"] or path.name,
        conditional=True,
        etag=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    if release["sha256"]:
        response.headers["X-Checksum-Sha256"] = release["sha256"]
    return response


def _download_error(message: str, status: int):
    return render_template("errors/download.html", page_title="Download unavailable", message=message), status


def register_errors(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("errors/400.html", page_title="Invalid request"), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html", page_title="Access denied"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html", page_title="Page not found"), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template(
            "errors/generic.html",
            page_title="Upload too large",
            message="The uploaded file exceeds the configured size limit.",
        ), 413

    @app.errorhandler(429)
    def rate_limited(error):
        from security import too_many_requests

        return too_many_requests(getattr(error, "retry_seconds", 15))

    @app.errorhandler(500)
    def server_error(_error):
        return render_template(
            "errors/generic.html",
            page_title="Something went wrong",
            message="The request could not be completed. Please try again later.",
        ), 500


def installer_download_url(release) -> str:
    """Return the live route, or a real GitHub Releases URL during static export."""
    if release is None:
        return url_for("download")
    template = current_app.config.get("STATIC_RELEASE_URL_TEMPLATE", "")
    if not current_app.config.get("STATIC_EXPORT") or not template:
        return url_for("download_release", release_id=release["id"])
    if "{version}" not in template or "{filename}" not in template:
        raise RuntimeError("SHADOW_STATIC_RELEASE_URL_TEMPLATE needs {version} and {filename}")
    filename = release["installer_name"] or Path(release["installer_path"] or "").name
    return template.format(
        version=quote(str(release["version"]), safe=""),
        filename=quote(str(filename), safe=""),
    )


def screenshot_display_url(shot) -> str:
    """Return the live media route, or a bundled static asset during export."""
    if not current_app.config.get("STATIC_EXPORT"):
        return url_for("screenshot", screenshot_id=shot["id"])
    filename = Path(shot["file_path"]).name
    return url_for("static", filename=f"screenshots/{filename}")


def register_template_helpers(app: Flask) -> None:
    app.jinja_env.filters["filesize"] = format_bytes
    app.jinja_env.filters["releasedate"] = format_date
    app.jinja_env.globals.update(
        release_notes_lines=release_notes_lines,
        screenshots_for=screenshots_for,
        installer_url=installer_download_url,
        screenshot_url=screenshot_display_url,
    )

    @app.context_processor
    def inject_site_context():
        connection = get_db()
        keys = (
            "hero_headline", "hero_description", "app_description", "features",
            "faq", "install_steps", "system_requirements", "support_url", "source_url",
        )
        content = {key: get_content(connection, key, "" if key.endswith("_url") else []) for key in keys}
        current = latest_release()
        return {
            "site": {
                "name": app.config["SITE_NAME"],
                "product": app.config["PRODUCT_NAME"],
                "base_url": app.config["BASE_URL"],
                "pages": PAGES,
                **content,
            },
            "latest": current,
            "releases": all_releases(),
            "current_year": datetime.now(timezone.utc).year,
        }


if __name__ == "__main__":
    application = create_app("development")
    application.run(
        host=os.getenv("SHADOW_HOST", "127.0.0.1"),
        port=config._int("SHADOW_PORT", 8000),
        debug=application.config["DEBUG"],
    )
