"""Hidden runner used by Windows Task Scheduler.

Unlike a normal console process, this script writes startup/crash information to
logs/server.log so an autostart failure can still be diagnosed.
"""

from __future__ import annotations

import os
import socket
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "logs" / "server.log"
MAX_LOG_BYTES = 2 * 1024 * 1024


def _rotate_log_if_needed() -> None:
    try:
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.1"))
    except OSError:
        pass


def log(message: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} [pid {os.getpid()}] {message}\n")
    except OSError:
        pass


def _port_is_open(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.25):
            return True
    except OSError:
        return False


def main() -> int:
    log("SHADOW DOWNLOAD server runner started")
    try:
        from wsgi import build_server, server_options

        options = server_options()
        if _port_is_open(str(options["host"]), int(options["port"])):
            log(f"Port {options['port']} is already serving; refusing to start a second listener.")
            return 1
        log(f"Starting Waitress on {options['host']}:{options['port']} ({options['threads']} threads)")
        build_server().run()
        log("Waitress server stopped")
        return 0
    except SystemExit as exc:
        log(f"SystemExit ({exc.code})")
        return int(exc.code or 0)
    except Exception:
        log("Fatal server error:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
