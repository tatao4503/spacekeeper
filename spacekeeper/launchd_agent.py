from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "com.spacekeeper.agent"
PLIST_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
)


def install_launchd_agent(interval_hours: int = 168) -> bool:
    """Generate a launchd plist and load it via *launchctl*.

    *interval_hours* controls the ``StartInterval`` value
    (converted to seconds).  Returns ``True`` on success.
    """
    # 번들(PyInstaller)에서는 실행 파일을 직접 호출하고, 개발 환경에서는
    # `python -m spacekeeper` 로 호출한다.
    if getattr(sys, "frozen", False):
        program_arguments = [sys.executable, "--scheduled-run"]
    else:
        program_arguments = [sys.executable, "-m", "spacekeeper", "--scheduled-run"]

    plist: dict = {
        "Label": PLIST_LABEL,
        "ProgramArguments": program_arguments,
        "StartInterval": interval_hours * 3600,
        "StandardOutPath": str(Path.home() / ".spacekeeper" / "agent.log"),
        "StandardErrorPath": str(Path.home() / ".spacekeeper" / "agent.log"),
    }

    try:
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PLIST_PATH.open("wb") as fh:
            plistlib.dump(plist, fh)

        subprocess.run(
            ["launchctl", "load", str(PLIST_PATH)],
            check=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def uninstall_launchd_agent() -> bool:
    """Unload the launchd agent and remove its plist file.

    Returns ``True`` on success.
    """
    try:
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            check=True,
        )
        PLIST_PATH.unlink(missing_ok=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def is_agent_installed() -> bool:
    """Return ``True`` if the plist file exists on disk."""
    return PLIST_PATH.is_file()
