"""Opt-in local OBS and Home Assistant adapters. Credentials never enter action YAML."""
import base64
import hashlib
import json
import os
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


def obs_request(action: str, arg: str):
    import websocket

    requests = {
        "obs.record_toggle": ("ToggleRecord", {}),
        "obs.scene": ("SetCurrentProgramScene", {"sceneName": arg}),
        "obs.input_mute": ("ToggleInputMute", {"inputName": arg}),
    }
    kind, payload = requests[action]
    try:
        port = int(os.environ.get("TABLETAP_OBS_PORT", "4455"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
    except ValueError:
        raise RuntimeError("TABLETAP_OBS_PORT must be a valid TCP port") from None
    ws = None
    try:
        # OBS is local-only; do not forward its password through a proxy.
        ws = websocket.create_connection(f"ws://127.0.0.1:{port}", timeout=3,
                                         http_no_proxy=["127.0.0.1"], suppress_origin=True)
        hello = json.loads(ws.recv())
        if hello.get("op") != 0 or hello["d"]["rpcVersion"] < 1:
            raise RuntimeError("Unexpected OBS protocol version")
        identify = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = hello["d"].get("authentication")
        if auth:
            password = os.environ.get("TABLETAP_OBS_PASSWORD")
            if not password:
                raise RuntimeError("Set TABLETAP_OBS_PASSWORD for authenticated OBS")
            secret = base64.b64encode(hashlib.sha256((password + auth["salt"]).encode()).digest()).decode()
            identify["authentication"] = base64.b64encode(hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
        ws.send(json.dumps({"op": 1, "d": identify}))
        if json.loads(ws.recv()).get("op") != 2:
            raise RuntimeError("OBS authentication failed")
        request_id = uuid.uuid4().hex
        ws.send(json.dumps({"op": 6, "d": {"requestType": kind, "requestId": request_id, "requestData": payload}}))
        response = json.loads(ws.recv())
        if response.get("op") != 7 or response["d"].get("requestId") != request_id:
            raise RuntimeError("Unexpected OBS response")
        status = response["d"]["requestStatus"]
        if status.get("result") is not True:
            raise RuntimeError(f"OBS request failed ({status.get('code', 'unknown')})")
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Cannot communicate with local OBS WebSocket") from None
    finally:
        if ws is not None:
            try:
                ws.close(timeout=0)
            except Exception:
                pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def home_request(action: str, entity: str):
    domain, service = {
        "home.light_toggle": ("light", "toggle"),
        "home.switch_toggle": ("switch", "toggle"),
        "home.scene": ("scene", "turn_on"),
    }[action]
    url = os.environ.get("TABLETAP_HA_URL", "")
    token = os.environ.get("TABLETAP_HA_TOKEN", "")
    parsed = urlsplit(url)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment or not token):
        raise RuntimeError("Configure a valid Home Assistant base URL and token")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1") and os.environ.get("TABLETAP_HA_ALLOW_HTTP") != "1":
        raise RuntimeError("Use HTTPS, or explicitly opt in to trusted LAN HTTP with TABLETAP_HA_ALLOW_HTTP=1")
    req = Request(f"{url.rstrip('/')}/api/services/{domain}/{service}",
                  data=json.dumps({"entity_id": entity}).encode(),
                  headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                  method="POST")
    try:
        with build_opener(NoRedirect()).open(req, timeout=5) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Home Assistant returned HTTP {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"Home Assistant returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Cannot reach Home Assistant") from None
