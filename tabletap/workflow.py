import json
import math

from .native_actions import validate_builtin


def parse_workflow(value: str) -> list[dict]:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Workflow must be JSON text under 8192 characters")
    try:
        steps = json.loads(value)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Workflow must be a JSON array of steps") from exc
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ValueError("Workflow requires 1–20 steps")
    total_delay = 0
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or set(step) != {"type", "value"}:
            raise ValueError(f"Step {index}: expected type and value")
        kind, arg = step["type"], step["value"]
        if kind == "wait":
            if (type(arg) not in (int, float) or not 0 <= arg <= 10000
                    or not math.isfinite(arg)):
                raise ValueError(f"Step {index}: wait must be 0–10000 milliseconds")
            total_delay += arg
        elif kind in ("key", "exec", "script", "builtin"):
            if not isinstance(arg, str) or not arg.strip() or len(arg) > 1024 or any(c in arg for c in "\r\n\x00"):
                raise ValueError(f"Step {index}: invalid action value")
            if kind == "builtin":
                validate_builtin(arg)
        else:
            raise ValueError(f"Step {index}: unsupported action type")
    if total_delay > 30000:
        raise ValueError("Total workflow wait must not exceed 30 seconds")
    return steps
