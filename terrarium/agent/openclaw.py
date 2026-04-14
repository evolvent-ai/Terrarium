"""OpenClaw agent adapter.

Runs OpenClaw CLI inside a pre-built Docker container (terrarium/openclaw).
Multi-turn conversations use --session-id for continuity.
Trajectory is reconstructed from session JSONL files
at ~/.openclaw/agents/main/sessions/<sessionId>.jsonl.
"""
from __future__ import annotations

import json
import re
import shlex
import uuid
from pathlib import Path

from loguru import logger

from terrarium.agent.base import BaseAgent
from terrarium.models.result import ActResult
from terrarium.models.trajectory import (
    ContentBlock,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Trajectory,
    TrajectoryMetrics,
)

DEFAULT_IMAGE = "terrarium/openclaw:latest"
SESSION_DIR = "/root/.openclaw/agents/main/sessions"
SKILLS_DIR = "/root/.openclaw/workspace/skills"

class OpenClawAgent(BaseAgent):
    """OpenClaw CLI agent running inside the workspace container.

    Requires a Docker image with OpenClaw pre-installed.
    Build with: docker build -t terrarium/openclaw -f docker/openclaw.Dockerfile docker/
    """

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-6",
        models_config_path: str = "",
    ):
        self._model = model
        self._models_config = json.loads(Path(models_config_path).read_text())

        self._workspace = None
        self._session_id: str | None = None
        self._version: str | None = None
        self._session_entry_count: int = 0

        self._act_results: list[ActResult] = []

    @staticmethod
    def name() -> str:
        return "openclaw"

    def version(self) -> str | None:
        return self._version

    @classmethod
    def workspace_config(cls) -> dict:
        return {"image": DEFAULT_IMAGE}

    def setup(self, workspace, conn_info: dict) -> None:
        self._workspace = workspace
        self._version = self._detect_version()
        self._write_config()
        self._session_id = str(uuid.uuid4())
        logger.info("OpenClaw agent ready: version={}", self._version)

    def install_skill(self, path: str | Path) -> None:
        """Install a skill into the agent. Uploads to ~/.openclaw/workspace/skills/."""
        path = Path(path).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Skill path is not a directory: {path}")
        skill_name = path.name
        dest = f"{SKILLS_DIR}/{skill_name}"
        self._workspace.fs.make_dir(SKILLS_DIR)
        self._workspace.fs.upload(str(path), dest)
        logger.info("Installed skill: {} -> {}", skill_name, dest)

    def act(self, instruction: str) -> ActResult:
        command = self._build_command(instruction)
        logger.info("OpenClaw act: instruction={}", instruction)

        result = self._workspace.shell.exec(command)
        if result.exit_code != 0:
            logger.warning("OpenClaw exit {}: {}", result.exit_code, result.stderr or "")

        # Read messages and usage from the session JSONL
        messages, usage = self._read_new_session_entries()

        act_result = ActResult(
            messages=messages,
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            cache_read_tokens=usage.get("cacheRead", 0),
            cache_creation_tokens=usage.get("cacheWrite", 0),
        )
        self._act_results.append(act_result)
        return act_result

    def get_trajectory(self) -> Trajectory:
        messages = []
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_creation = 0
        total_tool_calls = 0
        for r in self._act_results:
            messages.extend(r.messages)
            total_input += r.input_tokens
            total_output += r.output_tokens
            total_cache_read += r.cache_read_tokens
            total_cache_creation += r.cache_creation_tokens
            for m in r.messages:
                if isinstance(m.content, list):
                    total_tool_calls += sum(
                        1 for b in m.content if isinstance(b, ToolUseBlock)
                    )

        return Trajectory(
            messages=messages,
            metrics=TrajectoryMetrics(
                total_input_tokens=total_input or None,
                total_output_tokens=total_output or None,
                total_cache_read_tokens=total_cache_read or None,
                total_cache_creation_tokens=total_cache_creation or None,
                total_llm_calls=len(self._act_results) or None,
                total_tool_calls=total_tool_calls or None,
            ),
        )

    def _detect_version(self) -> str:
        result = self._workspace.shell.exec("openclaw --version")
        if result.exit_code != 0:
            raise RuntimeError(f"openclaw --version failed (exit {result.exit_code}): {result.stderr or ''}")
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else result.stdout.strip()

    def _write_config(self) -> None:
        config = {
            "agents": {
                "defaults": {
                    "workspace": "/root/workspace",
                    "model": {"primary": self._model},
                },
            },
            "tools": {
                "exec": {
                    "security": "full",
                    "ask": "off",
                },
            },
        }
        config["models"] = self._models_config

        config_dir = "/root/.openclaw"
        self._workspace.fs.make_dir(config_dir)
        self._workspace.fs.write_file(
            f"{config_dir}/openclaw.json",
            json.dumps(config, indent=2).encode(),
        )

    def _build_command(self, instruction: str) -> str:
        parts = [
            "openclaw", "agent",
            "--local",
            "--json",
            f"--session-id {shlex.quote(self._session_id)}",
            f"--message {shlex.quote(instruction)}",
        ]
        return " ".join(parts)

    def _read_new_session_entries(self) -> tuple[list[Message], dict[str, int]]:
        """Read new entries from the session JSONL file.

        Returns (messages, usage) where usage is summed from all assistant messages.
        """
        session_path = f"{SESSION_DIR}/{self._session_id}.jsonl"
        raw = self._workspace.fs.read_file(session_path)

        lines = raw.decode().strip().split("\n")
        new_lines = lines[self._session_entry_count:]
        self._session_entry_count = len(lines)

        messages = []
        usage: dict[str, int] = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse session line: {}", e)
                continue
            if entry.get("type") != "message":
                continue
            raw_msg = entry.get("message")
            if not isinstance(raw_msg, dict):
                continue
            msg = _parse_session_message(raw_msg)
            if msg:
                messages.append(msg)
            # Accumulate usage from assistant messages
            if raw_msg.get("role") == "assistant":
                msg_usage = raw_msg.get("usage") or {}
                usage["input"] += msg_usage.get("input") or 0
                usage["output"] += msg_usage.get("output") or 0
                usage["cacheRead"] += msg_usage.get("cacheRead") or 0
                usage["cacheWrite"] += msg_usage.get("cacheWrite") or 0

        return messages, usage


def _parse_session_message(msg: dict) -> Message | None:
    """Convert an OpenClaw session message entry to a Message."""
    role = msg.get("role")
    if role not in ("user", "assistant", "toolResult"):
        return None

    content = msg.get("content")

    # toolResult: wrap as ToolResultBlock
    if role == "toolResult":
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(b["text"] for b in content if "text" in b)
        else:
            text = None
        return Message(role="user", content=[ToolResultBlock(
            tool_use_id=msg.get("toolCallId", ""), content=text,
        )])

    if isinstance(content, str):
        return Message(role=role, content=[TextBlock(text=content)]) if content.strip() else None

    assert isinstance(content, list)

    # user / assistant: parse content blocks
    blocks: list[ContentBlock] = []
    for block in content:
        assert isinstance(block, dict)
        block_type = block.get("type")
        if block_type == "text" and block.get("text", "").strip():
            blocks.append(TextBlock(text=block["text"]))
        elif block_type == "thinking" and block.get("thinking", "").strip():
            blocks.append(ThinkingBlock(thinking=block["thinking"]))
        elif block_type == "toolCall":
            blocks.append(ToolUseBlock(
                id=block.get("id", ""),
                name=block.get("name", ""),
                input=block.get("arguments", {}),
            ))

    return Message(role=role, content=blocks) if blocks else None


