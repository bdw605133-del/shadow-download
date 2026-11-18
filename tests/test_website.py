"""Security and release-management tests (stdlib unittest + Flask test client)."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from app import create_app
from db import connect_db, init_db, set_content, utc_now
from security import hash_password

CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


class ShadowDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = config.TestingConfig
        self.db_path = Path(self.settings.DB_PATH)
        self.storage_root = Path(self.settings.STORAGE_ROOT)
        for path in (self.db_path, self.storage_root):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink(missing_ok=True)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        (self.storage_root / "releases").mkdir(exist_ok=True)
        (self.storage_root / "staging").mkdir(exist_ok=True)

        self.app = create_app("testing")
        self.app.config["COOKIE_SECURE"] = False
        self.client = self.app.test_client()
        connection = connect_db(self.db_path)
        connection.execute(
            "INSERT INTO admins (username, password_hash, display_name, must_change_password, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            ("admin", hash_password("TestAdminPassword!234"), "Test Admin", utc_now()),
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.db_path) + suffix)
            if path.exists():
                path.unlink(missing_ok=True)
        shutil.rmtree(self.storage_root, ignore_errors=True)
        secret = Path("storage") / "secret.txt"
        if secret.exists():
            secret.unlink()

    def _csrf(self, html: bytes) -> str:
        match = CSRF_RE.search(html.decode("utf-8"))
        self.assertIsNotNone(match, "No CSRF token found in form")
        return match.group(1)

    def _login(self) -> None:
        response = self.client.get("/admin/login")
        token = self._csrf(response.data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "TestAdminPassword!234", "csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_public_pages_render(self) -> None:
        for path in ("/", "/download", "/features", "/release-notes", "/system-requirements", "/installation", "/faq"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_no_fake_download(self) -> None:
        page = self.client.get("/download")
        self.assertIn(b"No verified release is available yet", page.data)
        response = self.client.get("/download/latest")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/download", response.headers["Location"])

    def test_admin_requires_authentication(self) -> None:
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

    def test_login_requires_csrf(self) -> None:
        response = self.client.post("/admin/login", data={"username": "admin", "password": "wrong"})
        self.assertEqual(response.status_code, 400)

    def test_session_cookie_is_hardened(self) -> None:
        response = self.client.get("/admin/login")
        token = self._csrf(response.data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "TestAdminPassword!234", "csrf_token": token},
        )
        cookie_header = response.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Lax", cookie_header)

    def test_admin_post_requires_session_csrf(self) -> None:
        self._login()
        response = self.client.post("/admin/logout", data={})
        self.assertEqual(response.status_code, 400)

    def test_security_headers(self) -> None:
        response = self.client.get("/")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_unpublished_release_is_not_downloadable(self) -> None:
        connection = connect_db(self.db_path)
        connection.execute(
            "INSERT INTO releases (version, title, release_date, notes, installer_name, installer_path, "
            "file_size, sha256, requirements, published, verified, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)",
            ("9.9.9", "Draft", "2026-01-01", "Draft notes", "setup.exe", "9.9.9/setup.exe",
             2048, "a" * 64, "Test requirements", utc_now(), utc_now()),
        )
        connection.commit()
        connection.close()
        self.assertEqual(self.client.get("/download/1/installer").status_code, 404)

    def test_path_traversal_is_blocked(self) -> None:
        secret = Path("storage") / "secret.txt"
        secret.write_text("not a release", encoding="utf-8")
        connection = connect_db(self.db_path)
        connection.execute(
            "INSERT INTO releases (version, title, release_date, notes, installer_name, installer_path, "
            "file_size, sha256, requirements, published, verified, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            ("8.8.8", "Evil", "2026-01-01", "Notes here", "setup.exe", "../secret.txt",
             13, "b" * 64, "Requirements here", utc_now(), utc_now()),
        )
        connection.commit()
        connection.close()
        response = self.client.get("/download/1/installer")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"not a release", response.data)

    def test_published_release_pages_render(self) -> None:
        connection = connect_db(self.db_path)
        connection.execute(
            "INSERT INTO releases (version, title, release_date, notes, installer_name, installer_path, "
            "file_size, sha256, min_windows, requirements, published, verified, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            ("1.0.0", "Test release", "2026-01-01", "First note\nSecond note", "setup.exe",
             "1.0.0/setup.exe", 2048, "c" * 64, "Windows 10", "Test requirements", utc_now(), utc_now()),
        )
        connection.commit()
        connection.close()
        for path in ("/", "/download", "/release-notes", "/system-requirements", "/installation"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_content_is_html_escaped(self) -> None:
        connection = connect_db(self.db_path)
        set_content(connection, "hero_headline", "<script>alert(1)</script>")
        connection.commit()
        connection.close()
        page = self.client.get("/")
        self.assertNotIn(b"<script>alert(1)</script>", page.data)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", page.data)

    def test_login_rate_limit(self) -> None:
        self.app.config["LOGIN_MAX_ATTEMPTS"] = 2
        response = self.client.get("/admin/login")
        token = self._csrf(response.data)
        for _ in range(3):
            self.client.post(
                "/admin/login",
                data={"username": "admin", "password": "bad", "csrf_token": token},
            )
        response = self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "bad", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
