"""Hermes agent adapter.

Runs hermes-agent CLI inside a pre-built Docker container (terrarium/hermes).
Multi-turn conversations use `--resume <session_id>` for continuity.
Trajectory is reconstructed from `hermes sessions export -` output.
"""
from __future__ import annotations

import json
import re
import shlex
from itertools import groupby
from pathlib import Path
from typing import Any

import yaml
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

DEFAULT_IMAGE = "terrarium/hermes:latest"
TERRARIUM_DIR = "/terrarium/hermes"
CONFIG_PATH = f"{TERRARIUM_DIR}/config.yaml"

HERMES_INSTALL_SCRIPT = f"""\
set -e
export HERMES_HOME={TERRARIUM_DIR}
export DEBIAN_FRONTEND=noninteractive
if command -v apk >/dev/null 2>&1; then
    apk add --no-cache curl bash git xz
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y curl git xz-utils
    elif command -v yum >/dev/null 2>&1; then yum install -y curl git xz
    else echo "No supported package manager (apk/apt-get/yum)" >&2; exit 1
    fi
fi
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
"""


class HermesAgent(BaseAgent):
    """Hermes CLI agent running inside the workspace container.

    Requires a Docker image with hermes-agent pre-installed.
    Build with: docker build -t terrarium/hermes -f docker/hermes.Dockerfile docker/
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        model_config_path: str = "",
    ):
        self._model = model
        self._model_config = yaml.safe_load(Path(model_config_path).read_text())

        self._workspace = None
        self._session_id: str | None = None
        self._version: str | None = None
        self._session_entry_count: int = 0
        self._last_usage: dict[str, int] = {}
        self._mcp_servers: dict[str, MCPServerConfig] = {}

        self._act_results: list[ActResult] = []
        self._stdouts: list[str] = []
        self._stderrs: list[str] = []

    @staticmethod
    def name() -> str:
        return "hermes"

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
        self._write_config()
        logger.info("Hermes agent ready: version={}", self._version)

    def _ensure_installed(self) -> None:
        check = self._workspace.shell.exec("command -v hermes")
        if check.exit_code == 0:
            return
        logger.info("Hermes CLI not found in workspace, installing...")
        result = self._workspace.shell.exec(HERMES_INSTALL_SCRIPT, user="root")
        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to install Hermes CLI (exit {result.exit_code}): "
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
        return f"{TERRARIUM_DIR}/skills"

    def add_mcp_server(self, config: MCPServerConfig) -> None:
        self._mcp_servers[config.name] = config
        self._write_config()

    def act(self, instruction: str) -> ActResult:
        command = self._build_command(instruction)
        logger.info("Hermes act: instruction={}", instruction)

        result = self._workspace.shell.exec(command)
        self._stdouts.append(result.stdout or "")
        self._stderrs.append(result.stderr or "")
        if result.exit_code != 0:
            logger.warning("Hermes exit {}: {}", result.exit_code, result.stderr or "")

        messages, usage, session_id = self._read_new_session_entries()
        if self._session_id is None:
            assert session_id is not None
            self._session_id = session_id

        act_result = ActResult(
            messages=messages,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_tokens", 0),
        )
        self._act_results.append(act_result)
        return act_result

    def collect_logs(self, dest_dir: Path) -> None:
        stdout = "".join(f"=== turn {i} ===\n{s}\n" for i, s in enumerate(self._stdouts, 1))
        stderr = "".join(f"=== turn {i} ===\n{s}\n" for i, s in enumerate(self._stderrs, 1))
        (dest_dir / "stdout.txt").write_text(stdout)
        (dest_dir / "stderr.txt").write_text(stderr)
        if self._session_id:
            result = self._workspace.shell.exec(self._export_session_command())
            if result.exit_code == 0 and result.stdout:
                (dest_dir / "session.jsonl").write_text(result.stdout)

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
        result = self._workspace.shell.exec("hermes version")
        if result.exit_code != 0:
            raise RuntimeError(f"hermes version failed (exit {result.exit_code}): {result.stderr or ''}")
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else result.stdout.strip()

    def _write_config(self) -> None:
        config: dict[str, Any] = {
            "model": {**self._model_config, "default": self._model},
        }
        if self._mcp_servers:
            servers: dict[str, dict[str, Any]] = {}
            for name, c in self._mcp_servers.items():
                if c.transport == "stdio":
                    servers[name] = {"command": c.command, "args": c.args, "env": c.env}
                elif c.transport == "sse":
                    servers[name] = {"url": c.url, "headers": c.headers, "transport": "sse"}
                else:
                    servers[name] = {"url": c.url, "headers": c.headers}
            config["mcp_servers"] = servers
        self._workspace.fs.write_file(CONFIG_PATH, yaml.dump(config, default_flow_style=False).encode())

    def _build_command(self, instruction: str) -> str:
        parts = [
            f"HERMES_HOME={TERRARIUM_DIR}",
            "hermes", "--yolo", "chat",
            "--quiet",
        ]
        if self._session_id is not None:
            parts.append(f"--resume {shlex.quote(self._session_id)}")
        parts.append(f"--query {shlex.quote(instruction)}")
        return " ".join(parts)

    def _export_session_command(self) -> str:
        parts = [
            f"HERMES_HOME={TERRARIUM_DIR}",
            "hermes sessions export -",
        ]
        if self._session_id is not None:
            parts.append(f"--session-id {shlex.quote(self._session_id)}")
        return " ".join(parts)

    def _read_new_session_entries(self) -> tuple[list[Message], dict[str, int], str | None]:
        result = self._workspace.shell.exec(self._export_session_command())
        if result.exit_code != 0 or not result.stdout:
            raise RuntimeError(
                f"hermes sessions export failed (exit {result.exit_code}): "
                f"{result.stderr or result.stdout}"
            )

        lines = [line for line in result.stdout.strip().split("\n") if line]
        if len(lines) != 1:
            raise RuntimeError(f"Expected exactly 1 hermes session in export, found {len(lines)}")

        entry = json.loads(lines[0])
        all_messages = entry.get("messages") or []
        cumulative_usage = {
            "input_tokens": entry.get("input_tokens") or 0,
            "output_tokens": entry.get("output_tokens") or 0,
            "cache_read_tokens": entry.get("cache_read_tokens") or 0,
            "cache_creation_tokens": entry.get("cache_write_tokens") or 0,
        }

        new_messages = all_messages[self._session_entry_count:]
        self._session_entry_count = len(all_messages)
        usage = {k: v - self._last_usage.get(k, 0) for k, v in cumulative_usage.items()}
        self._last_usage = cumulative_usage
        return _parse_hermes_messages(new_messages), usage, entry.get("id")


def _parse_hermes_messages(messages: list[dict]) -> list[Message]:
    """Parse hermes message dicts.

    Roles handled:
    - user / assistant: reasoning -> ThinkingBlock, content (string or
      list-of-parts) -> TextBlocks, tool_calls -> ToolUseBlocks
    - tool: consecutive entries collapse into one user Message carrying
      multiple ToolResultBlocks
    """
    result: list[Message] = []
    for role, group in groupby(messages, key=lambda m: m.get("role", "")):
        if role == "tool":
            tool_result_blocks: list[ContentBlock] = []
            for entry in group:
                content = entry.get("content")
                if isinstance(content, list):
                    text = "\n".join(p["text"] for p in content if "text" in p)
                elif isinstance(content, str):
                    text = content
                else:
                    text = None
                tool_result_blocks.append(ToolResultBlock(
                    tool_use_id=entry.get("tool_call_id", ""),
                    content=text or None,
                ))
            result.append(Message(role="user", content=tool_result_blocks))
        elif role in ("user", "assistant"):
            for entry in group:
                blocks: list[ContentBlock] = []

                reasoning = entry.get("reasoning_content") or entry.get("reasoning")
                if reasoning:
                    blocks.append(ThinkingBlock(thinking=reasoning))

                content = entry.get("content")
                if isinstance(content, str):
                    if content:
                        blocks.append(TextBlock(text=content))
                else:
                    blocks.extend(
                        TextBlock(text=p["text"])
                        for p in (content or [])
                        if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"]
                    )

                for tc in entry.get("tool_calls") or []:
                    func = tc.get("function", {})
                    blocks.append(ToolUseBlock(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        input=json.loads(func.get("arguments") or "{}"),
                    ))

                if blocks:
                    result.append(Message(role=role, content=blocks))
    return result
