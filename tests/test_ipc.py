import os
import threading
from unittest.mock import MagicMock, patch

from tabletap.ipc import ControlHub, control_request, watch_events
from tabletap.daemon import run_service


def test_private_socket_status_and_bounded_authorization(tmp_path):
    path = tmp_path / "engine.sock"
    with ControlHub(path) as hub:
        assert path.stat().st_mode & 0o077 == 0
        hub.publish("ready", dry_run=True, category="default", threshold_db=-30)
        assert control_request({"command":"status"}, path)["state"]["dry_run"]
        assert "error" in control_request({"command":"arm","seconds":601}, path)
        assert "error" in control_request({"command":"run","value":"arbitrary"}, path)
        runner = MagicMock()
        hub.set_runner(runner)
        assert control_request({"command":"arm","seconds":5}, path)["accepted"]
        runner.cancel.assert_called_once()
        assert hub.take_request() == {"command":"arm","seconds":5}
        assert not hub.interrupted.is_set()
    assert not path.exists()


def test_watch_has_ready_snapshot_and_live_events(tmp_path):
    path = tmp_path / "engine.sock"
    with ControlHub(path) as hub:
        hub.publish("ready", dry_run=True, category="default", threshold_db=-30)
        events = watch_events(path)
        try:
            import json
            assert json.loads(next(events))["type"] == "ready"
            hub.publish("level", db=-50, threshold_db=-30, spike=False)
            assert json.loads(next(events))["db"] == -50
        finally:
            events.close()


def test_service_expiry_returns_to_preview_and_stop(tmp_path):
    path = tmp_path / "engine.sock"
    calls = []
    def fake_bridge(config, category, dry_run, seconds, *, control, held_lock):
        calls.append((dry_run, seconds))
        control.publish("ready", dry_run=dry_run, category="default", threshold_db=-30)
        if len(calls) == 1:
            control.request({"command":"arm","seconds":2})
        elif len(calls) == 3:
            control.request({"command":"stop"})
        return 0
    with patch("tabletap.daemon.PIDLock") as lock, patch("tabletap.daemon.run_bridge", side_effect=fake_bridge):
        lock.return_value.acquire.return_value = True
        assert run_service(preview=True, hub_factory=lambda:ControlHub(path)) == 0
    assert calls == [(True,None),(False,2),(True,None)]
