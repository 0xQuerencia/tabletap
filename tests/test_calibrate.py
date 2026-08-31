"""Tests for calibrate module."""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from tabletap.calibrate import calibrate


class TestCalibrate:
    """Test calibration functionality."""
    
    def test_calibrate_returns_valid_dict(self, mock_pyaudio, sample_config):
        """Test calibrate returns valid dict with expected keys."""
        with patch('pyaudio.PyAudio', return_value=mock_pyaudio):
            with patch('builtins.input', return_value=''):
                with patch('tabletap.mic.MicCapture') as mock_mic_class:
                    mock_mic = MagicMock()
                    
                    # Return quiet noise for baseline
                    quiet_data = np.random.randn(1024).astype(np.float32) * 0.01
                    # Return loud data for slam
                    loud_data = np.random.randn(1024).astype(np.float32) * 0.5
                    
                    mock_mic.read.side_effect = [quiet_data] * 50 + [loud_data] * 20
                    mock_mic.__enter__.return_value = mock_mic
                    mock_mic.__exit__.return_value = False
                    mock_mic_class.return_value = mock_mic
                    
                    result = calibrate(sample_config, duration_sec=3)
        
        # Check structure
        assert isinstance(result, dict)
        assert 'noise_floor_db' in result
        assert 'slam_peak_db' in result
        assert 'threshold_db' in result
    
    def test_calibrate_with_margin(self, mock_pyaudio, sample_config):
        """Test calibrate with custom margin."""
        with patch('pyaudio.PyAudio', return_value=mock_pyaudio):
            with patch('builtins.input', return_value=''):
                with patch('tabletap.mic.MicCapture') as mock_mic_class:
                    mock_mic = MagicMock()
                    
                    # Return consistent data
                    test_data = np.random.randn(1024).astype(np.float32) * 0.1
                    mock_mic.read.side_effect = [test_data] * 70
                    mock_mic.__enter__.return_value = mock_mic
                    mock_mic.__exit__.return_value = False
                    mock_mic_class.return_value = mock_mic
                    
                    result = calibrate(sample_config, duration_sec=3, margin_db=10.0)
        
        # Check that result has all required keys and margin was applied
        assert isinstance(result, dict)
        assert 'noise_floor_db' in result
        assert 'slam_peak_db' in result
        assert 'threshold_db' in result
        # Threshold should be between noise floor and slam peak
        assert result['noise_floor_db'] <= result['threshold_db'] <= result['slam_peak_db'] + 10
