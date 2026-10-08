from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CG_", extra="ignore")

    planner_model: str = "claude-sonnet-4-5"
    coder_model: str = "claude-sonnet-4-5"
    # A different family for the critic. A model reviewing its own output is
    # blind as a reader to whatever it was blind to as a writer, so a second
    # family at least makes the blind spots less likely to coincide.
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
