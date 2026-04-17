"""Agent registry — create agents by name or import path."""
from __future__ import annotations
import importlib
from terrarium.agent.base import BaseAgent
from terrarium.models.config import AgentConfig

from terrarium.agent.claude_code import ClaudeCodeAgent
from terrarium.agent.codex import CodexAgent
from terrarium.agent.mini import MiniAgent
from terrarium.agent.openclaw import OpenClawAgent

_AGENTS: dict[str, type[BaseAgent]] = {
    "claude_code": ClaudeCodeAgent,
    "codex": CodexAgent,
    "openclaw": OpenClawAgent,
    "mini": MiniAgent,
}


def create_agent(config: AgentConfig) -> BaseAgent:
    """Create agent by import_path or name lookup.
    Priority: import_path > built-in registry.
    """
    if config.import_path:
        module_path, class_name = config.import_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        agent_cls = getattr(module, class_name)
    elif config.name in _AGENTS:
        agent_cls = _AGENTS[config.name]
    else:
        raise ValueError(
            f"Agent '{config.name}' not found. "
            f"Set import_path or use a built-in: {list(_AGENTS.keys())}"
        )
    kwargs = dict(config.kwargs)
    if config.model_name:
        kwargs.setdefault("model", config.model_name)
    return agent_cls(**kwargs)
