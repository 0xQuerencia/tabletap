import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from tabletap.mic import rms_db, is_spike, MicDisconnected


def test_rms_db_smooth_curve():
    chunk1 = np.array([1000], dtype=np.int16)
    chunk2 = np.array([0], dtype=np.int16)
    
    db1 = rms_db(chunk1)
    db2 = rms_db(chunk2)
    
    assert db1 > -120.0
    assert db2 <= -100.0


def test_rms_db_no_discontinuity_at_rms_one():
    chunk_below = np.array([0.5], dtype=np.float64)
    chunk_at = np.array([1.0], dtype=np.float64)
    chunk_above = np.array([2.0], dtype=np.float64)
    
    db_below = rms_db(chunk_below)
    db_at = rms_db(chunk_at)
    db_above = rms_db(chunk_above)
    
    assert db_below <= -90.0
    assert db_at <= -90.0
    assert db_above > -90.0


def test_rms_db_with_typical_audio():
    chunk = np.random.randint(-5000, 5000, size=1024, dtype=np.int16)
    
    db = rms_db(chunk)
    
    assert -80.0 < db < 0.0


def test_is_spike():
    loud_chunk = np.full(1024, 10000, dtype=np.int16)
    quiet_chunk = np.full(1024, 100, dtype=np.int16)
    
    assert is_spike(loud_chunk, -30.0)
    assert not is_spike(quiet_chunk, -30.0)


@patch("tabletap.mic.pyaudio")
def test_mic_capture_initialization(mock_pyaudio):
    mock_pa = MagicMock()
    mock_pyaudio.PyAudio.return_value = mock_pa
    
    from tabletap.mic import MicCapture
    
    cfg = {
        "sample_rate": 44100,
        "channels": 1,
        "chunk_size": 1024,
    }
    
    mic = MicCapture(cfg)
    
    mock_pa.open.assert_called_once()
    call_kwargs = mock_pa.open.call_args[1]
    assert call_kwargs["rate"] == 44100
    assert call_kwargs["channels"] == 1


@patch("tabletap.mic.pyaudio")
def test_mic_capture_read_chunk(mock_pyaudio):
    mock_pa = MagicMock()
    mock_stream = MagicMock()
    mock_pyaudio.PyAudio.return_value = mock_pa
    mock_pa.open.return_value = mock_stream
    
    raw_data = np.random.randint(-32768, 32767, size=1024, dtype=np.int16).tobytes()
    mock_stream.read.return_value = raw_data
    
    from tabletap.mic import MicCapture
    
    cfg = {"sample_rate": 44100, "channels": 1, "chunk_size": 1024}
    mic = MicCapture(cfg)
    
    chunk = mic.read_chunk()
    
    assert chunk.shape == (1024,)
    assert chunk.dtype == np.int16


@patch("tabletap.mic.pyaudio")
def test_mic_capture_close(mock_pyaudio):
    mock_pa = MagicMock()
    mock_stream = MagicMock()
    mock_pyaudio.PyAudio.return_value = mock_pa
    mock_pa.open.return_value = mock_stream
    
    from tabletap.mic import MicCapture
    
    cfg = {"sample_rate": 44100, "channels": 1, "chunk_size": 1024}
    mic = MicCapture(cfg)
    mic.close()
    
    mock_stream.stop_stream.assert_called_once()
    mock_stream.close.assert_called_once()
    mock_pa.terminate.assert_called_once()


@patch("tabletap.mic.pyaudio")
def test_mic_capture_context_manager(mock_pyaudio):
    mock_pa = MagicMock()
    mock_stream = MagicMock()
    mock_pyaudio.PyAudio.return_value = mock_pa
    mock_pa.open.return_value = mock_stream
    
    from tabletap.mic import MicCapture
    
    cfg = {"sample_rate": 44100, "channels": 1, "chunk_size": 1024}
    
    with MicCapture(cfg) as mic:
        pass
    
    mock_stream.stop_stream.assert_called_once()
    mock_stream.close.assert_called_once()
    mock_pa.terminate.assert_called_once()
