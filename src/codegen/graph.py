"""The loop.

    plan -> code -> test -> (pass?) -> critique -> (approved?) -> done
                      ^                    |              |
                      └──── repair ────────┘              └── repair

Two exits that are not success: `exhausted` when the repair budget runs out,
and `rejected` when the critic blocks and there is no budget left to act on
it. Both are recorded as outcomes rather than raised, because a run that
tried four times and failed is a useful artifact and an exception is not.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from codegen.agents.prompts import CODER, CRITIC, PLANNER, REPAIR
from codegen.config import get_settings
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


class Nodes:
    def __init__(self, planner, coder, critic, sandbox: Sandbox):
        self.planner = planner
        self.coder = coder
        self.critic = critic
        self.sandbox = sandbox
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

    async def test(self, state: RunState) -> RunState:
        run = await self.sandbox.run_tests(state["files"])
        log.info("round=%s passed=%s exit=%s %.1fs",
                 state.get("round", 0), run.passed, run.exit_code, run.duration_s)
        return {"last_run": run, "history": [*state.get("history", []), run]}

    async def repair(self, state: RunState) -> RunState:
        run = state["last_run"]
        chain = REPAIR | self.coder.with_structured_output(list[FileEdit])
        changed = await chain.ainvoke({
            "task": state["task"],
            "files": _render(state["files"]),
            "exit_code": run.exit_code,
            "stdout": run.stdout,
            "stderr": run.stderr,
            "round": state["round"] + 1,
            "max_rounds": self.cfg.max_repair_rounds,
        })
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
    for name in ("plan", "write", "test", "repair", "review", "finish"):
        g.add_node(name, getattr(nodes, name if name != "write" else "write"))

    g.set_entry_point("plan")
    g.add_edge("plan", "write")
    g.add_edge("write", "test")
    g.add_conditional_edges("test", after_test,
                            {"review": "review", "repair": "repair", "finish": "finish"})
    g.add_edge("repair", "test")
    g.add_conditional_edges("review", after_review, {"finish": "finish", "repair": "repair"})
    g.add_edge("finish", END)
    return g.compile()
