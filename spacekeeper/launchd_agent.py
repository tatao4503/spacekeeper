from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "com.spacekeeper.agent"
PLIST_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
)
LOG_PATH = Path.home() / ".spacekeeper" / "agent.log"


def install_launchd_agent(interval_hours: int = 168) -> bool:
    """Generate a launchd plist and load it via *launchctl*.

    *interval_hours* controls the ``StartInterval`` value
    (converted to seconds).  Returns ``True`` on success.
    """
    # 번들(PyInstaller)에서는 실행 파일을 직접 호출하고, 개발 환경에서는
    # `python -m spacekeeper` 로 호출한다.
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if "/AppTranslocation/" in str(executable) or executable.is_relative_to(
            Path("/Volumes")
        ):
            return False
        program_arguments = [sys.executable, "--scheduled-run"]
    else:
        program_arguments = [sys.executable, "-m", "spacekeeper", "--scheduled-run"]

    plist: dict = {
        "Label": PLIST_LABEL,
        "ProgramArguments": program_arguments,
        "StartInterval": interval_hours * 3600,
        "WorkingDirectory": str(Path(__file__).resolve().parents[1]),
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PLIST_PATH.open("wb") as fh:
            plistlib.dump(plist, fh)

        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["launchctl", "load", str(PLIST_PATH)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        try:
            PLIST_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def uninstall_launchd_agent() -> bool:
    """Unload the launchd agent and remove its plist file.

    Returns ``True`` on success.
    """
    if not PLIST_PATH.exists():
        return True
    try:
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        PLIST_PATH.unlink(missing_ok=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def is_agent_installed() -> bool:
    """Return ``True`` only when the plist targets an existing executable."""
    try:
        with PLIST_PATH.open("rb") as handle:
            plist = plistlib.load(handle)
        arguments = plist.get("ProgramArguments")
        return (
            plist.get("Label") == PLIST_LABEL
            and isinstance(arguments, list)
            and bool(arguments)
            and isinstance(arguments[0], str)
            and Path(arguments[0]).is_file()
        )
    except (OSError, plistlib.InvalidFileException, TypeError, ValueError):
        return False
