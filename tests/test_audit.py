"""Unit and subprocess tests for the zero-action work-noise audit."""
import json
import subprocess
import sys

import pytest

from tabletap.audit import WorkNoiseStats, format_audit, observe_work


def test_audit_accumulates_only_aggregate_non_audio_stats():
    a = WorkNoiseStats()
    a.consume("malformed")
    a.consume('{"type":"ready","dry_run":true}')
    a.consume('{"type":"level","db":-34.2,"threshold_db":-28.1}')
    a.consume('{"type":"level","db":-47,"threshold_db":-29}')
    a.consume('{"type":"gesture","pattern":"quadruple","dispatched":false,"action":"PRIVATE URL"}')
    a.consume('{"type":"rejected","reason":"sustained noise"}')
    report = a.result(60, 60, True)
    assert report["status"] == "warn"
    assert report["total_unintended_gestures"] == 1
    assert report["gestures"] == {"quadruple": 1}
    assert report["rejected_noise"] == {"sustained noise": 1}
    assert report["headroom_db"] == pytest.approx(5.2)
    assert "PRIVATE" not in json.dumps(report)
    assert report["raw_audio_recorded"] is False
    assert report["actions_enabled"] is False


def test_clean_audit_passes_but_does_not_claim_perfection():
    a = WorkNoiseStats()
    a.consume('{"type":"ready","dry_run":true}')
    a.consume('{"type":"level","db":-60,"threshold_db":-30}')
    report = a.result(60, 60, True)
    assert report["status"] == "pass"
    assert "not guarantee" in format_audit(report)


def test_bridge_dispatched_action_is_fatal_even_if_no_patterns():
    a = WorkNoiseStats()
    a.consume('{"type":"ready","dry_run":false}')
    a.consume('{"type":"gesture","pattern":"single","dispatched":true}')
    assert a.result(30, 10, True)["status"] == "error"


def test_audit_fails_when_child_does_not_ready_or_exits_early():
    report = observe_work(.05, command=[sys.executable, "-u", "-c", "print('nothing useful')"],
                          startup_timeout_sec=.2)
    assert report["status"] == "error"


def test_audit_reads_a_real_local_child_without_executing_actions():
    # Python subprocess is used so this exercises the selector/JSONL reader,
    # process cleanup, and timeout path without PortAudio hardware.
    script = (
        "import json,sys,time\n"
        "for line in ["
        "{'type':'ready','dry_run':True},"
        "{'type':'level','db':-28,'threshold_db':-25},"
        "{'type':'rejected','reason':'slow onset'},"
        "{'type':'gesture','pattern':'double','dispatched':False}]:\n"
        " print(json.dumps(line),flush=True)\n"
        "time.sleep(.4)\n"
    )
    report = observe_work(.15, command=[sys.executable, "-u", "-c", script])
    assert report["status"] == "warn", report
    assert report["gestures"] == {"double": 1}
    assert report["headroom_db"] == pytest.approx(3.0)


def test_duration_limit_is_enforced():
    with pytest.raises(ValueError, match="duration"):
        observe_work(0)
    with pytest.raises(ValueError, match="duration"):
        observe_work(601)
