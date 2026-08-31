import time
import sys

import numpy as np

from .mic import MicCapture, rms_db


def calibrate(cfg: dict, duration_sec: int = None, margin_db: float = None) -> dict:
    audio_cfg = cfg.get("audio", {})
    filter_cfg = cfg.get("filter", {})
    cal_cfg = cfg.get("calibration", {})
    duration = duration_sec or cal_cfg.get("duration_sec", 5)

    print("[tabletap] Phase 1: Listening to ambient noise...")
    print("[tabletap] Stay quiet for 5 seconds.")
    sys.stdout.flush()

    noise_samples = []
    start = time.monotonic()

    with MicCapture(audio_cfg, filter_cfg) as mic:
        while time.monotonic() - start < duration:
            _, filtered = mic.read_filtered()
            db = rms_db(filtered)
            noise_samples.append(db)
            elapsed = time.monotonic() - start
            bar_len = int((elapsed / duration) * 30)
            sys.stdout.write(f"\r  [{('#' * bar_len).ljust(30)}] {db:.1f} dB")
            sys.stdout.flush()

    print()

    noise_floor = float(np.percentile(noise_samples, 10))

    print(f"\n[tabletap] Phase 2: Tap/slam the table for {duration} seconds!")
    print("[tabletap] Hit it like you would during normal use.")
    sys.stdout.flush()

    time.sleep(2)

    slam_samples = []
    start = time.monotonic()

    with MicCapture(audio_cfg, filter_cfg) as mic:
        while time.monotonic() - start < duration:
            _, filtered = mic.read_filtered()
            db = rms_db(filtered)
            slam_samples.append(db)
            elapsed = time.monotonic() - start
            bar_len = int((elapsed / duration) * 30)
            spike = " <-- SLAM" if db > noise_floor + 10 else ""
            sys.stdout.write(f"\r  [{('#' * bar_len).ljust(30)}] {db:.1f} dB{spike}")
            sys.stdout.flush()

    print()

    slam_peak = float(np.percentile(slam_samples, 90))

    gap = slam_peak - noise_floor
    if gap >= 6:
        threshold = noise_floor + gap * 0.35
    else:
        threshold = noise_floor + 6

    print(f"[tabletap] Noise floor:  {noise_floor:.1f} dB")
    print(f"[tabletap] Slam peak:    {slam_peak:.1f} dB")
    print(f"[tabletap] Gap:          {gap:.1f} dB")
    print(f"[tabletap] Threshold:    {threshold:.1f} dB")
    print(f"[tabletap] Calibration complete.")

    return {
        "noise_floor_db": round(noise_floor, 1),
        "slam_peak_db": round(slam_peak, 1),
        "threshold_db": round(threshold, 1),
    }


def auto_calibrate(cfg: dict) -> dict:
    print("[tabletap] Auto-calibrating (first run)...")
    return calibrate(cfg, duration_sec=5)
