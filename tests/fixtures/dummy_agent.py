"""Dummy agent that returns fixed responses without calling any LLM."""
from __future__ import annotations

from terrarium.agent.base import BaseAgent
from terrarium.models.result import ActResult
from terrarium.models.trajectory import Message, TextBlock, Trajectory, TrajectoryMetrics


class DummyAgent(BaseAgent):
    """Agent that returns a fixed text response. No LLM calls."""

    def __init__(self, response: str = "OK", **kwargs):
        self._response = response
        self._act_results: list[ActResult] = []

    @staticmethod
    def name() -> str:
        return "dummy"

    @staticmethod
    def version() -> str:
        return "0.1.0"

    def workspace_config(self) -> None:
        return None

    def setup(self, workspace, conn_info) -> None:
        pass

    def act(self, instruction: str) -> ActResult:
        result = ActResult(
            messages=[
                Message(role="user", content=instruction),
                Message(role="assistant", content=[TextBlock(text=self._response)]),
            ],
        )
        self._act_results.append(result)
        return result

    def get_trajectory(self) -> Trajectory:
        msgs = []
        for r in self._act_results:
            msgs.extend(r.messages)
        return Trajectory(
            messages=msgs,
            metrics=TrajectoryMetrics(
                total_input_tokens=0,
                total_output_tokens=0,
                total_turns=0,
                total_tool_calls=0,
            ),
        )
