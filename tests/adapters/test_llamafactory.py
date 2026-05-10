"""Tests for LlamaFactory export adapters."""
from __future__ import annotations

import json
from pathlib import Path

from terrarium.adapters.llamafactory import (
    build_dataset_info,
    trajectory_to_llamafactory_messages,
    trajectory_to_llamafactory_tools,
    write_llamafactory_sft_dataset,
)
from terrarium.models.checker import Check, CheckerResults
from terrarium.models.common import ExceptionInfo
from terrarium.models.result import AgentInfo, TaskInfo, TrialResult
from terrarium.models.trajectory import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Trajectory,
)


def _checker(score: float = 1.0) -> CheckerResults:
    return CheckerResults(checks=[Check(name="ok", passed=score == 1.0)], score=score)


def _trial_result(trial_name: str, *, failed: bool = False) -> TrialResult:
    exception_info = None
    if failed:
        try:
            raise RuntimeError("trial failed")
        except RuntimeError as e:
            exception_info = ExceptionInfo.from_exception(e)

    return TrialResult(
        trial_name=trial_name,
        task_info=TaskInfo(name="task_a", path="/tmp/task_a", source="sample"),
        agent_info=AgentInfo(name="codex", model_name="gpt-5.4"),
        checker_result=_checker(0.0 if failed else 1.0),
        exception_info=exception_info,
    )


def _write_trial(job_dir: Path, trial_name: str, trajectory: Trajectory | None, *, failed: bool = False) -> None:
    trial_dir = job_dir / trial_name
    trial_dir.mkdir(parents=True)
    (trial_dir / "result.json").write_text(_trial_result(trial_name, failed=failed).model_dump_json(indent=2))
    if trajectory is not None:
        (trial_dir / "trajectory.json").write_text(trajectory.model_dump_json(indent=2))


def _align_like_llamafactory(record: dict, dataset_info_entry: dict) -> dict:
    columns = dataset_info_entry.get("columns", {})
    tags = dataset_info_entry.get("tags", {})
    messages_key = columns.get("messages", "conversations")
    tools_key = columns.get("tools")
    role_tag = tags.get("role_tag", "from")
    content_tag = tags.get("content_tag", "value")
    user_tag = tags.get("user_tag", "human")
    assistant_tag = tags.get("assistant_tag", "gpt")
    observation_tag = tags.get("observation_tag", "observation")
    function_tag = tags.get("function_tag", "function_call")
    system_tag = tags.get("system_tag", "system")
    tag_mapping = {
        user_tag: "user",
        assistant_tag: "assistant",
        observation_tag: "observation",
        function_tag: "function",
        system_tag: "system",
    }

    messages = list(record[messages_key])
    if messages and messages[0][role_tag] == system_tag:
        system = messages[0][content_tag]
        messages = messages[1:]
    else:
        system = ""

    aligned_messages = []
    accept_tags = ((user_tag, observation_tag), (assistant_tag, function_tag))
    for turn_idx, message in enumerate(messages):
        assert message[role_tag] in accept_tags[turn_idx % 2]
        aligned_messages.append({
            "role": tag_mapping[message[role_tag]],
            "content": message[content_tag],
        })

    assert len(aligned_messages) % 2 == 0
    tools = record.get(tools_key, "") if tools_key else ""
    if isinstance(tools, dict) or isinstance(tools, list):
        tools = json.dumps(tools, ensure_ascii=False)

    return {
        "_prompt": aligned_messages[:-1],
        "_response": aligned_messages[-1:],
        "_system": system,
        "_tools": tools,
    }


def test_exported_record_aligns_like_sharegpt_reference_format():
    reference_record = {
        "conversations": [
            {"from": "human", "value": "Add numbers"},
            {"from": "function_call", "value": '{"name": "add", "arguments": {"a": 1, "b": 2}}'},
            {"from": "observation", "value": "3"},
            {"from": "gpt", "value": "3"},
        ],
        "tools": [
            {
                "name": "add",
                "description": "Add two numbers",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["a", "b"],
                },
            }
        ],
    }
    reference_info = {
        "formatting": "sharegpt",
        "columns": {"messages": "conversations", "tools": "tools"},
    }
    exported_record = {
        "messages": [
            {"role": "user", "content": "Add numbers"},
            {"role": "function_call", "content": '{"name": "add", "arguments": {"a": 1, "b": 2}}'},
            {"role": "observation", "content": "3"},
            {"role": "assistant", "content": "3"},
        ],
        "tools": reference_record["tools"],
    }
    exported_info = build_dataset_info("terrarium_job")["terrarium_job"]

    assert _align_like_llamafactory(exported_record, exported_info) == _align_like_llamafactory(
        reference_record,
        reference_info,
    )


def test_converts_text_tool_and_observation_blocks_to_llamafactory_messages():
    trajectory = Trajectory(messages=[
        Message(role="user", content="List files"),
        Message(role="assistant", content=[
            ThinkingBlock(thinking="Need a shell command"),
            ToolUseBlock(id="call_1", name="exec_command", input={"cmd": "ls"}),
        ]),
        Message(role="user", content=[
            ToolResultBlock(tool_use_id="call_1", content="a.txt\n"),
        ]),
        Message(role="assistant", content=[
            TextBlock(text="Found a.txt"),
        ]),
    ])

    messages = trajectory_to_llamafactory_messages(trajectory)

    assert messages == [
        {"role": "user", "content": "List files"},
        {"role": "function_call", "content": '{"arguments": {"cmd": "ls"}, "name": "exec_command"}'},
        {"role": "observation", "content": "a.txt\n"},
        {"role": "assistant", "content": "Found a.txt"},
    ]


def test_can_include_thinking_blocks():
    trajectory = Trajectory(messages=[
        Message(role="user", content="Question"),
        Message(role="assistant", content=[
            ThinkingBlock(thinking="Reasoning"),
            TextBlock(text="Answer"),
        ]),
    ])

    messages = trajectory_to_llamafactory_messages(trajectory, include_thinking=True)

    assert messages == [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "<thinking>\nReasoning\n</thinking>\n\nAnswer"},
    ]


def test_drops_orphan_assistant_turns_that_cannot_form_sft_pairs():
    trajectory = Trajectory(messages=[
        Message(role="assistant", content="Answer without prompt"),
    ])

    assert trajectory_to_llamafactory_messages(trajectory) == []


def test_combines_multiple_tool_calls_into_one_function_turn():
    trajectory = Trajectory(messages=[
        Message(role="user", content="Call tools"),
        Message(role="assistant", content=[
            TextBlock(text="I will call tools."),
            ToolUseBlock(id="call_1", name="lookup_a", input={"id": "a"}),
            ToolUseBlock(id="call_2", name="lookup_b", input={"id": "b"}),
        ]),
        Message(role="user", content=[
            ToolResultBlock(tool_use_id="call_1", content="A"),
            ToolResultBlock(tool_use_id="call_2", content="B"),
        ]),
        Message(role="assistant", content="Done"),
    ])

    messages = trajectory_to_llamafactory_messages(trajectory)

    assert messages == [
        {"role": "user", "content": "Call tools"},
        {
            "role": "function_call",
            "content": '[{"arguments": {"id": "a"}, "name": "lookup_a"}, {"arguments": {"id": "b"}, "name": "lookup_b"}]',
        },
        {"role": "observation", "content": "A\n</tool_response>\n<tool_response>\nB"},
        {"role": "assistant", "content": "Done"},
    ]


def test_preserves_leading_system_message():
    trajectory = Trajectory(messages=[
        Message(role="system", content="You are careful."),
        Message(role="user", content="Hi"),
        Message(role="assistant", content="Hello"),
    ])

    messages = trajectory_to_llamafactory_messages(trajectory)

    assert messages == [
        {"role": "system", "content": "You are careful."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]


def test_ignores_mid_sequence_system_message_instead_of_corrupting_turns():
    trajectory = Trajectory(messages=[
        Message(role="user", content="Hi"),
        Message(role="system", content="Late system prompt"),
        Message(role="assistant", content="Hello"),
    ])

    messages = trajectory_to_llamafactory_messages(trajectory)

    assert messages == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]


def test_builds_dataset_info_for_openai_style_sharegpt():
    assert build_dataset_info("terrarium_job") == {
        "terrarium_job": {
            "file_name": "data.json",
            "formatting": "sharegpt",
            "columns": {
                "messages": "messages",
                "tools": "tools",
            },
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
                "function_tag": "function_call",
                "observation_tag": "observation",
            },
        }
    }


def test_writes_llamafactory_dataset_from_job_outputs(tmp_path):
    job_dir = tmp_path / "Job 01"
    _write_trial(
        job_dir,
        "trial_a",
        Trajectory(messages=[
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello"),
        ]),
    )
    _write_trial(
        job_dir,
        "trial_failed",
        Trajectory(messages=[
            Message(role="user", content="Broken"),
            Message(role="assistant", content="Nope"),
        ]),
        failed=True,
    )
    _write_trial(job_dir, "trial_missing_trajectory", None)
    _write_trial(
        job_dir,
        "trial_empty",
        Trajectory(messages=[Message(role="user", content="Only user")]),
    )

    result = write_llamafactory_sft_dataset(job_dir, tmp_path / "out")

    assert result.dataset_name == "job_01"
    assert result.n_trials_seen == 4
    assert result.n_records_written == 1
    assert result.n_failed_trials_skipped == 1
    assert result.n_missing_trajectory_skipped == 1
    assert result.n_empty_trajectory_skipped == 1

    data = json.loads(result.data_path.read_text())
    assert data == [
        {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            "tools": [],
        }
    ]

    dataset_info = json.loads(result.dataset_info_path.read_text())
    assert dataset_info["job_01"]["file_name"] == "data.json"
    assert dataset_info["job_01"]["columns"]["tools"] == "tools"


def test_infers_tools_column_from_trajectory_tool_calls():
    trajectory = Trajectory(messages=[
        Message(role="user", content="Call tools"),
        Message(role="assistant", content=[
            ToolUseBlock(id="call_1", name="lookup", input={
                "id": "a",
                "limit": 3,
                "exact": True,
                "tags": ["x"],
                "filters": {"kind": "demo"},
            }),
            ToolUseBlock(id="call_2", name="lookup", input={"id": "b"}),
        ]),
    ])

    tools = trajectory_to_llamafactory_tools(trajectory)

    assert tools == [
        {
            "name": "lookup",
            "description": "Tool captured from Terrarium trajectory: lookup",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "limit": {"type": "integer"},
                    "exact": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                },
                "required": ["id", "limit", "exact", "tags", "filters"],
            },
        }
    ]


def test_writes_tools_column_for_tool_call_trajectories(tmp_path):
    job_dir = tmp_path / "job"
    _write_trial(
        job_dir,
        "trial_tool",
        Trajectory(messages=[
            Message(role="user", content="Add numbers"),
            Message(role="assistant", content=[
                ToolUseBlock(id="call_1", name="add", input={"a": 1, "b": 2}),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="call_1", content="3"),
            ]),
            Message(role="assistant", content="3"),
        ]),
    )

    result = write_llamafactory_sft_dataset(job_dir, tmp_path / "out")

    data = json.loads(result.data_path.read_text())
    assert data == [
        {
            "messages": [
                {"role": "user", "content": "Add numbers"},
                {"role": "function_call", "content": '{"arguments": {"a": 1, "b": 2}, "name": "add"}'},
                {"role": "observation", "content": "3"},
                {"role": "assistant", "content": "3"},
            ],
            "tools": [
                {
                    "name": "add",
                    "description": "Tool captured from Terrarium trajectory: add",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                }
            ],
        }
    ]


def test_include_failed_exports_failed_trials(tmp_path):
    job_dir = tmp_path / "job"
    _write_trial(
        job_dir,
        "trial_failed",
        Trajectory(messages=[
            Message(role="user", content="Broken"),
            Message(role="assistant", content="Nope"),
        ]),
        failed=True,
    )

    result = write_llamafactory_sft_dataset(job_dir, tmp_path / "out", include_failed=True)

    assert result.n_records_written == 1
    assert result.n_failed_trials_skipped == 0
