"""Optional user-scoped systemd service for headless, always-on TableTap.

Installation only writes the unit file. The user explicitly enables or
starts it, preventing accidental background command execution.
"""
from __future__ import annotations

import os
from pathlib import Path


def user_service_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "systemd" / "user" / "tabletap.service"


def render_user_service(python_executable: str) -> str:
    executable = Path(python_executable)
    if not executable.is_absolute():
        raise ValueError("The service needs an absolute Python executable path")
    # systemd's quoting rules differ from shell evaluation. Escape percentage
    # specifiers and embedded quotes; do not interpolate shell commands.
    quoted = '"' + str(executable).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    return (
        "[Unit]\n"
        "Description=TableTap headless acoustic shortcuts\n"
        "After=graphical-session.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={quoted} -m tabletap start\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "Environment=PYTHONUNBUFFERED=1\n\n"
        "[Install]\n"
        "WantedBy=graphical-session.target\n"
    )


def install_user_service(python_executable: str) -> Path:
    target = user_service_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".tabletap.service.tmp-" + str(os.getpid()))
    try:
        temporary.write_text(render_user_service(python_executable), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def remove_user_service() -> Path:
    target = user_service_path()
    target.unlink(missing_ok=True)
    return target
