import signal
import time
import logging

from .mic import MicCapture, rms_db
from .filter import AdaptiveThreshold, OnsetDetector
from .pattern import PatternDetector
from .action import ActionRunner
from .calibrate import auto_calibrate

log = logging.getLogger("tabletap")


class Daemon:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.audio_cfg = cfg.get("audio", {})
        self.filter_cfg = cfg.get("filter", {})
        self.detect_cfg = cfg.get("detection", {})
        self.action_runner = ActionRunner(cfg.get("actions", {}))
        self.pattern_detector = PatternDetector(
            min_gap_ms=self.detect_cfg.get("min_gap_ms", 150),
            rhythm_window_ms=self.detect_cfg.get("rhythm_window_ms", 800),
            long_press_ms=self.detect_cfg.get("long_press_ms", 500),
        )
        self._running = False

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

    def run(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        if self.detect_cfg.get("threshold_db") is None and self.detect_cfg.get("noise_floor_db") is None:
            log.info("No calibration found, running auto-calibrate...")
            result = auto_calibrate(self.cfg)
            self.threshold.set_from_calibration(result["noise_floor_db"], result["slam_peak_db"])
            log.info("Auto-calibration done: noise=%.1f peak=%.1f threshold=%.1f",
                     result["noise_floor_db"], result["slam_peak_db"], self.threshold.threshold_db)

        log.info("tabletap starting (threshold: %.1f dB)", self.threshold.threshold_db)

        with MicCapture(self.audio_cfg, self.filter_cfg) as mic:
            log.info("Mic opened. Tap the table!")
            while self._running:
                raw, filtered = mic.read_filtered()
                db = rms_db(filtered)
                now = time.monotonic()

                is_spike = self.threshold.is_above(db)

                if is_spike:
                    self.threshold.update(db, True)
                    detected = self.onset.feed(db, now)
                    if detected:
                        event = self.pattern_detector.feed()
                        if event:
                            log.info("TAP -> %s (threshold: %.1f dB)", event.key(), self.threshold.threshold_db)
                            self.action_runner.run(event.key())
                else:
                    self.threshold.update(db, False)
                    event = self.pattern_detector.on_silence()
                    if event:
                        log.info("HOLD -> %s", event.key())
                        self.action_runner.run(event.key())

                timeout_event = self.pattern_detector.check_window_timeout()
                if timeout_event:
                    log.info("RHYTHM -> %s", timeout_event.key())
                    self.action_runner.run(timeout_event.key())

        log.info("tabletap stopped.")

    def _handle_signal(self, signum, frame):
        log.info("Received signal %s, shutting down...", signum)
        self._running = False
