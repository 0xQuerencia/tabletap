import argparse
import logging
import sys

from .config import load_config, init_config
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


def main():
    parser = argparse.ArgumentParser(
        prog="tabletap",
        description="Turn your table into a button pad using the laptop mic",
    )
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the tabletap daemon")
    start_p.add_argument("-c", "--config", help="Path to config.yaml")

    mon_p = sub.add_parser("monitor", help="Watch mic levels and spikes in real-time")
    mon_p.add_argument("-c", "--config", help="Path to config.yaml")

    cal_p = sub.add_parser("calibrate", help="Calibrate noise floor and threshold")
    cal_p.add_argument("-c", "--config", help="Path to config.yaml")
    cal_p.add_argument("-d", "--duration", type=int, help="Duration in seconds")

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
        daemon = Daemon(cfg)
        daemon.run()

    elif args.command == "monitor":
        monitor_cmd(cfg)

    elif args.command == "calibrate":
        result = calibrate(cfg, duration_sec=args.duration if hasattr(args, "duration") else None)
        print(f"\nAdd this to your config.yaml:")
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
