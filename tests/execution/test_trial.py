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


def _make_config(task_dir: Path = SAMPLE_TASK_DIR, **kwargs) -> TrialConfig:
    return TrialConfig(
        task=TaskConfig(path=str(task_dir)),
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


def _write_task(task_dir: Path, entry_args: str) -> Path:
    """Write a minimal task.py + task.toml under task_dir and return task_dir."""
    task_dir.mkdir()
    (task_dir / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "from terrarium.task.checking import run_checkers\n"
        "\n"
        f"@entry({entry_args})\n"
        "def task(env, agent):\n"
        "    return run_checkers({'ok': lambda: True})\n"
    )
    (task_dir / "task.toml").write_text('[metadata]\nname = "t"\n')
    return task_dir


@pytest.mark.asyncio
async def test_task_capabilities_config_passed_to_env(tmp_path):
    """Task.capabilities_config is forwarded to ComposableEnvironment.config."""
    task_dir = _write_task(
        tmp_path / "t",
        "capabilities=['postgres'], "
        "capabilities_config={'postgres': {'db_name': 'shop', 'port': 5433}}",
    )

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt) as env_ctor:
        await Trial(_make_config(task_dir=task_dir)).run()

    _, kwargs = env_ctor.call_args
    assert "postgres" in kwargs["capabilities"]
    assert kwargs["config"]["postgres"] == {"db_name": "shop", "port": 5433}


@pytest.mark.asyncio
async def test_agent_workspace_config_merged(tmp_path):
    """Task's workspace config wins over agent's; agent config is fallback default."""
    task_dir = _write_task(
        tmp_path / "t",
        "capabilities=['workspace'], "
        "capabilities_config={'workspace': {'image': 'task-img', 'command': 'sleep 1'}}",
    )

    from tests.agent.mock import MockAgent

    mock_rt = _make_mock_rt()
    with patch.object(MockAgent, "workspace_config", classmethod(lambda cls: {"image": "agent-img"})), \
         patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt) as env_ctor:
        await Trial(_make_config(task_dir=task_dir)).run()

    _, kwargs = env_ctor.call_args
    assert kwargs["capabilities"] == ["workspace"]
    # Task's image wins; task's 'command' kept; agent's image becomes a no-op.
    assert kwargs["config"]["workspace"] == {"image": "task-img", "command": "sleep 1"}


@pytest.mark.asyncio
async def test_agent_workspace_image_is_fallback(tmp_path):
    """When the task doesn't declare a workspace image, agent's image is used."""
    task_dir = _write_task(tmp_path / "t", "capabilities=[]")

    from tests.agent.mock import MockAgent

    mock_rt = _make_mock_rt()
    with patch.object(MockAgent, "workspace_config", classmethod(lambda cls: {"image": "agent-img"})), \
         patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt) as env_ctor:
        await Trial(_make_config(task_dir=task_dir)).run()

    _, kwargs = env_ctor.call_args
    assert kwargs["config"]["workspace"] == {"image": "agent-img"}


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
