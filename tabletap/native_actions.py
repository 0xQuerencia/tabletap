import json
import os
import shutil
import subprocess
from pathlib import Path


CATALOG = {
    item["id"]: item
    for item in json.loads((Path(__file__).parent / "ui" / "native-actions.json").read_text(encoding="utf-8"))
}


def execute_native(action_id: str):
    item = CATALOG.get(action_id)
    if item is None:
        raise ValueError(f"Unknown built-in action: {action_id}")
    argv = item["argv"]
    if action_id.startswith("hyprland.") and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise RuntimeError("This action requires a running Hyprland session")
    if not shutil.which(argv[0]):
        raise RuntimeError(f"{item['label']} requires {argv[0]} (not installed)")
    try:
        subprocess.run(argv, check=True, timeout=5, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().replace("\\n", " ")[:200]
        raise RuntimeError(f"{item['label']} failed: {detail or exc.returncode}") from exc
