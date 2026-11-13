"""JSON-lines audio bridge consumed by the OpenTUI front end.

Stdout is machine-readable events; diagnostic logs go to stderr.
The bridge intentionally keeps all audio processing and actions local.
"""
from __future__ import annotations

import json
import logging
import threading
import signal
import sys
import time

import yaml

from .action import ActionRunner
from .config import init_config, load_config
from .filter import AdaptiveThreshold, ImpactDetector
from .lock import PIDLock
from .mic import MicCapture, MicDisconnected, rms_db
from .pattern import PatternDetector

log = logging.getLogger(__name__)
_emit_lock = threading.Lock()


def emit(kind: str, **fields) -> None:
    def scalar(value):
        if hasattr(value, "item"):
            return value.item()  # NumPy scalar to a native JSON type.
        raise TypeError(f"Unsupported bridge value: {type(value).__name__}")

    line = json.dumps({"type": kind, **fields},
                      separators=(",", ":"), default=scalar)
    # Worker threads can finish launching actions while the mic emits levels.
    # Serialize a complete JSON line per write for the terminal bridge.
    with _emit_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def run_bridge(config_path=None, category=None, dry_run=False, live_seconds=None) -> int:
    """Listen continuously, report live levels/gestures, and execute mapped actions.

    A lock prevents a TUI bridge from racing the old systemd daemon.
    """
    try:
        if config_path is None:
            init_config()
        cfg = load_config(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        emit("error", message=f"Cannot load TableTap config: {exc}")
        return 2
    if live_seconds is not None:
        if dry_run or not 0 < live_seconds <= 600:
            emit("error", message="A live authorization must be between 0 and 600 seconds, and cannot be used with --dry-run")
            return 2
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
        threshold.set_from_calibration(noise, peak, detection.get('threshold_db'))

    pattern = PatternDetector(
        min_gap_ms=detection.get("min_gap_ms", 150),
        rhythm_window_ms=detection.get("rhythm_window_ms", 800),
        long_press_ms=detection.get("long_press_ms", 500),
        medium_hold_ms=detection.get("medium_hold_ms", 2000),
        long_hold_ms=detection.get("long_hold_ms", 4000),
        hold_repeat_ms=detection.get("hold_repeat_ms", 500),
        enable_hold=detection.get("enable_hold_gestures", False),
    )
    impact = ImpactDetector(
        min_gap_ms=detection.get("min_gap_ms", 150),
        max_width_ms=detection.get("max_impact_ms", 220),
        min_attack_db=detection.get("min_attack_db", 7.0),
    )
    runner = ActionRunner(
        cfg.get("actions", {}),
        category=category,
        on_result=lambda pattern, status, message: emit(
            "action_result", pattern=pattern, status=status, message=message
        ),
    )
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
        if key == "quadruple" and not detection.get("enable_four_taps", False):
            emit("rejected", reason="four-tap gesture disabled for safety")
            return
        action = runner._get_action(key)
        name = action.get("name") or action.get("value") if action else "unmapped"
        executable = isinstance(action, dict) and bool(str(action.get("value", "")).strip())
        emit("gesture", pattern=key, action=name, dispatched=executable and not dry_run)
        if executable and not dry_run:
            runner.run(key)

    try:
        with MicCapture(audio, filter_cfg) as mic:
            emit(
                "ready", category=category or "default",
                dry_run=dry_run, threshold_db=round(threshold.threshold_db + sensitivity_offset, 1),
            )
            last_level_at = 0.0
            deadline = time.monotonic() + live_seconds if live_seconds is not None else None
            while running:
                # Enforced inside the Python action-capable process, even if
                # the terminal UI freezes or its timer never gets CPU time.
                if deadline is not None and time.monotonic() >= deadline:
                    emit("live_expired", message="Live action authorization expired")
                    break
                _raw, filtered = mic.read_filtered()
                db = float(rms_db(filtered))
                now = time.monotonic()
                spike = bool(db > threshold.threshold_db + sensitivity_offset)
                # Feed the energy derivative on *every* chunk. Skipping silence
                # otherwise leaves the onset detector with stale energy.
                confirmed = impact.feed(db, threshold.threshold_db + sensitivity_offset, now)
                if confirmed:
                    handle(pattern.feed())
                if not spike:
                    handle(pattern.on_silence())
                if impact.rejected_reason and impact.rejected_reason != "echo / too close":
                    emit("rejected", reason=impact.rejected_reason)
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

    output = sys.stdout
    try:
        if config_path is None:
            init_config()
        cfg = load_config(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"type": "error", "message": f"Cannot load TableTap config: {exc}"}), file=output, flush=True)
        return 2
    lock = PIDLock()
    if not lock.acquire():
        print(json.dumps({"type": "error", "message": "Another TableTap listener is running. Stop it before calibration."}),
              file=output, flush=True)
        return 3
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
    except (MicDisconnected, OSError, ImportError, ValueError) as exc:
        print(json.dumps({"type": "error", "message": str(exc)}),
              file=output, flush=True)
        return 1
    finally:
        lock.release()
