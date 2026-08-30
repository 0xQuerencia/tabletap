import signal
import sys
import time
import logging

from .mic import MicCapture, is_spike
from .pattern import PatternDetector, TapPattern
from .action import ActionRunner

log = logging.getLogger("tabletap")


class Daemon:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.audio_cfg = cfg.get("audio", {})
        self.detect_cfg = cfg.get("detection", {})
        self.action_runner = ActionRunner(cfg.get("actions", {}))
        self.pattern_detector = PatternDetector(
            min_gap_ms=self.detect_cfg.get("min_gap_ms", 100),
            rhythm_window_ms=self.detect_cfg.get("rhythm_window_ms", 800),
            long_press_ms=self.detect_cfg.get("long_press_ms", 500),
        )
        self.threshold_db = self.detect_cfg.get("threshold_db", -30)
        self._running = False

    def run(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        log.info("tabletap starting (threshold: %.1f dB)", self.threshold_db)

        with MicCapture(self.audio_cfg) as mic:
            log.info("Mic opened. Tap the table!")
            while self._running:
                chunk = mic.read_chunk()

                if is_spike(chunk, self.threshold_db):
                    event = self.pattern_detector.feed()
                    if event:
                        log.info("TAP -> %s", event.key())
                        self.action_runner.run(event.key())
                else:
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
