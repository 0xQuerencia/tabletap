import os
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML

log = logging.getLogger("tabletap")

DEFAULT_PATHS = [
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tabletap" / "config.yaml",
    Path(__file__).parent / "default_config.yaml",
    Path(__file__).parent.parent / "config.yaml",
]


def validate_config(cfg: dict) -> list[str]:
    warnings = []
    
    if "audio" in cfg:
        sr = cfg["audio"].get("sample_rate", 44100)
        if sr < 8000 or sr > 96000:
            warnings.append(f"sample_rate {sr} outside valid range 8000-96000")
        
        chunk_size = cfg["audio"].get("chunk_size", 1024)
        if chunk_size < 128 or chunk_size > 8192:
            warnings.append(f"chunk_size {chunk_size} outside typical range 128-8192")
    
    if "filter" in cfg:
        low = cfg["filter"].get("low", 20)
        high = cfg["filter"].get("high", 200)
        if low >= high:
            warnings.append(f"filter low {low} >= high {high}")
        if low < 10:
            warnings.append(f"filter low {low} Hz may be too low (typical minimum: 10 Hz)")
        if high > 20000:
            warnings.append(f"filter high {high} Hz exceeds human hearing range")
        
        noise_alpha = cfg["filter"].get("noise_alpha", 0.05)
        if noise_alpha < 0 or noise_alpha > 1:
            warnings.append(f"noise_alpha {noise_alpha} outside valid range 0-1")
        
        peak_alpha = cfg["filter"].get("peak_alpha", 0.1)
        if peak_alpha < 0 or peak_alpha > 1:
            warnings.append(f"peak_alpha {peak_alpha} outside valid range 0-1")
    
    if "detection" in cfg:
        min_gap = cfg["detection"].get("min_gap_ms", 150)
        if min_gap < 50 or min_gap > 1000:
            warnings.append(f"min_gap_ms {min_gap} outside valid range 50-1000")
        
        rhythm_window = cfg["detection"].get("rhythm_window_ms", 800)
        if rhythm_window < 200 or rhythm_window > 3000:
            warnings.append(f"rhythm_window_ms {rhythm_window} outside typical range 200-3000")
        
        long_press = cfg["detection"].get("long_press_ms", 500)
        if long_press < 100 or long_press > 5000:
            warnings.append(f"long_press_ms {long_press} outside typical range 100-5000")
    
    return warnings


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path:
        p = Path(path)
    else:
        p = None
        for candidate in DEFAULT_PATHS:
            if candidate.exists():
                p = candidate
                break
    if p is None or not p.exists():
        raise FileNotFoundError(
            f"No config found. Tried: {DEFAULT_PATHS}\n"
            "Run `tabletap init` to create one."
        )
    with open(p) as f:
        cfg = yaml.safe_load(f)
    
    warnings = validate_config(cfg)
    for warning in warnings:
        log.warning(f"Config validation: {warning}")
    
    return cfg


def init_config(dest: str | Path | None = None) -> Path:
    dest = Path(dest or DEFAULT_PATHS[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    import shutil
    src = Path(__file__).parent / "default_config.yaml"
    shutil.copy2(src, dest)
    return dest


def save_calibration(cfg: dict, calibration: dict, path: Path | None = None) -> Path:
    """Persist calibration without deleting action comments or risking a partial write.

    The app's UI can edit the same YAML. Always reread the latest file instead
    of dumping an old in-memory configuration over changes made by the user.
    """
    path = Path(path) if path is not None else DEFAULT_PATHS[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml_editor = YAML()
    yaml_editor.preserve_quotes = True
    if path.exists():
        with path.open("r", encoding="utf-8") as source:
            document = yaml_editor.load(source)
        if not isinstance(document, dict):
            raise ValueError("Cannot save calibration: config YAML must be a mapping")
    else:
        document = dict(cfg)

    detection = document.setdefault("detection", {})
    if not isinstance(detection, dict):
        raise ValueError("Cannot save calibration: detection must be a mapping")
    for name in ("noise_floor_db", "slam_peak_db", "threshold_db"):
        detection[name] = float(calibration[name])

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=".config-", suffix=".tmp",
            encoding="utf-8", delete=False,
        ) as output:
            temporary_path = Path(output.name)
            yaml_editor.dump(document, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_path, 0o600)
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    # Existing callers can continue using their in-memory calibrated values.
    cfg.setdefault("detection", {}).update({
        key: float(calibration[key])
        for key in ("noise_floor_db", "slam_peak_db", "threshold_db")
    })
    return path
