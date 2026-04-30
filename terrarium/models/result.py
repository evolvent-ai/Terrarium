"""Result layer models."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, computed_field
from terrarium.models.checker import CheckerResults
from terrarium.models.common import ExceptionInfo
from terrarium.models.spec import TaskSpec
from terrarium.models.trajectory import Message, Trajectory


class TaskInfo(BaseModel):
    """Task identification in results."""
    name: str
    path: str
    source: str = "adhoc"
    spec: TaskSpec = Field(default_factory=TaskSpec)
    capabilities: list[str] = Field(default_factory=list)
    capabilities_config: dict[str, dict] = Field(default_factory=dict)


class AgentInfo(BaseModel):
    """Agent identification."""
    name: str
    import_path: str | None = None
    version: str | None = None
    model_name: str | None = None


class ActResult(BaseModel):
    """Return value of agent.act()."""
    messages: list[Message] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class TimingInfo(BaseModel):
    """Timing for an execution phase."""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @computed_field
    @property
    def duration_sec(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class TrialResult(BaseModel):
    """Complete result of a single trial."""
    id: UUID = Field(default_factory=uuid4)
    trial_name: str
    task_info: TaskInfo
    agent_info: AgentInfo
    checker_result: CheckerResults
    trajectory: Trajectory | None = Field(default=None, exclude=True)
    exception_info: ExceptionInfo | None = None
    timing: TimingInfo = Field(default_factory=TimingInfo)
    setup_timing: TimingInfo = Field(default_factory=TimingInfo)
    execution_timing: TimingInfo = Field(default_factory=TimingInfo)


class AgentDatasetStats(BaseModel):
    """Aggregated stats for one agent x dataset group."""
    n_trials: int = 0
    n_errors: int = 0
    metrics: dict[str, float] = Field(default_factory=dict)
    score_stats: dict[float, list[str]] = Field(default_factory=dict)
    exception_stats: dict[str, list[str]] = Field(default_factory=dict)


class JobStats(BaseModel):
    """Aggregated stats grouped by agent x dataset."""
    n_trials: int = 0
    n_errors: int = 0
    agent_dataset_stats: dict[str, AgentDatasetStats] = Field(default_factory=dict)


class JobResult(BaseModel):
    """Complete result of a job."""
    id: UUID = Field(default_factory=uuid4)
    trial_results: list[TrialResult] | None = Field(default=None, exclude=True)
    stats: JobStats
    timing: TimingInfo = Field(default_factory=TimingInfo)
