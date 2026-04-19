"""Tests for MockAgent."""
import pytest
from tests.agent.mock import MockAgent


def test_name():
    assert MockAgent.name() == "mock"


def test_version():
    assert MockAgent().version() == "0.1.0"


def test_install_skill_not_supported():
    """MockAgent inherits default install_skill which raises."""
    with pytest.raises(NotImplementedError, match="Agent 'mock' does not support skills"):
        MockAgent().install_skill("/some/path")


def test_skills_dir_defaults_to_none():
    """Agents that don't support skills return None from skills_dir."""
    assert MockAgent().skills_dir is None


def test_system_prompt_setter_not_supported():
    """MockAgent inherits default system_prompt setter which raises."""
    with pytest.raises(NotImplementedError, match="system_prompt"):
        MockAgent().system_prompt = "hi"


def test_system_prompt_getter_returns_none():
    """Default system_prompt getter returns None."""
    assert MockAgent().system_prompt is None


def test_register_tools_not_supported():
    """MockAgent inherits default register_tools which raises."""
    def dummy():
        pass
    with pytest.raises(NotImplementedError, match="register_tools"):
        MockAgent().register_tools(dummy)


def test_lifecycle():
    agent = MockAgent()
    agent.setup(workspace=None, conn_info={"key": "value"})

    result = agent.act("Do something")

    # ActResult has 2 messages: user + assistant
    assert len(result.messages) == 2
    assert result.messages[0].role == "user"
    assert result.messages[0].content == "Do something"
    assert result.messages[1].role == "assistant"
    assert "Do something" in result.messages[1].content

    # Trajectory should also have 2 messages
    trajectory = agent.get_trajectory()
    assert len(trajectory.messages) == 2

    agent.teardown()


def test_multi_turn():
    agent = MockAgent()
    agent.setup(workspace=None, conn_info={})

    agent.act("First instruction")
    agent.act("Second instruction")

    trajectory = agent.get_trajectory()
    assert len(trajectory.messages) == 4
