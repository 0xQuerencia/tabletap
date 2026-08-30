import os
import subprocess
from typing import Any

try:
    import pynput
except ImportError:
    pynput = None


class ActionRunner:
    def __init__(self, actions_cfg: dict[str, Any]):
        self.actions = actions_cfg

    def run(self, key: str):
        action = self.actions.get(key)
        if action is None:
            return

        action_type = action.get("type", "key")
        value = action.get("value", "")
        if not value:
            return

        if action_type == "key":
            self._press_key(value)
        elif action_type == "exec":
            self._launch(value)
        elif action_type == "script":
            self._run_script(value)

    def _press_key(self, combo: str):
        parts = combo.lower().split("+")
        keys = []
        for p in parts:
            p = p.strip()
            if p in ("ctrl", "control"):
                keys.append("ctrl")
            elif p in ("alt", "opt", "option"):
                keys.append("alt")
            elif p in ("shift",):
                keys.append("shift")
            elif p in ("super", "cmd", "win", "meta"):
                keys.append("super")
            else:
                keys.append(p)
        cmd = "xdotool key " + "+".join(keys)
        try:
            subprocess.run(cmd, shell=True, check=True)
        except FileNotFoundError:
            if pynput:
                self._pynput_press(combo)
            else:
                print(f"[tabletap] xdotool not found, cannot press: {combo}")

    def _pynput_press(self, combo: str):
        from pynput.keyboard import Key, Controller
        kb = Controller()
        parts = combo.lower().split("+")
        keys = []
        for p in parts:
            p = p.strip()
            if p == "ctrl":
                keys.append(Key.ctrl_l)
            elif p == "alt":
                keys.append(Key.alt_l)
            elif p == "shift":
                keys.append(Key.shift_l)
            elif p == "super":
                keys.append(Key.cmd)
            else:
                keys.append(p)
        try:
            kb.press(keys)
            kb.release(keys)
        except Exception as e:
            print(f"[tabletap] pynput error: {e}")

    def _launch(self, app: str):
        try:
            subprocess.Popen(
                app, shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[tabletap] launch error: {e}")

    def _run_script(self, script: str):
        script = os.path.expanduser(script)
        try:
            subprocess.Popen(
                ["bash", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[tabletap] script error: {e}")
