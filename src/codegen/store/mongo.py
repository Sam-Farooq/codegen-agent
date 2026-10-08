"""Run persistence.

Every attempt is stored, not just the final state. The failed rounds are the
interesting data: which error messages the repair loop recovers from and
which it circles on forever is the only way to know whether raising
max_repair_rounds would buy anything.
"""
from __future__ import annotations

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorClient

from codegen.config import get_settings
from codegen.state import RunState


class RunStore:
    def __init__(self, client: AsyncIOMotorClient | None = None):
        cfg = get_settings()
        self.client = client or AsyncIOMotorClient(cfg.mongo_uri)
        self.runs = self.client[cfg.mongo_db]["runs"]

    async def ensure_indexes(self) -> None:
        await self.runs.create_index("run_id", unique=True)
        await self.runs.create_index([("outcome", 1), ("created_at", -1)])

    async def start(self, run_id: str, task: str) -> None:
        await self.runs.insert_one({
            "run_id": run_id,
            "task": task,
            "created_at": datetime.now(UTC),
            "rounds": [],
            "outcome": None,
        })

    async def record_round(self, run_id: str, state: RunState) -> None:
        run = state["last_run"]
        await self.runs.update_one(
            {"run_id": run_id},
            {"$push": {"rounds": {
                "round": state.get("round", 0),
                "passed": run.passed,
                "exit_code": run.exit_code,
                "timed_out": run.timed_out,
                "duration_s": run.duration_s,
                # First 2k only. Storing the whole pytest dump for every round
                # of every run grew the collection to 4GB in a fortnight.
                "stdout_head": run.stdout[:2000],
            }}},
        )

    async def finish(self, run_id: str, state: RunState) -> None:
        await self.runs.update_one(
            {"run_id": run_id},
            {"$set": {
                "outcome": state.get("outcome"),
                "rounds_used": state.get("round", 0),
                "files": [f.model_dump() for f in state.get("files", [])],
                "critique": state["critique"].model_dump() if state.get("critique") else None,
                "finished_at": datetime.now(UTC),
            }},
        )

    async def stats(self) -> dict:
        pipeline = [{"$group": {"_id": "$outcome", "n": {"$sum": 1},
                                "avg_rounds": {"$avg": "$rounds_used"}}}]
        return {d["_id"]: {"n": d["n"], "avg_rounds": round(d["avg_rounds"] or 0, 2)}
                async for d in self.runs.aggregate(pipeline)}
