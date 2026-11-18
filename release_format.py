"""SHADOW release archive format used by the reproducible installer builder.

The installer is a small native Win32 stub followed by a private, length-prefixed
payload and a fixed footer. Keeping the format in one shared module lets the
website verify the exact bytes that the installer would extract.
"""

from __future__ import annotations

import hashlib
import os
import struct
import tarfile
import zipfile
from pathlib import Path
from typing import Iterator

MAGIC = b"SHADOWSFXv1\x00\x00\x00\x00\x00"
FOOTER_STRUCT = struct.Struct("<16sQQQ")
CHUNK = 1024 * 1024

EXCLUDED_NAMES = {
    "settings.ini",
    "models.json",
    "conversations.json",
    "self-test.txt",
    "portable.txt",
    "shadow_model_final_status.md",
    ".env",
    ".git",
}
EXCLUDED_SUFFIXES = {
    ".pdb", ".ilk", ".exp", ".log", ".tmp", ".bak", ".pyc",
    ".user", ".suo", ".idb", ".cache", ".crc",
}
EXCLUDED_PARTS = {"__pycache__", "devdata", "build", "tests", ".vs", ".git", "temp", "tmp"}


class ReleaseFormatError(ValueError):
    pass


def is_distributable(relative_path: str) -> bool:
    """Reject development files, temporary files and private user data."""
    if "\\" in relative_path or Path(relative_path).is_absolute():
        return False
    parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    if not parts or any(part in EXCLUDED_PARTS or part in {".", ".."} for part in parts):
        return False
    name = parts[-1].lower()
    if name in EXCLUDED_NAMES:
        return False
    if name.startswith("shadow-model") and name.endswith(".ckpt"):
        return False  # user-trained checkpoint, never shipped
    return Path(name).suffix.lower() not in EXCLUDED_SUFFIXES


def collect_files(source_dir: Path) -> list[tuple[str, Path]]:
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise ReleaseFormatError(f"Source directory does not exist: {source_dir}")
    files: list[tuple[str, Path]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir).as_posix()
        if is_distributable(relative):
            files.append((relative, path))
    if not files:
        raise ReleaseFormatError("No distributable files found in source directory.")
    return files


def iter_payload(installer_path: Path) -> Iterator[tuple[str, int, str]]:
    """Yield (relative path, byte size, SHA-256) for every embedded file."""
    path = Path(installer_path)
    size = path.stat().st_size
    if size < FOOTER_STRUCT.size:
        raise ReleaseFormatError("Installer is too small to contain a SHADOW payload.")
    with open(path, "rb") as handle:
        handle.seek(size - FOOTER_STRUCT.size)
        magic, offset, length, count = FOOTER_STRUCT.unpack(handle.read(FOOTER_STRUCT.size))
        if magic != MAGIC:
            raise ReleaseFormatError("Installer does not contain a SHADOW release payload.")
        if offset <= 0 or length <= 0 or count <= 0 or offset + length != size - FOOTER_STRUCT.size:
            raise ReleaseFormatError("SHADOW payload footer is inconsistent.")
        handle.seek(offset)
        end = offset + length
        for _ in range(count):
            if handle.tell() + 2 > end:
                raise ReleaseFormatError("Truncated payload entry.")
            (name_len,) = struct.unpack("<H", handle.read(2))
            if name_len == 0 or name_len > 4096 or handle.tell() + name_len + 8 > end:
                raise ReleaseFormatError("Invalid payload entry name.")
            name = handle.read(name_len).decode("utf-8")
            if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
                raise ReleaseFormatError(f"Unsafe payload path: {name}")
            (data_len,) = struct.unpack("<Q", handle.read(8))
            if handle.tell() + data_len > end:
                raise ReleaseFormatError("Truncated payload data.")
            digest = hashlib.sha256()
            remaining = data_len
            while remaining:
                chunk = handle.read(min(CHUNK, remaining))
                if not chunk:
                    raise ReleaseFormatError("Unexpected end of payload data.")
                digest.update(chunk)
                remaining -= len(chunk)
            yield name, data_len, digest.hexdigest()
        if handle.tell() != end:
            raise ReleaseFormatError("Payload has trailing data.")


def build_payload(source_dir: Path, payload_path: Path) -> list[tuple[str, int, str]]:
    """Write the length-prefixed payload and return its file manifest."""
    entries: list[tuple[str, int, str]] = []
    with open(payload_path, "wb") as output:
        for name, path in collect_files(source_dir):
            encoded = name.encode("utf-8")
            digest = hashlib.sha256()
            data_size = path.stat().st_size
            output.write(struct.pack("<H", len(encoded)))
            output.write(encoded)
            output.write(struct.pack("<Q", data_size))
            with open(path, "rb") as source:
                for chunk in iter(lambda: source.read(CHUNK), b""):
                    digest.update(chunk)
                    output.write(chunk)
            entries.append((name, data_size, digest.hexdigest()))
    return entries


def append_payload(stub_path: Path, payload_path: Path, output_path: Path, file_count: int) -> None:
    """Combine the compiled stub, payload and footer into one .exe."""
    with open(stub_path, "rb") as stub, open(payload_path, "rb") as payload, open(output_path, "wb") as output:
        for chunk in iter(lambda: stub.read(CHUNK), b""):
            output.write(chunk)
        offset = output.tell()
        total = 0
        for chunk in iter(lambda: payload.read(CHUNK), b""):
            output.write(chunk)
            total += len(chunk)
        output.write(FOOTER_STRUCT.pack(MAGIC, offset, total, file_count))


def inspect_other_archive(installer_path: Path) -> dict | None:
    """Best-effort inspection for ZIP-based third-party installers."""
    path = Path(installer_path)
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                return {"kind": "zip", "files": {n.lower(): i.file_size for n, i in
                        ((info.filename, info) for info in archive.infolist())}}
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                return {"kind": "tar", "files": {m.name.lower(): m.size for m in archive.getmembers() if m.isfile()}}
    except (OSError, zipfile.BadZipFile, tarfile.TarError):
        return None
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
