import time
import sys

import numpy as np

from .mic import MicCapture, rms_db
from .filter import ImpactDetector, is_broadband_noise


def fit_personalized_threshold(noise_floor: float, work_peak: float, samples: list,
                               detection: dict) -> tuple[float, float, int]:
    """Fit from individual confirmed impacts, not the loudest audio chunks."""
    floor = max(noise_floor + 6.0, work_peak + 4.0)
    detector = ImpactDetector(
        min_gap_ms=detection.get("min_gap_ms", 150),
        max_width_ms=detection.get("max_impact_ms", 220),
        min_attack_db=detection.get("min_attack_db", 7.0),
    )
    peaks = []
    peak = None
    for now, db, broadband in samples:
        if broadband:
            peak = None
        elif db > floor:
            peak = db if peak is None else max(peak, db)
        if detector.feed(db, floor, now, broadband=broadband) and peak is not None:
            peaks.append(peak)
        if db <= floor:
            peak = None
    if len(peaks) < 6:
        raise ValueError(
            f"Only {len(peaks)} of at least 6 clean taps recognized during training. "
            "Use a harder surface or different microphone and retry; previous calibration preserved."
        )
    weak = float(np.percentile(peaks, 20))
    # Never go below the measured worst-case work-noise level plus margin.
    threshold = max(floor, noise_floor + (weak - noise_floor) * 0.35)
    if weak - threshold < 2.0:
        raise ValueError("Soft taps overlap normal work noise; previous calibration preserved.")
    return weak, threshold, len(peaks)


def calibrate(cfg: dict, duration_sec: int = None, margin_db: float = None, progress=None) -> dict:
    audio_cfg = cfg.get("audio", {})
    filter_cfg = cfg.get("filter", {})
    cal_cfg = cfg.get("calibration", {})
    personalized = cal_cfg.get("personalized", False) is True
    detection = cfg.get("detection", {})
    duration = duration_sec if duration_sec is not None else cal_cfg.get("duration_sec", 5)
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("Calibration duration must be greater than zero seconds")

    print("[tabletap] Phase 1: Listening to ambient noise...")
    print("[tabletap] Stay quiet for 5 seconds.")
    sys.stdout.flush()

    if progress is not None:
        progress("noise", 0, duration, None)

    noise_samples = []
    start = time.monotonic()

    with MicCapture(audio_cfg, filter_cfg) as mic:
        while time.monotonic() - start < duration:
            _, filtered = mic.read_filtered()
            db = rms_db(filtered)
            noise_samples.append(db)
            elapsed = time.monotonic() - start
            if progress is not None:
                progress("noise", elapsed, duration, db)
            bar_len = int((elapsed / duration) * 30)
            sys.stdout.write(f"\r  [{('#' * bar_len).ljust(30)}] {db:.1f} dB")
            sys.stdout.flush()

    print()

    if not noise_samples:
        raise ValueError("No audio samples received during noise calibration")
    noise_floor = float(np.percentile(noise_samples, 50))

    print(f"\n[tabletap] Phase 2: TYPE, SPEAK and CLICK normally for {duration} seconds.")
    if progress is not None:
        progress("work", 0, duration, None)
    work_samples = []
    start = time.monotonic()
    with MicCapture(audio_cfg, filter_cfg) as mic:
        while time.monotonic() - start < duration:
            _, filtered = mic.read_filtered()
            db = rms_db(filtered)
            work_samples.append(db)
            if progress is not None:
                progress("work", time.monotonic() - start, duration, db)
    if not work_samples:
        raise ValueError("No audio samples received during normal-working calibration")
    work_peak = float(max(work_samples) if personalized else np.percentile(work_samples, 99.5))

    print(f"\n[tabletap] Phase 3: Deliberately tap the desk for {duration} seconds!")
    print("[tabletap] Make at least 6 separated soft and normal taps." if personalized else "[tabletap] Hit it like you would during normal use.")
    sys.stdout.flush()

    if progress is not None:
        progress("prepare", 0, 2, None)
    time.sleep(2)
    if progress is not None:
        progress("tap", 0, duration, None)

    slam_samples = []
    impact_samples = []
    start = time.monotonic()

    with MicCapture(audio_cfg, filter_cfg) as mic:
        while time.monotonic() - start < duration:
            raw, filtered = mic.read_filtered()
            db = rms_db(filtered)
            slam_samples.append(db)
            now = time.monotonic()
            elapsed = now - start
            if personalized:
                floor = max(noise_floor + 6.0, work_peak + 4.0)
                broadband = bool(
                    detection.get("broadband_guard", True)
                    and db > floor - 12.0
                    and rms_db(raw) > noise_floor + 14.0
                    and is_broadband_noise(raw, audio_cfg.get("sample_rate", 44100))
                )
                impact_samples.append((now, float(db), broadband))
            if progress is not None:
                progress("tap", elapsed, duration, db)
            bar_len = int((elapsed / duration) * 30)
            spike = " <-- SLAM" if db > noise_floor + 10 else ""
            sys.stdout.write(f"\r  [{('#' * bar_len).ljust(30)}] {db:.1f} dB{spike}")
            sys.stdout.flush()

    print()

    # Short desk impacts occupy only a few audio chunks, so P90 over
    # every chunk often represents quiet room audio, not taps.
    # P98 samples the high-energy impacts without relying on one
    # potentially clipped microphone frame.
    if not slam_samples:
        raise ValueError("No audio samples received during tap calibration")
    slam_peak = float(np.percentile(slam_samples, 98))

    gap = slam_peak - noise_floor
    # Negative training examples: ordinary keyboard and mouse noise must NOT
    # cross the minimum threshold even after adaptive-noise recalculation.
    threshold = max(noise_floor + max(6.0, gap * 0.40), work_peak + 4.0)
    if gap < 8.0 or threshold >= slam_peak - 2.0:
        raise ValueError(
            "Desk taps are not clearly louder than typing/room noise. "
            "Try a different microphone or tap surface, then recalibrate; "
            "your previous configuration was preserved."
        )
    if personalized:
        slam_peak, threshold, count = fit_personalized_threshold(noise_floor, work_peak, impact_samples, detection)
        gap = slam_peak - noise_floor
        print(f"[tabletap] Learned {count} distinct tap examples (weak-tap reference: {slam_peak:.1f} dB)")
        if margin_db is not None:
            threshold = max(work_peak + 4.0, noise_floor + 6.0, threshold + margin_db)
            if threshold >= slam_peak - 2.0:
                raise ValueError("Requested margin would reject soft taps; previous calibration preserved.")
    elif margin_db is not None:
        threshold = max(noise_floor, min(threshold + margin_db, slam_peak + margin_db - 0.5))

    print(f"[tabletap] Noise floor:  {noise_floor:.1f} dB")
    print(f"[tabletap] Slam peak:    {slam_peak:.1f} dB")
    print(f"[tabletap] Work peak:    {work_peak:.1f} dB")
    print(f"[tabletap] Gap:          {gap:.1f} dB")
    print(f"[tabletap] Threshold:    {threshold:.1f} dB")
    print(f"[tabletap] Calibration complete.")

    return {
        "noise_floor_db": round(noise_floor, 1),
        "work_peak_db": round(work_peak, 1),
        "slam_peak_db": round(slam_peak, 1),
        "threshold_db": round(threshold, 1),
    }


def auto_calibrate(cfg: dict) -> dict:
    print("[tabletap] Auto-calibrating (first run)...")
    return calibrate(cfg, duration_sec=5)

