"""Codex agent adapter.

Runs OpenAI Codex CLI inside a pre-built Docker container (terrarium/codex).
Multi-turn conversations use `codex exec resume <session_id>` for continuity.
Trajectory is reconstructed from session JSONL files at
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.
"""
from __future__ import annotations

import json
import os
import re
import shlex

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

DEFAULT_IMAGE = "terrarium/codex:latest"
CODEX_HOME = "/root/.codex"
SESSION_DIR = f"{CODEX_HOME}/sessions"
AUTH_PATH = f"{CODEX_HOME}/auth.json"


class CodexAgent(BaseAgent):
    """Codex CLI agent running inside the workspace container.

    Requires a Docker image with Codex pre-installed.
    Build with: docker build -t terrarium/codex -f docker/codex.Dockerfile docker/
    """

    def __init__(
        self,
        model: str = "gpt-5.4",
        api_key: str | None = None,
    ):
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

        self._workspace = None
        self._session_id: str | None = None
        self._session_file: str | None = None
        self._version: str | None = None
        self._session_entry_count: int = 0

        self._act_results: list[ActResult] = []

    @staticmethod
    def name() -> str:
        return "codex"

    def version(self) -> str | None:
        return self._version

    @classmethod
    def workspace_config(cls) -> dict:
        return {"image": DEFAULT_IMAGE}

    def setup(self, workspace, conn_info: dict) -> None:
        self._workspace = workspace
        self._version = self._detect_version()
        self._write_auth()
        logger.info("Codex agent ready: version={}", self._version)

    def act(self, instruction: str) -> ActResult:
        command = self._build_command(instruction)
        logger.info("Codex act: instruction={}", instruction)

        result = self._workspace.shell.exec(command)
        if result.exit_code != 0:
            logger.warning("Codex exit {}: {}", result.exit_code, result.stderr or "")

        messages, usage, session_id = self._read_new_session_entries()
        if self._session_id is None:
            assert session_id is not None
            self._session_id = session_id

        act_result = ActResult(
            messages=messages,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cached_input_tokens", 0),
        )
        self._act_results.append(act_result)
        return act_result

    def get_trajectory(self) -> Trajectory:
        messages = []
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_tool_calls = 0
        for r in self._act_results:
            messages.extend(r.messages)
            total_input += r.input_tokens
            total_output += r.output_tokens
            total_cache_read += r.cache_read_tokens
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
                total_llm_calls=len(self._act_results) or None,
                total_tool_calls=total_tool_calls or None,
            ),
        )

    def _detect_version(self) -> str:
        result = self._workspace.shell.exec("codex --version")
        if result.exit_code != 0:
            raise RuntimeError(f"codex --version failed (exit {result.exit_code}): {result.stderr or ''}")
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else result.stdout.strip()

    def _write_auth(self) -> None:
        auth = json.dumps({"OPENAI_API_KEY": self._api_key}).encode()
        self._workspace.fs.make_dir(CODEX_HOME)
        self._workspace.fs.write_file(AUTH_PATH, auth)

    def _read_new_session_entries(self) -> tuple[list[Message], dict[str, int], str | None]:
        if self._session_file is None:
            result = self._workspace.shell.exec(f"find {SESSION_DIR} -name 'rollout-*.jsonl' -type f")
            paths = [p for p in (result.stdout or "").strip().split("\n") if p]
            if len(paths) != 1:
                raise RuntimeError(f"Expected exactly 1 Codex session file, found {len(paths)}: {paths}")
            self._session_file = paths[0]
        raw = self._workspace.fs.read_file(self._session_file)
        lines = raw.decode().strip().split("\n")
        new_lines = lines[self._session_entry_count:]
        self._session_entry_count = len(lines)
        return parse_codex_session(new_lines)

    def _build_command(self, instruction: str) -> str:
        return f"{self._build_env_vars()}codex {self._build_subcommand()} {self._build_flags()}{shlex.quote(instruction)}"

    def _build_env_vars(self) -> str:
        parts = [
            f"OPENAI_API_KEY={shlex.quote(self._api_key)}",
        ]
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            parts.append(f"OPENAI_BASE_URL={shlex.quote(base_url)}")
        return " ".join(parts) + " "

    def _build_subcommand(self) -> str:
        if self._session_id is None:
            return "exec"
        return f"exec resume {shlex.quote(self._session_id)}"

    def _build_flags(self) -> str:
        parts = [
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            f"--model {shlex.quote(self._model)}",
        ]
        return " ".join(parts) + " "


def parse_codex_session(lines: list[str]) -> tuple[list[Message], dict[str, int], str | None]:
    """Parse Codex session JSONL lines into messages, usage totals, and session ID.

    Event types handled:
    - session_meta: contains session ID in payload.id
    - response_item: message, reasoning, function_call, function_call_output,
                     custom_tool_call, custom_tool_call_output, web_search_call
    - event_msg (type=token_count): contains per-call last_token_usage
    """
    messages: list[Message] = []
    usage: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
    }
    session_id: str | None = None
    reasoning: list[ThinkingBlock] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse Codex session line: {}", e)
            continue

        event_type = event.get("type")
        payload = event.get("payload", {})

        if event_type == "session_meta":
            session_id = payload.get("id")

        elif event_type == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            last = info.get("last_token_usage") or {}
            usage["input_tokens"] += last.get("input_tokens") or 0
            usage["output_tokens"] += (last.get("output_tokens") or 0) + (last.get("reasoning_output_tokens") or 0)
            usage["cached_input_tokens"] += last.get("cached_input_tokens") or 0

        elif event_type == "response_item":
            item_type = payload.get("type")

            if item_type == "reasoning":
                reasoning = [
                    ThinkingBlock(thinking=item["text"])
                    for item in payload.get("summary") or []
                    if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
                ]
                continue

            if item_type == "message":
                role = payload["role"]
                blocks: list[ContentBlock] = [
                    TextBlock(text=b["text"])
                    for b in payload.get("content", [])
                    if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()
                ]
                if blocks:
                    prefix = reasoning if role == "assistant" else []
                    messages.append(Message(role=role, content=prefix + blocks))

            elif item_type == "function_call":
                messages.append(Message(role="assistant", content=reasoning + [ToolUseBlock(
                    id=payload.get("call_id", ""),
                    name=payload.get("name", ""),
                    input=_parse_json_arguments(payload.get("arguments", "{}")),
                )]))

            elif item_type == "custom_tool_call":
                messages.append(Message(role="assistant", content=reasoning + [ToolUseBlock(
                    id=payload.get("call_id", ""),
                    name=payload.get("name", ""),
                    input=_parse_json_arguments(payload.get("input", "{}")),
                )]))

            elif item_type == "web_search_call":
                action = payload.get("action") or {}
                args: dict = {"action_type": action.get("type", "")}
                for key in ("query", "queries", "url", "pattern"):
                    if key in action:
                        args[key] = action[key]
                messages.append(Message(role="assistant", content=reasoning + [ToolUseBlock(
                    id=payload.get("id", ""),
                    name="web_search_call",
                    input=args,
                )]))

            elif item_type in ("function_call_output", "custom_tool_call_output"):
                messages.append(Message(role="user", content=[ToolResultBlock(
                    tool_use_id=payload.get("call_id", ""),
                    content=payload.get("output", ""),
                )]))

            reasoning = []

    return messages, usage, session_id


def _parse_json_arguments(arguments) -> dict:
    try:
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        if isinstance(arguments, str):
            return {"input": arguments}
        if arguments is None:
            return {}
        return {"value": arguments}
