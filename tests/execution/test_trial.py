"""Tests for Trial execution engine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from terrarium.execution.trial import Trial
from terrarium.models.config import AgentConfig, TaskConfig, TrialConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TASK_DIR = FIXTURES_DIR / "sample_task"
MOCK_AGENT_IMPORT = "tests.agent.mock:MockAgent"


def _make_config(**kwargs) -> TrialConfig:
    return TrialConfig(
        task=TaskConfig(path=str(SAMPLE_TASK_DIR)),
        agent=AgentConfig(name="mock", import_path=MOCK_AGENT_IMPORT),
        **kwargs,
    )


def _make_mock_rt():
    """Build a sync MagicMock that mimics ComposableEnvironment."""
    mock_cap = MagicMock()
    mock_cap.connection_info = {"hostname": "localhost"}
    mock_rt = MagicMock()
    mock_rt.workspace = mock_cap
    return mock_rt


@pytest.mark.asyncio
async def test_run_sample_task():
    """A successful trial has score=1.0, non-empty trajectory, no exception."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert result.exception_info is None
    assert result.checker_result.score == 1.0
    # trajectory should have messages from act()
    assert len(result.trajectory.messages) > 0


@pytest.mark.asyncio
async def test_trial_name_auto():
    """Auto-generated trial_name includes the task name."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert "sample_task" in result.trial_name


@pytest.mark.asyncio
async def test_trial_name_explicit():
    """An explicit trial_name is preserved."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config(trial_name="my_custom_trial")).run()

    assert result.trial_name == "my_custom_trial"


@pytest.mark.asyncio
async def test_exception_captured():
    """When ComposableEnvironment raises, exception_info is set and score remains 0."""
    mock_rt = MagicMock()
    mock_rt.start = MagicMock(side_effect=RuntimeError("boom"))
    mock_rt.stop = MagicMock()

    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert result.exception_info is not None
    assert result.exception_info.exception_type == "RuntimeError"
    assert result.checker_result.score == 0.0


@pytest.mark.asyncio
async def test_persistence(tmp_path):
    """When trial_dir is set, config.json and result.json are written."""
    trial_dir = tmp_path / "my_trial"
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await Trial(_make_config(trial_dir=trial_dir)).run()

    assert (trial_dir / "config.json").exists()
    assert (trial_dir / "result.json").exists()

    # Quick sanity check on JSON content
    config_data = json.loads((trial_dir / "config.json").read_text())
    result_data = json.loads((trial_dir / "result.json").read_text())
    assert "task" in config_data
    assert "trial_name" in result_data


@pytest.mark.asyncio
async def test_task_config_passed_to_env(tmp_path):
    """Task.config is forwarded to ComposableEnvironment on construction."""
    task_dir = tmp_path / "t"
    task_dir.mkdir()
    (task_dir / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "from terrarium.task.checking import run_checkers\n"
        "\n"
        "@entry(capabilities=['postgres'],\n"
        "       config={'postgres': {'db_name': 'shop', 'port': 5433}})\n"
        "def task(env, agent):\n"
        "    return run_checkers({'ok': lambda: True})\n"
    )
    (task_dir / "task.toml").write_text('[metadata]\nname = "t"\n')

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt) as env_ctor:
        await Trial(TrialConfig(
            task=TaskConfig(path=str(task_dir)),
            agent=AgentConfig(name="mock", import_path=MOCK_AGENT_IMPORT),
        )).run()

    _, kwargs = env_ctor.call_args
    assert "postgres" in kwargs["capabilities"]
    assert kwargs["config"]["postgres"] == {"db_name": "shop", "port": 5433}


@pytest.mark.asyncio
async def test_agent_workspace_config_merged(tmp_path):
    """Agent workspace_config() is merged into task config; agent wins on image."""
    task_dir = tmp_path / "t"
    task_dir.mkdir()
    (task_dir / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "from terrarium.task.checking import run_checkers\n"
        "\n"
        "@entry(capabilities=['workspace'],\n"
        "       config={'workspace': {'image': 'task-img', 'command': 'sleep 1'}})\n"
        "def task(env, agent):\n"
        "    return run_checkers({'ok': lambda: True})\n"
    )
    (task_dir / "task.toml").write_text('[metadata]\nname = "t"\n')

    class WSAgent:
        @staticmethod
        def name() -> str:
            return "ws"

        def version(self) -> str | None:
            return "0"

        @classmethod
        def workspace_config(cls) -> dict:
            return {"image": "agent-img"}

        def setup(self, workspace, conn_info) -> None:  # noqa: D401
            pass

        def act(self, instruction):
            from terrarium.models.result import ActResult
            return ActResult(messages=[])

        def get_trajectory(self):
            from terrarium.models.trajectory import Trajectory
            return Trajectory(messages=[])

        def teardown(self) -> None:
            pass

    import sys
    module = type(sys)("_ws_mod")
    module.WSAgent = WSAgent
    sys.modules["_ws_mod"] = module

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt) as env_ctor:
        await Trial(TrialConfig(
            task=TaskConfig(path=str(task_dir)),
            agent=AgentConfig(name="ws", import_path="_ws_mod:WSAgent"),
        )).run()

    _, kwargs = env_ctor.call_args
    assert kwargs["capabilities"] == ["workspace"]
    # Agent overrides image; task's 'command' survives.
    assert kwargs["config"]["workspace"] == {"image": "agent-img", "command": "sleep 1"}


@pytest.mark.asyncio
async def test_timing_info_recorded():
    """setup_timing and execution_timing are populated."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert result.setup_timing is not None
    assert result.setup_timing.started_at is not None
    assert result.setup_timing.finished_at is not None
    assert result.execution_timing is not None
    assert result.execution_timing.started_at is not None
    assert result.execution_timing.finished_at is not None
