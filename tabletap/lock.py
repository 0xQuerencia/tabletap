import fcntl
import os
from pathlib import Path


class PIDLock:
    def __init__(self):
        self.lock_file = Path.home() / ".cache/tabletap/daemon.pid"
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.fd = None

    def acquire(self) -> bool:
        try:
            self.fd = open(self.lock_file, 'w')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd.write(str(os.getpid()))
            self.fd.flush()
            return True
        except IOError:
            if self.fd:
                self.fd.close()
                self.fd = None
            return False

    def release(self):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
            except Exception:
                pass
            finally:
                self.fd = None

