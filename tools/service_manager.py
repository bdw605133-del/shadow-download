"""Manage a persistent Windows autostart task for SHADOW DOWNLOAD.

No administrator rights are required: the task runs for the current user at
logon and is restarted automatically if the server process exits unexpectedly.
"""

from __future__ import annotations

import argparse
import html
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (loads .env after ROOT is on sys.path)

TASK_NAME = "SHADOW DOWNLOAD Website"
BOOTSTRAP = ROOT / "boot_server.py"
# Use the base interpreter, not .venv\Scripts\pythonw.exe. The venv executable
# is a launcher that spawns a child process, which prevents Task Scheduler from
# attributing a crash to the task and triggering RestartOnFailure.
BASE_PYTHONW = Path(sys._base_executable).with_name("pythonw.exe")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _echo_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def _whoami() -> str:
    result = _run("whoami")
    if result.returncode != 0:
        raise RuntimeError("Unable to determine the current Windows account.")
    return result.stdout.strip()


def _port() -> int:
    try:
        return int(os.getenv("SHADOW_PORT", "8000"))
    except ValueError:
        return 8000


def _task_xml() -> str:
    user = html.escape(_whoami(), quote=True)
    command = html.escape(str(BASE_PYTHONW), quote=True)
    arguments = html.escape(f'"{BOOTSTRAP}"', quote=True)
    working_directory = html.escape(str(ROOT), quote=True)
    now = datetime.now()
    created = now.strftime("%Y-%m-%dT%H:%M:%S")
    start_boundary = now.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")

    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{created}</Date>
    <Author>{user}</Author>
    <Description>Keeps the official SHADOW MODEL download website available at logon.</Description>
    <URI>\\{html.escape(TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
    </LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT1M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''


def task_exists() -> bool:
    return _run("schtasks", "/Query", "/TN", TASK_NAME).returncode == 0


def _port_is_open(port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _health_ok(timeout: float = 1.0) -> bool:
    url = f"http://127.0.0.1:{_port()}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def stop_server(disable: bool = False) -> bool:
    """End the scheduled task and any matching server already holding the port."""
    stopped = False
    if task_exists():
        if disable:
            change = _run("schtasks", "/Change", "/TN", TASK_NAME, "/DISABLE")
            _echo_result(change)
        result = _run("schtasks", "/End", "/TN", TASK_NAME)
        if result.returncode == 0:
            stopped = True
        _echo_result(result)

    script = f"""
$port = {_port()}
$root = {_ps_quote(str(ROOT))}
$portOwners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)

$candidates = @()
foreach ($processId in $portOwners) {{
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if ($process) {{ $candidates += $process }}
}}
$candidates += Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -like 'python*.exe' -and $_.CommandLine -and $_.CommandLine -like "*$root*" -and
    ($_.CommandLine -like '*boot_server.py*' -or $_.CommandLine -like '*server_runner.py*' -or $_.CommandLine -like '*wsgi.py*')
}}

$seen = @()
foreach ($process in $candidates) {{
    if (-not $process -or -not $process.CommandLine -or $seen -contains $process.ProcessId) {{ continue }}
    $seen += $process.ProcessId
    $matchesScript = $process.CommandLine -like '*boot_server.py*' -or $process.CommandLine -like '*server_runner.py*' -or $process.CommandLine -like '*wsgi.py*'
    $isPortOwner = $portOwners -contains $process.ProcessId
    $matchesProject = $process.CommandLine -like "*$root*"
    if ($matchesScript -and ($isPortOwner -or $matchesProject)) {{
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped process $($process.ProcessId)"
    }}
}}
"""
    result = _run("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
    _echo_result(result)

    for _ in range(20):
        if not _port_is_open(_port()):
            break
        time.sleep(0.25)
    return stopped


def start_server() -> bool:
    if not task_exists():
        print("Autostart task is not installed. Run: install", file=sys.stderr)
        return False

    change = _run("schtasks", "/Change", "/TN", TASK_NAME, "/ENABLE")
    _echo_result(change)
    if change.returncode != 0:
        return False

    result = _run("schtasks", "/Run", "/TN", TASK_NAME)
    _echo_result(result)
    if result.returncode != 0:
        return False

    for _ in range(40):
        if _health_ok():
            print(f"SHADOW DOWNLOAD is running at http://127.0.0.1:{_port()}")
            return True
        time.sleep(0.25)

    print("Task started, but /health did not respond. Check logs/server.log.", file=sys.stderr)
    return False


def install() -> int:
    if not BASE_PYTHONW.is_file():
        print(f"Missing {BASE_PYTHONW}. A Python 3.12 installation is required.", file=sys.stderr)
        return 1
    if not (ROOT / ".venv" / "Lib" / "site-packages").is_dir():
        print("The virtual environment is missing. Run scripts\\start_local.bat first.", file=sys.stderr)
        return 1
    if not BOOTSTRAP.is_file():
        print(f"Missing {BOOTSTRAP}.", file=sys.stderr)
        return 1

    handle = tempfile.NamedTemporaryFile("w", encoding="utf-16", suffix=".xml", delete=False)
    try:
        handle.write(_task_xml())
        handle.close()
        result = _run("schtasks", "/Create", "/TN", TASK_NAME, "/XML", handle.name, "/F")
        _echo_result(result)
        if result.returncode != 0:
            print("Could not register the autostart task.", file=sys.stderr)
            return 1
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

    stop_server()
    return 0 if start_server() else 1


def uninstall() -> int:
    if not task_exists():
        print("Autostart task is not installed.")
        return 0
    stop_server(disable=True)
    result = _run("schtasks", "/Delete", "/TN", TASK_NAME, "/F")
    _echo_result(result)
    return result.returncode


def status() -> int:
    if task_exists():
        print(f"Autostart task: installed ({TASK_NAME})")
        result = _run("schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V")
        _echo_result(result)
    else:
        print(f"Autostart task: not installed ({TASK_NAME})")

    print(f"Port {_port()}: {'open' if _port_is_open(_port()) else 'closed'}")
    print(f"Health check: {'OK' if _health_ok() else 'FAILED'}")
    return 0 if _health_ok() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("install", "uninstall", "start", "stop", "restart", "status"),
        help="Action to perform",
    )
    args = parser.parse_args()

    if args.command == "install":
        return install()
    if args.command == "uninstall":
        return uninstall()
    if args.command == "start":
        return 0 if start_server() else 1
    if args.command == "stop":
        # Disable first: the minute health check would otherwise restart it.
        stop_server(disable=True)
        return 0
    if args.command == "restart":
        stop_server()
        return 0 if start_server() else 1
    return status()


if __name__ == "__main__":
    sys.exit(main())
