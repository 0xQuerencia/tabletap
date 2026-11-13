"""Single-listener lock, safe across competing processes and stale PID files."""
import fcntl
import os
from pathlib import Path


class PIDLock:
    def __init__(self, path=None):
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.lock_file = Path(path) if path is not None else base / "tabletap" / "daemon.pid"
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.fd = None

    def acquire(self) -> bool:
        if self.fd is not None:
            return True
        # Never open with "w" / O_TRUNC here: a contender must not truncate
        # the current listener's PID before flock rejects its lock attempt.
        fd = os.open(self.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            return False
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.fsync(fd)
        except OSError:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        self.fd = fd
        return True

    def release(self):
        if self.fd is None:
            return
        fd = self.fd
        self.fd = None
        try:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
