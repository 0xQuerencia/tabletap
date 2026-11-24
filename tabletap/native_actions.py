import json
import os
import shutil
import subprocess
from pathlib import Path

CATALOG = {
    item["id"]: item
    for item in json.loads((Path(__file__).parent / "ui" / "native-actions.json").read_text(encoding="utf-8"))
}


def validate_builtin(value: str):
    if not isinstance(value, str):
        raise ValueError("Built-in action must be text")
    action_id, sep, arg = value.partition(":")
    item = CATALOG.get(action_id)
    if item is None:
        raise ValueError(f"Unknown built-in action: {action_id}")
    param = item.get("parameter")
    if param:
        if not sep or not arg.strip() or len(arg) > 100 or any(not c.isprintable() for c in arg):
            raise ValueError(f"{item['label']} requires a {param} parameter")
    elif sep:
        raise ValueError(f"{item['label']} does not accept a parameter")
    return item, arg


def unavailable(item: dict) -> str | None:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    required = item.get("desktop")
    if required and required not in desktop:
        return f"Requires {required.upper()} desktop"
    if item["id"].startswith("hyprland.") and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "Requires a running Hyprland session"
    adapter = item.get("adapter")
    if adapter == "key":
        choices = ("wtype", "ydotool") if os.environ.get("WAYLAND_DISPLAY") else ("xdotool",)
        if not any(shutil.which(tool) for tool in choices):
            return "Install a supported keyboard shortcut tool"
    argv = item.get("argv") or (["notify-send"] if adapter == "notify" else [])
    if argv and not shutil.which(argv[0]):
        return f"Requires {argv[0]} (not installed)"
    return None


def action_catalog():
    return [{**item, "unavailable": unavailable(item)} for item in CATALOG.values()]


def execute_native(value: str, press_key=None):
    item, arg = validate_builtin(value)
    reason = unavailable(item)
    if reason:
        raise RuntimeError(f"{item['label']}: {reason}")
    adapter = item.get("adapter")
    if adapter == "key":
        if press_key is None:
            raise RuntimeError("Keyboard backend unavailable")
        return press_key(arg if item.get("parameter") else item["shortcut"])
    argv = ["notify-send", "-a", "TableTap", "--", arg] if adapter == "notify" else item["argv"]
    if item["id"] == "files.home":
        argv = [argv[0], str(Path.home())]
    try:
        subprocess.run(argv, check=True, timeout=5, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().replace("\n", " ")[:200]
        raise RuntimeError(f"{item['label']} failed: {detail or exc.returncode}") from exc
