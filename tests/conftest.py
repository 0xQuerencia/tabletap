"""Shared test fixtures and mocks."""
import pytest
import numpy as np
from unittest.mock import MagicMock, Mock, patch
import yaml
import tempfile
import os


@pytest.fixture
def mock_pyaudio():
    """Mock PyAudio for testing without audio hardware."""
    with patch('pyaudio.PyAudio') as mock_pa:
        mock_instance = MagicMock()
        mock_pa.return_value = mock_instance
        
        # Mock stream
        mock_stream = MagicMock()
        mock_stream.read.return_value = (np.random.randn(1024) * 0.1).astype(np.float32).tobytes()
        mock_stream.is_active.return_value = True
        mock_instance.open.return_value = mock_stream
        
        # Mock device info
        mock_instance.get_default_input_device_info.return_value = {
            'index': 0,
            'name': 'Mock Microphone',
            'defaultSampleRate': 44100
        }
        mock_instance.get_device_count.return_value = 1
        mock_instance.get_device_info_by_index.return_value = {
            'index': 0,
            'name': 'Mock Microphone',
            'maxInputChannels': 1,
            'defaultSampleRate': 44100
        }
        
        yield mock_instance


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for testing commands."""
    with patch('subprocess.Popen') as mock_popen:
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        yield mock_popen


@pytest.fixture
def mock_pynput():
    """Mock pynput keyboard for testing key presses."""
    with patch('pynput.keyboard.Controller') as mock_kb:
        mock_instance = MagicMock()
        mock_kb.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        'audio': {
            'sample_rate': 44100,
            'chunk_size': 1024,
            'device_index': None
        },
        'filter': {
            'lowcut': 50,
            'highcut': 300,
            'order': 4
        },
        'detection': {
            'onset_threshold': 3.0,
            'adaptive_window': 100,
            'spike_min_gap_ms': 50
        },
        'patterns': {
            'double_tap_window_ms': 800,
            'triple_tap_window_ms': 800,
            'long_press_spike_window_ms': 500,
            'long_press_min_spikes': 3,
            'medium_hold_duration_s': 2.0,
            'hold_timeout_s': 2.0,
            'silence_debounce_ms': 100
        },
        'actions': {
            'single': {'type': 'key', 'keys': ['space']},
            'double': {'type': 'key', 'keys': ['ctrl', 'c']},
            'triple': {'type': 'key', 'keys': ['ctrl', 'v']},
            'long': {'type': 'launch', 'command': 'spotify'},
            'medium': {'type': 'key', 'keys': ['escape']}
        },
        'calibration': {
            'noise_floor_db': -40.0,
            'slam_peak_db': -10.0
        }
    }


@pytest.fixture
def temp_config_file(sample_config):
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(sample_config, f)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def sample_audio_chunk():
    """Generate a sample audio chunk (1024 samples at 44.1kHz)."""
    return np.random.randn(1024).astype(np.float32)


@pytest.fixture
def spike_audio_chunk():
    """Generate an audio chunk with a clear spike."""
    chunk = np.random.randn(1024).astype(np.float32) * 0.01  # Low noise
    chunk[512:520] = 0.5  # Insert spike
    return chunk
