"""Configuration models."""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Any
from pydantic import BaseModel, Field, PrivateAttr

if TYPE_CHECKING:
    from terrarium.task.task import Task


class AgentConfig(BaseModel):
    """How to create an agent."""
    name: str
    import_path: str | None = None
    model_name: str | None = None
    kwargs: dict[str, Any] = Field(default_factory=dict)


class TaskConfig(BaseModel):
    """Reference to a task."""
    path: str
    name: str = ""
    source: str = "adhoc"
    _task: Task | None = PrivateAttr(default=None)


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
    trial_name: str = ""
    trial_dir: Path | None = None
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
    job_name: str = ""
    job_dir: Path | None = None
    agent_setup_timeout_sec: float | None = None
    agent_exec_timeout_sec: float | None = None
