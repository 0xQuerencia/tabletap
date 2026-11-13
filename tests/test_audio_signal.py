"""Signal-level integration tests using actual bandpass and RMS processing.

Only PortAudio hardware reads are replaced. The rest of the audio pipeline,
onset detector, gesture window and bridge remain production code.
"""
import json
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np

from tabletap.bridge import run_bridge
from tabletap.filter import StatefulBandpass, make_bandpass
from tabletap.mic import MicDisconnected


SAMPLE_RATE = 44100
CHUNK = 1024


def synthesize(taps, seconds=2.3):
    rng = np.random.default_rng(27)
    total = int(seconds * SAMPLE_RATE)
    audio = rng.normal(0, 75, total)
    for onset in taps:
        start = int(onset * SAMPLE_RATE)
        duration = int(0.045 * SAMPLE_RATE)
        time = np.arange(duration) / SAMPLE_RATE
        knock = 18000 * np.sin(2 * np.pi * 185 * time) * np.exp(-time * 35)
        audio[start:start + duration] += knock
    return np.clip(audio, -32768, 32767).astype(np.int16)


def stream_audio(samples, capsys):
    clock = {"now": 0.0}
    class FakeMic:
        def __init__(self, cfg, filter_cfg):
            self.cursor = 0
            self.bandpass = StatefulBandpass(make_bandpass(50, 800, SAMPLE_RATE))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read_filtered(self):
            if self.cursor + CHUNK > len(samples):
                raise MicDisconnected("synthetic stream completed")
            frame = samples[self.cursor:self.cursor + CHUNK]
            self.cursor += CHUNK
            clock["now"] = self.cursor / SAMPLE_RATE
            return frame, self.bandpass.process(frame)
    cfg = {
        "audio": {"sample_rate": SAMPLE_RATE, "chunk_size": CHUNK},
        "filter": {"enabled": True, "low": 50, "high": 800,
                   "noise_alpha": 0.05, "peak_alpha": 0.1, "snr_gate_db": 6.0},
        "detection": {"min_gap_ms": 150, "rhythm_window_ms": 800,
                      "noise_floor_db": -52.0, "slam_peak_db": -14.0,
                      "enable_four_taps": True, "enable_hold_gestures": False},
        "actions": {
            "single": {"type": "exec", "value": "true"},
            "double": {"type": "exec", "value": "true"},
            "triple": {"type": "exec", "value": "true"},
            "quadruple": {"type": "exec", "value": "true"},
        },
    }
    with ExitStack() as stack:
        stack.enter_context(patch("tabletap.bridge.MicCapture", FakeMic))
        stack.enter_context(patch("tabletap.bridge.load_config", return_value=cfg))
        stack.enter_context(patch("tabletap.bridge.time.monotonic", side_effect=lambda: clock["now"]))
        run_bridge(config_path="/synthetic", dry_run=True)
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_real_waveform_triple_tap(capsys):
    result = stream_audio(synthesize([0.2, 0.47, 0.73]), capsys)
    events = [v for v in result if v["type"] == "gesture"]
    assert [event["pattern"] for event in events] == ["triple"], result


def test_real_waveform_background_noise_only(capsys):
    result = stream_audio(synthesize([]), capsys)
    assert not [v for v in result if v["type"] == "gesture"]


def test_real_waveform_double_tap(capsys):
    result = stream_audio(synthesize([0.2, 0.52]), capsys)
    events = [v for v in result if v["type"] == "gesture"]
    assert [event["pattern"] for event in events] == ["double"], result


def test_real_waveform_four_taps(capsys):
    result = stream_audio(synthesize([0.2, 0.4, 0.6, 0.8]), capsys)
    events = [v for v in result if v["type"] == "gesture"]
    assert [event["pattern"] for event in events] == ["quadruple"], result


def test_continuous_loud_voice_like_tone_is_not_a_tap(capsys):
    # A long resonant tone can cross the volume threshold and look like a tap
    # to raw energy-only detectors, but it is not a short impulse.
    signal = synthesize([], seconds=2.3)
    start, stop = int(.25 * SAMPLE_RATE), int(1.10 * SAMPLE_RATE)
    ts = np.arange(stop - start) / SAMPLE_RATE
    drone = (10000 * np.sin(2 * np.pi * 185 * ts)).astype(np.int16)
    signal[start:stop] = drone
    data = stream_audio(signal, capsys)
    assert not [event for event in data if event["type"] == "gesture"]


def test_typing_burst_is_not_a_four_tap(capsys):
    # Seven impacts in ordinary typing cadence must be rejected as a burst,
    # not saturated to the old dangerous quadruple/Alt+Tab mapping.
    data = stream_audio(synthesize([.20, .36, .52, .68, .84, 1.00, 1.16],
                                   seconds=2.8), capsys)
    assert not [event for event in data if event["type"] == "gesture"], data


def test_bright_short_speech_bursts_not_misdetected_as_taps(capsys):
    audio = synthesize([], seconds=2.5).astype(np.float64)
    # Multiple short voice-like syllables with fundamental and upper harmonics.
    # A sharp envelope can fool energy-only detectors even when no desk is hit.
    for at in (0.22, 0.48, 0.75):
        start = round(at * SAMPLE_RATE)
        length = round(0.10 * SAMPLE_RATE)
        t = np.arange(length) / SAMPLE_RATE
        envelope = np.minimum(1.0, t / .004) * np.minimum(1.0, (.10 - t) / .004)
        voice = envelope * (
            7500 * np.sin(2 * np.pi * 190 * t)
            + 5500 * np.sin(2 * np.pi * 1900 * t)
        )
        audio[start:start + length] += voice
    received = stream_audio(np.clip(audio, -32768, 32767).astype(np.int16), capsys)
    assert not [v for v in received if v["type"] == "gesture"], received
