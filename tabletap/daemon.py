"""Background service: reuse the exact interactive JSONL recognition engine."""
import logging

from .bridge import run_bridge
from .ipc import ControlHub
from .lock import PIDLock

log = logging.getLogger("tabletap")


def run_service(config_path=None, category=None, preview=False, hub_factory=ControlHub):
    lock = PIDLock()
    if not lock.acquire():
        log.error("Another TableTap listener is already running")
        return 3
    try:
        with hub_factory() as hub:
            dry_run = preview
            seconds = None
            while True:
                hub.publish("transition", message="Opening background microphone")
                status = run_bridge(config_path, category, dry_run, seconds,
                                    control=hub, held_lock=lock)
                request = hub.take_request()
                if request and request["command"] == "stop":
                    break
                if request:
                    command = request["command"]
                    if command == "arm":
                        dry_run, seconds = False, request["seconds"]
                    else:
                        dry_run, seconds = True, None
                        if command == "reload":
                            category = request["category"]
                    continue
                if not dry_run and (status == 2 or (status == 0 and seconds is not None)):
                    # Failed live validation or expiry leaves a safe service.
                    dry_run, seconds = True, None
                    continue
                return status
            hub.publish("stopped")
            return 0
    except (OSError, RuntimeError) as exc:
        log.error("Background listener: %s", exc)
        return 1
    finally:
        lock.release()
