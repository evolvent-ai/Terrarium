"""Terrarium — Programmatic definition and execution of multi-stage, multi-turn agent tasks."""
from dotenv import load_dotenv
load_dotenv()

# Models
from terrarium.models import (
    AgentConfig, AgentDatasetStats, AgentInfo, ActResult, Check,
    CheckerResults, ContentBlock, DatasetSpec, ExceptionInfo, JobConfig, JobResult, JobStats,
    Message, RetryConfig, TaskConfig, TaskInfo, TaskSpec, TextBlock, ThinkingBlock, TimingInfo,
    ToolResultBlock, ToolUseBlock, Trajectory, TrajectoryMetrics,
    TrialConfig, TrialResult,
)
# Agent
from terrarium.agent.base import BaseAgent
from terrarium.agent.registry import create_agent
from terrarium.agent.claude_code import ClaudeCodeAgent
from terrarium.agent.codex import CodexAgent
from terrarium.agent.hermes import HermesAgent
from terrarium.agent.mini import MiniAgent
from terrarium.agent.openclaw import OpenClawAgent
# Task
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers, aggregate_results
from terrarium.task.task import Task
# Dataset
from terrarium.dataset.dataset import Dataset
# Execution
from terrarium.execution.trial import Trial
from terrarium.execution.job import Job
from terrarium.execution.events import EventBus, JobEvent, JobEventPayload, TrialEvent, TrialEventPayload
# Metrics
from terrarium.metrics.base import BaseMetric
from terrarium.metrics.builtins import Mean, Max, Min, Sum, PassAtK
from terrarium.metrics.registry import create_metric

__all__ = [
    "AgentConfig", "AgentDatasetStats", "AgentInfo", "ActResult",
    "Check", "CheckerResults", "ContentBlock", "DatasetSpec", "ExceptionInfo",
    "JobConfig", "JobResult", "JobStats",
    "Message", "RetryConfig", "TaskConfig", "TaskInfo", "TaskSpec", "TextBlock", "ThinkingBlock",
    "TimingInfo", "ToolResultBlock", "ToolUseBlock",
    "Trajectory", "TrajectoryMetrics", "TrialConfig", "TrialResult",
    "BaseAgent", "create_agent", "ClaudeCodeAgent", "CodexAgent", "HermesAgent", "MiniAgent", "OpenClawAgent",
    "entry", "run_checkers", "aggregate_results", "Task",
    "Dataset",
    "Trial", "Job",
    "EventBus", "TrialEvent", "JobEvent", "TrialEventPayload", "JobEventPayload",
    "BaseMetric", "Mean", "Max", "Min", "Sum", "PassAtK", "create_metric",
]
