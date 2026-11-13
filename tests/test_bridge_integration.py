"""Simulated end-to-end tap detection through the real bridge loop.

Fake microphone chunks preserve the same sequencing as PyAudio reads while
the output and action-dispatch paths remain production code.
"""
import json
from unittest.mock import patch
from contextlib import ExitStack

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
            "rhythm_window_ms": 800, "enable_four_taps": True, "enable_hold_gestures": False,
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
    with ExitStack() as stack:
        stack.enter_context(patch("tabletap.bridge.MicCapture", FakeMic))
        stack.enter_context(patch("tabletap.bridge.load_config", return_value=cfg))
        stack.enter_context(patch("tabletap.bridge.rms_db", side_effect=lambda _: current["db"]))
        stack.enter_context(patch("tabletap.bridge.time.monotonic", side_effect=lambda: current["now"]))
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


def test_python_live_deadline_is_enforced_even_without_tui(capsys):
    """A frozen UI cannot leave its Python action bridge armed forever."""
    import numpy as np
    from tabletap.bridge import run_bridge

    clock = {"now": 0.0}

    class SteadyMic:
        def __init__(self, *_a):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def read_filtered(self):
            clock["now"] += 0.025
            samples = np.zeros(1024, dtype=np.int16)
            return samples, samples

    config = {"audio": {}, "filter": {}, "detection": {}, "actions": {}}
    with patch("tabletap.bridge.load_config", return_value=config), \
         patch("tabletap.bridge.MicCapture", SteadyMic), \
         patch("tabletap.bridge.PIDLock") as lock, \
         patch("tabletap.bridge.rms_db", return_value=-70.0), \
         patch("tabletap.bridge.time.monotonic", side_effect=lambda: clock["now"]):
        lock.return_value.acquire.return_value = True
        status = run_bridge(config_path="/fake", dry_run=False, live_seconds=0.05)
    assert status == 0
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["type"] for item in emitted][-2:] == ["live_expired", "stopped"]
    assert not any(item["type"] == "gesture" for item in emitted)


def test_invalid_live_expiry_cannot_arm_bridge(capsys):
    from tabletap.bridge import run_bridge
    config = {"audio": {}, "filter": {}, "detection": {}, "actions": {}}
    with patch("tabletap.bridge.load_config", return_value=config):
        assert run_bridge(config_path="/fake", live_seconds=601) == 2
        assert run_bridge(config_path="/fake", live_seconds=10, dry_run=True) == 2
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(item["type"] == "error" for item in emitted)
