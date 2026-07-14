"""Unit tests for MiniAgent (no network required)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from terrarium.agent.mini import MiniAgent
from terrarium.models.trajectory import TextBlock, ToolResultBlock, ToolUseBlock


class _User(BaseModel):
    id: str
    name: str


# ── MiniAgent basics ─────────────────────────────────────────


class TestMiniAgentBasics:
    def test_name_and_version(self):
        assert MiniAgent.name() == "mini"
        agent = MiniAgent(model="gpt-4.1")
        assert agent.version() is not None

    def test_workspace_config_is_none(self):
        assert MiniAgent.workspace_config() is None

    def test_setup_noop(self):
        agent = MiniAgent(model="gpt-4.1")
        agent.setup(workspace=None, conn_info={})  # should not raise

    def test_register_tools_single(self):
        def get_user(user_id: str) -> str:
            """Get a user."""
            return user_id

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(get_user)
        assert "get_user" in agent._tools
        assert len(agent._tool_schemas) == 1
        assert agent._tool_schemas[0]["function"]["name"] == "get_user"

    def test_register_tools_multiple(self):
        def a(x: int):
            """a"""
            pass

        def b(y: str):
            """b"""
            pass

        def c():
            """c"""
            pass

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(a, b, c)
        assert set(agent._tools.keys()) == {"a", "b", "c"}
        assert len(agent._tool_schemas) == 3

    def test_init_with_system_prompt_and_tools(self):
        def search(query: str) -> list:
            """Search for things."""
            return []

        def lookup(id: str) -> dict:
            """Look up by id."""
            return {}

        agent = MiniAgent(
            model="gpt-4.1",
            system_prompt="You are helpful.",
            tools=[search, lookup],
        )
        assert agent._system_prompt == "You are helpful."
        assert "search" in agent._tools
        assert "lookup" in agent._tools
        assert len(agent._tool_schemas) == 2



# ── act() with mocked litellm ────────────────────────────────


def _mock_llm_response(content: str | None = None, tool_calls: list[dict] | None = None,
                       prompt_tokens: int = 10, completion_tokens: int = 20):
    """Build a MagicMock that mimics a litellm ModelResponse.

    ``tool_calls[i]["arguments"]`` accepts either a dict (json.dumps'd into a
    valid JSON string) or a raw str (passed through untouched, useful for
    simulating an LLM that emits malformed JSON).
    """
    msg = MagicMock()
    msg.content = content
    if tool_calls:
        mock_calls = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.id = tc["id"]
            mock_tc.function.name = tc["name"]
            args = tc["arguments"]
            mock_tc.function.arguments = args if isinstance(args, str) else json.dumps(args)
            mock_calls.append(mock_tc)
        msg.tool_calls = mock_calls
    else:
        msg.tool_calls = None

    choice = MagicMock()
    choice.message = msg

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    # Explicit None so MagicMock's auto-attribute creation doesn't silently
    # turn prompt_tokens_details into a mock that pydantic later coerces to 1.
    usage.prompt_tokens_details = None

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


class TestAct:
    def test_plain_text_response(self):
        agent = MiniAgent(model="gpt-4.1")
        agent.system_prompt = "You are a helper."

        with patch("litellm.completion", return_value=_mock_llm_response(content="Hello!")):
            result = agent.act("Hi")

        assert len(result.messages) == 2
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hi"
        assert result.messages[1].role == "assistant"
        assert isinstance(result.messages[1].content[0], TextBlock)
        assert result.messages[1].content[0].text == "Hello!"
        assert result.input_tokens == 10
        assert result.output_tokens == 20

    def test_tool_call_loop(self):
        calls = []

        def get_user(user_id: str) -> dict:
            """Get user."""
            calls.append(user_id)
            return {"id": user_id, "name": "Alice"}

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(get_user)

        responses = [
            _mock_llm_response(tool_calls=[
                {"id": "tc_1", "name": "get_user", "arguments": {"user_id": "alice"}}
            ]),
            _mock_llm_response(content="Found Alice.", prompt_tokens=15, completion_tokens=5),
        ]
        with patch("litellm.completion", side_effect=responses):
            result = agent.act("who is alice?")

        assert calls == ["alice"]
        # Trajectory: user, assistant(tool_use), user(tool_result), assistant(final text)
        assert len(result.messages) == 4
        assert result.messages[0].role == "user"
        assert result.messages[1].role == "assistant"
        assert isinstance(result.messages[1].content[0], ToolUseBlock)
        assert result.messages[1].content[0].name == "get_user"
        assert result.messages[2].role == "user"
        assert isinstance(result.messages[2].content[0], ToolResultBlock)
        assert result.messages[3].role == "assistant"
        assert result.messages[3].content[0].text == "Found Alice."
        # Usage accumulates across turns
        assert result.input_tokens == 25
        assert result.output_tokens == 25

    def test_unknown_tool_crashes(self):
        # Protocol violations (unknown tool name) bubble out of act() so
        # Trial-level retry can take over, matching tau-bench's semantics.
        agent = MiniAgent(model="gpt-4.1")

        responses = [
            _mock_llm_response(tool_calls=[
                {"id": "tc_1", "name": "nonexistent", "arguments": {}}
            ]),
        ]
        with patch("litellm.completion", side_effect=responses):
            with pytest.raises(KeyError, match="nonexistent"):
                agent.act("call nonexistent")

    def test_bad_json_arguments_crashes(self):
        # Malformed JSON is also a protocol violation — the LLM can't
        # self-correct on a parse error, so it crashes out to Trial retry.
        def get_user(user_id: str) -> str:
            """Get a user."""
            return user_id

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(get_user)

        responses = [
            _mock_llm_response(tool_calls=[
                # Raw str bypasses json.dumps in the helper.
                {"id": "tc_1", "name": "get_user", "arguments": '{"user_id": alice'}
            ]),
        ]
        with patch("litellm.completion", side_effect=responses):
            with pytest.raises(json.JSONDecodeError):
                agent.act("bad json")

    def test_tool_exception_returns_error(self):
        def bad(x: int) -> int:
            """Always fails."""
            raise ValueError("boom")

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(bad)

        responses = [
            _mock_llm_response(tool_calls=[
                {"id": "tc_1", "name": "bad", "arguments": {"x": 1}}
            ]),
            _mock_llm_response(content="ok"),
        ]
        with patch("litellm.completion", side_effect=responses):
            result = agent.act("call bad")

        tool_result = result.messages[2].content[0]
        assert "boom" in tool_result.content

    def test_max_tool_calls(self):
        def loop():
            """A tool that always gets called again."""
            return "result"

        agent = MiniAgent(model="gpt-4.1", max_tool_calls=3)
        agent.register_tools(loop)

        # Infinitely return tool calls
        def infinite_tc(*a, **kw):
            return _mock_llm_response(tool_calls=[
                {"id": f"tc_{id(object())}", "name": "loop", "arguments": {}}
            ])

        with patch("litellm.completion", side_effect=infinite_tc):
            with pytest.raises(RuntimeError, match="max_tool_calls"):
                agent.act("loop forever")

    def test_multi_turn_preserves_history(self):
        agent = MiniAgent(model="gpt-4.1")

        responses = [
            _mock_llm_response(content="Hi there"),
            _mock_llm_response(content="I'm good"),
        ]
        with patch("litellm.completion", side_effect=responses) as mock:
            agent.act("Hello")
            agent.act("How are you?")

        # Second call should have seen the full history: user, assistant, user
        second_call_messages = mock.call_args_list[1].kwargs["messages"]
        roles = [m["role"] for m in second_call_messages]
        assert roles == ["user", "assistant", "user"]
        assert second_call_messages[0]["content"] == "Hello"

    def test_pydantic_tool_result_serialized(self):
        def get_user(user_id: str) -> _User:
            """Get user."""
            return _User(id=user_id, name="Alice")

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(get_user)

        responses = [
            _mock_llm_response(tool_calls=[
                {"id": "tc_1", "name": "get_user", "arguments": {"user_id": "a"}}
            ]),
            _mock_llm_response(content="done"),
        ]
        with patch("litellm.completion", side_effect=responses):
            result = agent.act("who?")

        tool_result = result.messages[2].content[0].content
        parsed = json.loads(tool_result)
        assert parsed == {"id": "a", "name": "Alice"}


class TestTrajectory:
    def test_aggregates_across_acts(self):
        agent = MiniAgent(model="gpt-4.1")
        responses = [
            _mock_llm_response(content="A", prompt_tokens=5, completion_tokens=2),
            _mock_llm_response(content="B", prompt_tokens=7, completion_tokens=3),
        ]
        with patch("litellm.completion", side_effect=responses):
            agent.act("first")
            agent.act("second")

        traj = agent.get_trajectory()
        assert len(traj.messages) == 4  # 2 user + 2 assistant
        assert traj.metrics.total_input_tokens == 12
        assert traj.metrics.total_output_tokens == 5
        assert traj.metrics.total_turns == 2

    def test_counts_tool_calls(self):
        def foo():
            """foo"""
            return "ok"

        agent = MiniAgent(model="gpt-4.1")
        agent.register_tools(foo)
        responses = [
            _mock_llm_response(tool_calls=[
                {"id": "t1", "name": "foo", "arguments": {}}
            ]),
            _mock_llm_response(content="done"),
        ]
        with patch("litellm.completion", side_effect=responses):
            agent.act("call")

        traj = agent.get_trajectory()
        assert traj.metrics.total_tool_calls == 1
