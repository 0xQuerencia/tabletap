import json
import math
import os
import re
import shutil
import subprocess

from .native_actions import CATALOG

LEAF_TYPES = ("key", "exec", "script", "builtin", "wait")
CONDITIONS = ("tool_available", "hyprland", "media_playing", "microphone_muted", "speakers_muted")


def parse_workflow(value: str) -> list[dict]:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Workflow must be JSON text under 8192 characters")
    try:
        steps = json.loads(value)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Workflow must be a JSON array of steps") from exc
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ValueError("Workflow requires 1–20 steps")
    count, total_delay = 0, 0

    def validate(step, path, nested=False, parallel=False):
        nonlocal count, total_delay
        count += 1
        if count > 20:
            raise ValueError("Workflow requires at most 20 total steps, including blocks")
        if not isinstance(step, dict) or set(step) != {"type", "value"}:
            raise ValueError(f"Step {path}: expected type and value")
        kind, arg = step["type"], step["value"]
        if kind == "wait":
            if (type(arg) not in (int, float) or not 0 <= arg <= 10_000
                    or not math.isfinite(arg)):
                raise ValueError(f"Step {path}: wait must be 0–10000 milliseconds")
            total_delay += arg
        elif kind in ("key", "exec", "script", "builtin"):
            if not isinstance(arg, str) or not arg.strip() or len(arg) > 1024 or any(c in arg for c in "\r\n\x00"):
                raise ValueError(f"Step {path}: invalid action value")
            if kind == "builtin" and arg not in CATALOG:
                raise ValueError(f"Step {path}: unknown built-in action")
            if parallel and kind == "key":
                raise ValueError(f"Step {path}: keyboard shortcuts cannot run in parallel")
        elif not nested and kind == "parallel":
            if not isinstance(arg, list) or not 2 <= len(arg) <= 4:
                raise ValueError(f"Step {path}: parallel requires 2–4 independent actions")
            for i, child in enumerate(arg, 1):
                validate(child, f"{path}.{i}", nested=True, parallel=True)
        elif not nested and kind == "if":
            if not isinstance(arg, dict) or set(arg) != {"condition", "then", "else"}:
                raise ValueError(f"Step {path}: condition requires condition, then and else")
            condition = arg["condition"]
            if not isinstance(condition, dict) or condition.get("type") not in CONDITIONS:
                raise ValueError(f"Step {path}: unsupported condition")
            if condition["type"] == "tool_available":
                name = condition.get("value")
                if set(condition) != {"type", "value"} or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", name):
                    raise ValueError(f"Step {path}: invalid tool name")
            elif set(condition) != {"type"}:
                raise ValueError(f"Step {path}: unexpected condition value")
            for branch in ("then", "else"):
                children = arg[branch]
                if not isinstance(children, list) or len(children) > 4 or (branch == "then" and not children):
                    raise ValueError(f"Step {path}: invalid {branch} branch (max 4 steps)")
                for i, child in enumerate(children, 1):
                    validate(child, f"{path}.{branch}.{i}", nested=True)
        else:
            raise ValueError(f"Step {path}: unsupported action type")
    for i, step in enumerate(steps, 1):
        validate(step, str(i))
    if total_delay > 30_000:
        raise ValueError("Total workflow wait must not exceed 30 seconds")
    return steps


def evaluate_condition(condition: dict) -> bool:
    kind = condition["type"]
    if kind == "tool_available":
        return shutil.which(condition["value"]) is not None
    if kind == "hyprland":
        return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
    if kind == "media_playing":
        argv, expected = ["playerctl", "status"], "Playing"
    elif kind == "microphone_muted":
        argv, expected = ["pactl", "get-source-mute", "@DEFAULT_SOURCE@"], "Mute: yes"
    elif kind == "speakers_muted":
        argv, expected = ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], "Mute: yes"
    else:
        raise ValueError("Unsupported condition")
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=3,
                            env={**os.environ, "LC_ALL": "C"})
    output = result.stdout.strip()
    valid = ("Playing", "Paused", "Stopped") if kind == "media_playing" else ("Mute: yes", "Mute: no")
    if output not in valid:
        raise RuntimeError("Cannot determine system state")
    return output == expected
