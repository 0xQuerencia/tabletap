"""Install user-scoped launchers without a system package or shell."""
import os
import sys
from pathlib import Path


def _exec(executable):
    if not Path(executable).is_absolute() or any(c in executable for c in "\r\n\x00"):
        raise ValueError("Launcher needs an absolute Python executable")
    escaped = executable.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("\x60", "\\\x60").replace("%", "%%")
    return '"' + escaped + '" -m tabletap'


def install_launcher(executable=None):
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    target = root / "applications" / "art.querencia.tabletap.desktop"
    icons = root / "icons/hicolor/scalable/apps"
    icons.mkdir(parents=True, exist_ok=True)
    (icons / "art.querencia.tabletap.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        '<rect width="128" height="128" rx="28" fill="#181715"/>'
        '<circle cx="64" cy="64" r="43" fill="none" stroke="#725333" stroke-width="3"/>'
        '<circle cx="64" cy="64" r="28" fill="none" stroke="#e6a15d" stroke-width="4"/>'
        '<circle cx="64" cy="64" r="12" fill="#e6a15d"/></svg>\n', encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[Desktop Entry]\nType=Application\nName=TableTap\n"
                      "Comment=Turn desk taps into shortcuts\n"
                      f"Exec={_exec(executable or sys.executable)} desktop\n"
                      "Icon=art.querencia.tabletap\nTerminal=false\nCategories=Utility;\n"
                      "StartupNotify=true\n", encoding="utf-8")
    return target


def autostart_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "art.querencia.tabletap.desktop"


def set_autostart(enabled, executable=None):
    target = autostart_path()
    if not enabled:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[Desktop Entry]\nType=Application\nName=TableTap preview\n"
                      f"Exec={_exec(executable or sys.executable)} start --preview\n"
                      "Terminal=false\n", encoding="utf-8")
