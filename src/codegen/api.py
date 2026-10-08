from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from codegen.config import get_settings
from codegen.graph import Nodes, build
from codegen.sandbox.runner import Sandbox
from codegen.store.mongo import RunStore

logging.basicConfig(level=logging.INFO)
rt: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    store = RunStore()
    await store.ensure_indexes()
    rt["store"] = store
    rt["graph"] = build(Nodes(
        planner=ChatAnthropic(model=cfg.planner_model, temperature=0),
        coder=ChatAnthropic(model=cfg.coder_model, temperature=0),
        critic=ChatOpenAI(model=cfg.critic_model, temperature=0),
        sandbox=Sandbox(),
    ))
    yield


app = FastAPI(title="codegen-agent", version="0.6.2", lifespan=lifespan)


class TaskRequest(BaseModel):
    task: str = Field(min_length=10, max_length=4000)


@app.post("/runs", status_code=202)
async def create_run(req: TaskRequest, background: BackgroundTasks) -> dict:
    run_id = uuid.uuid4().hex[:12]
    await rt["store"].start(run_id, req.task)

    async def execute() -> None:
        state = await rt["graph"].ainvoke({"run_id": run_id, "task": req.task})
        await rt["store"].finish(run_id, state)

    background.add_task(execute)
    return {"run_id": run_id, "status": "accepted"}


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    doc = await rt["store"].runs.find_one({"run_id": run_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="no such run")
    return doc


@app.get("/stats")
async def stats() -> dict:
    return await rt["store"].stats()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
