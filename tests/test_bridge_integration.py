"""Simulated end-to-end tap detection through the real bridge loop.

Fake microphone chunks preserve the same sequencing as PyAudio reads while
the output and action-dispatch paths remain production code.
"""
import json
from unittest.mock import patch

import numpy as np

from tabletap.bridge import run_bridge
from tabletap.mic import MicDisconnected


def make_trace(pattern: list[float]):
    # Every pattern entry is the time of one sharp audio impact (seconds).
    # The silence between impacts matters for rhythmic grouping.
    frames = [(0.00, -58.0), (0.11, -57.0)]
    for at in pattern:
        frames.extend([
            (at - 0.04, -58.0),
            (at, -12.0),
            (at + 0.03, -15.0),
            (at + 0.17, -57.0),
        ])
    frames.extend([(pattern[0] + 0.85, -58.0), (pattern[0] + 1.04, -58.0)])
    return sorted(frames, key=lambda x: x[0])


def simulate(trace, capsys, category=None):
    current = {"db": -60.0, "now": 0.0}

    class FakeMic:
        def __init__(self, cfg, filter_cfg):
            self.frames = iter(trace)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read_filtered(self):
            try:
                at, db = next(self.frames)
            except StopIteration:
                raise MicDisconnected("synthetic input finished")
            current["now"] = at
            current["db"] = db
            zero = np.zeros(1024, dtype=np.int16)
            return zero, zero

    cfg = {
        "audio": {"sample_rate": 44100, "chunk_size": 1024},
        "filter": {"enabled": False, "adaptive": True, "snr_gate_db": 6.0},
        "detection": {
            "threshold_db": -30.0, "noise_floor_db": -55.0,
            "slam_peak_db": -12.0, "min_gap_ms": 150,
            "rhythm_window_ms": 800, "enable_hold_gestures": False,
        },
        "actions": {
            "single": {"type": "exec", "value": "echo one"},
            "double": {"type": "exec", "value": "echo two"},
            "triple": {"type": "exec", "value": "echo three"},
            "quadruple": {"type": "exec", "value": "echo four"},
            "media": {
                1: {"type": "exec", "value": "echo media-one"},
                4: {"type": "exec", "value": "echo media-four"},
            },
        },
    }
    with patch("tabletap.bridge.MicCapture", FakeMic),          patch("tabletap.bridge.load_config", return_value=cfg),          patch("tabletap.bridge.rms_db", side_effect=lambda _: current["db"]),          patch("tabletap.bridge.time.monotonic", side_effect=lambda: current["now"]):
        run_bridge(config_path="/synthetic", category=category, dry_run=True)
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_single_tap_end_to_end(capsys):
    data = simulate(make_trace([0.2]), capsys)
    matches = [v for v in data if v["type"] == "gesture"]
    assert len(matches) == 1, data
    assert matches[0]["pattern"] == "single"
    assert matches[0]["dispatched"] is False


def test_double_tap_end_to_end(capsys):
    data = simulate(make_trace([0.2, 0.5]), capsys)
    matches = [v for v in data if v["type"] == "gesture"]
    assert [m["pattern"] for m in matches] == ["double"], data


def test_triple_tap_end_to_end(capsys):
    data = simulate(make_trace([0.2, 0.44, 0.68]), capsys)
    matches = [v for v in data if v["type"] == "gesture"]
    assert [m["pattern"] for m in matches] == ["triple"], data


def test_four_taps_reach_fourth_media_mapping(capsys):
    data = simulate(make_trace([0.2, 0.38, 0.56, 0.74]), capsys, category="media")
    matches = [v for v in data if v["type"] == "gesture"]
    assert [m["pattern"] for m in matches] == ["quadruple"], data
    assert matches[0]["action"] == "echo media-four"


def test_background_noise_does_not_dispatch(capsys):
    data = simulate([(i * 0.08, -65.0) for i in range(20)], capsys)
    assert not [v for v in data if v["type"] == "gesture"]
