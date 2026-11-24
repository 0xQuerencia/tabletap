"""Portable action-only profiles. Import is explicit and never executes a mapping."""
import json
import os
import re
from pathlib import Path

from .config import load_config, init_config, edit_config
from .lock import PIDLock
from .workflow import parse_workflow

RESERVED = {"default", "single", "double", "triple", "quadruple", "long", "medium", "extended", "repeat",
            "__proto__", "constructor", "prototype"}


def check_name(name):
    if not isinstance(name, str) or name in RESERVED or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise ValueError("Choose a named profile: 1–40 letters, numbers, underscores or hyphens")
    return name


def validate_pack(pack):
    if not isinstance(pack, dict) or set(pack) != {"format", "name", "actions"} or pack["format"] != "tabletap-profile-v1":
        raise ValueError("Unknown or invalid TableTap profile format")
    name = check_name(pack["name"])
    actions = pack["actions"]
    if not isinstance(actions, dict) or len(actions) > 20:
        raise ValueError("Profile must contain at most 20 numbered actions")
    result = {}
    for key, action in actions.items():
        if isinstance(key, bool) or not re.fullmatch(r"(?:[1-9]|1[0-9]|20)", str(key)):
            raise ValueError("Action numbers must be 1–20")
        if int(key) in result:
            raise ValueError("Duplicate action number")
        if not isinstance(action, dict) or not {"type", "value"} <= set(action) or set(action) - {"type", "name", "value"}:
            raise ValueError("Invalid mapping")
        kind, value = action["type"], action["value"]
        title = action.get("name", f"Action {key}")
        if not isinstance(title, str) or not title.strip() or len(title) > 100 or not title.isprintable():
            raise ValueError("Invalid action name")
        if kind == "workflow":
            parse_workflow(value)
        elif kind in ("builtin", "key", "exec", "script"):
            parse_workflow(json.dumps([{"type":kind, "value":value}]))
        else:
            raise ValueError("Portable profiles cannot reference other local profiles (launcher mappings)")
        result[int(key)] = {"type":kind, "value":value, "name":title}
    return {"format":"tabletap-profile-v1", "name":name, "actions":result}


def read_pack(file):
    with Path(file).open("rb") as stream:
        raw = stream.read(131073)
    if len(raw) > 131072:
        raise ValueError("Profile file exceeds 128 KiB")
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("Duplicate JSON field")
            result[k] = v
        return result
    try:
        return validate_pack(json.loads(raw, object_pairs_hook=unique))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid profile file") from exc


def export_pack(cfg, name, file):
    name = check_name(name)
    group = cfg.get("actions", {}).get(name)
    if not isinstance(group, dict):
        raise ValueError("Named profile not found")
    pack = validate_pack({"format":"tabletap-profile-v1", "name":name, "actions":group})
    encoded = json.dumps(pack, indent=2, ensure_ascii=True) + "\n"
    with os.fdopen(os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(encoded)


def import_pack(pack, config_path, name=None, trust=False):
    if not trust:
        raise ValueError("Inspect the file first, then use --trust to authorize storing its mappings")
    pack = validate_pack(pack)
    name = check_name(name if name is not None else pack["name"])
    lock = PIDLock()
    if not lock.acquire():
        raise ValueError("Stop the listener before importing profiles")
    try:
        path = init_config(config_path)
        def update(doc):
            actions = doc.setdefault("actions", {})
            if name in actions:
                raise ValueError("Profile already exists; choose a new name")
            actions[name] = pack["actions"]
        edit_config(path, update)
    finally:
        lock.release()
    return name


def pack_command(args):
    if args.operation == "export":
        export_pack(load_config(args.config), args.name, args.file)
        return "Profile exported. Review all command values before sharing."
    pack = read_pack(args.file)
    if args.operation == "inspect":
        return json.dumps(pack, indent=2, ensure_ascii=True)
    name = import_pack(pack, args.config, name=args.name, trust=args.trust)
    return f"Imported {name}; mappings were not executed. Select it in safe preview."
