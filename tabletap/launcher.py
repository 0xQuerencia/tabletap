"""Optional desktop action menu, using an existing local dmenu-compatible utility."""

import json
import shutil
import subprocess
import time

from .workflow import parse_workflow


def profile_menu(actions: dict, profile: str) -> dict:
    group = actions.get(profile)
    if not isinstance(group, dict):
        raise ValueError("Choose an existing named action profile")
    entries = {}
    numbered = []
    for key, action in group.items():
        if not isinstance(action, dict) or isinstance(key, bool):
            continue
        if not (isinstance(key, int) or (isinstance(key, str) and key.isascii() and key.isdecimal() and len(key) <= 4)):
            continue
        number = int(key)
        if 1 <= number <= 9999:
            numbered.append((number, action))
    for _, action in sorted(numbered, key=lambda item: item[0]):
        kind, value = action.get("type", "key"), action.get("value")
        if kind == "launcher":
            continue
        if kind == "workflow":
            parse_workflow(value)
        else:
            parse_workflow(json.dumps([{"type": kind, "value": value}]))
        title = action.get("name") or ("Workflow" if kind == "workflow" else value)
        title = "".join(char for char in str(title) if char.isprintable()).strip()[:100] or "Action"
        entries[f"{len(entries) + 1}. {title}"] = action
    if not entries:
        raise ValueError("This profile has no launchable actions")
    if len(entries) > 20:
        raise ValueError("Launcher profiles support at most 20 actions")
    return entries


def menu_command(display: str) -> list[str]:
    candidates = {
        "wayland": [
            ["fuzzel", "--dmenu"],
            ["wofi", "--dmenu", "--prompt", "TableTap"],
            ["rofi", "-dmenu", "-p", "TableTap", "-no-custom"],
        ],
        "x11": [
            ["rofi", "-dmenu", "-p", "TableTap", "-no-custom"],
            ["dmenu", "-i", "-p", "TableTap"],
        ],
    }.get(display, [])
    for argv in candidates:
        executable = shutil.which(argv[0])
        if executable:
            return [executable, *argv[1:]]
    raise RuntimeError("No supported desktop launcher found (install fuzzel, wofi, rofi or dmenu)")


def choose_action(entries: dict, display: str, check_authorized):
    argv = menu_command(display)
    check_authorized()
    deadline = time.monotonic() + 30
    with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        pending_input = "\n".join(entries) + "\n"
        try:
            while True:
                check_authorized()
                if time.monotonic() >= deadline:
                    return None
                try:
                    stdout, stderr = process.communicate(input=pending_input, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
            check_authorized()
            if process.returncode == 1:
                return None
            if process.returncode != 0:
                raise RuntimeError("Launcher failed: " + (stderr.strip()[:200] or str(process.returncode)))
            # Never interpret arbitrary menu input as a command.
            return entries.get(stdout.rstrip("\r\n"))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
