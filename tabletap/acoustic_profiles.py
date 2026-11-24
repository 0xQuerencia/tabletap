import hashlib
import json
import math
import re

from .mic import list_input_devices

FIELDS = ("noise_floor_db", "work_peak_db", "slam_peak_db", "threshold_db")


def device_identity(cfg: dict, devices=None) -> str:
    devices = list_input_devices() if devices is None else devices
    audio = cfg.get("audio", {})
    filt = cfg.get("filter", {})
    index = audio.get("device_index")
    chosen = next((d for d in devices if (d["default"] if index is None else d["index"] == index)), None)
    if chosen is None:
        raise ValueError("Selected microphone is unavailable")
    descriptor = [chosen["name"], chosen["channels"], chosen["sample_rate"]]
    same = [d for d in devices if [d["name"], d["channels"], d["sample_rate"]] == descriptor]
    # Identical names cannot reliably identify distinct microphones.
    if len(same) != 1:
        descriptor.append(chosen["index"])
    settings = [audio.get("sample_rate", 44100), audio.get("channels", 1),
                audio.get("chunk_size", 1024), filt.get("enabled", True),
                filt.get("low", 20), filt.get("high", 200)]
    return hashlib.sha256(json.dumps([descriptor, settings], ensure_ascii=False).encode()).hexdigest()


def profile_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise ValueError("Profile name must be 1–40 letters, digits, underscores or hyphens")
    return name


def snapshot(cfg: dict) -> dict:
    detection = cfg.get("detection", {})
    if any(type(detection.get(k)) not in (int, float) or not math.isfinite(detection[k]) for k in FIELDS):
        raise ValueError("Complete calibration is required")
    return {k: float(detection[k]) for k in FIELDS}


def remember(cfg: dict, identity: str):
    cal = cfg.setdefault("calibration", {})
    name = profile_name(cal.get("active_name", "default"))
    entry = {"levels": snapshot(cfg), "offset": float(cfg.get("filter", {}).get("sensitivity_offset_db", 0))}
    cal.setdefault("profiles", {}).setdefault(name, {})[identity] = entry
    cal.update(active_name=name, device_key=identity, required=False)


def select(cfg: dict, identity: str, name: str):
    name = profile_name(name)
    cal = cfg.setdefault("calibration", {})
    entry = cal.get("profiles", {}).get(name, {}).get(identity)
    det = cfg.setdefault("detection", {})
    for key in FIELDS:
        det.pop(key, None)
    if entry is not None:
        det.update(entry["levels"])
    cfg.setdefault("filter", {})["sensitivity_offset_db"] = entry.get("offset", 0) if entry else 0
    cal.update(active_name=name, device_key=identity, required=entry is None)
    return entry is not None


def verify_live(cfg: dict):
    cal = cfg.get("calibration", {})
    if cal.get("required"):
        raise ValueError("This microphone/desk profile needs calibration before live actions")
    if cal.get("device_key") and device_identity(cfg) != cal["device_key"]:
        raise ValueError("Microphone or audio settings changed; recalibrate or select a matching profile")


def add_feedback(cfg: dict, label: str, db: float, accepted: bool):
    verify_live(cfg)
    cal = cfg.setdefault("calibration", {})
    if not cal.get("device_key"):
        raise ValueError("Calibrate the current microphone first")
    if label not in ("tap", "noise") or type(db) not in (float, int) or not math.isfinite(db) or not -120 <= db <= 0:
        raise ValueError("Invalid feedback sample")
    data = cal.setdefault("feedback", {}).setdefault(cal["active_name"], {}).setdefault(cal["device_key"], [])
    data.append({"label": label, "db": round(db, 1), "accepted": accepted})
    del data[:-100]
    return len(data)


def fit_feedback(cfg: dict) -> dict:
    verify_live(cfg)
    cal = cfg.get("calibration", {})
    levels = snapshot(cfg)
    data = cal.get("feedback", {}).get(cal.get("active_name"), {}).get(cal.get("device_key"), [])
    missed = sorted(x["db"] for x in data if x["label"] == "tap" and not x["accepted"])
    false = sorted(x["db"] for x in data if x["label"] == "noise" and x["accepted"])
    if len(missed) < 3 and len(false) < 3:
        raise ValueError("Label at least 3 missed taps or 3 false detections before fitting")
    floor = max(levels["work_peak_db"] + 4, levels["noise_floor_db"] + 6)
    ceiling = levels["slam_peak_db"] - 2
    if len(false) >= 3:
        floor = max(floor, false[-1] + 3)
    if len(missed) >= 3:
        ceiling = min(ceiling, missed[max(0, len(missed)//5)] - 1)
    if floor > ceiling:
        raise ValueError("Labeled taps and work noise overlap; recalibrate or move the microphone")
    old = levels["threshold_db"]
    proposed = max(floor, min(ceiling, old))
    if abs(proposed - old) < .05:
        raise ValueError("No safe threshold improvement found")
    return {**levels, "threshold_db": round(proposed, 1)}


def apply_feedback(cfg: dict):
    levels = fit_feedback(cfg)
    cal = cfg["calibration"]
    cal["previous"] = {"name":cal["active_name"], "device_key":cal["device_key"], "levels":snapshot(cfg),
                       "offset":cfg.get("filter", {}).get("sensitivity_offset_db", 0)}
    cfg["detection"].update(levels)
    cfg.setdefault("filter", {})["sensitivity_offset_db"] = 0
    remember(cfg, cal["device_key"])
    return levels["threshold_db"]


def rollback(cfg: dict):
    verify_live(cfg)
    cal = cfg.get("calibration", {})
    previous = cal.get("previous")
    if not previous or previous["name"] != cal.get("active_name") or previous["device_key"] != cal.get("device_key"):
        raise ValueError("No rollback point for this microphone and desk")
    cfg["detection"].update(previous["levels"])
    cfg.setdefault("filter", {})["sensitivity_offset_db"] = previous["offset"]
    remember(cfg, cal["device_key"])
    del cal["previous"]
