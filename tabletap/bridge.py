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
from .acoustic_profiles import verify_live, device_identity
from .config import init_config, load_config, DEFAULT_PATHS
from .filter import AdaptiveThreshold, ImpactDetector, is_broadband_noise, effective_threshold
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


def run_bridge(config_path=None, category=None, dry_run=False, live_seconds=None, *, control=None, held_lock=None, event_sink=None, duration=None) -> int:
    """Listen continuously, report live levels/gestures, and execute mapped actions.

    A lock prevents a TUI bridge from racing the old systemd daemon.
    """
    def report(kind, **fields):
        if event_sink is not None:
            event_sink(kind, **fields)
        elif control is None:
            emit(kind, **fields)
        else:
            control.publish(kind, **fields)
            if kind in ("error", "gesture", "action_result", "ready", "live_expired"):
                log.info("%s: %s", kind, fields)
    try:
        if config_path is None:
            init_config()
        cfg = load_config(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        report("error", message=f"Cannot load TableTap config: {exc}")
        return 2
    if duration is not None and (not dry_run or not 0 < duration <= 600):
        report("error", message="Preview duration must be between 0 and 600 seconds")
        return 2
    if live_seconds is not None:
        if dry_run or not 0 < live_seconds <= 600:
            report("error", message="A live authorization must be between 0 and 600 seconds, and cannot be used with --dry-run")
            return 2
    if not dry_run:
        try:
            if control is not None and not all(cfg.get("detection", {}).get(k) is not None for k in ("threshold_db", "noise_floor_db", "slam_peak_db")):
                raise ValueError("Calibrate before arming the background listener")
            verify_live(cfg)
        except (OSError, ValueError, RuntimeError) as exc:
            report("error", message=str(exc))
            return 2
    audio = cfg.get("audio", {})
    filter_cfg = cfg.get("filter", {})
    detection = cfg.get("detection", {})
    sensitivity_offset = float(filter_cfg.get("sensitivity_offset_db", 0.0))
    managed = bool(cfg.get("calibration", {}).get("device_key"))
    def limit_db():
        return effective_threshold(threshold.threshold_db, sensitivity_offset, detection, managed)

    if category is not None and category not in cfg.get("actions", {}):
        report("error", message=f"Unknown category: {category}")
        return 2

    threshold = AdaptiveThreshold(
        initial_threshold_db=detection.get("threshold_db", -30),
        noise_alpha=filter_cfg.get("noise_alpha", 0.05),
        peak_alpha=filter_cfg.get("peak_alpha", 0.1),
        snr_gate_db=filter_cfg.get("snr_gate_db", 6.0),
        use_calibrated_floor=managed,
    )
    noise = detection.get("noise_floor_db")
    peak = detection.get("slam_peak_db")
    if noise is not None and peak is not None:
        threshold.set_from_calibration(noise, peak, detection.get('threshold_db'))

    pattern = PatternDetector(
        min_gap_ms=detection.get("min_gap_ms", 150),
        rhythm_window_ms=detection.get("rhythm_window_ms", 800),
    )
    impact = ImpactDetector(
        min_gap_ms=detection.get("min_gap_ms", 150),
        max_width_ms=detection.get("max_impact_ms", 220),
        min_attack_db=detection.get("min_attack_db", 7.0),
    )
    runner = ActionRunner(
        cfg.get("actions", {}),
        category=category,
        on_result=lambda pattern, status, message: report(
            "action_result", pattern=pattern, status=status, message=message
        ),
    )
    lock = held_lock or PIDLock()
    if held_lock is None and not lock.acquire():
        report("error", message="Another TableTap listener is already running")
        runner.shutdown()
        return 3

    running = True
    if control is not None:
        control.set_runner(runner)

    def stop(_signum, _frame):
        nonlocal running
        running = False
        runner.cancel()
        if control is not None:
            control.signal_stop()

    previous_int = signal.signal(signal.SIGINT, stop)
    previous_term = signal.signal(signal.SIGTERM, stop)
    previous_hup = signal.signal(signal.SIGHUP, lambda *_: control.signal_reload()) if control is not None else None

    def handle(event):
        if event is None or (control is not None and control.interrupted.is_set()):
            return
        key = event.key()
        if key == "quadruple" and not detection.get("enable_four_taps", False):
            report("rejected", reason="four-tap gesture disabled for safety")
            return
        action = runner._get_action(key)
        name = action.get("name") or action.get("value") if action else "unmapped"
        executable = isinstance(action, dict) and bool(str(action.get("value", "")).strip())
        report("gesture", pattern=key, action=name, dispatched=executable and not dry_run)
        if executable and not dry_run:
            runner.run(key)

    try:
        with MicCapture(audio, filter_cfg) as mic:
            report(
                "ready", category=category or "default",
                dry_run=dry_run, threshold_db=round(limit_db(), 1),
                **({"config_path":str(__import__("pathlib").Path(config_path or DEFAULT_PATHS[0]).absolute())} if control is not None else {}),
            )
            last_level_at = 0.0
            deadline = time.monotonic() + live_seconds if live_seconds is not None else None
            runner.deadline = deadline
            preview_end = time.monotonic() + duration if duration is not None else None
            while running and not (control is not None and control.interrupted.is_set()):
                # Enforced inside the Python action-capable process, even if
                # the terminal UI freezes or its timer never gets CPU time.
                if preview_end is not None and time.monotonic() >= preview_end:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    report("live_expired", message="Live action authorization expired")
                    break
                raw, filtered = mic.read_filtered()
                if control is not None and control.interrupted.is_set():
                    break
                db = float(rms_db(filtered))
                now = time.monotonic()
                limit = limit_db()
                spike = bool(db > limit)
                broadband = bool(
                    detection.get("broadband_guard", True)
                    and db > limit - 12.0
                    and rms_db(raw) > threshold.noise_floor_db + 14.0
                    and is_broadband_noise(raw, audio.get("sample_rate", 44100))
                )
                if broadband:
                    pattern.reset()
                # Feed the energy derivative on *every* chunk. Skipping silence
                # otherwise leaves the onset detector with stale energy.
                confirmed = impact.feed(db, limit, now, broadband=broadband)
                if confirmed:
                    if dry_run and impact.confirmed_peak is not None:
                        report("impact_sample", db=round(impact.confirmed_peak, 1), accepted=True)
                    pattern.feed()
                if impact.rejected_reason and impact.rejected_reason != "echo / too close":
                    report("rejected", reason=impact.rejected_reason,
                         db=round(db, 1), threshold_db=round(limit, 1))
                if impact.near_miss is not None:
                    report("near_miss", **impact.near_miss)
                threshold.update(db, spike)
                handle(pattern.check_window_timeout())
                if now - last_level_at >= 0.1:
                    report(
                        "level", db=round(db, 1),
                        threshold_db=round(limit_db(), 1),
                        spike=spike,
                    )
                    last_level_at = now
    except (MicDisconnected, OSError, ImportError) as exc:
        report("error", message=str(exc))
        return 1
    except Exception as exc:
        log.exception("Audio bridge crashed")
        report("error", message=str(exc))
        return 1
    finally:
        runner.shutdown()
        if control is not None:
            control.set_runner(None)
        if held_lock is None:
            lock.release()
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        if control is None:
            report("stopped")
        else:
            signal.signal(signal.SIGHUP, previous_hup)
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
        identity = device_identity(cfg)
        with redirect_stdout(sys.stderr):
            result = calibrate(cfg, progress=progress)
        save_calibration(cfg, result, config_path, identity=identity)
        print(json.dumps({"type": "calibration_done", **result}),
              file=output, flush=True)
        return 0
    except (MicDisconnected, OSError, ImportError, ValueError) as exc:
        print(json.dumps({"type": "error", "message": str(exc)}),
              file=output, flush=True)
        return 1
    finally:
        lock.release()
