import argparse
import logging
import sys

from .config import load_config, init_config, save_calibration
from .daemon import Daemon
from .calibrate import calibrate
from .filter import AdaptiveThreshold


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

    args = parser.parse_args()

    if args.command == "init":
        dest = init_config(args.path)
        print(f"[tabletap] Config created at {dest}")
        return

    if args.command is None:
        parser.print_help()
        return

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

