"""Mock agent for testing."""
from __future__ import annotations
from terrarium.agent.base import BaseAgent
from terrarium.models.result import ActResult
from terrarium.models.trajectory import Message, Trajectory


class MockAgent(BaseAgent):
    """Test agent that records act() calls."""

    def __init__(self, on_act=None):
        self._on_act = on_act
        self._workspace = None
        self._conn_info = {}
        self._all_messages: list[Message] = []

    @staticmethod
    def name() -> str:
        return "mock"

    def version(self) -> str | None:
        return "0.1.0"

    def setup(self, workspace, conn_info: dict) -> None:
        self._workspace = workspace
        self._conn_info = conn_info

    def act(self, instruction: str) -> ActResult:
        messages = [
            Message(role="user", content=instruction),
            Message(role="assistant", content=f"Mock response to: {instruction}"),
        ]
        self._all_messages.extend(messages)
        if self._on_act:
            self._on_act(instruction, self._workspace, self._conn_info)
        return ActResult(messages=messages)

    def get_trajectory(self) -> Trajectory:
        return Trajectory(messages=list(self._all_messages))
