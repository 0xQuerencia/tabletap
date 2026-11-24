import json
import pytest
from tabletap.profile_packs import export_pack, read_pack, import_pack, validate_pack
from tabletap.config import load_config


def test_profile_roundtrip_never_overwrites_and_requires_trust(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text("actions: {}\n")
    file = tmp_path / "pack.json"
    export_pack({"actions":{"study":{1:{"type":"exec","value":"echo hello"}}}}, "study", file)
    with pytest.raises(FileExistsError):
        export_pack({"actions":{"study":{}}}, "study", file)
    pack = read_pack(file)
    with pytest.raises(ValueError,match="trust"):
        import_pack(pack, cfg)
    assert import_pack(pack, cfg, trust=True) == "study"
    assert load_config(cfg)["actions"]["study"][1]["value"] == "echo hello"
    with pytest.raises(ValueError,match="exists"):
        import_pack(pack, cfg, trust=True)


def test_invalid_profiles_are_rejected():
    for action in [{"type":"launcher","value":"other"}, {"type":"workflow","value":"[]"},
                   {"type":"builtin","value":"missing"}, {"type":"exec","value":"a\nb"}]:
        with pytest.raises(ValueError):
            validate_pack({"format":"tabletap-profile-v1","name":"study","actions":{"1":action}})
