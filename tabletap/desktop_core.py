"""Desktop controls for the existing config and background listener."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from .config import edit_config, init_config, load_config
from .ipc import control_request
from .lock import PIDLock
from .native_actions import validate_builtin
from .workflow import parse_workflow

GESTURES = ("single", "double", "triple", "quadruple")
RESERVED = {*GESTURES, "default", "long", "medium", "extended", "repeat"}
ACTION_TYPES = ("builtin", "key", "exec", "script", "workflow", "launcher")


def profiles(cfg):
    return ["default", *(name for name, group in cfg.get("actions", {}).items()
                         if isinstance(name, str) and name not in RESERVED
                         and isinstance(group, dict)
                         and all(str(key).isdigit() for key in group))]


def rows(cfg, profile):
    actions = cfg.get("actions", {})
    if profile == "default":
        return [(key, actions.get(key) or {}) for key in GESTURES]
    group = actions.get(profile, {})
    keys = sorted({1, 2, 3, 4, *(int(key) for key in group if str(key).isdigit() and 1 <= int(key) <= 20)})
    return [(number, group.get(number) or group.get(str(number)) or {}) for number in keys]


def validate_action(action, cfg):
    name, kind, value = (action.get(key, "") for key in ("name", "type", "value"))
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or not name.isprintable():
        raise ValueError("Give your shortcut a name (1–100 characters).")
    if kind not in ACTION_TYPES or not isinstance(value, str) or not value.strip():
        raise ValueError("Choose an action and enter its value.")
    if kind == "workflow":
        parse_workflow(value)
    else:
        if len(value) > 1024 or any(char in value for char in "\r\n\x00"):
            raise ValueError("Enter a single-line command under 1024 characters.")
        if kind == "builtin":
            validate_builtin(value)
        elif kind == "key" and not re.fullmatch(r"[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*", value):
            raise ValueError("Use keys joined by +, for example ctrl+shift+t.")
        elif kind == "launcher" and (value == "default" or value not in profiles(cfg)):
            raise ValueError("Choose an existing named profile for the menu.")


class DesktopSession:
    def __init__(self, path=None):
        self.path = init_config(path).absolute()
        self.process = None

    def config(self):
        return load_config(self.path)

    def status(self):
        try:
            response = control_request({"command": "status"})
        except (FileNotFoundError, ConnectionRefusedError):
            return {"state": {"type": "stopped"}, "level": None}
        if "error" in response:
            raise RuntimeError(response["error"])
        return response

    def _request(self, command, **fields):
        result = control_request({"command": command, **fields})
        if not result.get("accepted"):
            raise RuntimeError(result.get("error", "Listener did not accept request"))
        return result

    def _same_config(self, state):
        path = state.get("config_path")
        if not path or Path(path).resolve() != self.path.resolve():
            raise RuntimeError("Another listener is using a different configuration. Stop it first.")

    def start(self, profile="default"):
        if profile not in profiles(self.config()):
            raise ValueError("Unknown profile")
        state = self.status()["state"]
        if state.get("type") == "ready":
            self._same_config(state)
            self._request("reload", category=None if profile == "default" else profile)
            return
        if state.get("type") != "stopped":
            raise RuntimeError("The listener is changing state; try again.")
        cmd = [sys.executable, "-m", "tabletap", "start", "--preview", "-c", str(self.path)]
        if profile != "default":
            cmd += ["--category", profile]
        self.process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + 6
        while time.monotonic() < end:
            state = self.status()["state"]
            if state.get("type") == "ready":
                self._same_config(state)
                if not state.get("dry_run"):
                    raise RuntimeError("Another live listener was started; pause it first.")
                return
            if self.process.poll() is not None:
                raise RuntimeError("Could not start microphone. Stop any terminal listener and check microphone permissions.")
            time.sleep(.1)
        if self.process.poll() is None:
            self.process.terminate()
        raise RuntimeError("Microphone did not become ready.")

    def arm(self):
        state = self.status()["state"]
        self._same_config(state)
        if not state.get("dry_run"):
            raise RuntimeError("Start safe preview first.")
        return self._request("arm", seconds=600)

    def pause(self):
        state = self.status()["state"]
        if state.get("type") != "stopped":
            self._request("safe")

    def stop(self):
        if self.status()["state"].get("type") != "stopped":
            self._request("stop")
        end = time.monotonic() + 6
        while time.monotonic() < end:
            if self.status()["state"].get("type") == "stopped":
                lock = PIDLock()
                if lock.acquire():
                    lock.release()
                    return
            time.sleep(.1)
        raise RuntimeError("Stop the other TableTap listener before continuing.")

    def edit(self, mutate):
        # Config changes must never run against a live listener.
        self.stop()
        lock = PIDLock()
        if not lock.acquire():
            raise RuntimeError("Another TableTap listener is running.")
        try:
            return edit_config(self.path, mutate)
        finally:
            lock.release()

    def mapping(self, profile, key, action):
        def update(cfg):
            if profile not in profiles(cfg):
                raise ValueError("Unknown profile")
            if profile == "default":
                if key not in GESTURES:
                    raise ValueError("Unknown gesture")
                group = cfg.setdefault("actions", {})
            else:
                if type(key) is not int or not 1 <= key <= 20:
                    raise ValueError("Choose a numbered slot from 1 to 20")
                group = cfg["actions"][profile]
                group.pop(str(key), None)
            if action is None:
                group.pop(key, None)
            else:
                validate_action(action, cfg)
                group[key] = {k: action[k].strip() for k in ("name", "type", "value")}
        self.edit(update)

    def new_profile(self, name):
        def update(cfg):
            actions = cfg.setdefault("actions", {})
            if (not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name) or name in RESERVED
                    or name in actions or name in ("constructor", "prototype", "__proto__")):
                raise ValueError("Choose a unique profile name (letters, digits, hyphens, underscores).")
            actions[name] = {}
        self.edit(update)

    def delete_profile(self, name):
        def update(cfg):
            if name == "default" or name not in profiles(cfg):
                raise ValueError("Choose a named profile.")
            for profile in profiles(cfg):
                if profile != name and any(a.get("type") == "launcher" and a.get("value") == name
                                           for _, a in rows(cfg, profile) if isinstance(a, dict)):
                    raise ValueError("Remove gesture menus that reference this profile first.")
            del cfg["actions"][name]
        self.edit(update)

    def device(self, value):
        from .acoustic_cli import acoustic_command
        from types import SimpleNamespace
        self.stop()
        return acoustic_command(SimpleNamespace(config=str(self.path), operation="device", value=value))

    def calibrate(self, event):
        self.edit(lambda cfg: cfg.setdefault("calibration", {}).update(personalized=True, duration_sec=8))
        with subprocess.Popen([sys.executable, "-m", "tabletap", "bridge", "--calibrate", "-c", str(self.path)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
            completed = False
            error = "Calibration did not finish. Try a different microphone or harder surface."
            for line in process.stdout:
                record = json.loads(line)
                event(record)
                if record.get("type") == "calibration_done":
                    completed = True
                if record.get("type") == "error":
                    error = record.get("message", error)
            if process.wait() or not completed:
                raise RuntimeError(error)

    def complete_onboarding(self, action):
        def update(cfg):
            validate_action(action, cfg)
            cfg.setdefault("actions", {})["double"] = action
            cfg.setdefault("desktop", {})["onboarded"] = True
        self.edit(update)
