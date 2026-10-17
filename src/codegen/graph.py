"""The loop.

    plan -> write -> lint -> test -> (pass?) -> critique -> (approved?) -> done
                       ^                |                        |
                       └──── repair ────┴────────────────────────┘

Three things route to repair: a lint finding, a failed suite, and a blocking
critique. Repair goes back to lint rather than straight to test, so a fix that
introduces a parse error is caught before the next container starts.

Two exits that are not success: `exhausted` when the repair budget runs out,
and `rejected` when the critic blocks and there is no budget left to act on
it. Both are recorded as outcomes rather than raised, because a run that
tried four times and failed is a useful artifact and an exception is not.
"""
from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph

from codegen.agents.prompts import CODER, CRITIC, LINT_REPAIR, PLANNER, REPAIR
from codegen.config import get_settings
from codegen.lint import Linter
from codegen.sandbox.runner import Sandbox
from codegen.state import Critique, FileEdit, Plan, RunState

log = logging.getLogger(__name__)


def _render(files: list[FileEdit]) -> str:
    return "\n\n".join(f"=== {f.path} ===\n{f.content}" for f in files)


def _merge(existing: list[FileEdit], incoming: list[FileEdit]) -> list[FileEdit]:
    """Repair returns only changed files, so the rest have to survive."""
    by_path = {f.path: f for f in existing}
    for f in incoming:
        by_path[f.path] = f
    return list(by_path.values())


def _repair_inputs(state: RunState, max_rounds: int) -> tuple[ChatPromptTemplate, dict]:
    """Which failure this repair round is shown.

    A lint finding arrives before any container has run, so there is no exit
    code to quote and `last_run` may not exist at all. Routing guarantees only
    one of the two is outstanding: a dirty report reaches repair only while
    budget remains, and once the budget is gone a dirty report goes to the
    container instead, so repair is never entered from test with lint findings
    still open.
    """
    common = {
        "task": state["task"],
        "files": _render(state["files"]),
        "round": state["round"] + 1,
        "max_rounds": max_rounds,
    }

    report = state.get("lint")
    if report is not None and not report.clean:
        return LINT_REPAIR, {**common, "findings": report.findings, "count": report.count}

    run = state["last_run"]
    return REPAIR, {**common, "exit_code": run.exit_code,
                    "stdout": run.stdout, "stderr": run.stderr}


class Nodes:
    def __init__(self, planner, coder, critic, sandbox: Sandbox, linter: Linter | None = None):
        self.planner = planner
        self.coder = coder
        self.critic = critic
        self.sandbox = sandbox
        self.linter = linter or Linter()
        self.cfg = get_settings()

    async def plan(self, state: RunState) -> RunState:
        chain = PLANNER | self.planner.with_structured_output(Plan)
        return {"plan": await chain.ainvoke({"task": state["task"]}), "round": 0, "history": []}

    async def write(self, state: RunState) -> RunState:
        chain = CODER | self.coder.with_structured_output(list[FileEdit])
        files = await chain.ainvoke(
            {"task": state["task"], "plan": state["plan"].model_dump_json(indent=2)}
        )
        return {"files": files}

    async def lint(self, state: RunState) -> RunState:
        report = await self.linter.check(state["files"])
        log.info("round=%s lint_findings=%s available=%s",
                 state.get("round", 0), report.count, report.available)
        return {"lint": report}

    async def test(self, state: RunState) -> RunState:
        run = await self.sandbox.run_tests(state["files"])
        log.info("round=%s passed=%s exit=%s %.1fs",
                 state.get("round", 0), run.passed, run.exit_code, run.duration_s)
        return {"last_run": run, "history": [*state.get("history", []), run]}

    async def repair(self, state: RunState) -> RunState:
        prompt, inputs = _repair_inputs(state, self.cfg.max_repair_rounds)
        chain = prompt | self.coder.with_structured_output(list[FileEdit])
        changed = await chain.ainvoke(inputs)
        return {"files": _merge(state["files"], changed), "round": state["round"] + 1}

    async def review(self, state: RunState) -> RunState:
        chain = CRITIC | self.critic.with_structured_output(Critique)
        critique = await chain.ainvoke({
            "task": state["task"],
            "files": _render(state["files"]),
            "edge_cases": "\n".join(state["plan"].edge_cases),
        })
        return {"critique": critique}

    async def finish(self, state: RunState) -> RunState:
        if state["last_run"].passed and state["critique"].approved:
            return {"outcome": "passed"}
        if state["last_run"].passed:
            return {"outcome": "rejected"}
        return {"outcome": "exhausted"}


def after_lint(state: RunState) -> str:
    if state["lint"].clean:
        return "test"
    # Out of budget, so the container runs anyway. The findings are real, but
    # finishing here would report an outcome no suite ever produced, and the
    # repair rounds are what cost money, not the container.
    return "repair" if state["round"] < get_settings().max_repair_rounds else "test"


def after_test(state: RunState) -> str:
    if state["last_run"].passed:
        return "review"
    return "repair" if state["round"] < get_settings().max_repair_rounds else "finish"


def after_review(state: RunState) -> str:
    if state["critique"].approved or not state["critique"].blocking:
        return "finish"
    return "repair" if state["round"] < get_settings().max_repair_rounds else "finish"


def build(nodes: Nodes):
    g = StateGraph(RunState)
    for name in ("plan", "write", "lint", "test", "repair", "review", "finish"):
        g.add_node(name, getattr(nodes, name))

    g.set_entry_point("plan")
    g.add_edge("plan", "write")
    g.add_edge("write", "lint")
    g.add_conditional_edges("lint", after_lint, {"test": "test", "repair": "repair"})
    g.add_edge("repair", "lint")
    g.add_conditional_edges("test", after_test,
                            {"review": "review", "repair": "repair", "finish": "finish"})
    g.add_conditional_edges("review", after_review, {"finish": "finish", "repair": "repair"})
    g.add_edge("finish", END)
    return g.compile()
