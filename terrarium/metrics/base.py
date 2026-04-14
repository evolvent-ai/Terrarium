"""Base metric interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from terrarium.models.result import TrialResult


class BaseMetric(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def compute(self, results: list[TrialResult]) -> float: ...
