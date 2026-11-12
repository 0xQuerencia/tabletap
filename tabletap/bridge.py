"""JSON-lines audio bridge consumed by the OpenTUI front end.

Stdout is machine-readable events; diagnostic logs go to stderr.
The bridge intentionally keeps all audio processing and actions local.
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import time

from .action import ActionRunner
from .config import init_config, load_config
from .filter import AdaptiveThreshold, OnsetDetector
from .lock import PIDLock
from .mic import MicCapture, MicDisconnected, rms_db
from .pattern import PatternDetector

log = logging.getLogger(__name__)


def emit(kind: str, **fields) -> None:
    print(json.dumps({"type": kind, **fields}, separators=(",", ":")), flush=True)


def run_bridge(config_path=None, category=None, dry_run=False) -> int:
    """Listen continuously, report live levels/gestures, and execute mapped actions.

    A lock prevents a TUI bridge from racing the old systemd daemon.
    """
    if config_path is None:
        init_config()
    cfg = load_config(config_path)
    audio = cfg.get("audio", {})
    filter_cfg = cfg.get("filter", {})
    detection = cfg.get("detection", {})
    sensitivity_offset = float(filter_cfg.get("sensitivity_offset_db", 0.0))

    if category is not None and category not in cfg.get("actions", {}):
        emit("error", message=f"Unknown category: {category}")
        return 2

    threshold = AdaptiveThreshold(
        initial_threshold_db=detection.get("threshold_db", -30),
        noise_alpha=filter_cfg.get("noise_alpha", 0.05),
        peak_alpha=filter_cfg.get("peak_alpha", 0.1),
        snr_gate_db=filter_cfg.get("snr_gate_db", 6.0),
    )
    noise = detection.get("noise_floor_db")
    peak = detection.get("slam_peak_db")
    if noise is not None and peak is not None:
        threshold.set_from_calibration(noise, peak)

    pattern = PatternDetector(
        min_gap_ms=detection.get("min_gap_ms", 150),
        rhythm_window_ms=detection.get("rhythm_window_ms", 800),
        long_press_ms=detection.get("long_press_ms", 500),
        medium_hold_ms=detection.get("medium_hold_ms", 2000),
        long_hold_ms=detection.get("long_hold_ms", 4000),
        hold_repeat_ms=detection.get("hold_repeat_ms", 500),
        enable_hold=detection.get("enable_hold_gestures", False),
    )
    onset = OnsetDetector(min_gap_ms=detection.get("min_gap_ms", 150))
    runner = ActionRunner(cfg.get("actions", {}), category=category)
    lock = PIDLock()
    if not lock.acquire():
        emit("error", message="Another TableTap listener is already running")
        runner.shutdown()
        return 3

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    previous_int = signal.signal(signal.SIGINT, stop)
    previous_term = signal.signal(signal.SIGTERM, stop)

    def handle(event):
        if event is None:
            return
        key = event.key()
        action = runner._get_action(key)
        name = action.get("name") or action.get("value") if action else "unmapped"
        emit("gesture", pattern=key, action=name, dispatched=bool(action) and not dry_run)
        if action and not dry_run:
            runner.run(key)

    try:
        with MicCapture(audio, filter_cfg) as mic:
            emit(
                "ready", category=category or "default",
                dry_run=dry_run, threshold_db=round(threshold.threshold_db + sensitivity_offset, 1),
            )
            last_level_at = 0.0
            while running:
                _raw, filtered = mic.read_filtered()
                db = rms_db(filtered)
                now = time.monotonic()
                spike = db > threshold.threshold_db + sensitivity_offset
                # Feed the energy derivative on *every* chunk. Skipping silence
                # otherwise leaves the onset detector with stale energy.
                started = onset.feed(db, now)
                if spike and started:
                    handle(pattern.feed())
                elif not spike:
                    handle(pattern.on_silence())
                threshold.update(db, spike)
                handle(pattern.check_window_timeout())
                if now - last_level_at >= 0.1:
                    emit(
                        "level", db=round(db, 1),
                        threshold_db=round(threshold.threshold_db + sensitivity_offset, 1),
                        spike=spike,
                    )
                    last_level_at = now
    except (MicDisconnected, OSError, ImportError) as exc:
        emit("error", message=str(exc))
        return 1
    except Exception as exc:
        log.exception("Audio bridge crashed")
        emit("error", message=str(exc))
        return 1
    finally:
        runner.shutdown()
        lock.release()
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        emit("stopped")
    return 0


def run_calibration(config_path=None) -> int:
    """Calibrate through machine-readable progress events for the TUI."""
    from contextlib import redirect_stdout
    from .calibrate import calibrate
    from .config import save_calibration

    if config_path is None:
        init_config()
    cfg = load_config(config_path)
    output = sys.stdout
    last_progress_at = 0.0

    def progress(phase, elapsed, duration, db):
        nonlocal last_progress_at
        now = time.monotonic()
        if elapsed and now - last_progress_at < 0.12:
            return
        last_progress_at = now
        record = {
            "type": "calibration_progress", "phase": phase,
            "elapsed": round(elapsed, 2), "duration": duration,
        }
        if db is not None:
            record["db"] = round(db, 1)
        print(json.dumps(record), file=output, flush=True)

    try:
        # calibrate() includes human-readable prompts for the old CLI. Keep
        # them on stderr so stdout remains a JSONL-only protocol for OpenTUI.
        with redirect_stdout(sys.stderr):
            result = calibrate(cfg, progress=progress)
        save_calibration(cfg, result, config_path)
        print(json.dumps({"type": "calibration_done", **result}),
              file=output, flush=True)
        return 0
    except (OSError, ImportError, ValueError) as exc:
        print(json.dumps({"type": "error", "message": str(exc)}),
              file=output, flush=True)
        return 1
