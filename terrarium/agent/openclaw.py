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

DEFAULT_IMAGE = "terrarium/openclaw:latest"
TERRARIUM_DIR = "/terrarium/openclaw"
SESSION_DIR = f"{TERRARIUM_DIR}/agents/main/sessions"
CONFIG_PATH = f"{TERRARIUM_DIR}/openclaw.json"

OPENCLAW_INSTALL_SCRIPT = """\
set -e
export DEBIAN_FRONTEND=noninteractive
if command -v apk >/dev/null 2>&1; then
    apk add --no-cache curl bash nodejs npm
    npm install -g openclaw
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y curl
    elif command -v yum >/dev/null 2>&1; then yum install -y curl
    else echo "No supported package manager (apk/apt-get/yum)" >&2; exit 1
    fi
fi
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard
"""

class OpenClawAgent(BaseAgent):
    """OpenClaw CLI agent running inside the workspace container.

    Requires a Docker image with OpenClaw pre-installed.
    Build with: docker build -t terrarium/openclaw -f docker/openclaw.Dockerfile docker/
    """

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-6",
        models_config_path: str = "",
        system_prompt: str | None = None,
    ):
        self._model = model
        self._models_config = json.loads(Path(models_config_path).read_text())
        self._system_prompt: str | None = system_prompt

        self._workspace = None
        self._session_id: str | None = None
        self._version: str | None = None
        self._session_entry_count: int = 0
        self._mcp_servers: dict[str, MCPServerConfig] = {}

        self._act_results: list[ActResult] = []
        self._stdouts: list[str] = []
        self._stderrs: list[str] = []

    @staticmethod
    def name() -> str:
        return "openclaw"

    def version(self) -> str | None:
        return self._version

    @classmethod
    def workspace_config(cls) -> dict:
        return {"image": {"name": DEFAULT_IMAGE}}

    @property
    def system_prompt(self) -> str | None:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str | None) -> None:
        self._system_prompt = value
        self._write_config()

    def setup(self, workspace, conn_info: dict) -> None:
        self._workspace = workspace
        self._workspace.shell.exec(
            f"mkdir -p {TERRARIUM_DIR} && chmod 1777 {TERRARIUM_DIR}",
            user="root",
        )
        self._ensure_installed()
        self._version = self._detect_version()
        self._write_config()
        self._session_id = str(uuid.uuid4())
        logger.info("OpenClaw agent ready: version={}", self._version)

    def _ensure_installed(self) -> None:
        check = self._workspace.shell.exec("command -v openclaw")
        if check.exit_code == 0:
            return
        logger.info("OpenClaw CLI not found in workspace, installing...")
        result = self._workspace.shell.exec(OPENCLAW_INSTALL_SCRIPT, user="root")
        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to install OpenClaw CLI (exit {result.exit_code}): "
                f"{result.stderr or result.stdout}"
            )

    def install_skill(self, path: str | Path) -> None:
        """Install a skill into the agent. Uploads to <skills_dir>/<name>."""
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
        return f"{TERRARIUM_DIR}/workspace/skills"

    def add_mcp_server(self, config: MCPServerConfig) -> None:
        self._mcp_servers[config.name] = config
        self._write_config()

    def act(self, instruction: str) -> ActResult:
        command = self._build_command(instruction)
        logger.info("OpenClaw act: instruction={}", instruction)

        result = self._workspace.shell.exec(command)
        self._stdouts.append(result.stdout or "")
        self._stderrs.append(result.stderr or "")
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

    def collect_logs(self, dest_dir: Path) -> None:
        stdout = "".join(f"=== turn {i} ===\n{s}\n" for i, s in enumerate(self._stdouts, 1))
        stderr = "".join(f"=== turn {i} ===\n{s}\n" for i, s in enumerate(self._stderrs, 1))
        (dest_dir / "stdout.txt").write_text(stdout)
        (dest_dir / "stderr.txt").write_text(stderr)
        self._workspace.fs.download(f"{SESSION_DIR}/{self._session_id}.jsonl", str(dest_dir / "session.jsonl"))

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
        config: dict = {
            "agents": {
                "defaults": {
                    "workspace": f"{TERRARIUM_DIR}/workspace",
                    "model": {"primary": self._model},
                },
            },
            "tools": {
                "exec": {
                    "security": "full",
                    "ask": "off",
                },
            },
            "models": self._models_config,
        }
        if self._system_prompt:
            config["agents"]["defaults"]["systemPromptOverride"] = self._system_prompt
        if self._mcp_servers:
            config["mcp"] = {
                "servers": {
                    name: (
                        {"transport": "stdio", "command": c.command, "args": c.args, "env": c.env}
                        if c.transport == "stdio"
                        else {"transport": c.transport, "url": c.url, "headers": c.headers}
                    )
                    for name, c in self._mcp_servers.items()
                },
            }
        self._workspace.fs.write_file(CONFIG_PATH, json.dumps(config, indent=2).encode())

    def _build_command(self, instruction: str) -> str:
        parts = [
            f"OPENCLAW_STATE_DIR={shlex.quote(TERRARIUM_DIR)}",
            f"OPENCLAW_CONFIG_PATH={shlex.quote(CONFIG_PATH)}",
            "openclaw", "agent",
            "--local",
            "--json",
            f"--session-id {shlex.quote(self._session_id)}",
            f"--message {shlex.quote(instruction)}",
        ]
        return " ".join(parts)

    def _read_new_session_entries(self) -> tuple[list[Message], dict[str, int]]:
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


