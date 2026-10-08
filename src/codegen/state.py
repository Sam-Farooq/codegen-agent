from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class FileEdit(BaseModel):
    path: str
    content: str


class Plan(BaseModel):
    summary: str = Field(max_length=500)
    files_to_create: list[str]
    test_file: str
    # Asked for explicitly because the planner otherwise writes tests that
    # only assert the happy path, and the repair loop then converges on code
    # that is wrong in exactly the way nobody checked.
    edge_cases: list[str] = Field(min_length=1)


class SuiteRun(BaseModel):
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False


class Critique(BaseModel):
    approved: bool
    blocking: list[str] = Field(default_factory=list)
    nits: list[str] = Field(default_factory=list)


class RunState(TypedDict, total=False):
    run_id: str
    task: str
    plan: Plan
    files: list[FileEdit]
    last_run: SuiteRun
    history: list[SuiteRun]
    critique: Critique
    round: int
    outcome: Literal["passed", "exhausted", "rejected"]
