import numpy as np
import pytest
from tabletap.filter import make_bandpass, apply_bandpass, AdaptiveThreshold, OnsetDetector


def test_bandpass_maintains_state_across_chunks():
    fs = 44100
    sos = make_bandpass(20, 200, fs)
    
    t = np.linspace(0, 1, fs)
    signal = np.sin(2 * np.pi * 100 * t)
    
    chunk_size = 1024
    chunks = [signal[i:i+chunk_size] for i in range(0, len(signal), chunk_size)]
    
    filtered_chunks = [apply_bandpass(chunk, sos) for chunk in chunks]
    
    assert len(filtered_chunks) == len(chunks)
    for fc in filtered_chunks:
        assert fc.dtype == np.float64
        assert not np.any(np.isnan(fc))


def test_bandpass_multichannel():
    fs = 44100
    sos = make_bandpass(20, 200, fs)
    
    stereo = np.random.randint(-32768, 32767, size=(1024, 2), dtype=np.int16)
    filtered = apply_bandpass(stereo, sos)
    
    assert filtered.shape == stereo.shape
    assert filtered.dtype == np.float64


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


def test_onset_detector_detects_energy_spike():
    detector = OnsetDetector(min_gap_ms=80)
    
    assert not detector.feed(-40.0, 0.0)
    assert not detector.feed(-38.0, 0.05)
    
    assert detector.feed(-30.0, 0.1)


def test_onset_detector_respects_min_gap():
    detector = OnsetDetector(min_gap_ms=100)
    
    detector.feed(-30.0, 0.0)
    detector.feed(-25.0, 0.02)
    detector.feed(-20.0, 0.04)
    
    assert not detector.feed(-15.0, 0.05)


def test_onset_detector_allows_onset_after_gap():
    detector = OnsetDetector(min_gap_ms=100)
    
    detector.feed(-40.0, 0.0)
    detector.feed(-38.0, 0.02)
    
    result = detector.feed(-30.0, 0.2)
    assert result


def test_quiet_energy_rise_does_not_consume_tap_debounce():
    detector = OnsetDetector(min_gap_ms=150)
    assert not detector.feed(-60.0, 0.0, active=False)
    assert not detector.feed(-54.0, 0.10, active=False)
    assert detector.feed(-20.0, 0.20, active=True)
    assert not detector.feed(-62.0, 0.35, active=False)
    # This spurious 5 dB quiet rise must not block the next tap at 0.73.
    assert not detector.feed(-57.0, 0.66, active=False)
    assert detector.feed(-20.0, 0.73, active=True)
