import json
import threading
from unittest.mock import patch
import pytest
from tabletap.action import ActionRunner
from tabletap.workflow import parse_workflow


def workflow(*steps):
    return json.dumps([{"type": kind, "value": value} for kind, value in steps])


def test_sequence_validates_before_dispatch():
    runner = ActionRunner({})
    try:
        with patch.object(runner, "_launch") as launch:
            with pytest.raises(ValueError):
                runner._run_workflow(workflow(("exec", "first"), ("workflow", "[]")))
            launch.assert_not_called()
    finally:
        runner.shutdown()


def test_sequence_order_and_fail_fast():
    runner = ActionRunner({})
    try:
        with patch.object(runner, "_launch", side_effect=[None, RuntimeError("missing")]) as launch:
            with pytest.raises(RuntimeError, match="step 2"):
                runner._run_workflow(workflow(("exec", "first"), ("exec", "second"), ("exec", "third")))
            assert [c.args[0] for c in launch.call_args_list] == ["first", "second"]
    finally:
        runner.shutdown()


def test_cancel_stops_wait_and_future_steps():
    runner = ActionRunner({"single": {"type": "workflow", "value": workflow(("exec", "first"), ("wait", 10000), ("exec", "never"))}})
    started = threading.Event()
    try:
        with patch.object(runner, "_launch", side_effect=lambda _: started.set()) as launch:
            task = runner.run("single")
            assert started.wait(2)
            runner.cancel()
            with pytest.raises(RuntimeError, match="cancelled"):
                task.result(timeout=2)
            launch.assert_called_once_with("first")
    finally:
        runner.shutdown()


def test_expired_authorization_refuses_action():
    runner = ActionRunner({})
    runner.deadline = 0
    try:
        with patch.object(runner, "_launch") as launch:
            with pytest.raises(RuntimeError, match="expired"):
                runner._execute_action({"type": "exec", "value": "never"})
            launch.assert_not_called()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("value", ["[]", '[{"type":"wait","value":NaN}]', '[{"type":"wait","value":true}]', '[{"type":"builtin","value":"missing"}]'])
def test_invalid_workflow(value):
    with pytest.raises(ValueError):
        parse_workflow(value)


def test_conditional_uses_only_selected_branch():
    runner = ActionRunner({})
    block = {"condition":{"type":"tool_available","value":"playerctl"},"then":[{"type":"exec","value":"yes"}],"else":[{"type":"exec","value":"no"}]}
    try:
        with patch("tabletap.action.evaluate_condition", return_value=False), patch.object(runner, "_launch") as launch:
            runner._run_workflow(workflow(("if", block)))
            launch.assert_called_once_with("no")
    finally:
        runner.shutdown()


def test_parallel_completes_before_next_step():
    runner = ActionRunner({})
    barrier = threading.Barrier(2)
    done = []
    def launch(value):
        if value != "after":
            barrier.wait(timeout=2)
        else:
            assert set(done) == {"first", "second"}
        done.append(value)
    try:
        with patch.object(runner, "_launch", side_effect=launch):
            runner._run_workflow(workflow(("parallel", [{"type":"exec","value":"first"},{"type":"exec","value":"second"}]), ("exec", "after")))
        assert done[-1] == "after"
    finally:
        runner.shutdown()


def test_parallel_invalid_shortcut_and_untaken_branch_rejected():
    with pytest.raises(ValueError, match="keyboard"):
        parse_workflow(workflow(("parallel",[{"type":"key","value":"ctrl+a"},{"type":"exec","value":"true"}])))
    with pytest.raises(ValueError, match="unsupported action"):
        parse_workflow(workflow(("if",{"condition":{"type":"hyprland"},"then":[{"type":"exec","value":"true"}],"else":[{"type":"launcher","value":"bad"}]})))


def test_state_query_fails_closed_on_unexpected_response():
    from tabletap.workflow import evaluate_condition
    from types import SimpleNamespace
    with patch("tabletap.workflow.subprocess.run", return_value=SimpleNamespace(stdout="Mute: yes\n")):
        assert evaluate_condition({"type":"microphone_muted"})
    with patch("tabletap.workflow.subprocess.run", return_value=SimpleNamespace(stdout="unknown")):
        with pytest.raises(RuntimeError, match="determine"):
            evaluate_condition({"type":"microphone_muted"})
