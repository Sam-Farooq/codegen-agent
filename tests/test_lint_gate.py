"""What the gate is for: a container start that was never going to produce
anything but a parse error.

These drive the real graph with fake models and a sandbox that counts its
starts, so the number asserted here is the number of containers a run of this
shape would create.
"""
from langchain_core.runnables import RunnableLambda

from codegen.agents.prompts import LINT_REPAIR, REPAIR
from codegen.graph import Nodes, _repair_inputs, build
from codegen.state import Critique, FileEdit, LintReport, Plan, SuiteRun

BROKEN = "def total(items:\n    return sum(items)\n"
FIXED = "def total(items):\n    return sum(items)\n"
TEST_FILE = "def test_total():\n    from m import total\n    assert total([1, 2]) == 3\n"


class FakeModel:
    """Returns canned structured output and keeps every rendered prompt, so a
    test can assert what the repair round was actually told."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        def respond(prompt_value):
            self.prompts.append(prompt_value.to_string())
            return self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]

        return RunnableLambda(respond)


class CountingSandbox:
    """Stands in for the container, and fails the way pytest does on a file
    that will not compile: non-zero before a single test runs."""

    def __init__(self):
        self.starts = 0

    async def run_tests(self, files):
        self.starts += 1
        for f in files:
            try:
                compile(f.content, f.path, "exec")
            except SyntaxError as exc:
                return SuiteRun(
                    passed=False, exit_code=2, duration_s=0.4, stderr="",
                    stdout=f"ERROR collecting {f.path}\nE   SyntaxError: {exc.msg}",
                )
        return SuiteRun(passed=True, exit_code=0, stdout="2 passed", stderr="", duration_s=0.6)


def _graph(*coder_outputs):
    plan = Plan(summary="sum a list", files_to_create=["m.py"], test_file="test_m.py",
                edge_cases=["empty list"])
    coder = FakeModel(*coder_outputs)
    sandbox = CountingSandbox()
    graph = build(Nodes(planner=FakeModel(plan), coder=coder,
                        critic=FakeModel(Critique(approved=True)), sandbox=sandbox))
    return graph, coder, sandbox


def files(module: str) -> list[FileEdit]:
    return [FileEdit(path="m.py", content=module), FileEdit(path="test_m.py", content=TEST_FILE)]


async def test_a_syntax_error_is_repaired_without_starting_a_container():
    graph, _coder, sandbox = _graph(files(BROKEN), files(FIXED))
    state = await graph.ainvoke({"run_id": "r1", "task": "sum a list of numbers"})

    assert state["outcome"] == "passed"
    assert state["round"] == 1
    # The repair happened, and the only container start is the one that ran
    # the repaired code.
    assert sandbox.starts == 1


async def test_the_repair_round_is_told_what_ruff_found():
    graph, coder, _sandbox = _graph(files(BROKEN), files(FIXED))
    await graph.ainvoke({"run_id": "r2", "task": "sum a list of numbers"})

    repair_prompt = coder.prompts[1]
    assert "m.py:1" in repair_prompt
    assert "invalid-syntax" in repair_prompt


async def test_code_that_parses_goes_straight_to_the_container():
    graph, coder, sandbox = _graph(files(FIXED))
    state = await graph.ainvoke({"run_id": "r3", "task": "sum a list of numbers"})

    assert state["outcome"] == "passed"
    # No repair round, and exactly one container start: the gate costs a run
    # that was already clean nothing but a ruff invocation.
    assert state["round"] == 0
    assert sandbox.starts == 1
    assert len(coder.prompts) == 1


async def test_a_finding_the_repair_cannot_fix_still_ends_at_the_container():
    """The budget bounds the gate. Four repairs that do not help, then the
    container runs and the normal exhausted exit applies."""
    graph, coder, sandbox = _graph(files(BROKEN))
    state = await graph.ainvoke({"run_id": "r4", "task": "sum a list of numbers"})

    assert state["outcome"] == "exhausted"
    assert state["round"] == 4
    assert sandbox.starts == 1
    # One write and four repairs, which is the budget this loop already had.
    assert len(coder.prompts) == 5


def test_findings_choose_the_prompt_that_does_not_claim_a_suite_ran():
    state = {"task": "t", "files": files(BROKEN), "round": 0,
             "lint": LintReport(clean=False, count=2,
                                findings="m.py:1:7: invalid-syntax: Expected `)`")}
    prompt, inputs = _repair_inputs(state, 4)

    assert prompt is LINT_REPAIR
    assert "exit_code" not in inputs
    # format() is the check that the template and these inputs agree.
    rendered = prompt.format(**inputs)
    assert "m.py:1:7" in rendered
    assert "2 problems" in rendered
    assert "Attempt 1 of 4" in rendered


def test_a_failed_suite_chooses_the_pytest_prompt():
    state = {"task": "t", "files": files(FIXED), "round": 1,
             "lint": LintReport(clean=True),
             "last_run": SuiteRun(passed=False, exit_code=1, duration_s=0.2,
                                  stdout="E       assert 3 == 4", stderr="")}
    prompt, inputs = _repair_inputs(state, 4)

    assert prompt is REPAIR
    assert "findings" not in inputs
    rendered = prompt.format(**inputs)
    assert "assert 3 == 4" in rendered
    assert "Attempt 2 of 4" in rendered


def test_a_state_that_never_reached_the_gate_still_repairs_on_the_suite():
    state = {"task": "t", "files": files(FIXED), "round": 0,
             "last_run": SuiteRun(passed=False, exit_code=1, duration_s=0.2,
                                  stdout="E       TypeError", stderr="")}
    prompt, _inputs = _repair_inputs(state, 4)
    assert prompt is REPAIR
