import signal
import sys
import time
import logging
import subprocess
import shutil

from .mic import MicCapture, rms_db, MicDisconnected
from .filter import AdaptiveThreshold, OnsetDetector
from .pattern import PatternDetector
from .action import ActionRunner
from .calibrate import auto_calibrate
from .lock import PIDLock
from .config import load_config, save_calibration

log = logging.getLogger("tabletap")


class Daemon:
    def __init__(self, cfg: dict, category: str | None = None):
        self.cfg = cfg
        self.category = category
        self._running = False
        self._needs_reload = False
        self.lock = PIDLock()
        self._build_components()

    def _build_components(self):
        self.audio_cfg = self.cfg.get("audio", {})
        self.filter_cfg = self.cfg.get("filter", {})
        self.detect_cfg = self.cfg.get("detection", {})
        self.feedback_cfg = self.cfg.get("feedback", {})
        self.action_runner = ActionRunner(self.cfg.get("actions", {}), category=self.category)
        self.pattern_detector = PatternDetector(
            min_gap_ms=self.detect_cfg.get("min_gap_ms", 150),
            rhythm_window_ms=self.detect_cfg.get("rhythm_window_ms", 800),
            long_press_ms=self.detect_cfg.get("long_press_ms", 500),
            enable_hold=self.detect_cfg.get("enable_hold_gestures", False),
        )
        self._notifications_enabled = self.feedback_cfg.get("notifications", True)
        self._notification_urgency = self.feedback_cfg.get("notification_urgency", "low")

        self.adaptive = self.filter_cfg.get("adaptive", True)
        self.threshold = AdaptiveThreshold(
            initial_threshold_db=self.detect_cfg.get("threshold_db", -30),
            noise_alpha=self.filter_cfg.get("noise_alpha", 0.05),
            peak_alpha=self.filter_cfg.get("peak_alpha", 0.1),
            snr_gate_db=self.filter_cfg.get("snr_gate_db", 6.0),
        )
        self.onset = OnsetDetector(min_gap_ms=self.detect_cfg.get("min_gap_ms", 80))

        saved_noise = self.detect_cfg.get("noise_floor_db")
        saved_peak = self.detect_cfg.get("slam_peak_db")
        if saved_noise is not None and saved_peak is not None:
            self.threshold.set_from_calibration(saved_noise, saved_peak)
            log.info("Loaded calibration: noise=%.1f peak=%.1f threshold=%.1f",
                     saved_noise, saved_peak, self.threshold.threshold_db)

    def _reload_config(self):
        try:
            log.info("Reloading configuration...")
            new_cfg = load_config()
            old_cfg, old_runner = self.cfg, self.action_runner
            self.cfg = new_cfg
            try:
                self._build_components()
            except Exception:
                self.cfg = old_cfg
                self.action_runner = old_runner
                raise
            old_runner.shutdown()
            log.info("Configuration reloaded successfully (threshold: %.1f dB)", 
                     self.threshold.threshold_db)
            self._needs_reload = False
        except Exception as e:
            log.error(f"Failed to reload config: {e}")
            self._needs_reload = False

    def run(self):
        if not self.lock.acquire():
            log.error("Another tabletap instance is already running. Exiting.")
            sys.exit(1)

        self._running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGHUP, self._handle_reload)

        if self.detect_cfg.get("threshold_db") is None and self.detect_cfg.get("noise_floor_db") is None:
            log.info("No calibration found, running auto-calibrate...")
            result = auto_calibrate(self.cfg)
            save_calibration(self.cfg, result)
            self.threshold.set_from_calibration(result["noise_floor_db"], result["slam_peak_db"])
            log.info("Auto-calibration done: noise=%.1f peak=%.1f threshold=%.1f",
                     result["noise_floor_db"], result["slam_peak_db"], self.threshold.threshold_db)

        log.info("tabletap starting (threshold: %.1f dB)", self.threshold.threshold_db)

        try:
            with MicCapture(self.audio_cfg, self.filter_cfg) as mic:
                log.info("Mic opened. Tap the table!")
                while self._running:
                    if self._needs_reload:
                        self._reload_config()
                        log.info("Config reloaded - restart service for audio changes to take effect")

                    raw, filtered = mic.read_filtered()
                    db = rms_db(filtered)
                    now = time.monotonic()

                    is_spike = self.threshold.is_above(db)
                    # Feed the onset detector for quiet frames too, otherwise
                    # its baseline stays stale and isolated taps are missed.
                    detected = self.onset.feed(db, now)

                    if is_spike:
                        self.threshold.update(db, True)
                        if detected:
                            event = self.pattern_detector.feed()
                            if event:
                                log.info("TAP -> %s (threshold: %.1f dB)", event.key(), self.threshold.threshold_db)
                                self._notify(event.key())
                                self.action_runner.run(event.key())
                    else:
                        self.threshold.update(db, False)
                        event = self.pattern_detector.on_silence()
                        if event:
                            log.info("HOLD -> %s", event.key())
                            self._notify(event.key())
                            self.action_runner.run(event.key())

                    timeout_event = self.pattern_detector.check_window_timeout()
                    if timeout_event:
                        log.info("RHYTHM -> %s", timeout_event.key())
                        self._notify(timeout_event.key())
                        self.action_runner.run(timeout_event.key())
        except MicDisconnected as e:
            log.error("Microphone permanently disconnected: %s", e)
            self.lock.release()
            sys.exit(1)

        log.info("tabletap stopped.")

    def _notify(self, pattern: str):
        if not self._notifications_enabled:
            return
        
        if not shutil.which("notify-send"):
            return
        
        try:
            subprocess.Popen(
                [
                    "notify-send",
                    "-a", "tabletap",
                    "-u", self._notification_urgency,
                    "-i", "input-touchpad",
                    f"Tap: {pattern}"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            log.debug("Failed to send notification: %s", e)

    def _handle_signal(self, signum, frame):
        log.info("Received signal %s, shutting down...", signum)
        self.action_runner.shutdown()
        self.lock.release()
        self._running = False

    def _handle_reload(self, signum, frame):
        log.info("Received SIGHUP, will reload config...")
        self._needs_reload = True

