"""Packaging and release-verification tests using a small synthetic build."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.package_release import CRITICAL_FILES  # noqa: E402
from release_format import is_distributable, iter_payload  # noqa: E402

PYTHON = sys.executable


class PackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "app"
        self.output = self.root / "out"
        self.source.mkdir()
        for relative in CRITICAL_FILES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = b"MZ synthetic" if relative.endswith(".exe") else b"payload"
            path.write_bytes(content * 40)
        license_file = self.source / "engine" / "llama" / "LICENSE-LLVM-OpenMP"
        license_file.parent.mkdir(parents=True, exist_ok=True)
        license_file.write_bytes(b"LLVM OpenMP license")
        (self.source / "settings.ini").write_text("api_key=SECRET", encoding="utf-8")
        (self.source / "debug.pdb").write_bytes(b"debug symbols")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_package_and_verify(self) -> None:
        result = subprocess.run(
            [PYTHON, str(ROOT / "tools" / "package_release.py"),
             "--source-dir", str(self.source),
             "--output-dir", str(self.output),
             "--version", "0.0.1-test",
             "--skip-smoke-test"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installer = self.output / "SHADOW-MODEL-0.0.1-test-setup.exe"
        manifest_path = self.output / "manifest.json"
        self.assertTrue(installer.is_file())
        self.assertTrue(manifest_path.is_file())

        names = [name.lower() for name, _size, _digest in iter_payload(installer)]
        self.assertIn("shadowai.exe", names)
        self.assertNotIn("settings.ini", names)
        self.assertNotIn("debug.pdb", names)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.0.1-test")
        self.assertTrue(all(item["sha256"] for item in manifest["required_files"]))

        failed = subprocess.run(
            [PYTHON, str(ROOT / "tools" / "verify_release.py"), str(installer)],
            capture_output=True, text=True,
        )
        self.assertEqual(failed.returncode, 1, failed.stdout)
        self.assertIn("smoke test", failed.stdout.lower())

        manifest["smoke_test"] = {"passed": True, "command": "test", "exit_code": 0}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        passed = subprocess.run(
            [PYTHON, str(ROOT / "tools" / "verify_release.py"), str(installer)],
            capture_output=True, text=True,
        )
        self.assertEqual(passed.returncode, 0, passed.stdout)

        env = dict(__import__("os").environ)
        env["SHADOW_DB_PATH"] = str(self.root / "test.db")
        env["SHADOW_STORAGE_PATH"] = str(self.root / "storage")
        published = subprocess.run(
            [PYTHON, str(ROOT / "tools" / "publish_release.py"),
             "--version", "0.0.1-test",
             "--installer", str(installer),
             "--publish", "--title", "Test release",
             "--notes-file", str(self._write_text("release notes for test")),
             "--requirements-file", str(self._write_text("requirements for test"))],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        self.assertIn('"published": true', published.stdout)

    def _write_text(self, content: str) -> Path:
        path = self.root / f"text-{len(list(self.root.glob('text-*')))}.txt"
        path.write_text(content, encoding="utf-8")
        return path

    def test_distributable_filter(self) -> None:
        self.assertTrue(is_distributable("ShadowAI.exe"))
        self.assertTrue(is_distributable("engine/llama/llama-server.exe"))
        self.assertFalse(is_distributable("settings.ini"))
        self.assertFalse(is_distributable("devdata/settings.ini"))
        self.assertFalse(is_distributable("ShadowAI.pdb"))
        self.assertFalse(is_distributable("../outside.exe"))


if __name__ == "__main__":
    unittest.main()
