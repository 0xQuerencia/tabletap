import pytest
from pathlib import Path
import yaml
from tabletap.config import load_config, init_config, save_calibration


def test_load_config_with_valid_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_data = {
        "mic": {"sample_rate": 44100},
        "detection": {"threshold_db": -30},
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(config_data, f)
    
    cfg = load_config(config_file)
    
    assert cfg["mic"]["sample_rate"] == 44100
    assert cfg["detection"]["threshold_db"] == -30


def test_load_config_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")


def test_init_config_creates_file(tmp_path):
    dest = tmp_path / "tabletap" / "config.yaml"
    
    created_path = init_config(dest)
    
    assert created_path.exists()
    assert created_path == dest


def test_init_config_creates_parent_dirs(tmp_path):
    dest = tmp_path / "nested" / "dir" / "config.yaml"
    
    created_path = init_config(dest)
    
    assert created_path.parent.exists()
    assert created_path.exists()


def test_init_config_preserves_existing_file(tmp_path):
    config_file = tmp_path / "config.yaml"
    original_content = {"test": "data"}
    with open(config_file, "w") as f:
        yaml.safe_dump(original_content, f)
    
    returned_path = init_config(config_file)
    
    with open(returned_path) as f:
        content = yaml.safe_load(f)
    assert content == original_content


def test_save_calibration(tmp_path):
    config_file = tmp_path / "config.yaml"
    cfg = {"mic": {"sample_rate": 44100}, "detection": {}}
    calibration = {
        "noise_floor_db": -45.0,
        "slam_peak_db": -20.0,
        "threshold_db": -35.0,
    }
    
    saved_path = save_calibration(cfg, calibration, config_file)
    
    assert saved_path.exists()
    with open(saved_path) as f:
        loaded = yaml.safe_load(f)
    
    assert loaded["detection"]["noise_floor_db"] == -45.0
    assert loaded["detection"]["slam_peak_db"] == -20.0
    assert loaded["detection"]["threshold_db"] == -35.0


def test_save_calibration_creates_detection_section(tmp_path):
    config_file = tmp_path / "config.yaml"
    cfg = {"mic": {"sample_rate": 44100}}
    calibration = {
        "noise_floor_db": -45.0,
        "slam_peak_db": -20.0,
        "threshold_db": -35.0,
    }
    
    save_calibration(cfg, calibration, config_file)
    
    with open(config_file) as f:
        loaded = yaml.safe_load(f)
    
    assert "detection" in loaded
    assert "noise_floor_db" in loaded["detection"]
