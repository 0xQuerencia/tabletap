"""Native GTK4 window. The recognition engine runs in its existing process."""
import json
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
window { background: #181715; color: #f0ede7; }
label { color: #f0ede7; }
.sidebar { background: #211f1c; padding: 18px; border-right: 1px solid #38342f; }
.brand { font-size: 22px; font-weight: 800; letter-spacing: -1px; }
.heading { font-size: 30px; font-weight: 750; letter-spacing: -1px; }
.subtitle { color: #b1aaa0; font-size: 14px; }
.muted { color: #b1aaa0; font-size: 12px; }
.section { color: #b1aaa0; font-weight: 700; font-size: 11px; letter-spacing: 1px; }
.panel { background: #22201d; border: 1px solid #38342f; border-radius: 12px; padding: 16px; }
button { background: #2c2925; color: #f0ede7; border: 1px solid #403b35; border-radius: 8px; padding: 8px 12px; }
button:hover { background: #39342e; }
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
.lesson { font-size: 34px; font-weight: 800; letter-spacing: -1px; }
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
            self.closed = False
            self.state = {"type": "stopped"}
            self.history = deque(maxlen=30)
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
            self.cfg = self.session.config() if self.session else {"actions": {"double": self.choice}, "desktop": {"onboarded": True}}
            self.catalog = action_catalog()
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS.encode())
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.win = Gtk.ApplicationWindow(application=self, title="TableTap", default_width=920, default_height=690)
            self.win.set_size_request(740, 560)
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
                GLib.timeout_add(400, self.poll)
                self.poll()

        def smoke(self):
            try:
                from .desktop_tray import ITEM_XML, MENU_XML
                Gio.DBusNodeInfo.new_for_xml(ITEM_XML)
                Gio.DBusNodeInfo.new_for_xml(MENU_XML)
                for page in ("General", "Gestures", "Calibration", "Profiles", "Activity", "Settings"):
                    self.page = page
                    self.render()
                self.onboarding = True
                for step in range(6):
                    self.lesson = step
                    self.render()
                self.onboarding = False
                self.quit()
            except Exception as exc:
                self.exit_error = exc
                self.quit()
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
                    self.notice.set_text(str(exc))
                    self.notice.add_css_class("error")
                return False
            future.add_done_callback(lambda _: GLib.idle_add(complete))

        def poll(self):
            if self.closed:
                return False
            if not self.busy:
                self.busy = True
                future = self.worker.submit(self.session.status)
                def apply():
                    self.busy = False
                    if self.closed:
                        return False
                    try:
                        result = future.result()
                        self.state = result["state"]
                        self.level = result.get("level") or {}
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
            if self.watch and self.watch.poll() is None:
                return
            self.watch = subprocess.Popen([sys.executable, "-m", "tabletap", "control", "watch"],
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            proc = self.watch
            def read():
                for line in proc.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") in ("gesture", "action_result", "near_miss", "error", "live_expired"):
                        GLib.idle_add(self.event, event)
                proc.wait()
            threading.Thread(target=read, daemon=True).start()

        def stop_watch(self):
            if self.watch and self.watch.poll() is None:
                self.watch.terminate()
            self.watch = None

        def event(self, event):
            if self.closed:
                return False
            kind = event.get("type")
            if kind == "gesture":
                self.history.appendleft(("Preview" if not event.get("dispatched") else "Detected") + " · " +
                                        event.get("pattern", "") + " · " + str(event.get("action", "")))
                if self.onboarding and self.lesson == 4 and event.get("pattern") == "double" and not event.get("dispatched"):
                    self.practiced = True
                    self.render()
            elif kind == "action_result":
                self.history.appendleft(event.get("status", "") + " · " + event.get("pattern", "") + " " + event.get("message", ""))
            elif kind == "near_miss":
                self.history.appendleft("Possible soft tap · " + str(event.get("db")) + " dB")
            else:
                self.history.appendleft(event.get("message", kind))
            if not self.onboarding and self.page == "Activity":
                self.activity_content()
            return False

        def update_status(self):
            state = self.state
            ready = state.get("type") == "ready"
            live = ready and not state.get("dry_run")
            text = "● Live shortcuts" if live else "● Preview listening" if ready else "○ " + state.get("type", "stopped").capitalize()
            self.status.set_text(text)
            if getattr(self, "meter", None):
                db = getattr(self, "level", {}).get("db", -100)
                self.meter.set_fraction(max(0, min(1, (db + 80) / 80)))
            if getattr(self, "state_label", None):
                self.state_label.set_text(text)
            if getattr(self, "arm_button", None):
                self.arm_button.set_sensitive(ready and not live and not self.busy)
            if getattr(self, "pause_button", None):
                self.pause_button.set_sensitive(ready and live)
            if getattr(self, "start_button", None):
                self.start_button.set_sensitive(not ready and state.get("type") == "stopped")
            if getattr(self, "stop_button", None):
                self.stop_button.set_sensitive(state.get("type") != "stopped")
            if self.onboarding and self.lesson == 4 and getattr(self, "lesson_next", None):
                self.lesson_next.set_sensitive(self.practiced and not self.busy)

        def render(self):
            clear(self.root)
            self.meter = self.state_label = self.arm_button = self.pause_button = self.start_button = self.stop_button = self.lesson_next = None
            self.notice = label("", "muted", True)
            self.status = label("○ Stopped", "muted")
            if self.onboarding:
                self.onboarding_view()
                return
            sidebar = box(spacing=8)
            sidebar.add_css_class("sidebar")
            sidebar.set_size_request(202, -1)
            sidebar.append(label("tabletap.", "brand"))
            sidebar.append(label("ACOUSTIC SHORTCUTS", "section"))
            for name in ("General", "Gestures", "Calibration", "Profiles", "Activity", "Settings"):
                nav = button(name, lambda name=name: self.navigate(name), "nav")
                if name == self.page:
                    nav.add_css_class("selected")
                sidebar.append(nav)
            sidebar.append(spacer(True))
            sidebar.append(self.status)
            sidebar.append(label("v" + __version__, "muted"))
            self.root.append(sidebar)
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_hexpand(True)
            scroll.set_vexpand(True)
            self.content = box(spacing=16)
            for side in ("top", "bottom", "start", "end"):
                getattr(self.content, "set_margin_" + side)(28)
            scroll.set_child(self.content)
            self.root.append(scroll)
            headings = {"General":"Your desk, connected.", "Gestures":"Gestures", "Calibration":"Calibration",
                        "Profiles":"Profiles", "Activity":"Activity", "Settings":"Settings"}
            self.content.append(label(headings[self.page], "heading"))
            getattr(self, self.page.lower() + "_page")()
            self.content.append(self.notice)
            self.update_status()

        def navigate(self, name):
            if self.busy or self.calibration_running:
                return
            self.page = name
            self.render()

        def general_page(self):
            self.content.append(label("Tap your desk. Trigger the things you do every day.", "subtitle", True))
            card = panel()
            self.state_label = label("Stopped", "heading")
            card.append(self.state_label)
            self.meter = Gtk.ProgressBar()
            card.append(self.meter)
            card.append(label("Microphone level · local audio only", "muted"))
            controls = box(False, 8)
            self.start_button = button("Start preview", lambda: self.async_job(lambda: self.session.start(self.profile)), "accent")
            self.arm_button = button("Enable for 10 min", self.confirm_arm)
            self.pause_button = button("Pause actions", lambda: self.async_job(self.session.pause))
            self.stop_button = button("Stop", lambda: self.async_job(self.session.stop), "danger")
            for w in (self.start_button, self.arm_button, self.pause_button, self.stop_button):
                controls.append(w)
            card.append(controls)
            card.append(label("Preview detects taps without running commands. Closing this window leaves the listener running; live authorization expires after 10 minutes.", "muted", True))
            self.content.append(card)
            self.content.append(label("YOUR SHORTCUTS", "section"))
            for i, (_, action) in enumerate(rows(self.cfg, self.profile)[:4], 1):
                row = panel()
                row.append(label("● " * i, "rhythm"))
                row.append(label(action.get("name") or action.get("value") or "Not assigned", wrap=True))
                self.content.append(row)
            self.content.append(button("Edit gestures", lambda: self.navigate("Gestures")))

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
            for w in (label("Name", "section"), name, label("Action type", "section"), kind, presets, value,
                      label("Workflows accept the existing sequential JSON format. Launcher values name a profile. Saving stops the listener.", "muted", True)):
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
            self.cal_prompt = label("Ready to calibrate?", "heading", True)
            self.cal_detail = label("Three short rounds: quiet, normal work, and desk taps.", "subtitle", True)
            self.cal_bar = Gtk.ProgressBar()
            for w in (self.cal_prompt, self.cal_detail, self.cal_bar, button("Start calibration", self.begin_calibration, "accent")):
                card.append(w)
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
            return False

        def cal_done(self, _):
            self.calibration_running = False
            self.calibrated = True
            self.cal_prompt.set_text("Calibration saved")
            self.cal_detail.set_text("Your working noise and taps have been measured.")
            self.cal_bar.set_fraction(1)
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
                        self.calibrated = False
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
            for line in self.history or ["No gestures yet. Start preview and tap your desk."]:
                self.activity.append(label(line, "muted", True))

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

        def onboarding_view(self):
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_hexpand(True)
            scroll.set_vexpand(True)
            outer = box(spacing=18)
            outer.set_halign(Gtk.Align.CENTER)
            outer.set_size_request(530, -1)
            outer.set_margin_top(32)
            outer.set_margin_bottom(32)
            outer.set_margin_start(24)
            outer.set_margin_end(24)
            scroll.set_child(outer)
            self.root.append(scroll)
            top = box(False)
            back = button("Back", lambda: self.lesson_move(-1))
            back.set_sensitive(self.lesson > 0)
            top.append(back)
            progress = Gtk.ProgressBar()
            progress.set_hexpand(True)
            progress.set_valign(Gtk.Align.CENTER)
            progress.set_fraction((self.lesson+1)/6)
            top.append(progress)
            top.append(label(str(self.lesson+1) + " / 6", "muted"))
            outer.append(top)
            outer.append(spacer(True))
            outer.append(label(("Your desk is a button.", "First, let’s listen.", "Teach us your desk.", "Make it yours.", "Try a double tap.", "You’re ready.")[self.lesson], "lesson", True))
            if self.lesson == 0:
                outer.append(label("●  ●", "rhythm"))
                outer.append(label("Turn desk taps into shortcuts. No extra hardware. No accounts.", "subtitle", True))
            elif self.lesson == 1:
                outer.append(label("The microphone listens for short impacts. Your audio stays on your computer.", "subtitle", True))
                outer.append(button("Choose microphone", self.choose_mic))
                outer.append(label("The system default works for most laptops.", "muted", True))
            elif self.lesson == 2:
                self.calibration_card(outer)
                if self.calibrated:
                    self.cal_prompt.set_text("Calibration saved")
                    self.cal_bar.set_fraction(1)
            elif self.lesson == 3:
                outer.append(label("What should two taps do? This replaces your current default double-tap mapping only when you finish.", "subtitle", True))
                for title, value in (("Play / pause music", "media.play_pause"), ("Mute microphone", "audio.mic_toggle"), ("Show a notification", "notify:Hello from TableTap")):
                    def choose(title=title, value=value):
                        self.choice = {"name": title, "type": "builtin", "value": value}
                        self.render()
                    outer.append(button(("✓ " if self.choice["value"] == value else "") + title, choose, "selected" if self.choice["value"] == value else None))
            elif self.lesson == 4:
                outer.append(label("●  ●", "rhythm"))
                outer.append(label("Tap twice within a second, then wait. Preview never runs the mapped command.", "subtitle", True))
                outer.append(button("Start safe practice", lambda: self.async_job(lambda: self.session.start("default"), lambda _: self.start_watch()), "accent"))
                outer.append(label("✓ Double tap recognized!" if self.practiced else "Waiting for a real double tap…", "success" if self.practiced else "muted"))
            else:
                outer.append(label("●  ●  →  " + self.choice["name"], "rhythm", True))
                outer.append(label("Your first shortcut is ready to save. You decide when to enable actual actions.", "subtitle", True))
            outer.append(spacer(True))
            self.lesson_next = button("Get started" if self.lesson == 0 else "Save & open TableTap" if self.lesson == 5 else "Continue", lambda: self.lesson_move(1), "accent")
            self.lesson_next.set_sensitive((self.lesson != 2 or self.calibrated) and (self.lesson != 4 or self.practiced))
            outer.append(self.notice)
            outer.append(self.lesson_next)
            if self.lesson == 0:
                outer.append(button("Skip setup (configure manually)", self.skip_setup))
            outer.append(self.status)
            self.update_status()

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
            if direction == 1 and self.lesson == 5:
                self.async_job(lambda: self.session.complete_onboarding(self.choice), lambda _: self.skip())
                return
            self.lesson = max(0, min(5, self.lesson + direction))
            self.render()

    app = App()
    status = app.run([])
    if app.exit_error:
        raise app.exit_error
    return status
