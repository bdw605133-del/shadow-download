"""Bootstrap the hidden server with this project's virtual environment.

Windows Task Scheduler launches this file with the base pythonw.exe rather than
the venv launcher. That keeps the long-running process as the task itself, so
Task Scheduler can detect a crash and apply its RestartOnFailure policy.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_ROOT = ROOT / ".venv"
VENV_SITE_PACKAGES = VENV_ROOT / "Lib" / "site-packages"

if VENV_ROOT.is_dir():
    sys.prefix = str(VENV_ROOT)
    sys.exec_prefix = str(VENV_ROOT)

if VENV_SITE_PACKAGES.is_dir():
    site.addsitedir(str(VENV_SITE_PACKAGES))
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

sys.path.insert(0, str(ROOT))

from server_runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
