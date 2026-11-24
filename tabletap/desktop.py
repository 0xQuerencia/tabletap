"""Native GTK4 window. The recognition engine runs in its existing process."""
import json
import os
import socket
import time
import subprocess
import sys
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .desktop_core import DesktopSession, profiles, rows, ACTION_TYPES
from .native_actions import action_catalog

CSS = """
window { background: #191919; color: #f0ede7; font-size: 13px; }
label { color: #f0ede7; }
.sidebar { background: #202020; padding: 14px; border-right: 1px solid #333333; }
.brand { font-size: 21px; font-weight: 700; letter-spacing: -0.5px; }
.heading { font-size: 25px; font-weight: 700; letter-spacing: -0.5px; }
.subheading { font-size: 17px; font-weight: 650; }
.row-title { font-size: 14px; font-weight: 600; }
.list-row { padding: 10px 0; border-bottom: 1px solid #373737; }
.icon-tile { background: #30302e; color: #e6a15d; border-radius: 7px; padding: 10px; }
.brand-mark { color: #e6a15d; }
.nav label { font-weight: 500; }
.level-meter trough { min-height: 7px; }
.level-meter progress { background: #94ba8d; }
.subtitle { color: #b1aaa0; font-size: 14px; }
.muted { color: #b1aaa0; font-size: 12px; }
.section { color: #b1aaa0; font-weight: 700; font-size: 11px; letter-spacing: 1px; }
.panel { background: #202020; border: 1px solid #383838; border-radius: 8px; padding: 16px; }
button { background: #292929; color: #f0ede7; border: 1px solid #444444; border-radius: 6px; padding: 8px 11px; }
button:hover { background: #343434; }
button:focus-visible, entry:focus-visible { outline: 2px solid #e6a15d; }
button:disabled { opacity: .5; }
button.accent { background: #e6a15d; color: #21170f; border-color: #e6a15d; font-weight: 700; }
button.accent:hover { background: #f0b77e; }
button.nav { background: transparent; border-color: transparent; }
button.selected { background: #3a3025; color: #f4b979; border-color: #51402d; }
button.danger { color: #e79a83; }
entry, dropdown { background: #1b1917; color: #f0ede7; border: 1px solid #403b35; border-radius: 8px; padding: 6px; }
progressbar trough { background: #39342e; border-radius: 8px; min-height: 7px; }
progressbar progress { background: #e6a15d; border-radius: 8px; min-height: 7px; }
.rhythm { color: #e6a15d; font-size: 20px; letter-spacing: 4px; }
.success { color: #a1c6a1; }
.error { color: #f0a48e; }
.lesson { font-size: 28px; font-weight: 700; letter-spacing: -0.6px; }
.lesson-step { padding: 12px; border: 1px solid #3b3b3b; border-radius: 6px; }
.lesson-current { border-color: #e6a15d; }
window.light .list-row { border-color: #d5cbbd; }
window.light .icon-tile { background: #e0d6c8; color: #9a501c; }
.tap-ring { border: 1px solid #654c32; border-radius: 100px; padding: 18px; }
.tap-inner { border: 2px solid #9a7049; border-radius: 100px; padding: 16px; }
.tap-core { background: #e6a15d; color: #21170f; border-radius: 80px; min-width: 64px; min-height: 64px; font-size: 26px; font-weight: 700; }
.tap-success { background: #a1c6a1; }
window.light .tap-core { color: #21170f; }
.light window, window.light { background: #f6f2eb; color: #26221d; }
window.light label { color: #26221d; }
window.light .sidebar, window.light .panel { background: #ebe5dc; border-color: #d5cbbd; }
window.light .muted, window.light .subtitle, window.light .section { color: #62594e; }
window.light button { background: #eee7de; border-color: #cfc4b6; color: #26221d; }
window.light button.selected, window.light button.accent { background: #c87932; color: #fff; }
window.light entry, window.light dropdown { background: #fffaf3; color: #26221d; border-color: #cfc4b6; }
window.light .rhythm { color: #9a501c; }
window.light .error { color: #a13321; }
window.light .success { color: #346d42; }
"""


def run_desktop(demo=False, smoke=False):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib, Gio

    def box(vertical=True, spacing=12):
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)

    def label(text="", css=None, wrap=False):
        w = Gtk.Label(label=text, xalign=0, wrap=wrap)
        if css:
            w.add_css_class(css)
        return w

    def button(text, callback, css=None):
        w = Gtk.Button(label=text)
        if css:
            w.add_css_class(css)
        w.connect("clicked", lambda *_: callback())
        return w

    def icon(name, size=20, css=None):
        w = Gtk.Image.new_from_icon_name(name)
        w.set_pixel_size(size)
        if css:
            w.add_css_class(css)
        return w

    def icon_button(text, symbol, callback, css=None):
        w = button("", callback, css)
        line = box(False, 10)
        line.append(icon(symbol, 18))
        line.append(label(text))
        w.set_child(line)
        return w

    def panel():
        w = box()
        w.add_css_class("panel")
        return w

    def spacer(vertical=False):
        w = box()
        if vertical:
            w.set_vexpand(True)
        else:
            w.set_hexpand(True)
        return w

    def clear(w):
        while w.get_first_child():
            w.remove(w.get_first_child())

    def dropdown(items, current=0):
        w = Gtk.DropDown.new_from_strings(items)
        w.set_selected(current)
        w.set_enable_search(len(items) > 8)
        w.set_hexpand(True)
        return w

    def text_entry(text="", placeholder=""):
        w = Gtk.Entry(text=text, placeholder_text=placeholder)
        w.set_hexpand(True)
        return w

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="art.querencia.tabletap", flags=Gio.ApplicationFlags.NON_UNIQUE if demo else Gio.ApplicationFlags.DEFAULT_FLAGS)
            self.session = None
            self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desktop")
            self.busy = False
            self.polling = False
            self.closed = False
            self.state = {"type": "stopped"}
            self.history = deque(maxlen=30)
            self.level = {}
            self.watch_socket = None
            self.watch_generation = 0
            self.practice_listening = False
            self.practice_starting = False
            self.last_active_profile = None
            self.profile = "default"
            self.page = "General"
            self.lesson = 0
            self.calibrated = False
            self.practiced = False
            self.calibration_running = False
            self.practice_listening = False
            self.watch = None
            self.mics = []
            self.choice = {"name": "Play / pause", "type": "builtin", "value": "media.play_pause"}
            self.catalog = []
            self.light = False
            self.tray = None
            self.exit_error = None

        def do_activate(self):
            if getattr(self, "win", None):
                self.win.present()
                return
            self.session = DesktopSession() if not demo else None
            self.cfg = self.session.config() if self.session else {"actions": {
                "single": {"name":"Play / pause music", "type":"builtin", "value":"media.play_pause"},
                "double": {"name":"Mute microphone", "type":"builtin", "value":"audio.mic_toggle"},
                "triple": {"name":"Open terminal", "type":"exec", "value":"foot"}}, "desktop": {"onboarded": True}}
            if demo:
                self.state = {"type":"ready", "dry_run":True, "category":"default", "threshold_db":-30}
                self.level = {"db":-46}
                self.history.extend(["Preview · double · Mute microphone", "Preview · single · Play / pause music", "Preview · triple · Open terminal"])
            self.catalog = action_catalog()
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS.encode())
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.win = Gtk.ApplicationWindow(application=self, title="TableTap", default_width=1100, default_height=690)
            self.win.set_size_request(900, 560)
            self.win.connect("close-request", self.close)
            self.root = box(False, 0)
            self.win.set_child(self.root)
            self.light = self.cfg.get("desktop", {}).get("light", False)
            if self.light:
                self.win.add_css_class("light")
            self.onboarding = not self.cfg.get("desktop", {}).get("onboarded", False)
            self.render()
            self.win.present()
            if smoke:
                GLib.idle_add(self.smoke)
            if not demo:
                try:
                    from .desktop_tray import Tray
                    self.tray = Tray(self.win.present, lambda: self.async_job(self.session.pause),
                                     lambda: self.async_job(self.session.stop), self.quit_desktop)
                except GLib.Error:
                    pass
                GLib.timeout_add(800, self.poll)
                self.poll()

        def smoke(self):
            from .desktop_tray import ITEM_XML, MENU_XML
            try:
                Gio.DBusNodeInfo.new_for_xml(ITEM_XML)
                Gio.DBusNodeInfo.new_for_xml(MENU_XML)
            except Exception as exc:
                self.exit_error = exc
                self.quit()
                return False
            targets = [(False, page) for page in ("General", "Gestures", "Calibration", "Profiles", "Activity", "Settings")]
            targets += [(True, step) for step in range(4)]
            directory = os.environ.get("TABLETAP_RENDER_DIR")
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
            def advance():
                try:
                    if not targets:
                        self.quit()
                        return False
                    onboarding, target = targets.pop(0)
                    self.onboarding = onboarding
                    if onboarding:
                        self.lesson = target
                    else:
                        self.page = target
                    self.render()
                    name = f"setup-{target+1}" if onboarding else target.lower()
                    def capture():
                        try:
                            if directory:
                                subprocess.run(["import", "-window", "root", str(Path(directory) / (name + ".png"))], check=True, timeout=10)
                            GLib.idle_add(advance)
                        except Exception as exc:
                            self.exit_error = exc
                            self.quit()
                        return False
                    GLib.timeout_add(350, capture)
                except Exception as exc:
                    self.exit_error = exc
                    self.quit()
                return False
            GLib.idle_add(advance)
            return False

        def quit_desktop(self):
            if self.busy:
                self.win.present()
                self.notice.set_text("Finish the current operation before quitting.")
                return
            self.async_job(self.session.stop, lambda _: self.shutdown_desktop())

        def shutdown_desktop(self):
            self.closed = True
            if self.tray:
                self.tray.close()
            self.stop_watch()
            self.worker.shutdown(wait=False, cancel_futures=True)
            self.quit()

        def close(self, *_):
            if self.busy or self.calibration_running:
                self.notice.set_text("Finish the current operation before closing.")
                return True
            if self.tray and self.tray.registered:
                self.win.hide()
                return True
            self.shutdown_desktop()
            return False

        def async_job(self, task, done=None):
            if demo:
                self.notice.set_text("Demo only — no microphone or command execution.")
                return
            if self.busy:
                return
            self.busy = True
            self.notice.remove_css_class("error")
            self.notice.set_text("Working…")
            future = self.worker.submit(task)
            def complete():
                self.busy = False
                if self.closed:
                    return False
                try:
                    result = future.result()
                    self.cfg = self.session.config()
                    self.notice.set_text("Ready")
                    if done:
                        done(result)
                    self.update_status()
                except Exception as exc:
                    self.calibration_running = False
                    self.practice_starting = False
                    self.notice.set_text(str(exc))
                    self.notice.add_css_class("error")
                return False
            future.add_done_callback(lambda _: GLib.idle_add(complete))

        def poll(self):
            if self.closed:
                return False
            if not self.win.get_visible():
                self.stop_watch()
                return True
            if not self.busy and not self.polling:
                self.polling = True
                future = self.worker.submit(self.session.status)
                def apply():
                    self.polling = False
                    if self.closed:
                        return False
                    try:
                        result = future.result()
                        previous = self.state.get("category")
                        self.state = result["state"]
                        self.level = result.get("level") or {}
                        if not self.onboarding and self.page == "General" and previous != self.state.get("category"):
                            self.render()
                        self.update_status()
                        if self.state.get("type") == "ready":
                            self.start_watch()
                        elif self.state.get("type") == "stopped":
                            self.stop_watch()
                    except Exception as exc:
                        self.notice.set_text(str(exc))
                    return False
                future.add_done_callback(lambda _: GLib.idle_add(apply))
            return True

        def start_watch(self):
            if self.watch and self.watch.is_alive():
                return
            from .ipc import socket_path, encode
            self.watch_generation += 1
            generation = self.watch_generation
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.watch_socket = client
            def read():
                try:
                    client.settimeout(3)
                    client.connect(str(socket_path()))
                    client.sendall(encode({"command":"watch"}))
                    client.settimeout(None)
                    with client.makefile("rb") as stream:
                        while True:
                            line = stream.readline(65537)
                            if not line or len(line) > 65536:
                                break
                            event = json.loads(line)
                            if event.get("type") in ("gesture", "action_result", "near_miss", "error", "live_expired", "ready", "transition", "stopped"):
                                GLib.idle_add(self.watch_event, generation, event)
                except (OSError, ValueError):
                    pass
                finally:
                    client.close()
            self.watch = threading.Thread(target=read, daemon=True)
            self.watch.start()

        def watch_event(self, generation, event):
            if generation != self.watch_generation or self.closed:
                return False
            kind = event.get("type")
            if kind in ("ready", "transition", "stopped"):
                self.state = event
                if kind == "ready" and self.practice_starting and event.get("dry_run") and event.get("category") == "default":
                    self.practice_listening = True
                    self.practice_starting = False
                self.update_status()
                return False
            return self.event(event)

        def stop_watch(self):
            self.watch_generation += 1
            if self.watch_socket:
                try:
                    self.watch_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.watch_socket.close()
            self.watch_socket = self.watch = None

        def event(self, event):
            if self.closed:
                return False
            kind = event.get("type")
            if kind == "gesture":
                self.history.appendleft(("Preview" if not event.get("dispatched") else "Detected") + " · " +
                                        event.get("pattern", "") + " · " + str(event.get("action", "")))
                if self.onboarding and self.lesson == 3 and self.practice_listening and event.get("pattern") == "double" and not event.get("dispatched"):
                    self.practiced = True
                    self.render()
            elif kind == "action_result":
                self.history.appendleft(event.get("status", "") + " · " + event.get("pattern", "") + " " + event.get("message", ""))
            elif kind == "near_miss":
                self.history.appendleft("Possible soft tap · " + str(event.get("db")) + " dB")
            else:
                self.history.appendleft(event.get("message", kind))
            if not self.onboarding and self.page in ("Activity", "General"):
                self.activity_content()
            return False

        def update_status(self):
            state = self.state
            ready = state.get("type") == "ready"
            live = ready and not state.get("dry_run")
            text = "● Listening" if live else "● Preview listening" if ready else "○ " + state.get("type", "stopped").capitalize()
            self.status.set_text(text)
            if getattr(self, "meter", None):
                db = getattr(self, "level", {}).get("db", -100)
                self.meter.set_fraction(max(0, min(1, (db + 80) / 80)))
            if getattr(self, "state_label", None):
                self.state_label.set_text("Listening" if live else "Preview listening" if ready else state.get("type", "stopped").capitalize())
            if getattr(self, "state_detail", None):
                self.state_detail.set_text("Shortcuts are enabled" if live else "Detecting taps without running shortcuts" if ready else "Start preview to try your gestures")
            if getattr(self, "footer_status", None):
                limit = state.get("threshold_db")
                self.footer_status.set_text("Sensitivity: " + (f"{limit:.1f} dB" if isinstance(limit, (int, float)) else "not measured"))
            if getattr(self, "arm_button", None):
                self.arm_button.set_sensitive(ready and not live and not self.busy)
            if getattr(self, "pause_button", None):
                self.pause_button.set_sensitive(ready and live)
            if getattr(self, "start_button", None):
                self.start_button.set_sensitive(not ready and state.get("type") == "stopped")
            if getattr(self, "stop_button", None):
                self.stop_button.set_sensitive(state.get("type") != "stopped")
            if self.onboarding and self.lesson == 3 and getattr(self, "lesson_next", None):
                self.lesson_next.set_sensitive(self.practiced and not self.busy)

        def render(self):
            clear(self.root)
            self.meter = self.state_label = self.state_detail = self.arm_button = self.pause_button = self.start_button = self.stop_button = self.lesson_next = self.footer_status = None
            self.notice = label("", "muted", True)
            self.status = label("○ Stopped", "muted")
            sidebar = box(spacing=5)
            sidebar.add_css_class("sidebar")
            sidebar.set_size_request(190, -1)
            brand = box(False, 10)
            brand.append(icon("audio-input-microphone-symbolic", 23, "brand-mark"))
            brand.append(label("tabletap", "brand"))
            brand.set_margin_bottom(18)
            sidebar.append(brand)
            for name, title, symbol in (("General","Home","go-home-symbolic"),
                    ("Gestures","Gestures","input-dialpad-symbolic"),
                    ("Calibration","Calibrate","audio-input-microphone-symbolic"),
                    ("Profiles","Profiles","folder-symbolic"), ("Activity","Activity","document-open-recent-symbolic"),
                    ("Settings","Settings","preferences-system-symbolic")):
                nav = icon_button(title, symbol, lambda name=name: self.navigate(name), "nav")
                if (self.onboarding and name == "General") or (not self.onboarding and name == self.page):
                    nav.add_css_class("selected")
                nav.set_sensitive(not self.onboarding)
                sidebar.append(nav)
            sidebar.append(spacer(True))
            sidebar.append(self.status)
            sidebar.append(label("v" + __version__, "muted"))
            self.root.append(sidebar)
            if self.onboarding:
                self.onboarding_view()
                return
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_hexpand(True)
            scroll.set_vexpand(True)
            self.content = box(spacing=16)
            for side in ("top", "bottom", "start", "end"):
                getattr(self.content, "set_margin_" + side)(24)
            scroll.set_child(self.content)
            self.root.append(scroll)
            if self.page != "General":
                self.content.append(label(self.page, "heading"))
            getattr(self, self.page.lower() + "_page")()
            self.content.append(self.notice)
            self.update_status()

        def navigate(self, name):
            if self.busy or self.calibration_running:
                return
            self.page = name
            self.render()

        def general_page(self):
            header = box(False)
            titles = box(spacing=4)
            titles.append(label("tabletap", "heading"))
            titles.append(label("Tap your desk. Trigger your workflow.", "subtitle"))
            header.append(titles)
            header.append(spacer())
            header.append(icon_button("Microphone", "audio-input-microphone-symbolic", self.choose_mic))
            self.content.append(header)
            card = panel()
            line = box(False, 18)
            line.append(icon("media-record-symbolic", 22, "brand-mark"))
            titles = box(spacing=5)
            self.state_label = label("Stopped", "subheading")
            self.state_detail = label("", "muted", True)
            titles.append(self.state_label)
            titles.append(self.state_detail)
            line.append(titles)
            line.append(spacer())
            self.meter = Gtk.ProgressBar()
            self.meter.add_css_class("level-meter")
            self.meter.set_size_request(120, -1)
            self.meter.set_valign(Gtk.Align.CENTER)
            line.append(self.meter)
            card.append(line)
            controls = box(False, 8)
            self.start_button = button("Start preview", lambda: self.async_job(lambda: self.session.start(self.profile)), "accent")
            self.arm_button = button("Enable · 10 min", self.confirm_arm)
            self.pause_button = button("Pause actions", lambda: self.async_job(self.session.pause))
            self.stop_button = button("Stop", lambda: self.async_job(self.session.stop))
            for w in (self.start_button, self.arm_button, self.pause_button, self.stop_button):
                controls.append(w)
            card.append(controls)
            self.content.append(card)
            active = self.state.get("category", self.profile)
            if active not in profiles(self.cfg):
                active = "default"
            columns = box(False, 14)
            left = panel()
            left.set_hexpand(True)
            heading = box(False)
            heading.append(label("Active gestures", "subheading"))
            heading.append(spacer())
            heading.append(button("+ Edit", lambda: self.select_gestures(active)))
            left.append(heading)
            left.append(label("Mappings in " + active, "muted"))
            for i, (key, action) in enumerate(rows(self.cfg, active)[:4], 1):
                if i == 4 and not self.cfg.get("detection", {}).get("enable_four_taps", False):
                    continue
                row = box(False, 12)
                row.add_css_class("list-row")
                row.append(icon(self.action_icon(action), 19, "icon-tile"))
                detail = box(spacing=4)
                detail.set_hexpand(True)
                title = label(action.get("name") or action.get("value") or "Not assigned", "row-title", True)
                detail.append(title)
                detail.append(label("● " * i + "  " + ("Single", "Double", "Triple", "Quadruple")[i-1] + " tap", "muted"))
                row.append(detail)
                row.append(button("Edit", lambda k=key, a=action: self.home_edit(active, k, a)))
                left.append(row)
            columns.append(left)
            right = panel()
            right.set_size_request(270, -1)
            right.append(label("Recent activity", "subheading"))
            right.append(label("Latest detections", "muted"))
            self.activity = box(spacing=8)
            right.append(self.activity)
            self.activity_content()
            right.append(spacer(True))
            right.append(button("View activity", lambda: self.navigate("Activity")))
            columns.append(right)
            self.content.append(columns)
            self.content.append(spacer(True))
            footer = box(False)
            footer.append(icon_button("Profile: " + active, "folder-symbolic", lambda: self.navigate("Profiles")))
            footer.append(spacer())
            self.footer_status = label("", "muted")
            footer.append(self.footer_status)
            self.content.append(footer)

        def action_icon(self, action):
            value = str(action.get("value", ""))
            if value.startswith("media."):
                return "media-playback-start-symbolic"
            if value.startswith("audio.mic"):
                return "microphone-sensitivity-muted-symbolic"
            if action.get("type") in ("exec", "script"):
                return "utilities-terminal-symbolic"
            return "input-keyboard-symbolic"

        def select_gestures(self, profile):
            self.profile = profile
            self.navigate("Gestures")

        def home_edit(self, profile, key, action):
            self.profile = profile
            self.edit_mapping(key, action)

        def confirm_arm(self):
            dialog = Gtk.MessageDialog(transient_for=self.win, modal=True, text="Enable actual shortcuts?",
                                       secondary_text="Desk taps will run your configured commands for up to 10 minutes. Use Pause or Stop at any time.")
            dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Enable", Gtk.ResponseType.OK)
            dialog.connect("response", lambda d, response: (d.destroy(), self.async_job(self.session.arm) if response == Gtk.ResponseType.OK else None))
            dialog.present()

        def gestures_page(self):
            self.content.append(label("One gesture, one useful shortcut. Edit mappings while stopped.", "subtitle", True))
            names = profiles(self.cfg)
            self.profile = self.profile if self.profile in names else "default"
            pick = dropdown(names, names.index(self.profile))
            pick.connect("notify::selected", lambda w, *_: self.select_view_profile(names[w.get_selected()]))
            self.content.append(pick)
            for i, (key, action) in enumerate(rows(self.cfg, self.profile)):
                card = panel()
                line = box(False)
                line.append(label("● " * (i+1) if i < 4 else "Menu " + str(key), "rhythm"))
                details = box(spacing=4)
                details.set_hexpand(True)
                details.append(label(action.get("name") or action.get("value") or "Not assigned", wrap=True))
                details.append(label(str(action.get("type", "")) + (" · " + str(action["value"]) if action.get("value") else ""), "muted", True))
                line.append(details)
                line.append(button("Edit", lambda k=key, a=action: self.edit_mapping(k, a)))
                if action:
                    line.append(button("Clear", lambda k=key: self.async_job(lambda: self.session.mapping(self.profile, k, None), lambda _: self.render()), "danger"))
                card.append(line)
                self.content.append(card)
            if self.profile != "default":
                used = {k for k, a in rows(self.cfg, self.profile) if a}
                free = next((k for k in range(5, 21) if k not in used), None)
                if free:
                    self.content.append(button("Add menu action", lambda: self.edit_mapping(free, {})))

        def select_view_profile(self, profile):
            self.profile = profile
            self.render()

        def edit_sequence(self, parent, value):
            from .workflow import parse_workflow
            try:
                steps = parse_workflow(value.get_text())
            except ValueError:
                steps = []
            dialog = Gtk.Dialog(title="Edit action sequence", transient_for=parent, modal=True)
            dialog.set_default_size(650, 420)
            body = dialog.get_content_area()
            body.set_spacing(10)
            body.set_margin_top(16)
            body.set_margin_bottom(16)
            body.set_margin_start(16)
            body.set_margin_end(16)
            body.append(label("Actions run in order. Add a wait to space them apart.", "subtitle", True))
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_vexpand(True)
            items = box(spacing=8)
            scroll.set_child(items)
            body.append(scroll)
            error = label("", "error", True)
            widgets = []
            types = ["builtin", "key", "exec", "script", "wait"]
            def collect():
                result = []
                for kind, entry in widgets:
                    t = types[kind.get_selected()]
                    raw = entry.get_text().strip()
                    if t == "wait":
                        try:
                            raw = float(raw)
                        except ValueError:
                            pass
                    result.append({"type": t, "value": raw})
                return result
            def rebuild():
                clear(items)
                widgets.clear()
                for i, step in enumerate(steps):
                    row = box(False, 6)
                    row.append(label(str(i+1) + "."))
                    kind = dropdown(types, types.index(step["type"]))
                    kind.set_hexpand(False)
                    entry = text_entry(str(step["value"]), "Command or wait in ms")
                    widgets.append((kind, entry))
                    row.append(kind)
                    row.append(entry)
                    def move(offset, index=i):
                        steps[:] = collect()
                        target = index + offset
                        if 0 <= target < len(steps):
                            steps[index], steps[target] = steps[target], steps[index]
                            rebuild()
                    def remove(index=i):
                        steps[:] = collect()
                        del steps[index]
                        rebuild()
                    up = button("↑", lambda fn=move: fn(-1))
                    down = button("↓", lambda fn=move: fn(1))
                    up.set_sensitive(i > 0)
                    down.set_sensitive(i < len(steps)-1)
                    row.append(up)
                    row.append(down)
                    row.append(button("Remove", remove))
                    items.append(row)
            def add():
                steps[:] = collect()
                if len(steps) >= 20:
                    error.set_text("At most 20 steps.")
                    return
                steps.append({"type": "wait", "value": 500})
                rebuild()
            body.append(button("Add step", add))
            body.append(error)
            dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Apply sequence", Gtk.ResponseType.OK)
            def save(d, response):
                if response == Gtk.ResponseType.OK:
                    encoded = json.dumps(collect(), allow_nan=True)
                    try:
                        parse_workflow(encoded)
                    except ValueError as exc:
                        error.set_text(str(exc))
                        return
                    value.set_text(encoded)
                d.destroy()
            dialog.connect("response", save)
            rebuild()
            dialog.present()

        def edit_mapping(self, key, action):
            if self.busy:
                return
            profile = self.profile
            dialog = Gtk.Dialog(title="Edit shortcut", transient_for=self.win, modal=True)
            dialog.set_default_size(520, 360)
            body = dialog.get_content_area()
            body.set_spacing(12)
            for side in ("top", "bottom", "start", "end"):
                getattr(body, "set_margin_" + side)(20)
            name = text_entry(action.get("name", ""), "Shortcut name")
            kind = dropdown(list(ACTION_TYPES), ACTION_TYPES.index(action.get("type")) if action.get("type") in ACTION_TYPES else 0)
            value = text_entry(action.get("value", ""), "Command or shortcut")
            presets = dropdown(["Choose an action…"] + [a["label"] + (" · unavailable" if a.get("unavailable") else "") for a in self.catalog])
            def preset(w, *_):
                i = w.get_selected()
                if i and i <= len(self.catalog):
                    item = self.catalog[i-1]
                    kind.set_selected(0)
                    name.set_text(item["label"])
                    value.set_text(item["id"] + (":" + item["example"] if item.get("parameter") else ""))
            presets.connect("notify::selected", preset)
            sequence = button("Edit sequence", lambda: self.edit_sequence(dialog, value))
            def type_changed(w, *_):
                sequence.set_visible(ACTION_TYPES[w.get_selected()] == "workflow")
            kind.connect("notify::selected", type_changed)
            type_changed(kind)
            for w in (label("Name", "section"), name, label("Action type", "section"), kind, presets, value, sequence,
                      label("Launcher values name a profile. Saving stops the listener. No commands execute while editing.", "muted", True)):
                body.append(w)
            dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
            def save(d, response):
                if response != Gtk.ResponseType.OK:
                    d.destroy()
                    return
                new = {"name": name.get_text(), "type": ACTION_TYPES[kind.get_selected()], "value": value.get_text()}
                from .desktop_core import validate_action
                try:
                    validate_action(new, self.cfg)
                except ValueError as exc:
                    body.append(label(str(exc), "error", True))
                    return
                d.destroy()
                self.async_job(lambda: self.session.mapping(profile, key, new), lambda _: self.render())
            dialog.connect("response", save)
            dialog.present()

        def calibration_page(self):
            self.content.append(label("Teach TableTap to distinguish taps from typing, speech and clicks.", "subtitle", True))
            self.calibration_card(self.content)
            self.content.append(button("Choose microphone", self.choose_mic))
            self.content.append(label("Advanced settings stay in your YAML file. Previous calibration is preserved if training fails.", "muted", True))

        def calibration_card(self, parent):
            card = panel()
            line = box(False, 14)
            stages = box(spacing=10)
            self.cal_stages = []
            for i, (title, description, symbol) in enumerate((
                    ("Stay quiet", "Measure the room.", "audio-volume-muted-symbolic"),
                    ("Work normally", "Type, speak and click.", "input-keyboard-symbolic"),
                    ("Tap your desk", "Six separated taps.", "input-dialpad-symbolic"))):
                stage = box(False, 10)
                stage.add_css_class("lesson-step")
                stage.append(icon(symbol, 20))
                words = box(spacing=4)
                words.append(label(str(i+1) + ". " + title, "row-title"))
                words.append(label(description, "muted", True))
                stage.append(words)
                stages.append(stage)
                self.cal_stages.append(stage)
            line.append(stages)
            controls = box(spacing=12)
            controls.set_hexpand(True)
            self.cal_prompt = label("Ready to calibrate?", "subheading", True)
            self.cal_detail = label("Three short rounds help separate taps from ordinary sounds.", "subtitle", True)
            self.cal_bar = Gtk.ProgressBar()
            self.cal_meter = Gtk.ProgressBar()
            self.cal_meter.add_css_class("level-meter")
            controls.append(self.cal_prompt)
            controls.append(self.cal_detail)
            controls.append(self.cal_bar)
            controls.append(label("Microphone level", "muted"))
            controls.append(self.cal_meter)
            controls.append(button("Start calibration", self.begin_calibration, "accent"))
            line.append(controls)
            card.append(line)
            parent.append(card)

        def begin_calibration(self):
            if self.busy:
                return
            self.calibrated = False
            self.calibration_running = True
            self.async_job(lambda: self.session.calibrate(lambda event: GLib.idle_add(self.cal_event, event)), self.cal_done)
            if demo:
                self.calibration_running = False

        def cal_event(self, event):
            phase = event.get("phase")
            prompts = {"noise": ("Stay quiet", "Let the microphone hear the room."),
                       "work": ("Work normally", "Type, click and speak naturally."),
                       "prepare": ("Get ready", "Use the same spot on the desk for each tap."),
                       "tap": ("Tap your desk", "Make at least six separated soft and normal taps.")}
            if phase in prompts:
                title, detail = prompts[phase]
                self.cal_prompt.set_text(title)
                self.cal_detail.set_text(detail)
                self.cal_bar.set_fraction(min(1, event["elapsed"] / event["duration"]))
                index = {"noise":0, "work":1, "prepare":2, "tap":2}[phase]
                for i, stage in enumerate(self.cal_stages):
                    if i == index:
                        stage.add_css_class("lesson-current")
                    else:
                        stage.remove_css_class("lesson-current")
                if "db" in event:
                    self.cal_meter.set_fraction(max(0, min(1, (event["db"]+80)/80)))
            return False

        def cal_done(self, _):
            self.calibration_running = False
            self.calibrated = True
            self.cal_prompt.set_text("Calibration saved")
            self.cal_detail.set_text("Your working noise and taps have been measured.")
            self.cal_bar.set_fraction(1)
            for stage in self.cal_stages:
                stage.remove_css_class("lesson-current")
            if self.onboarding:
                self.lesson_next.set_sensitive(True)

        def choose_mic(self):
            from .mic import list_input_devices
            def show(devices):
                dialog = Gtk.Dialog(title="Choose microphone", transient_for=self.win, modal=True)
                content = dialog.get_content_area()
                names = ["System default"] + [d["name"] for d in devices]
                choose = dropdown(names)
                content.append(choose)
                dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Use microphone", Gtk.ResponseType.OK)
                def save(d, response):
                    index = choose.get_selected()
                    d.destroy()
                    if response == Gtk.ResponseType.OK:
                        value = "default" if index == 0 else str(devices[index-1]["index"])
                        self.calibrated = self.practiced = False
                        if self.onboarding and self.lesson == 2:
                            self.lesson_next.set_sensitive(False)
                        self.async_job(lambda: self.session.device(value), lambda _: self.notice.set_text("Microphone selected. Calibrate before enabling actions."))
                dialog.connect("response", save)
                dialog.present()
            self.async_job(list_input_devices, show)

        def profiles_page(self):
            self.content.append(label("Switch shortcut collections without changing recognition.", "subtitle", True))
            for name in profiles(self.cfg):
                row = panel()
                line = box(False)
                title = label(name)
                title.set_hexpand(True)
                line.append(title)
                line.append(button("Use in preview", lambda n=name: self.async_job(lambda: self.session.start(n), lambda _: self.select_view_profile(n)), "accent"))
                if name != "default":
                    line.append(button("Delete", lambda n=name: self.async_job(lambda: self.session.delete_profile(n), lambda _: self.select_view_profile("default")), "danger"))
                row.append(line)
                self.content.append(row)
            new = text_entry("", "New profile name")
            line = box(False)
            line.append(new)
            line.append(button("Create", lambda: self.async_job(lambda: self.session.new_profile(new.get_text()), lambda _: self.render())))
            self.content.append(line)

        def activity_page(self):
            self.content.append(label("See detected gestures and action results. No audio is stored.", "subtitle", True))
            self.activity = panel()
            self.content.append(self.activity)
            self.activity_content()
            self.content.append(button("Clear activity", lambda: (self.history.clear(), self.activity_content())))

        def activity_content(self):
            clear(self.activity)
            limit = 5 if self.page == "General" else 30
            for text in list(self.history)[:limit] or ["No gestures yet. Start preview and tap your desk."]:
                row = box(False, 8)
                row.add_css_class("list-row")
                row.append(icon("document-open-recent-symbolic", 15))
                message = label(text, "muted", True)
                message.set_hexpand(True)
                row.append(message)
                self.activity.append(row)

        def settings_page(self):
            self.content.append(label("Make TableTap feel at home on your desktop.", "subtitle", True))
            card = panel()
            card.append(label("Appearance", "section"))
            card.append(button("Switch to dark" if self.light else "Switch to light", self.toggle_theme))
            card.append(button("Choose microphone", self.choose_mic))
            four = Gtk.CheckButton(label="Enable four-tap gestures")
            four.set_active(self.cfg.get("detection", {}).get("enable_four_taps", False))
            def four_changed(widget):
                enabled = widget.get_active()
                self.async_job(lambda: self.session.edit(lambda c: c.setdefault("detection", {}).update(enable_four_taps=enabled)))
            four.connect("toggled", four_changed)
            card.append(four)
            self.content.append(card)
            from .desktop_install import autostart_path, set_autostart
            startup = Gtk.CheckButton(label="Start safe preview at login")
            startup.set_active(autostart_path().exists())
            def startup_changed(widget):
                enabled = widget.get_active()
                self.async_job(lambda: set_autostart(enabled))
            startup.connect("toggled", startup_changed)
            self.content.append(startup)
            self.content.append(button("Replay guided setup", self.replay))
            if self.tray and self.tray.registered:
                self.content.append(button("Quit TableTap", self.quit_desktop, "danger"))
            self.content.append(label("Configuration: " + str(self.session.path if self.session else "~/.config/tabletap/config.yaml"), "muted", True))

        def toggle_theme(self):
            self.light = not self.light
            if self.light:
                self.win.add_css_class("light")
            else:
                self.win.remove_css_class("light")
            if self.session:
                from .config import edit_config
                self.async_job(lambda: edit_config(self.session.path, lambda cfg: cfg.setdefault("desktop", {}).update(light=self.light)), lambda _: self.render())
            else:
                self.render()

        def replay(self):
            self.onboarding = True
            self.lesson = 0
            self.practiced = self.calibrated = False
            self.render()

        def tap_illustration(self, success=False):
            outer = box()
            outer.add_css_class("tap-ring")
            outer.set_halign(Gtk.Align.CENTER)
            outer.set_valign(Gtk.Align.CENTER)
            inner = box()
            inner.add_css_class("tap-inner")
            inner.set_halign(Gtk.Align.CENTER)
            inner.set_valign(Gtk.Align.CENTER)
            core = label("✓" if success else "●", "tap-core")
            core.set_halign(Gtk.Align.CENTER)
            core.set_valign(Gtk.Align.CENTER)
            if success:
                core.add_css_class("tap-success")
            inner.append(core)
            outer.append(inner)
            return outer

        def onboarding_view(self):
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_hexpand(True)
            scroll.set_vexpand(True)
            outer = box(spacing=20)
            for side in ("top", "bottom", "start", "end"):
                getattr(outer, "set_margin_" + side)(28)
            scroll.set_child(outer)
            self.root.append(scroll)
            top = box(False, 14)
            top.append(label("Setup", "muted"))
            for i in range(4):
                segment = Gtk.ProgressBar()
                segment.set_hexpand(True)
                segment.set_valign(Gtk.Align.CENTER)
                segment.set_fraction(1 if i <= self.lesson else 0)
                top.append(segment)
            top.append(label(f"{self.lesson+1} of 4", "muted"))
            outer.append(top)
            outer.append(Gtk.Separator())
            outer.append(label(("Your desk can be a shortcut button", "First, let’s listen", "Teach us your desk", "Try your first shortcut")[self.lesson], "lesson", True))
            if self.lesson == 0:
                outer.append(label("TableTap turns desk taps into shortcuts.", "subtitle", True))
                outer.append(spacer(True))
                hero = box(False, 28)
                art = box()
                art.set_hexpand(True)
                art.set_valign(Gtk.Align.CENTER)
                art.append(self.tap_illustration())
                hero.append(art)
                features = box(spacing=18)
                for symbol, title, desc in (("computer-symbolic","No extra hardware","Use the desk and microphone you already have."),
                    ("changes-prevent-symbolic","Runs locally","Audio never leaves your device."),
                    ("emblem-ok-symbolic","Learn by doing","Calibrate, pick a shortcut, and practice.")):
                    row = box(False, 12)
                    row.append(icon(symbol, 24, "brand-mark"))
                    words = box(spacing=4)
                    words.append(label(title, "subheading"))
                    words.append(label(desc, "muted", True))
                    row.append(words)
                    features.append(row)
                hero.append(features)
                outer.append(hero)
            elif self.lesson == 1:
                outer.append(label("TableTap listens for short impacts. Audio stays on your computer.", "subtitle", True))
                card = panel()
                card.append(icon_button("Choose microphone", "audio-input-microphone-symbolic", self.choose_mic))
                device = self.cfg.get("audio", {}).get("device_index")
                card.append(label("System default" if device is None else f"Input device {device}", "muted"))
                card.append(label("Test the microphone in safe preview.", "muted", True))
                card.append(button("Test microphone", lambda: self.async_job(lambda: self.session.start("default"))))
                self.meter = Gtk.ProgressBar()
                self.meter.add_css_class("level-meter")
                card.append(self.meter)
                outer.append(card)
                outer.append(label("No account. No uploaded audio. No commands run in preview.", "muted", True))
            elif self.lesson == 2:
                outer.append(label("A quick calibration learns what is normal on your desk.", "subtitle", True))
                self.calibration_card(outer)
                if self.calibrated:
                    self.cal_prompt.set_text("Calibration saved")
                    self.cal_bar.set_fraction(1)
            else:
                outer.append(label("Choose what two taps should do, then practice in safe preview.", "subtitle", True))
                columns = box(False, 14)
                choices = panel()
                choices.set_hexpand(True)
                choices.append(label("Your first shortcut", "subheading"))
                for title, kind, value, symbol in (("Play / pause music","builtin","media.play_pause","media-playback-start-symbolic"),
                    ("Mute microphone","builtin","audio.mic_toggle","microphone-sensitivity-muted-symbolic"),
                    ("Show a notification","builtin","notify:Hello from TableTap","dialog-information-symbolic")):
                    def choose(title=title, kind=kind, value=value):
                        if not self.busy:
                            self.choice = {"name":title,"type":kind,"value":value}
                            self.render()
                    choices.append(icon_button(("✓ " if self.choice["value"] == value else "") + title, symbol, choose,
                                               "selected" if self.choice["value"] == value else None))
                columns.append(choices)
                practice = panel()
                practice.set_hexpand(True)
                practice.append(label("Practice a double tap", "subheading"))
                practice.append(label("Tap twice, then wait for recognition.", "muted", True))
                practice.append(self.tap_illustration(self.practiced))
                practice.append(label("✓ Double tap recognized" if self.practiced else "Listening for two taps…" if self.practice_listening else "Start safe practice", "success" if self.practiced else "muted", True))
                practice.append(button("Start practice", self.start_practice))
                columns.append(practice)
                outer.append(columns)
                outer.append(label("Saving replaces only your default double-tap mapping. Live shortcuts remain disabled.", "muted", True))
            outer.append(spacer(True))
            outer.append(self.notice)
            nav = box(False)
            if self.lesson:
                nav.append(button("← Back", lambda: self.lesson_move(-1)))
            else:
                nav.append(button("Skip for now", self.skip_setup))
            nav.append(spacer())
            self.lesson_next = button("Get started →" if self.lesson == 0 else "Finish setup →" if self.lesson == 3 else "Continue →", lambda: self.lesson_move(1), "accent")
            self.lesson_next.set_sensitive((self.lesson != 2 or self.calibrated) and (self.lesson != 3 or self.practiced))
            nav.append(self.lesson_next)
            outer.append(nav)
            self.update_status()

        def start_practice(self):
            if self.busy:
                return
            self.practice_listening = False
            self.practiced = False
            self.stop_watch()
            self.practice_starting = True
            self.async_job(lambda: self.session.start("default"), lambda _: self.start_watch())

        def skip_setup(self):
            if demo:
                self.skip()
                return
            self.async_job(lambda: self.session.edit(lambda c: c.setdefault("desktop", {}).update(onboarded=True)), lambda _: self.skip())

        def skip(self):
            if not self.busy:
                self.onboarding = False
                self.render()

        def lesson_move(self, direction):
            if self.busy or self.calibration_running:
                return
            if direction == 1 and self.lesson == 3:
                if not self.calibrated or not self.practiced:
                    return
                self.async_job(lambda: self.session.complete_onboarding(self.choice), lambda _: self.skip())
                return
            if direction == 1 and self.lesson == 2 and not self.calibrated:
                return
            if self.lesson == 3 and direction < 0:
                self.practice_listening = self.practice_starting = self.practiced = False
            self.lesson = max(0, min(3, self.lesson + direction))
            self.render()

    app = App()
    status = app.run([])
    if app.exit_error:
        raise app.exit_error
    return status
