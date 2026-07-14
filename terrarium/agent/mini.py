"""Minimal LLM agent adapter.

Runs in-process (no Docker container). Tools are registered as plain
Python callables with schemas auto-generated from signatures and
docstrings. Uses litellm for provider-agnostic LLM calls.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from typing import Any, Callable

import litellm
from langchain_core.utils.function_calling import convert_to_openai_tool
from litellm import experimental_mcp_client
from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic_core import to_jsonable_python

from terrarium.agent.base import BaseAgent
from terrarium.models.mcp import MCPServerConfig
from terrarium.models.result import ActResult
from terrarium.models.trajectory import (
    ContentBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Trajectory,
    TrajectoryMetrics,
)


class MiniAgent(BaseAgent):
    """Minimal in-process LLM agent with function calling.

    Each act() call runs a single LLM tool-call loop until the model
    produces a plain-text response.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        max_tool_calls: int | None = None,
        system_prompt: str | None = None,
        tools: list[Callable] | None = None,
    ):
        self._model = model
        self._temperature = temperature
        self._max_tool_calls = max_tool_calls
        self._system_prompt: str | None = system_prompt

        self._tools: dict[str, Callable] = {}
        self._tool_schemas: list[dict] = []

        self._mcp_sessions: list[_MCPSession] = []

        self._messages: list[dict] = []
        self._act_results: list[ActResult] = []

        if tools:
            self.register_tools(*tools)

    @staticmethod
    def name() -> str:
        return "mini"

    def version(self) -> str | None:
        return "0.0.1"

    @classmethod
    def workspace_config(cls) -> dict | None:
        return None

    def setup(self, workspace, conn_info: dict) -> None:
        pass

    @property
    def system_prompt(self) -> str | None:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str | None) -> None:
        self._system_prompt = value

    def register_tools(self, *fns: Callable) -> None:
        for fn in fns:
            schema = convert_to_openai_tool(fn)
            name = schema["function"]["name"]
            self._tools[name] = fn
            self._tool_schemas.append(schema)

    def add_mcp_server(self, config: MCPServerConfig) -> None:
        session = _MCPSession(config)
        self._mcp_sessions.append(session)

        def wrap_tool(name: str) -> Callable:
            def call(**kwargs):
                return session.call_tool(name, kwargs)
            return call

        for tool in session.tools:
            name = tool["function"]["name"]
            self._tools[name] = wrap_tool(name)
            self._tool_schemas.append(dict(tool))

    def teardown(self) -> None:
        for session in self._mcp_sessions:
            session.close()

    def act(self, instruction: str) -> ActResult:
        logger.info("MiniAgent act: instruction={}", instruction)
        start = len(self._messages)
        self._messages.append({"role": "user", "content": instruction})
        tool_call_count = 0
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0

        while True:
            messages = []
            if self._system_prompt:
                messages.append({"role": "system", "content": self._system_prompt})
            messages.extend(self._messages)

            response = litellm.completion(
                model=self._model,
                messages=messages,
                tools=self._tool_schemas or None,
                temperature=self._temperature,
            )

            msg = response.choices[0].message
            usage = response.usage
            input_tokens += usage.prompt_tokens or 0
            output_tokens += usage.completion_tokens or 0
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                cache_read_tokens += getattr(details, "cached_tokens", 0) or 0
                cache_creation_tokens += getattr(details, "cache_creation_tokens", 0) or 0

            if not msg.tool_calls:
                self._messages.append({"role": "assistant", "content": msg.content or ""})
                break

            self._messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                tool_call_count += 1
                if self._max_tool_calls is not None and tool_call_count > self._max_tool_calls:
                    raise RuntimeError(
                        f"MiniAgent exceeded max_tool_calls={self._max_tool_calls}"
                    )

                fn = self._tools[tc.function.name]
                args = json.loads(tc.function.arguments)
                try:
                    result_str = _to_llm_string(fn(**args))
                except Exception as e:
                    logger.warning("MiniAgent tool {} raised: {}", tc.function.name, e)
                    result_str = _to_llm_string({"error": str(e)})

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        act_result = ActResult(
            messages=_openai_dicts_to_trajectory(self._messages[start:]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
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
                total_turns=len(self._act_results) or None,
                total_tool_calls=total_tool_calls or None,
            ),
        )


class _MCPSession:
    """Persistent MCP session on a dedicated bg thread+loop. Sync facade over async mcp SDK."""

    def __init__(self, config: MCPServerConfig):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name=f"miniagent-mcp-{config.name}")
        self._thread.start()
        promise: concurrent.futures.Future = concurrent.futures.Future()

        async def _serve():
            stop = asyncio.Event()
            try:
                if config.transport == "stdio":
                    ctx = stdio_client(StdioServerParameters(command=config.command, args=config.args, env=config.env))
                elif config.transport == "sse":
                    ctx = sse_client(config.url, headers=config.headers)
                elif config.transport == "streamable-http":
                    ctx = streamable_http_client(config.url, headers=config.headers)
                else:
                    raise ValueError(f"Unsupported MCP transport: {config.transport!r}")
                async with ctx as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await experimental_mcp_client.load_mcp_tools(session=session, format="openai")
                        promise.set_result((session, tools, stop))
                        await stop.wait()
            except BaseException as e:
                if not promise.done():
                    promise.set_exception(e)
                raise

        self._worker_future = asyncio.run_coroutine_threadsafe(_serve(), self._loop)
        self._session, self.tools, self._stop_event = promise.result()

    def call_tool(self, name: str, args: dict):
        return asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(self._session.call_tool(name, args), timeout=60),
            self._loop,
        ).result()

    def close(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._stop_event.set)
            self._worker_future.result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        except Exception as e:
            logger.warning("MCP session close failed: {}", e)


def _openai_dicts_to_trajectory(openai_messages: list[dict]) -> list[Message]:
    """Convert OpenAI chat-completion dicts into Terrarium trajectory Messages.

    Consecutive tool-result dicts collapse into one user Message with multiple
    ToolResultBlocks, matching the Anthropic content-block shape.
    """
    result: list[Message] = []
    i = 0
    while i < len(openai_messages):
        entry = openai_messages[i]
        role = entry["role"]
        if role == "user":
            result.append(Message(role="user", content=entry["content"]))
            i += 1
        elif role == "assistant":
            blocks: list[ContentBlock] = []
            if entry.get("content"):
                blocks.append(TextBlock(text=entry["content"]))
            for tc in entry.get("tool_calls") or []:
                # Arguments JSON was already validated upstream in act(), so
                # plain json.loads is safe here.
                blocks.append(ToolUseBlock(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    input=json.loads(tc["function"]["arguments"]),
                ))
            if blocks:
                result.append(Message(role="assistant", content=blocks))
            i += 1
        elif role == "tool":
            tool_blocks: list[ContentBlock] = []
            while i < len(openai_messages) and openai_messages[i]["role"] == "tool":
                tool_entry = openai_messages[i]
                tool_blocks.append(ToolResultBlock(
                    tool_use_id=tool_entry["tool_call_id"],
                    content=tool_entry["content"],
                ))
                i += 1
            result.append(Message(role="user", content=tool_blocks))
        else:
            raise ValueError(f"Unexpected OpenAI message role: {role!r}")
    return result


def _to_llm_string(value: Any) -> str:
    """Serialize a tool return value into a string for the LLM wire.

    Uses pydantic_core.to_jsonable_python to cover Pydantic models, dataclasses,
    datetime, Decimal, UUID, bytes and nested combinations. Falls back to str()
    on anything it still can't serialize.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(to_jsonable_python(value))
    except (TypeError, ValueError):
        return str(value)
