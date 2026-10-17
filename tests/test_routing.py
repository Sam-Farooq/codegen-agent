"""Routing. The sandbox and the models are integration concerns; these are the
decisions that make this a loop rather than a pipeline."""
from codegen.graph import after_lint, after_review, after_test
from codegen.state import Critique, LintReport, SuiteRun


def run(passed: bool) -> SuiteRun:
    return SuiteRun(passed=passed, exit_code=0 if passed else 1,
                   stdout="", stderr="", duration_s=0.1)


def report(clean: bool, count: int = 0) -> LintReport:
    return LintReport(clean=clean, count=count,
                      findings="" if clean else "m.py:1:1: F821 Undefined name `helper`")


def test_a_clean_report_goes_to_the_container():
    assert after_lint({"lint": report(True), "round": 0}) == "test"


def test_findings_are_repaired_before_any_container_starts():
    assert after_lint({"lint": report(False, 1), "round": 0}) == "repair"
    assert after_lint({"lint": report(False, 1), "round": 3}) == "repair"


def test_findings_with_no_budget_left_run_the_container_anyway():
    """Ending here would report an outcome no suite ever produced."""
    assert after_lint({"lint": report(False, 1), "round": 4}) == "test"


def test_findings_never_reach_repair_by_way_of_the_container():
    """What _repair_inputs relies on to read last_run without a guard: at
    every round where a dirty report is sent to the container, a failed suite
    finishes rather than repairing."""
    sent_to_container = [r for r in range(8)
                         if after_lint({"lint": report(False, 1), "round": r}) == "test"]
    assert sent_to_container
    for r in sent_to_container:
        assert after_test({"last_run": run(False), "round": r}) == "finish"


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
