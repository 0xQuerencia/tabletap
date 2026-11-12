import argparse
import logging
import sys
import os
import shutil
import subprocess
from pathlib import Path

from .config import load_config, init_config, save_calibration
from .daemon import Daemon
from .calibrate import calibrate
from .filter import AdaptiveThreshold


def _prepare_ui():
    """Copy bundled TUI sources into a user-writable cache directory."""
    from . import __version__
    bundled = Path(__file__).resolve().parent / "ui"
    if not (bundled / "index.tsx").exists():
        raise FileNotFoundError("TableTap OpenTUI resources are missing from this installation")
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    ui = base / "tabletap" / ("ui-v" + __version__)
    ui.mkdir(parents=True, exist_ok=True)
    for name in ("index.tsx", "package.json", "tsconfig.json", "bunfig.toml"):
        shutil.copy2(bundled / name, ui / name)
    return ui


def monitor_cmd(cfg: dict):
    import time
    from .mic import MicCapture, rms_db
    from .filter import make_bandpass, apply_bandpass

    audio_cfg = cfg.get("audio", {})
    filter_cfg = cfg.get("filter", {})

    threshold = AdaptiveThreshold(
        initial_threshold_db=cfg.get("detection", {}).get("threshold_db", -30),
    )
    saved_noise = cfg.get("detection", {}).get("noise_floor_db")
    saved_peak = cfg.get("detection", {}).get("slam_peak_db")
    if saved_noise is not None and saved_peak is not None:
        threshold.set_from_calibration(saved_noise, saved_peak)

    sos = None
    if filter_cfg.get("enabled", True):
        sos = make_bandpass(
            filter_cfg.get("low", 20),
            filter_cfg.get("high", 200),
            audio_cfg.get("sample_rate", 44100),
        )

    print(f"[tabletap monitor] Threshold: {threshold.threshold_db:.1f} dB")
    print("[tabletap monitor] Watching mic levels... (Ctrl+C to stop)\n")

    try:
        with MicCapture(audio_cfg, filter_cfg) as mic:
            while True:
                raw, filtered = mic.read_filtered()
                db = rms_db(filtered)
                spike = " <-- SPIKE!" if db > threshold.threshold_db else ""

                bar_db = max(0, db + 100)
                bar_len = int(bar_db / 2)
                bar = "#" * min(bar_len, 50)

                print(f"\r  {db:6.1f} dB |{bar.ljust(50)}|{spike}", end="", flush=True)
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n\n[tabletap monitor] Stopped.")


def test_cmd(cfg: dict, duration: int):
    import time
    from .mic import MicCapture, rms_db
    from .pattern import PatternDetector
    from .filter import OnsetDetector

    print(f"[tabletap test] Testing tap detection for {duration} seconds...")
    print("[tabletap test] Detected patterns will be printed (no actions executed)\n")

    audio_cfg = cfg.get("audio", {})
    filter_cfg = cfg.get("filter", {})
    detect_cfg = cfg.get("detection", {})

    threshold = AdaptiveThreshold(
        initial_threshold_db=detect_cfg.get("threshold_db", -30),
        noise_alpha=filter_cfg.get("noise_alpha", 0.05),
        peak_alpha=filter_cfg.get("peak_alpha", 0.1),
        snr_gate_db=filter_cfg.get("snr_gate_db", 6.0),
    )
    saved_noise = detect_cfg.get("noise_floor_db")
    saved_peak = detect_cfg.get("slam_peak_db")
    if saved_noise is not None and saved_peak is not None:
        threshold.set_from_calibration(saved_noise, saved_peak)

    pattern_detector = PatternDetector(
        min_gap_ms=detect_cfg.get("min_gap_ms", 150),
        rhythm_window_ms=detect_cfg.get("rhythm_window_ms", 800),
        long_press_ms=detect_cfg.get("long_press_ms", 500),
    )
    onset = OnsetDetector(min_gap_ms=detect_cfg.get("min_gap_ms", 80))

    print(f"[tabletap test] Threshold: {threshold.threshold_db:.1f} dB\n")

    start_time = time.time()
    try:
        with MicCapture(audio_cfg, filter_cfg) as mic:
            while time.time() - start_time < duration:
                raw, filtered = mic.read_filtered()
                db = rms_db(filtered)
                now = time.monotonic()

                is_spike = threshold.is_above(db)

                if is_spike:
                    threshold.update(db, True)
                    detected = onset.feed(db, now)
                    if detected:
                        event = pattern_detector.feed()
                        if event:
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"\n[{timestamp}] Detected: {event.key().upper()}")
                else:
                    threshold.update(db, False)
                    event = pattern_detector.on_silence()
                    if event:
                        timestamp = time.strftime("%H:%M:%S")
                        print(f"\n[{timestamp}] Detected: {event.key().upper()}")

                timeout_event = pattern_detector.check_window_timeout()
                if timeout_event:
                    timestamp = time.strftime("%H:%M:%S")
                    print(f"\n[{timestamp}] Detected: {timeout_event.key().upper()}")

                bar_db = max(0, db + 100)
                bar_len = int(bar_db / 2)
                bar = "#" * min(bar_len, 50)
                spike = " <-- SPIKE!" if is_spike else ""
                
                elapsed = int(time.time() - start_time)
                remaining = duration - elapsed
                print(f"\r  [{remaining:2d}s] {db:6.1f} dB (thr: {threshold.threshold_db:.1f}) |{bar.ljust(50)}|{spike}", end="", flush=True)

                time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    print("\n\n[tabletap test] Test completed.")


def main():
    parser = argparse.ArgumentParser(
        prog="tabletap",
        description="Turn your table into a button pad using the laptop mic",
    )
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the tabletap daemon")
    start_p.add_argument("-c", "--config", help="Path to config.yaml")
    start_p.add_argument("--category", help="Action category to use (productivity, multitasking, smart_home, media)")

    mon_p = sub.add_parser("monitor", help="Watch mic levels and spikes in real-time")
    mon_p.add_argument("-c", "--config", help="Path to config.yaml")

    cal_p = sub.add_parser("calibrate", help="Calibrate noise floor and threshold")
    cal_p.add_argument("-c", "--config", help="Path to config.yaml")
    cal_p.add_argument("-d", "--duration", type=int, help="Duration in seconds")
    cal_p.add_argument("--no-save", action="store_true", help="Don't save calibration to config (dry-run)")

    test_p = sub.add_parser("test", help="Dry-run mode: detect taps but don't execute actions")
    test_p.add_argument("-c", "--config", help="Path to config.yaml")
    test_p.add_argument("-d", "--duration", type=int, default=30, help="Test duration in seconds (default: 30)")

    init_p = sub.add_parser("init", help="Create default config at ~/.config/tabletap/config.yaml")
    init_p.add_argument("--path", help="Custom destination path")

    sub.add_parser("status", help="Show current config and device info")
    sub.add_parser("setup", help="Initialize config and install OpenTUI dependencies")
    sub.add_parser("doctor", help="Check microphone, shortcuts, config, and OpenTUI installation")
    bridge_p = sub.add_parser("bridge", help=argparse.SUPPRESS)
    bridge_p.add_argument("-c", "--config", help="Path to config.yaml")
    bridge_p.add_argument("--category", help="Action category")
    bridge_p.add_argument("--dry-run", action="store_true", help="Detect but do not execute")
    bridge_p.add_argument("--calibrate", action="store_true", help="Stream calibration progress")
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

    if args.command in ("setup", "doctor"):
        from .config import init_config
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
        keytool = "ydotool" if os.environ.get("WAYLAND_DISPLAY") else "xdotool"
        print("  Key tool: " + (shutil.which(keytool) or "MISSING (" + keytool + ")"))
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
        from .config import init_config
        init_config()
        env = os.environ.copy()
        env["TABLETAP_PYTHON"] = sys.executable
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
        daemon = Daemon(cfg, category=args.category if hasattr(args, 'category') else None)
        daemon.run()

    elif args.command == "monitor":
        monitor_cmd(cfg)

    elif args.command == "test":
        test_cmd(cfg, args.duration)

    elif args.command == "calibrate":
        result = calibrate(cfg, duration_sec=args.duration if hasattr(args, "duration") else None)
        
        if not args.no_save:
            config_path = save_calibration(cfg, result, args.config if hasattr(args, "config") else None)
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

    elif args.command == "status":
        print("[tabletap] Current config:")
        import yaml
        print(yaml.dump(cfg, default_flow_style=False))


if __name__ == "__main__":
    main()

