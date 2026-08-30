import time
import sys

import numpy as np

from .mic import MicCapture, rms_db


def calibrate(cfg: dict, duration_sec: int = None, margin_db: float = None) -> float:
    audio_cfg = cfg.get("audio", {})
    cal_cfg = cfg.get("calibration", {})
    duration = duration_sec or cal_cfg.get("duration_sec", 10)
    margin = margin_db or cal_cfg.get("noise_floor_margin_db", 6)

    print(f"[tabletap] Calibrating... listen for {duration}s in silence.")
    print("[tabletap] Do NOT tap anything during calibration.")
    sys.stdout.flush()

    samples = []
    start = time.monotonic()

    with MicCapture(audio_cfg) as mic:
        while time.monotonic() - start < duration:
            chunk = mic.read_chunk()
            db = rms_db(chunk)
            samples.append(db)
            elapsed = time.monotonic() - start
            bar_len = int((elapsed / duration) * 30)
            sys.stdout.write(f"\r  [{('#' * bar_len).ljust(30)}] {db:.1f} dB")
            sys.stdout.flush()

    print()

    noise_floor = float(np.percentile(samples, 50))
    threshold = noise_floor + margin

    print(f"[tabletap] Noise floor: {noise_floor:.1f} dB")
    print(f"[tabletap] Threshold:   {threshold:.1f} dB")
    print(f"[tabletap] Calibration complete.")

    return threshold
