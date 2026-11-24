"""Private, bounded Unix-socket control for the single background listener."""
from __future__ import annotations

import json
import math
import os
import queue
import socket
import socketserver
import stat
import threading
from pathlib import Path


def socket_path():
    root = Path(os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    directory = root / "tabletap-ipc"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("TableTap IPC requires a private user-owned directory")
    return directory / "engine.sock"


def encode(record):
    return (json.dumps(record, separators=(",", ":"), default=lambda x: x.item(), allow_nan=False) + "\n").encode()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8

    def __init__(self, path, hub):
        self.hub = hub
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(str(path), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(2)
        hub = self.server.hub
        try:
            line = self.rfile.readline(4097)
            if not line or len(line) > 4096 or not line.endswith(b"\n"):
                return
            request = json.loads(line)
            if not isinstance(request, dict):
                return
            if request == {"command": "watch"}:
                with hub.subscribe() as channel:
                    while not hub.closed.is_set():
                        try:
                            record = channel.get(timeout=.25)
                        except queue.Empty:
                            continue
                        if record is None:
                            return
                        self.wfile.write(record)
            else:
                self.wfile.write(encode(hub.request(request)))
        except (OSError, ValueError, TypeError):
            return


class ControlHub:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else socket_path()
        self.guard = threading.Lock()
        self.interrupted = threading.Event()
        self.shutdown_requested = threading.Event()
        self.reload_requested = threading.Event()
        self.closed = threading.Event()
        self.pending = None
        self.runner = None
        self.last_state = {"type": "transition", "message": "Starting listener"}
        self.last_level = None
        self.watchers = set()
        self.server = None
        self.thread = None

    def __enter__(self):
        # Caller holds the single-listener lock for the entire server lifetime.
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError("Refusing to replace an unsafe socket path")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(.2)
                probe.connect(str(self.path))
            except ConnectionRefusedError:
                self.path.unlink()
            else:
                raise RuntimeError("A TableTap control server is already running")
            finally:
                probe.close()
        self.server = Server(self.path, self)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval":.1}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.closed.set()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=1)
            self.path.unlink(missing_ok=True)

    def set_runner(self, runner):
        with self.guard:
            self.runner = runner
            if runner is not None and self.interrupted.is_set():
                runner.cancel()

    def signal_stop(self):
        self.shutdown_requested.set()
        self.interrupted.set()
        runner = self.runner
        if runner:
            runner.cancel()

    def signal_reload(self):
        self.reload_requested.set()
        self.interrupted.set()
        runner = self.runner
        if runner:
            runner.cancel()

    def request(self, request):
        command = request.get("command")
        if command == "status" and set(request) == {"command"}:
            with self.guard:
                return {"state":self.last_state, "level":self.last_level, "pending":self.pending is not None}
        if command not in ("safe", "reload", "arm", "stop"):
            return {"error":"Unsupported control command"}
        expected = {"command"}
        if command == "arm":
            expected.add("seconds")
            seconds = request.get("seconds")
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 600:
                return {"error":"Authorization must be 0–600 seconds"}
        if command == "reload":
            expected.add("category")
            category = request.get("category")
            if category is not None and (not isinstance(category, str) or not category or len(category) > 100):
                return {"error":"Invalid profile"}
        if set(request) != expected:
            return {"error":"Invalid control fields"}
        with self.guard:
            if self.pending is not None and command not in ("safe", "stop", "reload"):
                return {"error":"Listener transition in progress"}
            if self.pending and self.pending["command"] == "stop":
                return {"error":"Listener stopping"}
            if command == "arm" and (self.last_state.get("type") != "ready" or not self.last_state.get("dry_run")):
                return {"error":"Start safe preview before arming"}
            self.pending = request
            self.interrupted.set()
            if self.runner is not None:
                self.runner.cancel()
            return {"accepted":True, "command":command}

    def take_request(self):
        with self.guard:
            if self.shutdown_requested.is_set():
                return {"command":"stop"}
            request = self.pending
            if self.reload_requested.is_set() and request is None:
                request = {"command":"safe"}
            self.reload_requested.clear()
            self.pending = None
            self.interrupted.clear()
            return request

    def publish(self, kind, **fields):
        record = {"type":kind, **fields}
        data = encode(record)
        with self.guard:
            if kind in ("ready", "transition", "error", "stopped"):
                self.last_state = record
                if kind != "ready":
                    self.last_level = None
            elif kind == "level":
                self.last_level = record
            for watcher in tuple(self.watchers):
                try:
                    watcher.put_nowait(data)
                except queue.Full:
                    # Slow clients lose their subscription; never block audio.
                    self.watchers.discard(watcher)
                    while not watcher.empty():
                        try:
                            watcher.get_nowait()
                        except queue.Empty:
                            break
                    watcher.put_nowait(None)

    def subscribe(self):
        from contextlib import contextmanager
        @contextmanager
        def subscription():
            channel = queue.Queue(maxsize=128)
            with self.guard:
                channel.put_nowait(encode(self.last_state))
                if self.last_level:
                    channel.put_nowait(encode(self.last_level))
                self.watchers.add(channel)
            try:
                yield channel
            finally:
                with self.guard:
                    self.watchers.discard(channel)
        return subscription()


def control_request(request, path=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path if path is not None else socket_path()))
        client.sendall(encode(request))
        with client.makefile("rb") as reader:
            line = reader.readline(65537)
            if not line or len(line) > 65536:
                raise RuntimeError("Invalid response from TableTap listener")
            return json.loads(line)


def watch_events(path=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path if path is not None else socket_path()))
        client.sendall(encode({"command":"watch"}))
        client.settimeout(None)
        with client.makefile("rb") as reader:
            while True:
                line = reader.readline(65537)
                if not line or len(line) > 65536:
                    return
                yield line.decode().rstrip("\n")
