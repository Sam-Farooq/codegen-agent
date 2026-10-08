from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CG_", extra="ignore")

    planner_model: str = "claude-sonnet-4-5"
    coder_model: str = "claude-sonnet-4-5"
    # A different family for the critic. Same-model review agrees with itself
    # far too readily: on the first 40 runs the critic approved 38 of its own
    # coder's diffs, and 9 of those failed the very next test run.
    critic_model: str = "gpt-4o"

    max_repair_rounds: int = 4

    sandbox_image: str = "python:3.11-slim"
    sandbox_timeout_seconds: int = 60
    sandbox_memory_mb: int = 512
    sandbox_pids_limit: int = 128
    sandbox_cpu_quota: float = 1.0

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "codegen"


@lru_cache
def get_settings() -> Settings:
    return Settings()
