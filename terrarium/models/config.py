"""Configuration models."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator

from terrarium.task.task import Task


class AgentConfig(BaseModel):
    """How to create an agent."""
    name: str
    import_path: str | None = None
    model_name: str | None = None
    kwargs: dict[str, Any] = Field(default_factory=dict)


class SandboxProviderConfig(BaseModel):
    """How to create a sandbox provider."""
    name: str = "docker"
    import_path: str | None = None
    kwargs: dict[str, Any] = Field(default_factory=dict)


class TaskConfig(BaseModel):
    """Reference to a task."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: str
    name: str = ""
    source: str = "adhoc"
    instance: Task | None = Field(default=None, exclude=True)


class RetryConfig(BaseModel):
    """Retry settings for failed trials."""
    max_retries: int = 0
    min_wait_sec: float = 1.0
    max_wait_sec: float = 60.0
    wait_multiplier: float = 2.0


class TrialConfig(BaseModel):
    """Config for a single trial."""
    task: TaskConfig
    agent: AgentConfig
    trial_name: str
    trial_dir: Path
    sandbox_provider: SandboxProviderConfig = Field(default_factory=SandboxProviderConfig)
    agent_setup_timeout_sec: float | None = None
    agent_exec_timeout_sec: float | None = None


class JobConfig(BaseModel):
    """Config for a batch job."""
    agents: list[AgentConfig]
    datasets: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    n_attempts: int = 1
    n_concurrent_trials: int = 4
    retry: RetryConfig = Field(default_factory=RetryConfig)
    sandbox_provider: SandboxProviderConfig = Field(default_factory=SandboxProviderConfig)
    job_name: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    job_dir: Path | None = None
    agent_setup_timeout_sec: float | None = None
    agent_exec_timeout_sec: float | None = None
    resume: bool = True

    @model_validator(mode="after")
    def _default_job_dir(self) -> Self:
        if self.job_dir is None:
            self.job_dir = Path("outputs") / self.job_name
        return self
