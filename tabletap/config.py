import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATHS = [
    Path.home() / ".config" / "tabletap" / "config.yaml",
    Path(__file__).parent.parent / "config.yaml",
]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path:
        p = Path(path)
    else:
        p = None
        for candidate in DEFAULT_PATHS:
            if candidate.exists():
                p = candidate
                break
    if p is None or not p.exists():
        raise FileNotFoundError(
            f"No config found. Tried: {DEFAULT_PATHS}\n"
            "Run `tabletap init` to create one."
        )
    with open(p) as f:
        return yaml.safe_load(f)


def init_config(dest: str | Path | None = None) -> Path:
    dest = Path(dest or DEFAULT_PATHS[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    import shutil
    src = Path(__file__).parent.parent / "config.yaml"
    shutil.copy2(src, dest)
    return dest
