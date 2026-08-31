import os
import subprocess
import shlex
import shutil
from typing import Any
from concurrent.futures import ThreadPoolExecutor

try:
    import pynput
except ImportError:
    pynput = None


def _detect_display_server() -> str:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    elif os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"

KEY_MAP = {
    "enter": "Return",
    "return": "Return",
    "escape": "Escape",
    "space": "space",
    "tab": "Tab",
    "backspace": "BackSpace",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "insert": "Insert",
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
    "f9": "F9",
    "f10": "F10",
    "f11": "F11",
    "f12": "F12",
}


class ActionRunner:
    def __init__(self, actions_cfg: dict[str, Any], category: str = None):
        self.actions = actions_cfg
        self.category = category
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="action")
        self.display_server = _detect_display_server()
        
        self._category_map = {}
        if category and category in actions_cfg:
            cat_actions = actions_cfg[category]
            if isinstance(cat_actions, dict):
                for num, action in cat_actions.items():
                    if isinstance(num, int) or (isinstance(num, str) and num.isdigit()):
                        self._category_map[int(num)] = action

    def run(self, key: str):
        self._executor.submit(self._execute, key)
    
    def _execute(self, key: str):
        action = self._get_action(key)
        if action is None:
            return
        
        self._execute_action(action)
    
    def run_category(self, category: str, number: int):
        action = self.get_action(category, number)
        if action is None:
            return
        
        self._executor.submit(self._execute_action, action)
    
    def get_action(self, category: str, number: int) -> dict[str, Any] | None:
        cat_actions = self.actions.get(category)
        if not isinstance(cat_actions, dict):
            return None
        
        action = cat_actions.get(number) or cat_actions.get(str(number))
        if not isinstance(action, dict):
            return None
        
        return action
    
    def _get_action(self, key: str) -> dict[str, Any] | None:
        if self.category and self._category_map:
            number_map = {
                "single": 1,
                "double": 2,
                "triple": 3,
                "long": 4,
            }
            num = number_map.get(key)
            if num and num in self._category_map:
                return self._category_map[num]
            return None
        
        action = self.actions.get(key)
        if not isinstance(action, dict):
            return None
        
        return action
    
    def _execute_action(self, action: dict[str, Any]):
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
                keys.append(KEY_MAP.get(p, p))
        
        if self.display_server == "wayland":
            self._press_key_wayland(keys)
        elif self.display_server == "x11":
            self._press_key_x11(keys)
        else:
            if pynput:
                self._pynput_press(combo)
            else:
                print(f"[tabletap] Unknown display server, cannot press: {combo}")

    def _press_key_x11(self, keys: list[str]):
        cmd = ["xdotool", "key", "+".join(keys)]
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            if pynput:
                combo = "+".join(keys)
                self._pynput_press(combo)
            else:
                print(f"[tabletap] xdotool not found, cannot press: {'+'.join(keys)}")

    def _press_key_wayland(self, keys: list[str]):
        if shutil.which("wlrctl"):
            try:
                subprocess.Popen(
                    ["wlrctl", "keyboard", "type", "+".join(keys)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                print(f"[tabletap] wlrctl error: {e}")
        
        if shutil.which("ydotool"):
            try:
                ydotool_keys = self._convert_to_ydotool_format(keys)
                subprocess.Popen(
                    ["ydotool", "key"] + ydotool_keys,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                print(f"[tabletap] ydotool error: {e}")
        
        if pynput:
            combo = "+".join(keys)
            self._pynput_press(combo)
        else:
            print(f"[tabletap] No Wayland input tool found (wlrctl/ydotool), cannot press: {'+'.join(keys)}")

    def _convert_to_ydotool_format(self, keys: list[str]) -> list[str]:
        ydotool_map = {
            "ctrl": "29:1 29:0",
            "alt": "56:1 56:0",
            "shift": "42:1 42:0",
            "super": "125:1 125:0",
            "tab": "15:1 15:0",
            "space": "57:1 57:0",
            "Return": "28:1 28:0",
        }
        
        result = []
        for key in keys:
            if key in ydotool_map:
                result.extend(ydotool_map[key].split())
            else:
                result.append(f"{key}:1")
                result.append(f"{key}:0")
        
        return result

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
            for k in keys:
                kb.press(k)
            for k in reversed(keys):
                kb.release(k)
        except Exception as e:
            print(f"[tabletap] pynput error: {e}")

    def _launch(self, app: str):
        try:
            subprocess.Popen(
                shlex.split(app),
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
    
    def shutdown(self):
        self._executor.shutdown(wait=True, cancel_futures=False)

