"""Tests for agent registry."""
import pytest
from terrarium.agent.base import BaseAgent
from terrarium.agent.registry import create_agent
from terrarium.models.config import AgentConfig


def test_by_import_path():
    config = AgentConfig(name="mock", import_path="tests.agent.mock:MockAgent")
    agent = create_agent(config)
    assert isinstance(agent, BaseAgent)
    assert agent.name() == "mock"


def test_with_kwargs():
    config = AgentConfig(
        name="mock",
        import_path="tests.agent.mock:MockAgent",
        kwargs={"on_act": None},
    )
    agent = create_agent(config)
    assert isinstance(agent, BaseAgent)
    assert agent._on_act is None


def test_invalid_import_path():
    config = AgentConfig(
        name="mock",
        import_path="tests.agent.nonexistent_module:MockAgent",
    )
    with pytest.raises(ModuleNotFoundError):
        create_agent(config)


def test_no_import_path_no_builtin():
    config = AgentConfig(name="unknown_agent_xyz")
    with pytest.raises(ValueError, match="not found"):
        create_agent(config)
