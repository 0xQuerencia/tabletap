"""Local-only work-noise audit; the microphone stays in dry-run mode.

An audit is deliberately performed while *not* tapping. Any gesture emitted
during this interval therefore represents an unintended activation. No raw
waveforms, keyboard input, filenames, command values, or microphone audio are
recorded, uploaded, or written to disk.
"""
from __future__ import annotations

import codecs
from collections import Counter
import json
import os
import selectors
import subprocess
import sys
import time


class WorkNoiseStats:
    def __init__(self):
        self.ready = False
        self.dry_run = False
        self.gestures: Counter[str] = Counter()
        self.rejected: Counter[str] = Counter()
        self.level_samples = 0
        self.max_level_db: float | None = None
        self.last_threshold_db: float | None = None
        self.error: str | None = None

    def consume(self, line: str) -> None:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            return
        if not isinstance(record, dict):
            return
        kind = record.get("type")
        if kind == "ready":
            self.ready = True
            self.dry_run = record.get("dry_run") is True
            if not self.dry_run:
                self.error = "Safety check failed: the audio bridge was not in dry-run mode."
        elif kind == "level":
            db, threshold = record.get("db"), record.get("threshold_db")
            if isinstance(db, (int, float)) and not isinstance(db, bool):
                self.level_samples += 1
                self.max_level_db = max(float(db), self.max_level_db) if self.max_level_db is not None else float(db)
            if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
                self.last_threshold_db = float(threshold)
        elif kind == "gesture":
            pattern = record.get("pattern")
            if isinstance(pattern, str) and pattern:
                self.gestures[pattern] += 1
            if record.get("dispatched") is True:
                self.error = "Safety check failed: bridge reported a dispatched action."
        elif kind == "rejected":
            reason = record.get("reason")
            if isinstance(reason, str) and reason:
                self.rejected[reason] += 1
        elif kind == "error":
            self.error = str(record.get("message") or "Audio bridge reported an error")

    def result(self, duration_sec: float, observed_sec: float, complete: bool) -> dict:
        total = sum(self.gestures.values())
        status = "error" if self.error or not self.ready or not complete or not self.level_samples else (
            "warn" if total else "pass"
        )
        error = self.error
        if status == "error" and not error:
            error = "Audio bridge stopped before completing the audit. Run: tabletap doctor"
        margin = (round(self.last_threshold_db - self.max_level_db, 1)
                  if self.last_threshold_db is not None and self.max_level_db is not None else None)
        return {
            "status": status,
            "duration_requested_sec": round(duration_sec, 1),
            "duration_observed_sec": round(observed_sec, 1),
            "mic_level_samples": self.level_samples,
            "gestures": dict(sorted(self.gestures.items())),
            "total_unintended_gestures": total,
            "rejected_noise": dict(sorted(self.rejected.items())),
            "max_work_level_db": round(self.max_level_db, 1) if self.max_level_db is not None else None,
            "last_threshold_db": round(self.last_threshold_db, 1) if self.last_threshold_db is not None else None,
            "headroom_db": margin,
            "error": error,
            "raw_audio_recorded": False,
            "actions_enabled": False,
        }


def observe_work(duration_sec: float = 30, config_path: str | None = None,
                 *, command: list[str] | None = None,
                 startup_timeout_sec: float = 10) -> dict:
    """Observe the *existing* bridge rather than maintaining a second detector.

    Exactly the same algorithm, profile-independent settings and microphone
    backend used by interactive TableTap are exercised. Always force dry-run.
    The command argument exists for subprocess testing; the public CLI never
    supplies an arbitrary command.
    """
    if not 0 < duration_sec <= 600:
        raise ValueError("Audit duration must be greater than 0 and at most 600 seconds")
    stats = WorkNoiseStats()
    args = command or [sys.executable, "-u", "-m", "tabletap", "bridge", "--dry-run"]
    if command is None and config_path:
        args = [*args, "--config", str(config_path)]
    proc = None
    watch = selectors.DefaultSelector()
    ready_at = None
    opened_at = time.monotonic()
    complete = False
    interrupted = False
    ended = False
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    pending = ""

    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0,
        )
        if proc.stdout is None:
            raise RuntimeError("Audio bridge stdout unavailable")
        watch.register(proc.stdout, selectors.EVENT_READ)
        while True:
            now = time.monotonic()
            if stats.error:
                break
            if ready_at is not None and now - ready_at >= duration_sec:
                complete = True
                break
            if ready_at is None and now - opened_at >= startup_timeout_sec:
                stats.error = "Microphone did not open in time. Run: tabletap doctor"
                break
            for key, _mask in watch.select(timeout=0.10):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    ended = True
                    break
                pending += decoder.decode(chunk)
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    stats.consume(line)
                    if stats.ready and ready_at is None:
                        ready_at = time.monotonic()
            if ended:
                if pending.strip():
                    stats.consume(pending)
                break
    except KeyboardInterrupt:
        interrupted = True
        stats.error = "Audit interrupted."
    except (OSError, RuntimeError) as exc:
        stats.error = f"Could not start audio audit: {exc}"
    finally:
        watch.close()
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
            if proc.stdout is not None:
                proc.stdout.close()
    observed = min(time.monotonic() - ready_at, duration_sec) if ready_at is not None else 0.0
    report = stats.result(duration_sec, max(0, observed), complete)
    if interrupted:
        report["interrupted"] = True
    return report


def format_audit(report: dict) -> str:
    status = report["status"]
    total = report["total_unintended_gestures"]
    lines = [
        "TableTap work-noise audit · NO commands were executed",
        f"Observed: {report['duration_observed_sec']:.1f}s  |  measured levels: {report['mic_level_samples']}",
    ]
    if status == "error":
        lines += ["ERROR: " + (report["error"] or "Unknown microphone error")]
    elif status == "pass":
        lines += ["PASS: No unintended tap patterns during this observation."]
    else:
        lines += [f"WARNING: {total} gesture(s) detected while working normally.",
                  "Keep live actions disabled. Recalibrate and retest before arming."]
    if report["gestures"]:
        lines.append("Unintended patterns: " + ", ".join(f"{k}={v}" for k, v in report["gestures"].items()))
    if report["rejected_noise"]:
        lines.append("Ignored noises: " + ", ".join(f"{k}={v}" for k, v in report["rejected_noise"].items()))
    if report["headroom_db"] is not None:
        lines.append(
            f"Peak work level: {report['max_work_level_db']:.1f} dB"
            f"  |  trigger threshold: {report['last_threshold_db']:.1f} dB"
            f"  |  headroom: {report['headroom_db']:+.1f} dB"
        )
        if report["headroom_db"] <= 3:
            lines.append("Low threshold headroom: recalibrate while typing normally (press c in TUI).")
    if status != "error":
        lines.append("Note: A clean short audit does not guarantee zero false positives.")
    lines.append("Privacy: only aggregate loudness/gesture counts; no recordings or key data.")
    return "\n".join(lines)
