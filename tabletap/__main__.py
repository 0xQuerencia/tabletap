import argparse
import logging
import sys
import os
import shutil
import subprocess
from pathlib import Path

from . import __version__
from .config import load_config, init_config, save_calibration
from .daemon import run_service
from .calibrate import calibrate


def _prepare_ui():
    """Copy bundled TUI sources into a user-writable cache directory."""
    from . import __version__
    bundled = Path(__file__).resolve().parent / "ui"
    if not (bundled / "index.tsx").exists():
        raise FileNotFoundError("TableTap OpenTUI resources are missing from this installation")
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    ui = base / "tabletap" / ("ui-v" + __version__)
    ui.mkdir(parents=True, exist_ok=True)
    for name in ("index.tsx", "config-store.ts", "safety.ts", "themes.ts", "commands.ts", "action-builder.ts", "native-actions.json", "package.json", "tsconfig.json", "bunfig.toml"):
        shutil.copy2(bundled / name, ui / name)
    return ui


def preview_cmd(config_path=None, duration=None):
    """Use exactly the same detector and lock as preview in the TUI."""
    from .bridge import run_bridge
    def event(kind, **fields):
        if kind == "level":
            db = fields["db"]
            bar = "#" * max(0, min(50, int((db + 100) / 2)))
            print(f"\r  {db:6.1f} dB |{bar.ljust(50)}| threshold {fields['threshold_db']:.1f}", end="", flush=True)
        elif kind == "gesture":
            print(f"\nDetected: {fields['pattern'].upper()} (preview)")
        elif kind == "error":
            print("\n[tabletap] " + fields["message"], file=sys.stderr)
        elif kind == "stopped":
            print("\n[tabletap] Preview stopped.")
    print("[tabletap] Safe preview; no actions execute. Ctrl+C to stop.")
    return run_bridge(config_path=config_path, dry_run=True, event_sink=event, duration=duration)


def main():
    parser = argparse.ArgumentParser(
        prog="tabletap",
        description="Turn your table into a button pad using the laptop mic",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the tabletap daemon")
    start_p.add_argument("-c", "--config", help="Path to config.yaml")
    start_p.add_argument("--category", help="Action category to use (productivity, multitasking, smart_home, media)")
    start_p.add_argument("--preview", action="store_true", help="Start the background service with actions disabled")
    control_p = sub.add_parser("control", help="Control or watch the running background listener")
    control_p.add_argument("operation", choices=("status","watch","safe","stop","reload","arm"))
    control_p.add_argument("--category")
    control_p.add_argument("--seconds", type=float, default=600)

    mon_p = sub.add_parser("monitor", help="Watch mic levels and spikes in real-time")
    mon_p.add_argument("-c", "--config", help="Path to config.yaml")

    cal_p = sub.add_parser("calibrate", help="Calibrate noise floor and threshold")
    cal_p.add_argument("-c", "--config", help="Path to config.yaml")
    cal_p.add_argument("-d", "--duration", type=int, help="Duration in seconds")
    cal_p.add_argument("--no-save", action="store_true", help="Don't save calibration to config (dry-run)")

    test_p = sub.add_parser("test", help="Dry-run mode: detect taps but don't execute actions")
    test_p.add_argument("-c", "--config", help="Path to config.yaml")
    test_p.add_argument("-d", "--duration", type=int, default=30, help="Test duration in seconds (default: 30)")

    audit_p = sub.add_parser("audit", help="Measure false tap detections while working (always dry-run, offline)")
    audit_p.add_argument("-d", "--duration", type=int, default=30, help="Observe normal work for 5–600 seconds (default: 30)")
    audit_p.add_argument("-c", "--config", help="Path to config.yaml")
    audit_p.add_argument("--json", action="store_true", help="One JSON result, for local scripts and bug reports")

    init_p = sub.add_parser("init", help="Create default config at ~/.config/tabletap/config.yaml")
    init_p.add_argument("--path", help="Custom destination path")

    sub.add_parser("status", help="Show current config and device info")
    sub.add_parser("setup", help="Initialize config and install OpenTUI dependencies")
    sub.add_parser("actions", help="List built-in actions and local capability checks")
    sub.add_parser("doctor", help="Check microphone, shortcuts, config, and OpenTUI installation")
    service_p = sub.add_parser("service", help="Manage optional background systemd user-service integration")
    service_p.add_argument("service_action", choices=("install", "uninstall", "path"))
    service_p.add_argument("--live", action="store_true", help="Explicitly enable persistent live actions for an installed service")
    devices_p = sub.add_parser("devices", help="List available microphone input devices")
    devices_p.add_argument("--json", action="store_true", help="Machine-readable microphone list")
    bridge_p = sub.add_parser("bridge", help=argparse.SUPPRESS)
    bridge_p.add_argument("-c", "--config", help="Path to config.yaml")
    bridge_p.add_argument("--category", help="Action category")
    bridge_p.add_argument("--dry-run", action="store_true", help="Detect but do not execute")
    bridge_p.add_argument("--max-live-seconds", type=float, help=argparse.SUPPRESS)
    bridge_p.add_argument("--calibrate", action="store_true", help="Stream calibration progress")
    acoustic_p = sub.add_parser("acoustic", help="Manage microphone/desk calibration and labeled feedback")
    acoustic_p.add_argument("operation", choices=("list", "device", "use", "feedback", "propose", "apply", "rollback"))
    acoustic_p.add_argument("value", nargs="?")
    acoustic_p.add_argument("-c", "--config")
    acoustic_p.add_argument("--label", choices=("tap", "noise"))
    acoustic_p.add_argument("--db", type=float)
    acoustic_p.add_argument("--accepted", action="store_true")
    packs_p = sub.add_parser("profiles", help="Export, inspect and import portable action profiles")
    packs_p.add_argument("operation", choices=("export","inspect","import"))
    packs_p.add_argument("file")
    packs_p.add_argument("--name")
    packs_p.add_argument("--trust", action="store_true", help="Explicitly trust reviewed executable mappings")
    packs_p.add_argument("-c", "--config")
    tui_p = sub.add_parser("tui", help="Launch OpenTUI terminal dashboard")
    tui_p.add_argument("--demo", action="store_true", help="Preview TUI without opening the microphone")

    args = parser.parse_args()

    if args.command == "init":
        dest = init_config(args.path)
        print(f"[tabletap] Config created at {dest}")
        return

    if args.command is None:
        args.command = "tui"
        args.demo = False

    if args.command == "control":
        import json
        from .ipc import control_request, watch_events
        try:
            if args.operation == "watch":
                for event in watch_events():
                    print(event, flush=True)
            else:
                request = {"command":args.operation}
                if args.operation == "arm": request["seconds"] = args.seconds
                if args.operation == "reload": request["category"] = args.category
                response = control_request(request)
                print(json.dumps(response))
                if "error" in response: sys.exit(1)
        except (OSError, ValueError, RuntimeError) as exc:
            print(json.dumps({"error":str(exc)}))
            sys.exit(1)
        except KeyboardInterrupt:
            pass
        return

    if args.command == "profiles":
        from .profile_packs import pack_command
        try:
            print(pack_command(args))
        except (OSError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        return

    if args.command == "actions":
        import json
        from .native_actions import action_catalog
        print(json.dumps(action_catalog(), indent=2))
        return

    if args.command == "acoustic":
        import json
        from .acoustic_cli import acoustic_command
        try:
            print(json.dumps(acoustic_command(args)))
        except (ValueError, OSError, RuntimeError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}))
            sys.exit(1)
        return

    if args.command == "audit":
        from .audit import observe_work, format_audit
        import json
        if not 5 <= args.duration <= 600:
            parser.error("audit duration must be between 5 and 600 seconds")
        if not args.json:
            print("[tabletap] Work normally: type and click, but DO NOT intentionally tap the desk.")
            print("[tabletap] Every reported tap is a potential false positive. Actions stay disabled.\n")
        result = observe_work(args.duration, args.config)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(format_audit(result))
        sys.exit(2 if result["status"] == "error" else 1 if result["status"] == "warn" else 0)

    if args.command == "service":
        from .service import install_user_service, remove_user_service, user_service_path
        if args.service_action == "path":
            print(user_service_path())
        elif args.service_action == "install":
            path = install_user_service(sys.executable, live=args.live)
            print(f"[tabletap] Created {path} (uses {sys.executable})")
            print("Run: systemctl --user daemon-reload")
            print("Then: systemctl --user enable --now tabletap.service")
            print("On Hyprland, import your Wayland session variables into systemd first.")
        else:
            path = remove_user_service()
            print(f"[tabletap] Removed {path} (if it existed)")
            print("If active, stop/disable it first: systemctl --user disable --now tabletap.service")
            print("Then run: systemctl --user daemon-reload")
        return

    if args.command == "devices":
        from .mic import list_input_devices
        import json
        try:
            devices = list_input_devices()
        except (OSError, IOError, RuntimeError) as exc:
            if args.json:
                print(json.dumps({"devices": [], "error": str(exc)}))
            else:
                print("[tabletap] Unable to list microphones: " + str(exc), file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps({"devices": devices}))
        else:
            print("TableTap microphone inputs:")
            if not devices:
                print("  No capture devices found. Run tabletap doctor.")
            for device in devices:
                marker = " (system default)" if device["default"] else ""
                print(f"  [{device['index']}] {device['name']}{marker}")
            print("Change the selected microphone in TUI Settings (press m), or edit")
            print("  ~/.config/tabletap/config.yaml: audio.device_index")
        return

    if args.command in ("setup", "doctor"):
        from .config import validate_config
        dest = init_config()
        bun = shutil.which("bun")
        ui = _prepare_ui()
        installed = (ui / "node_modules" / "@opentui").is_dir()

        if args.command == "setup":
            if not bun:
                print("[tabletap] Bun missing. Install Bun from https://bun.sh")
                sys.exit(1)
            if not (ui / "package.json").exists():
                print("[tabletap] TUI sources are missing from this Python installation.", file=sys.stderr)
                sys.exit(1)
            print("[tabletap] Config: " + str(dest))
            print("[tabletap] Installing OpenTUI dependencies…")
            sys.exit(subprocess.call([bun, "install"], cwd=ui))

        import platform
        print("TableTap diagnostics")
        print("  Python: " + platform.python_version())
        print("  Config: " + str(dest))
        try:
            cfg = load_config(dest)
            warnings = validate_config(cfg)
            print("  Config valid: " + ("yes" if not warnings else "warnings"))
            for warning in warnings:
                print("    WARNING: " + warning)
        except Exception as exc:
            print("  Config: ERROR " + str(exc))
        print("  Bun: " + (bun or "MISSING (install Bun)"))
        print("  TUI sources: " + ("yes" if (ui / "index.tsx").exists() else "NO"))
        print("  TUI packages: " + ("installed" if installed else "MISSING (tabletap setup)"))
        print("  Display: " + ("Wayland" if os.environ.get("WAYLAND_DISPLAY") else
                              "X11" if os.environ.get("DISPLAY") else "headless"))
        if os.environ.get("WAYLAND_DISPLAY"):
            keytool = shutil.which("wtype") or shutil.which("ydotool")
            missing = "MISSING (install wtype or ydotool)"
        else:
            keytool = shutil.which("xdotool")
            missing = "MISSING (install xdotool)"
        print("  Key tool: " + (keytool or missing))
        from .native_actions import action_catalog
        catalog = action_catalog()
        print(f"  Built-in actions available: {sum(not item['unavailable'] for item in catalog)}/{len(catalog)} (tabletap actions)")
        try:
            from .mic import pyaudio
            if pyaudio is None:
                raise RuntimeError("pyaudio not installed")
            pa = pyaudio.PyAudio()
            try:
                inputs = [
                    pa.get_device_info_by_index(index)
                    for index in range(pa.get_device_count())
                    if pa.get_device_info_by_index(index).get("maxInputChannels", 0) > 0
                ]
                print("  Microphone devices: " + str(len(inputs)))
                for item in inputs[:6]:
                    print("    - " + str(item.get("name", "?")))
            finally:
                pa.terminate()
        except Exception as exc:
            print("  Microphone: unavailable: " + str(exc))
        return

    if args.command == "tui":
        bun = shutil.which("bun")
        if not bun:
            print("[tabletap] Bun is required for the OpenTUI interface.")
            print("Install Bun: https://bun.sh then run: tabletap setup")
            sys.exit(1)
        ui = _prepare_ui() / "index.tsx"
        if not (ui.parent / "node_modules" / "@opentui").is_dir():
            print("[tabletap] OpenTUI dependencies missing. Run: tabletap setup", file=sys.stderr)
            sys.exit(1)
        if not ui.exists():
            print("[tabletap] TUI sources missing from the installed Python package.", file=sys.stderr)
            sys.exit(1)
        init_config()
        env = os.environ.copy()
        env["TABLETAP_PYTHON"] = sys.executable
        env["TABLETAP_VERSION"] = __version__
        cmd = [bun, "run", str(ui)]
        if args.demo:
            cmd.append("--demo")
        sys.exit(subprocess.call(cmd, cwd=str(ui.parent), env=env))

    if args.command == "bridge":
        from .bridge import run_bridge, run_calibration
        if args.calibrate:
            sys.exit(run_calibration(config_path=args.config))
        sys.exit(run_bridge(
            config_path=args.config,
            category=args.category,
            dry_run=args.dry_run,
            live_seconds=args.max_live_seconds,
        ))

    try:
        cfg = load_config(args.config if hasattr(args, "config") else None)
    except FileNotFoundError as e:
        print(f"[tabletap] {e}", file=sys.stderr)
        sys.exit(1)

    log_level = cfg.get("logging", {}).get("level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "start":
        sys.exit(run_service(args.config, args.category, preview=args.preview))

    elif args.command == "monitor":
        sys.exit(preview_cmd(args.config))

    elif args.command == "test":
        sys.exit(preview_cmd(args.config, args.duration))

    elif args.command == "calibrate":
        from .lock import PIDLock
        lock = PIDLock()
        if not lock.acquire():
            parser.error("Stop the TableTap listener before calibration")
        try:
            from .acoustic_profiles import device_identity
            identity = None if args.no_save else device_identity(cfg)
            result = calibrate(cfg, duration_sec=args.duration if hasattr(args, "duration") else None)
            
            if not args.no_save:
                config_path = save_calibration(cfg, result, args.config if hasattr(args, "config") else None, identity=identity)
                print(f"\n✓ Calibration saved to {config_path}")
                print(f"\nCalibration values:")
                print(f"  noise_floor_db: {result['noise_floor_db']}")
                print(f"  slam_peak_db: {result['slam_peak_db']}")
                print(f"  threshold_db: {result['threshold_db']}")
            else:
                print(f"\nCalibration results (not saved):")
                print(f"  detection:")
                print(f"    noise_floor_db: {result['noise_floor_db']}")
                print(f"    slam_peak_db: {result['slam_peak_db']}")
                print(f"    threshold_db: {result['threshold_db']}")

        except (OSError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        finally:
            lock.release()

    elif args.command == "status":
        print("[tabletap] Current config:")
        import yaml
        print(yaml.dump(cfg, default_flow_style=False))


if __name__ == "__main__":
    main()

