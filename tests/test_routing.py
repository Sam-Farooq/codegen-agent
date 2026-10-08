"""Routing. The sandbox and the models are integration concerns; these are the
decisions that make this a loop rather than a pipeline."""
from codegen.graph import after_review, after_test
from codegen.state import Critique, SuiteRun


def run(passed: bool) -> SuiteRun:
    return SuiteRun(passed=passed, exit_code=0 if passed else 1,
                   stdout="", stderr="", duration_s=0.1)


def test_passing_tests_go_to_review_not_straight_out():
    assert after_test({"last_run": run(True), "round": 0}) == "review"


def test_failing_tests_repair_while_budget_remains():
    assert after_test({"last_run": run(False), "round": 0}) == "repair"
    assert after_test({"last_run": run(False), "round": 3}) == "repair"


def test_failing_tests_stop_at_the_budget():
    assert after_test({"last_run": run(False), "round": 4}) == "finish"


def test_an_approving_critic_finishes():
    assert after_review({"critique": Critique(approved=True), "round": 1}) == "finish"


def test_a_critic_with_only_nits_finishes():
    state = {"critique": Critique(approved=False, nits=["naming"]), "round": 1}
    assert after_review(state) == "finish"


def test_a_blocking_critique_sends_it_back():
    state = {"critique": Critique(approved=False, blocking=["leaks the file handle"]), "round": 1}
    assert after_review(state) == "repair"


def test_a_blocking_critique_with_no_budget_left_stops():
    state = {"critique": Critique(approved=False, blocking=["unhandled error path"]), "round": 4}
    assert after_review(state) == "finish"
