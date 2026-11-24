import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tabletap.integrations import home_request, obs_request
from tabletap.native_actions import validate_builtin, execute_native


def test_home_entity_domain_and_redirect_protection():
    with pytest.raises(ValueError):
        validate_builtin("home.light_toggle:lock.front_door")
    with patch.dict("os.environ", {"TABLETAP_HA_URL":"https://ha.local","TABLETAP_HA_TOKEN":"secret"}, clear=True):
        with patch("tabletap.integrations.build_opener") as builder:
            response = builder.return_value.open.return_value.__enter__.return_value
            response.status = 200
            home_request("home.light_toggle", "light.desk")
            req = builder.return_value.open.call_args.args[0]
            assert req.full_url == "https://ha.local/api/services/light/toggle"
            assert json.loads(req.data) == {"entity_id":"light.desk"}
            assert req.get_header("Authorization") == "Bearer secret"
            from tabletap.integrations import NoRedirect
            assert isinstance(builder.call_args.args[0], NoRedirect)


def test_insecure_home_connection_requires_opt_in():
    with patch.dict("os.environ", {"TABLETAP_HA_URL":"http://ha.local:8123","TABLETAP_HA_TOKEN":"secret"}, clear=True):
        with patch("tabletap.integrations.build_opener") as builder:
            with pytest.raises(RuntimeError, match="HTTPS"):
                home_request("home.light_toggle", "light.desk")
            builder.assert_not_called()


def test_discord_uses_user_configured_shortcut():
    press = MagicMock()
    with patch("tabletap.native_actions.unavailable", return_value=None):
        execute_native("discord.mute:ctrl+alt+m", press_key=press)
    press.assert_called_once_with("ctrl+alt+m")


def test_obs_v5_handshake_and_request():
    socket = MagicMock()
    socket.recv.side_effect = [
        json.dumps({"op":0,"d":{"rpcVersion":1,"authentication":{"salt":"salt","challenge":"challenge"}}}),
        json.dumps({"op":2,"d":{"negotiatedRpcVersion":1}}),
        json.dumps({"op":7,"d":{"requestId":"id","requestStatus":{"result":True}}}),
    ]
    with patch.dict(sys.modules, {"websocket": SimpleNamespace(create_connection=MagicMock(return_value=socket))}), \
         patch.dict("os.environ", {"TABLETAP_OBS_PASSWORD":"secret"}, clear=True), \
         patch("tabletap.integrations.uuid.uuid4", return_value=SimpleNamespace(hex="id")):
        obs_request("obs.scene", "Focus")
    identify, request = [json.loads(c.args[0]) for c in socket.send.call_args_list]
    assert identify["op"] == 1 and "authentication" in identify["d"]
    assert "secret" not in json.dumps(identify)
    assert request["d"]["requestData"] == {"sceneName":"Focus"}
    socket.close.assert_called_once()
