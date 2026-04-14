"""Tests for trajectory models."""
from terrarium.models.trajectory import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Trajectory,
    TrajectoryMetrics,
)


class TestTextBlock:
    def test_create(self):
        b = TextBlock(text="hello")
        assert b.type == "text"
        assert b.text == "hello"


class TestThinkingBlock:
    def test_create(self):
        b = ThinkingBlock(thinking="Let me think...")
        assert b.type == "thinking"
        assert b.thinking == "Let me think..."


class TestToolUseBlock:
    def test_create(self):
        b = ToolUseBlock(id="call_1", name="Bash", input={"command": "ls"})
        assert b.type == "tool_use"
        assert b.id == "call_1"
        assert b.name == "Bash"
        assert b.input == {"command": "ls"}

    def test_empty_input(self):
        b = ToolUseBlock(id="call_2", name="Read")
        assert b.input == {}


class TestToolResultBlock:
    def test_create(self):
        b = ToolResultBlock(tool_use_id="call_1", content="file1.txt")
        assert b.type == "tool_result"
        assert b.tool_use_id == "call_1"

    def test_no_content(self):
        b = ToolResultBlock(tool_use_id="call_1")
        assert b.content is None


class TestMessage:
    def test_simple_string(self):
        m = Message(role="user", content="Hello")
        assert m.role == "user"
        assert m.content == "Hello"

    def test_content_blocks(self):
        m = Message(role="assistant", content=[
            ThinkingBlock(thinking="Let me think..."),
            TextBlock(text="The answer is 42."),
            ToolUseBlock(id="call_1", name="Bash", input={"command": "ls"}),
        ])
        assert isinstance(m.content, list)
        assert len(m.content) == 3
        assert isinstance(m.content[0], ThinkingBlock)
        assert isinstance(m.content[1], TextBlock)
        assert isinstance(m.content[2], ToolUseBlock)

    def test_user_with_tool_result(self):
        m = Message(role="user", content=[
            ToolResultBlock(tool_use_id="call_1", content="output"),
        ])
        assert isinstance(m.content, list)
        assert isinstance(m.content[0], ToolResultBlock)

    def test_default_content(self):
        m = Message(role="user")
        assert m.content == ""


class TestTrajectory:
    def test_create(self):
        t = Trajectory(messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ])
        assert len(t.messages) == 2
        assert t.metrics is None

    def test_with_metrics(self):
        t = Trajectory(
            messages=[Message(role="user", content="hi")],
            metrics=TrajectoryMetrics(total_input_tokens=100, total_llm_calls=1),
        )
        assert t.metrics.total_input_tokens == 100

    def test_serialization(self):
        t = Trajectory(messages=[
            Message(role="assistant", content=[
                ToolUseBlock(id="c1", name="Bash", input={"command": "ls"}),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="c1", content="file.txt"),
            ]),
        ])
        data = t.model_dump()
        t2 = Trajectory.model_validate(data)
        assert len(t2.messages) == 2

    def test_metrics_defaults(self):
        m = TrajectoryMetrics()
        assert m.total_input_tokens is None
        assert m.total_llm_calls is None
