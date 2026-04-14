"""LLM conversation trajectory models.

Content block types align with Claude API message format.
"""
from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    """Text content block."""
    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(BaseModel):
    """Extended thinking content block."""
    type: Literal["thinking"] = "thinking"
    thinking: str


class ToolUseBlock(BaseModel):
    """Tool use content block."""
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    """Tool result content block (appears in user messages)."""
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | None = None


ContentBlock = Union[TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock]


class Message(BaseModel):
    """An LLM conversation message."""
    role: str
    content: str | list[ContentBlock] = ""


class TrajectoryMetrics(BaseModel):
    """Aggregated metrics for a trajectory."""
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_cache_read_tokens: int | None = None
    total_cache_creation_tokens: int | None = None
    total_llm_calls: int | None = None
    total_tool_calls: int | None = None
    total_duration_sec: float | None = None


class Trajectory(BaseModel):
    """Complete LLM conversation history for a trial."""
    messages: list[Message]
    metrics: TrajectoryMetrics | None = None
