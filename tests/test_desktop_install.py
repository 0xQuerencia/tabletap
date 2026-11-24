from tabletap.desktop_install import install_launcher, set_autostart, autostart_path, _exec
import pytest


def test_user_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = install_launcher("/home/user/my env/bin/python")
    assert "Exec=\"/home/user/my env/bin/python\" -m tabletap desktop" in path.read_text()
    assert "Terminal=false" in path.read_text()
    assert (tmp_path / "icons/hicolor/scalable/apps/art.querencia.tabletap.svg").exists()


def test_autostart_is_preview_only(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    set_autostart(True, "/tmp/env/bin/python")
    assert "start --preview" in autostart_path().read_text()
    set_autostart(False)
    assert not autostart_path().exists()


def test_launcher_rejects_relative_and_newline():
    for value in ("python", "/tmp/test\nExec=other"):
        with pytest.raises(ValueError):
            _exec(value)
