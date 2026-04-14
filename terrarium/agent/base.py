"""BaseAgent abstract interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from terrarium.environment.capabilities.workspace import WorkspaceCapability
    from terrarium.models.result import ActResult
    from terrarium.models.trajectory import Trajectory


class BaseAgent(ABC):
    """Pluggable LLM agent adapter."""

    @staticmethod
    @abstractmethod
    def name() -> str:
        """Agent identifier."""

    @abstractmethod
    def version(self) -> str | None:
        """Agent version."""

    @classmethod
    def workspace_config(cls) -> dict | None:
        """Return workspace sandbox configuration. None means in-process."""
        return {}

    @abstractmethod
    def setup(self, workspace: WorkspaceCapability, conn_info: dict) -> None:
        """Configure agent in the workspace container."""

    @property
    def system_prompt(self) -> str | None:
        """Current system prompt, if supported. Returns None by default."""
        return None

    @system_prompt.setter
    def system_prompt(self, value: str | None) -> None:
        """Set the system prompt. Raises NotImplementedError by default."""
        raise NotImplementedError(
            f"Agent '{self.name()}' does not support setting system_prompt"
        )

    def register_tools(self, *fns: Callable) -> None:
        """Register Python callables as tools. Raises NotImplementedError by default."""
        raise NotImplementedError(
            f"Agent '{self.name()}' does not support register_tools"
        )

    def install_skill(self, path: str | Path) -> None:
        """Install a skill into the agent. Raises NotImplementedError by default."""
        raise NotImplementedError(f"Agent '{self.name()}' does not support skills")

    @abstractmethod
    def act(self, instruction: str) -> ActResult:
        """Execute an instruction. Returns ActResult and accumulates internally."""

    @abstractmethod
    def get_trajectory(self) -> Trajectory:
        """Return complete trajectory from all accumulated act() calls."""

    def teardown(self) -> None:
        """Clean up resources. No-op by default."""
