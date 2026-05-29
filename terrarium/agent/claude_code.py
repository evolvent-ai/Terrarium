"""Claude Code agent adapter.

Runs Claude Code CLI inside a pre-built Docker container (vab-claude-code).
Multi-turn conversations use --session-id / --resume for continuity.
Trajectory is parsed from the --output-format stream-json stdout.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import uuid
from itertools import groupby
from pathlib import Path
from typing import Any

from loguru import logger

from terrarium.agent.base import BaseAgent
from terrarium.models.mcp import MCPServerConfig
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

import os as _os
_AGENT_IMAGE_PREFIX = _os.environ.get("IMAGE_REGISTRY_PREFIX", "")
DEFAULT_IMAGE = f"{_AGENT_IMAGE_PREFIX}/vab-claude-code:latest" if _AGENT_IMAGE_PREFIX else "terrarium/claude-code:latest"
TERRARIUM_DIR = "/terrarium/claude_code"

CLAUDE_INSTALL_SCRIPT = """\
set -e
export DEBIAN_FRONTEND=noninteractive
if command -v apk >/dev/null 2>&1; then
    apk add --no-cache curl bash nodejs npm
    npm install -g @anthropic-ai/claude-code
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y curl
    elif command -v yum >/dev/null 2>&1; then yum install -y curl
    else echo "No supported package manager (apk/apt-get/yum)" >&2; exit 1
    fi
fi
curl -fsSL https://claude.ai/install.sh | bash
cp "$HOME/.local/bin/claude" /usr/local/bin/claude
"""


class ClaudeCodeAgent(BaseAgent):
    """Claude Code CLI agent running inside the workspace container.

    Requires a Docker image with Claude Code pre-installed.
    Build with: docker build -t vab-claude-code -f docker/claude-code.Dockerfile docker/
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        max_turns: int | None = None,
    ):
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._max_turns = max_turns

        self._workspace = None
        self._session_id: str | None = None
        self._version: str | None = None
        self._mcp_servers: dict[str, MCPServerConfig] = {}

        self._act_results: list[ActResult] = []
        self._stdouts: list[str] = []
        self._stderrs: list[str] = []


    @staticmethod
    def name() -> str:
        return "claude_code"

    def version(self) -> str | None:
        return self._version

    @classmethod
    def workspace_config(cls) -> dict:
        return {"image": {"name": DEFAULT_IMAGE}}

    def setup(self, workspace, conn_info: dict) -> None:
        self._workspace = workspace
        self._workspace.shell.exec(
            f"mkdir -p {TERRARIUM_DIR} && chmod 1777 {TERRARIUM_DIR}",
            user="root",
        )
        self._ensure_installed()
        self._version = self._detect_version()
        logger.info("Claude Code agent ready: version={}", self._version)

    def _ensure_installed(self) -> None:
        check = self._workspace.shell.exec("command -v claude")
        if check.exit_code == 0:
            return
        logger.info("Claude Code CLI not found in workspace, installing...")
        result = self._workspace.shell.exec(CLAUDE_INSTALL_SCRIPT, user="root")
        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to install Claude Code CLI (exit {result.exit_code}): "
                f"{result.stderr or result.stdout}"
            )

    def install_skill(self, path: str | Path) -> None:
        path = Path(path).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Skill path is not a directory: {path}")
        skill_name = path.name
        dest = f"{self.skills_dir}/{skill_name}"
        self._workspace.fs.make_dir(self.skills_dir)
        self._workspace.fs.upload(str(path), dest)
        logger.info("Installed skill: {} -> {}", skill_name, dest)

    @property
    def skills_dir(self) -> str:
        return f"{TERRARIUM_DIR}/skills"

    def add_mcp_server(self, config: MCPServerConfig) -> None:
        self._mcp_servers[config.name] = config
        servers: dict[str, dict[str, Any]] = {}
        for name, c in self._mcp_servers.items():
            if c.transport == "stdio":
                entry: dict[str, Any] = {"type": "stdio", "command": c.command, "args": c.args, "env": c.env}
            else:
                transport = "http" if c.transport == "streamable-http" else c.transport
                entry = {"type": transport, "url": c.url, "headers": c.headers}
            servers[name] = entry
        self._workspace.fs.write_file(
            f"{TERRARIUM_DIR}/.claude.json",
            json.dumps({"mcpServers": servers}, indent=2).encode(),
        )

    def act(self, instruction: str) -> ActResult:
        command = self._build_command(instruction)
        logger.info("Claude Code act: instruction={}", instruction)

        result = self._workspace.shell.exec(command)
        self._stdouts.append(result.stdout or "")
        self._stderrs.append(result.stderr or "")
        if result.exit_code != 0:
            logger.warning("Claude Code exit {}: {}", result.exit_code, result.stderr or "")

        messages, usage = _parse_stream_json(result.stdout or "")
        messages.insert(0, Message(role="user", content=instruction))

        act_result = ActResult(
            messages=messages,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        )
        self._act_results.append(act_result)
        return act_result

    def collect_logs(self, dest_dir: Path) -> None:
        stdout = "".join(f"=== turn {i} ===\n{s}\n" for i, s in enumerate(self._stdouts, 1))
        stderr = "".join(f"=== turn {i} ===\n{s}\n" for i, s in enumerate(self._stderrs, 1))
        (dest_dir / "stdout.txt").write_text(stdout)
        (dest_dir / "stderr.txt").write_text(stderr)

        result = self._workspace.shell.exec(
            f"find {TERRARIUM_DIR}/projects -name {shlex.quote(self._session_id + '.jsonl')} -type f"
        )
        paths = [p for p in (result.stdout or "").strip().split("\n") if p]
        if len(paths) != 1:
            raise RuntimeError(f"Expected exactly 1 Claude Code session file, found {len(paths)}: {paths}")
        self._workspace.fs.download(paths[0], str(dest_dir / "session.jsonl"))

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
        result = self._workspace.shell.exec("claude --version")
        if result.exit_code != 0:
            raise RuntimeError(f"claude --version failed (exit {result.exit_code}): {result.stderr or ''}")
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else result.stdout.strip()

    def _build_command(self, instruction: str) -> str:
        return f"{self._build_env_vars()} claude {self._build_flags()}-- {shlex.quote(instruction)}"

    def _build_env_vars(self) -> str:
        parts = [
            f"ANTHROPIC_API_KEY={shlex.quote(self._api_key)}",
            f"ANTHROPIC_MODEL={shlex.quote(self._model)}",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
            "IS_SANDBOX=1",
            f"CLAUDE_CONFIG_DIR={TERRARIUM_DIR}",
        ]
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            parts.append(f"ANTHROPIC_BASE_URL={shlex.quote(base_url)}")
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if auth_token:
            parts.append(f"ANTHROPIC_AUTH_TOKEN={shlex.quote(auth_token)}")
        return " ".join(parts) + " "

    def _build_flags(self) -> str:
        parts = [
            "--verbose",
            "--output-format stream-json",
            "--permission-mode bypassPermissions",
            "--print",
        ]
        if self._max_turns is not None:
            parts.append(f"--max-turns {self._max_turns}")
        if self._session_id is None:
            self._session_id = str(uuid.uuid4())
            parts.append(f"--session-id {self._session_id}")
        else:
            parts.append(f"--resume {self._session_id}")
        return " ".join(parts) + " "


def _parse_stream_json(stdout: str) -> tuple[list[Message], dict[str, int]]:
    """Parse stream-json stdout into messages and usage totals.

    Two-pass: first parse and filter all JSON lines, then group consecutive
    events by msg id to merge content blocks and dedup usage.
    """
    # Pass 1: parse and filter valid events
    events: list[tuple[str, dict]] = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse stream-json line: {}", e)
            continue
        msg = event.get("message")
        if not isinstance(msg, dict):
            continue
        events.append((msg.get("id"), event))

    # Pass 2: group by msg id, build messages and accumulate usage
    messages: list[Message] = []
    usage: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    for _, group in groupby(events, key=lambda e: e[0]):
        blocks: list[ContentBlock] = []
        role: str | None = None
        usage_counted = False
        for _, event in group:
            msg = event["message"]
            role = event["type"]
            blocks.extend(_extract_blocks(msg.get("content")))
            # Count usage once per group (all events in group carry the same usage)
            if not usage_counted and role == "assistant":
                msg_usage = msg.get("usage") or {}
                usage["input_tokens"] += msg_usage.get("input_tokens") or 0
                usage["output_tokens"] += msg_usage.get("output_tokens") or 0
                usage["cache_read_input_tokens"] += msg_usage.get("cache_read_input_tokens") or 0
                usage["cache_creation_input_tokens"] += msg_usage.get("cache_creation_input_tokens") or 0
                usage_counted = True
        if blocks and role:
            messages.append(Message(role=role, content=blocks))

    return messages, usage


def _extract_blocks(content: Any) -> list[ContentBlock]:
    """Extract content blocks from a message's content field.

    Handles all block types: text, thinking, tool_use, tool_result.
    If content is a plain string, wraps it as a single TextBlock.
    """
    if isinstance(content, str):
        return [TextBlock(text=content)] if content.strip() else []
    
    assert isinstance(content, list)

    blocks: list[ContentBlock] = []
    for block in content:
        assert isinstance(block, dict)
        block_type = block.get("type")
        if block_type == "text" and block.get("text", "").strip():
            blocks.append(TextBlock(text=block["text"]))
        elif block_type == "thinking" and block.get("thinking", "").strip():
            blocks.append(ThinkingBlock(thinking=block["thinking"]))
        elif block_type == "tool_use":
            blocks.append(ToolUseBlock(
                id=block.get("id", ""),
                name=block.get("name", ""),
                input=block.get("input", {}),
            ))
        elif block_type == "tool_result":
            raw = block.get("content")
            if isinstance(raw, list):
                text = "\n".join(b["text"] for b in raw if "text" in b)
            elif isinstance(raw, str):
                text = raw
            else:
                text = None
            blocks.append(ToolResultBlock(
                tool_use_id=block.get("tool_use_id", ""),
                content=text,
            ))
    return blocks
