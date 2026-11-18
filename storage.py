"""Release storage, checksum generation and installer verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CHUNK_SIZE = 1024 * 1024

PE_SIGNATURE = b"MZ"
MSI_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
WEBP_SIGNATURE = b"RIFF"

SCREENSHOT_MIMES = {
    "image/png": PNG_SIGNATURE,
    "image/jpeg": JPEG_SIGNATURE,
    "image/webp": WEBP_SIGNATURE,
}


class StorageError(ValueError):
    """Raised when an upload or release payload is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_folder(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise StorageError("Invalid version identifier.")
    return version


def storage_root() -> Path:
    return Path(current_app.config["RELEASE_STORAGE"])


def staging_root() -> Path:
    return Path(current_app.config["STAGING_STORAGE"])


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve a DB-controlled relative path and keep it inside root."""
    if not relative or Path(relative).is_absolute():
        raise StorageError("Invalid storage path.")
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if root_resolved not in candidate.parents and candidate != root_resolved:
        raise StorageError("Storage path escapes the release directory.")
    return candidate


def release_directory(version: str, *, create: bool = False) -> Path:
    directory = storage_root() / version_folder(version)
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _detect_installer_type(path: Path) -> str:
    with open(path, "rb") as handle:
        header = handle.read(8)
    if header.startswith(PE_SIGNATURE):
        return "exe"
    if header.startswith(MSI_SIGNATURE):
        return "msi"
    raise StorageError("The uploaded installer is not a valid Windows PE (.exe) or MSI file.")


def _detect_screenshot_type(path: Path) -> str:
    with open(path, "rb") as handle:
        header = handle.read(12)
    for mime, signature in SCREENSHOT_MIMES.items():
        if header.startswith(signature):
            if mime == "image/webp" and header[8:12] != b"WEBP":
                continue
            return mime
    raise StorageError("Screenshots must be PNG, JPEG or WebP images.")


def _write_stream(file_storage, destination: Path, max_bytes: int) -> int:
    digest = hashlib.sha256()
    written = 0
    with open(destination, "wb") as handle:
        while True:
            chunk = file_storage.stream.read(CHUNK_SIZE)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise StorageError("Uploaded file is too large.")
            digest.update(chunk)
            handle.write(chunk)
            handle.flush()
    return written


def save_installer(file_storage, version: str) -> dict[str, object]:
    """Stream an installer into dedicated release storage (never into the DB)."""
    original = secure_filename(file_storage.filename or "")
    suffix = Path(original).suffix.lower()
    if suffix not in {".exe", ".msi"}:
        raise StorageError("Only .exe and .msi installers are accepted.")

    directory = release_directory(version, create=True)
    staging = staging_root()
    staging.mkdir(parents=True, exist_ok=True)
    temp_path = staging / f"installer-{os.urandom(8).hex()}{suffix}"
    final_name = f"SHADOW-MODEL-{version_folder(version)}-setup{suffix}"
    final_path = directory / final_name
    try:
        written = _write_stream(file_storage, temp_path, current_app.config["MAX_CONTENT_LENGTH"])
        if written < 1024 * 1024:
            raise StorageError("Installer is too small to be a real application build.")
        kind = _detect_installer_type(temp_path)
        if kind == "msi" and suffix != ".msi":
            raise StorageError("MSI payload must use the .msi extension.")
        if kind == "exe" and suffix != ".exe":
            raise StorageError("Windows executable payload must use the .exe extension.")
        checksum = sha256_file(temp_path)
        os.replace(temp_path, final_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return {
        "installer_path": str(final_path.relative_to(storage_root())).replace("\\", "/"),
        "installer_name": final_name,
        "file_size": written,
        "sha256": checksum,
    }


def save_screenshot(file_storage, version: str, index: int) -> dict[str, str]:
    staging = staging_root()
    staging.mkdir(parents=True, exist_ok=True)
    temp_path = staging / f"screenshot-{os.urandom(8).hex()}.bin"
    try:
        _write_stream(file_storage, temp_path, current_app.config["MAX_SCREENSHOT_BYTES"])
        mime = _detect_screenshot_type(temp_path)
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
        directory = release_directory(version, create=True)
        directory.mkdir(parents=True, exist_ok=True)
        final_name = f"screenshot-{index}-{os.urandom(4).hex()}{extension}"
        final_path = directory / final_name
        os.replace(temp_path, final_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return {
        "file_path": str(final_path.relative_to(storage_root())).replace("\\", "/"),
        "mime_type": mime,
    }


def delete_file(relative: str | None) -> None:
    if not relative:
        return
    try:
        path = resolve_inside(storage_root(), relative)
    except StorageError:
        return
    if path.is_file():
        path.unlink(missing_ok=True)


def delete_release_directory(version: str) -> None:
    directory = release_directory(version)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


def read_manifest(version: str) -> dict | None:
    path = release_directory(version) / "manifest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def verify_release(release) -> tuple[bool, list[str], list[str]]:
    """Verify a release before it can be marked stable.

    Returns (ok, errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []
    version = release["version"]

    required_metadata = {
        "version": release["version"],
        "release date": release["release_date"],
        "release notes": release["notes"],
        "minimum Windows version": release["min_windows"],
        "system requirements": release["requirements"],
        "installer name": release["installer_name"],
        "SHA-256 checksum": release["sha256"],
        "file size": release["file_size"],
    }
    for label, value in required_metadata.items():
        if not value:
            errors.append(f"Missing release metadata: {label}.")

    if not release["installer_path"]:
        errors.append("No installer has been uploaded for this release.")
        return False, errors, warnings

    try:
        installer = resolve_inside(storage_root(), release["installer_path"])
    except StorageError as exc:
        errors.append(str(exc))
        return False, errors, warnings

    if not installer.is_file():
        errors.append("Installer file is missing from release storage.")
        return False, errors, warnings
    if not os.access(installer, os.R_OK):
        errors.append("Installer file is not readable.")
        return False, errors, warnings

    try:
        detected = _detect_installer_type(installer)
    except StorageError as exc:
        errors.append(str(exc))
        detected = ""
    expected_suffix = Path(release["installer_name"]).suffix.lower().lstrip(".")
    if detected and detected != expected_suffix:
        errors.append("Installer extension does not match its binary format.")

    actual_size = installer.stat().st_size
    if release["file_size"] and actual_size != int(release["file_size"]):
        errors.append(f"File size mismatch: expected {release['file_size']}, found {actual_size}.")

    actual_hash = sha256_file(installer)
    if release["sha256"] and actual_hash.lower() != str(release["sha256"]).lower():
        errors.append("SHA-256 mismatch: the stored checksum does not match the installer.")

    manifest = read_manifest(version)
    if manifest is None:
        errors.append(
            "No verifiable build manifest found. Package the release with tools/package_release.py "
            "so required application files can be checked."
        )
    else:
        required = manifest.get("required_files")
        if not isinstance(required, list) or not required:
            errors.append("Build manifest has no required_files list.")
        else:
            from release_format import ReleaseFormatError, inspect_other_archive, iter_payload

            embedded: dict[str, tuple[int, str]] = {}
            try:
                for name, item_size, item_hash in iter_payload(installer):
                    embedded[name.replace("\\", "/").lower()] = (item_size, item_hash)
            except ReleaseFormatError:
                other = inspect_other_archive(installer)
                if other:
                    embedded = {
                        name: (size, "") for name, size in other["files"].items()
                    }
                    warnings.append("Third-party archive format detected; file checksums were not verified.")
                elif not manifest.get("external_verification"):
                    errors.append(
                        "Installer payload cannot be inspected. Use the SHADOW packaging tool or "
                        "provide external verification in the build manifest."
                    )
            for item in required:
                if not isinstance(item, dict) or not item.get("path"):
                    errors.append("Build manifest contains an invalid required file entry.")
                    continue
                relative = str(item["path"]).replace("\\", "/").lower()
                matches = [
                    value for name, value in embedded.items()
                    if name == relative or name.endswith("/" + relative)
                ]
                if not matches:
                    errors.append(f"Required application file is absent from installer: {relative}.")
                    continue
                expected_hash = str(item.get("sha256") or "").lower()
                if expected_hash and matches[0][1] and expected_hash != matches[0][1]:
                    errors.append(f"Required file checksum mismatch: {relative}.")

    for screenshot in _release_screenshots(release):
        try:
            image_path = resolve_inside(storage_root(), screenshot["file_path"])
        except StorageError:
            errors.append("A screenshot path is invalid.")
            continue
        if not image_path.is_file():
            errors.append("A published screenshot is missing from storage.")

    return not errors, errors, warnings


def _release_screenshots(release) -> list:
    from db import get_db

    if "id" not in release.keys():
        return []
    return get_db().execute(
        "SELECT file_path FROM screenshots WHERE release_id = ?", (release["id"],)
    ).fetchall()


def written_at() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
