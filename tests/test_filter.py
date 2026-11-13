import numpy as np
from tabletap.filter import make_bandpass, StatefulBandpass, AdaptiveThreshold


def test_bandpass_preserves_history_across_chunks():
    fs = 44100
    samples = np.sin(2 * np.pi * 100 * np.arange(4096) / fs)
    filter = StatefulBandpass(make_bandpass(20, 200, fs))
    pieces = [filter.process(chunk) for chunk in np.split(samples, 4)]
    filtered = np.concatenate(pieces)
    assert np.isfinite(filtered).all()
    assert filtered.shape == samples.shape
    assert np.abs(filtered[-1024:]).mean() > 0.1


def test_stateful_bandpass_handles_stereo():
    filter = StatefulBandpass(make_bandpass(20, 200, 44100), channels=2)
    result = filter.process(np.ones((1024, 2), dtype=np.float64))
    assert result.shape == (1024, 2)
    assert np.isfinite(result).all()


def test_adaptive_threshold_convergence_on_noise():
    threshold = AdaptiveThreshold(
        initial_threshold_db=-30,
        noise_alpha=0.1,
        peak_alpha=0.1,
        snr_gate_db=6.0,
    )
    
    noise_db = -40.0
    for _ in range(50):
        threshold.update(noise_db, is_spike=False)
    
    state = threshold.get_state()
    assert abs(state["noise_floor_db"] - noise_db) < 2.0


def test_adaptive_threshold_convergence_on_spikes():
    threshold = AdaptiveThreshold(
        initial_threshold_db=-30,
        noise_alpha=0.05,
        peak_alpha=0.1,
        snr_gate_db=6.0,
    )
    
    spike_db = -20.0
    for _ in range(20):
        threshold.update(spike_db, is_spike=True)
    
    state = threshold.get_state()
    assert abs(state["peak_db"] - spike_db) < 3.0


def test_adaptive_threshold_respects_snr_gate():
    threshold = AdaptiveThreshold(
        initial_threshold_db=-30,
        noise_alpha=0.1,
        peak_alpha=0.1,
        snr_gate_db=10.0,
    )
    
    threshold.noise_floor_db = -40.0
    threshold.peak_db = -35.0
    threshold.update(-40.0, is_spike=False)
    
    state = threshold.get_state()
    assert state["threshold_db"] >= state["noise_floor_db"] + 10.0


def test_adaptive_threshold_respects_min_threshold():
    threshold = AdaptiveThreshold(
        initial_threshold_db=-30,
        min_threshold_db=-50,
    )
    
    threshold.noise_floor_db = -70.0
    threshold.update(-70.0, is_spike=False)
    
    assert threshold.threshold_db >= -50.0


def test_adaptive_threshold_is_above():
    threshold = AdaptiveThreshold(initial_threshold_db=-30)
    
    assert threshold.is_above(-20.0)
    assert not threshold.is_above(-40.0)


def test_adaptive_threshold_calibration():
    threshold = AdaptiveThreshold()
    
    threshold.set_from_calibration(noise_floor_db=-45.0, slam_peak_db=-20.0)
    
    assert threshold.noise_floor_db == -45.0
    assert threshold.peak_db == -20.0
    assert -45.0 < threshold.threshold_db < -20.0


