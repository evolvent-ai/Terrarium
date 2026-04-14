"""Spec models — declarative definitions (task.toml, dataset.toml, etc.)."""
from __future__ import annotations
from pydantic import BaseModel, Field


class TaskMetadata(BaseModel):
    """Task metadata from task.toml."""
    name: str | None = None
    author: str | None = None
    difficulty: str | None = None
    category: str | None = None
    tags: list[str] = []
    description: str | None = None


class TaskSpec(BaseModel):
    """Parsed task.toml."""
    metadata: TaskMetadata = Field(default_factory=TaskMetadata)


class DatasetMetadata(BaseModel):
    """Dataset metadata from dataset.toml."""
    name: str | None = None


class DatasetMetrics(BaseModel):
    """Dataset metrics declaration."""
    types: list[str] = ["mean"]


class DatasetSpec(BaseModel):
    """Parsed dataset.toml."""
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)
    metrics: DatasetMetrics = Field(default_factory=DatasetMetrics)
