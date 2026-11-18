#!/usr/bin/env python3
"""Reproducible SHADOW MODEL Windows release packaging.

Input:  the portable application folder produced by the existing project's
        scripts/package.ps1 (ShadowAI.exe + Qt/VC++ runtimes + engines + models).
Output: a single self-extracting .exe installer + manifest.json.

The tool refuses to package incomplete builds, includes only distributable
files, runs the application's smoke test, and records every embedded file hash.
It never publishes anything: publishing is a separate, authenticated step in
the website admin dashboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from release_format import (  # noqa: E402
    ReleaseFormatError,
    append_payload,
    build_payload,
    collect_files,
    iter_payload,
)

DEFAULT_SOURCE = Path(
    os.getenv(
        "SHADOW_APP_DIST",
        r"C:\Users\shado\OneDrive\Desktop\SHADOW_AI\dist\ShadowAI",
    )
)
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "release"
STUB_PATH = PROJECT_ROOT / "tools" / "installer_stub" / "shadow_installer_stub.exe"

CRITICAL_FILES = [
    "ShadowAI.exe",
    "config/settings.example.ini",
    "Qt6Core.dll",
    "Qt6Gui.dll",
    "Qt6Widgets.dll",
    "Qt6Network.dll",
    "Qt6Multimedia.dll",
    "Qt6Svg.dll",
    "platforms/qwindows.dll",
    "styles/qmodernwindowsstyle.dll",
    "multimedia/ffmpegmediaplugin.dll",
    "msvcp140.dll",
    "vcruntime140.dll",
    "engine/llama/llama-server.exe",
    "engine/whisper/whisper-cli.exe",
    "models/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "models/ggml-base.bin",
    "THIRD_PARTY_NOTICES.md",
    "licenses/Apache-2.0.txt",
]

MODEL_LICENSES = [
    {"file": "models/qwen2.5-1.5b-instruct-q4_k_m.gguf", "license": "Apache-2.0", "path": "licenses/Apache-2.0.txt"},
    {"file": "models/ggml-base.bin", "license": "MIT (Whisper Base)", "path": "THIRD_PARTY_NOTICES.md"},
    {"file": "engine/llama", "license": "MIT (llama.cpp) + LLVM OpenMP", "path": "engine/llama/LICENSE-LLVM-OpenMP"},
    {"file": "engine/whisper", "license": "MIT (whisper.cpp)", "path": "THIRD_PARTY_NOTICES.md"},
    {"file": "Qt runtime DLLs", "license": "LGPL-3.0 (dynamic linking)", "path": "THIRD_PARTY_NOTICES.md"},
]


def read_version(project_root: Path) -> str:
    cmake = project_root / "CMakeLists.txt"
    if cmake.is_file():
        match = re.search(r"project\s*\(\s*ShadowAI[\s\S]*?VERSION\s+(\d+\.\d+\.\d+)", cmake.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return match.group(1)
    raise ValueError("Could not determine version from CMakeLists.txt; pass --version explicitly.")


def ensure_stub() -> Path:
    if STUB_PATH.is_file() and STUB_PATH.stat().st_size > 1024:
        return STUB_PATH
    if sys.platform != "win32":
        raise FileNotFoundError("Installer stub is missing and can only be built on Windows.")
    batch = STUB_PATH.parent / "build_stub.bat"
    subprocess.run(["cmd", "/c", str(batch)], check=True, cwd=STUB_PATH.parent)
    if not STUB_PATH.is_file():
        raise FileNotFoundError("Installer stub build did not produce shadow_installer_stub.exe.")
    return STUB_PATH


def run_smoke_test(source_dir: Path) -> dict:
    exe = source_dir / "ShadowAI.exe"
    if not exe.is_file():
        raise FileNotFoundError("ShadowAI.exe is missing; cannot run smoke test.")
    completed = subprocess.run(
        [str(exe), "--smoke-test"],
        cwd=str(source_dir),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Application smoke test failed (exit {}): {}".format(
                completed.returncode, (completed.stdout + completed.stderr).strip()[:1000]
            )
        )
    return {"passed": True, "command": "ShadowAI.exe --smoke-test", "exit_code": 0}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a verified SHADOW MODEL Windows installer.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE, help="Portable app folder from package.ps1")
    parser.add_argument("--project-root", type=Path, default=None, help="SHADOW_AI source root (for version detection)")
    parser.add_argument("--version", default=None, help="Release version (default: from CMakeLists.txt)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-smoke-test", action="store_true")
    parser.add_argument("--install-to-storage", action="store_true", help="Copy artifacts into website release storage (still unpublished)")
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    project_root = (args.project_root or source_dir.parent.parent).resolve()
    version = args.version or read_version(project_root)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        raise ValueError("Invalid version string.")

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Portable application folder not found: {source_dir}")

    print(f"[1/6] Checking required application files in {source_dir}")
    missing = [item for item in CRITICAL_FILES if not (source_dir / item.replace("/", os.sep)).is_file()]
    if missing:
        raise RuntimeError("Build is incomplete; missing required files:\n  " + "\n  ".join(missing))

    if not args.skip_smoke_test:
        print("[2/6] Running application smoke test")
        smoke = run_smoke_test(source_dir)
    else:
        print("[2/6] Skipping smoke test (release must not be labelled stable)")
        smoke = {"passed": False, "skipped": True}

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = PROJECT_ROOT / "storage" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    payload_path = staging / f"payload-{version}-{os.urandom(4).hex()}.bin"

    print("[3/6] Building private payload (development/user data excluded)")
    try:
        entries = build_payload(source_dir, payload_path)
    finally:
        pass
    entry_map = {name.replace("\\", "/"): (size, digest) for name, size, digest in entries}
    missing_embedded = [item for item in CRITICAL_FILES if item not in entry_map]
    if missing_embedded:
        payload_path.unlink(missing_ok=True)
        raise RuntimeError("Required files were excluded from payload: " + ", ".join(missing_embedded))

    print("[4/6] Building self-extracting installer")
    stub = ensure_stub()
    installer_name = f"SHADOW-MODEL-{version}-setup.exe"
    installer_path = output_dir / installer_name
    append_payload(stub, payload_path, installer_path, len(entries))
    payload_path.unlink(missing_ok=True)

    print("[5/6] Verifying installer contents and writing manifest")
    installer_hash = sha256(installer_path)
    verified_entries = list(iter_payload(installer_path))
    if len(verified_entries) != len(entries):
        raise RuntimeError("Installer payload verification failed: file count mismatch.")

    manifest = {
        "product": "SHADOW MODEL",
        "version": version,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": "shadow-download/tools/package_release.py",
        "source": str(source_dir),
        "critical_files": CRITICAL_FILES,
        "required_files": [
            {"path": name, "size": size, "sha256": digest}
            for name, (size, digest) in sorted(entry_map.items())
        ],
        "file_count": len(entries),
        "installer": {"name": installer_name, "size": installer_path.stat().st_size, "sha256": installer_hash},
        "licenses": MODEL_LICENSES,
        "smoke_test": smoke,
        "stable_eligible": bool(smoke.get("passed")),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.install_to_storage:
        target = PROJECT_ROOT / "storage" / "releases" / version
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(installer_path, target / installer_name)
        shutil.copy2(manifest_path, target / "manifest.json")
        print(f"  Artifacts staged in {target} (not published)")

    print("[6/6] Done")
    print(f"  Installer: {installer_path} ({installer_path.stat().st_size / (1024**3):.2f} GiB)")
    print(f"  SHA-256:   {installer_hash}")
    print(f"  Manifest:  {manifest_path}")
    if not smoke.get("passed"):
        print("  WARNING: no smoke test result. Do not publish as stable.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError, ReleaseFormatError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
