"""Launch the real OpenTUI demo in a pseudo-terminal and quit via keyboard."""
import fcntl
import os
import pty
import select
import struct
import subprocess
import termios
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 36, 125, 0, 0))
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
    proc = subprocess.Popen(
        ["bun", "run", "index.tsx", "--demo"],
        cwd=root, env=env, stdin=slave, stdout=slave, stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = b""
    start = time.monotonic()
    try:
        while time.monotonic() - start < 5:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    output += os.read(master, 8192)
                except OSError:
                    break
            if b"tabletap" in output.lower() and time.monotonic() - start > 1.0:
                break
            if proc.poll() is not None:
                break
        assert proc.poll() is None, (
            f"OpenTUI exited unexpectedly: rc={proc.returncode}, output={output[-1000:]!r}"
        )
        assert output, "No terminal output from OpenTUI"
        os.write(master, b"q")
        proc.wait(timeout=10)
        assert proc.returncode == 0, f"OpenTUI exited with code {proc.returncode}"
        print("OpenTUI PTY smoke: passed (rendered and accepted q)")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        os.close(master)


if __name__ == "__main__":
    main()
