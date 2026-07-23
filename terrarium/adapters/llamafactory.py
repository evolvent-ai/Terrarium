"""LlamaFactory SFT export adapter."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from terrarium.models.result import TrialResult
from terrarium.models.trajectory import (
    ContentBlock,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Trajectory,
)

LLAMAFACTORY_DATA_FILE = "data.json"
LLAMAFACTORY_DATASET_INFO_FILE = "dataset_info.json"


@dataclass(frozen=True)
class LlamaFactorySFTExportResult:
    """Summary of a LlamaFactory SFT export."""

    dataset_name: str
    output_dir: Path
    data_path: Path
    dataset_info_path: Path
    n_trials_seen: int
    n_records_written: int
    n_failed_trials_skipped: int
    n_missing_trajectory_skipped: int
    n_empty_trajectory_skipped: int


def trajectory_to_llamafactory_messages(
    trajectory: Trajectory,
) -> list[dict[str, str]]:
    """Convert a Terrarium trajectory to LlamaFactory ShareGPT/OpenAI messages."""
    messages: list[dict[str, str]] = []
    for message in trajectory.messages:
        messages.extend(_message_to_llamafactory_messages(message))
    return _normalize_message_sequence(messages)


def build_dataset_info(
    dataset_name: str,
    *,
    data_file_name: str = LLAMAFACTORY_DATA_FILE,
) -> dict[str, Any]:
    """Build the LlamaFactory dataset_info.json entry for exported SFT data."""
    return {
        dataset_name: {
            "file_name": data_file_name,
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


def load_llamafactory_sft_records(
    job_dir: str | Path,
    *,
    include_failed: bool = False,
) -> tuple[list[dict[str, Any]], LlamaFactorySFTExportResult]:
    """Load LlamaFactory SFT records from a Terrarium job output directory."""
    job_dir = Path(job_dir)
    records: list[dict[str, Any]] = []
    n_trials_seen = 0
    n_failed_trials_skipped = 0
    n_missing_trajectory_skipped = 0
    n_empty_trajectory_skipped = 0

    for result_path in sorted(job_dir.glob("*/result.json")):
        n_trials_seen += 1
        trial_result = TrialResult.model_validate_json(result_path.read_text())
        if trial_result.exception_info is not None and not include_failed:
            n_failed_trials_skipped += 1
            continue

        trajectory_path = result_path.parent / "trajectory.json"
        if not trajectory_path.exists():
            n_missing_trajectory_skipped += 1
            continue

        trajectory = Trajectory.model_validate_json(trajectory_path.read_text())
        messages = trajectory_to_llamafactory_messages(trajectory)
        if not _has_trainable_assistant_turn(messages):
            n_empty_trajectory_skipped += 1
            continue

        records.append({
            "messages": messages,
            "tools": trajectory_to_llamafactory_tools_json(trajectory),
        })

    placeholder_result = LlamaFactorySFTExportResult(
        dataset_name="",
        output_dir=Path(),
        data_path=Path(),
        dataset_info_path=Path(),
        n_trials_seen=n_trials_seen,
        n_records_written=len(records),
        n_failed_trials_skipped=n_failed_trials_skipped,
        n_missing_trajectory_skipped=n_missing_trajectory_skipped,
        n_empty_trajectory_skipped=n_empty_trajectory_skipped,
    )
    return records, placeholder_result


def write_llamafactory_sft_dataset(
    job_dir: str | Path,
    output_dir: str | Path,
    *,
    dataset_name: str | None = None,
    data_file_name: str = LLAMAFACTORY_DATA_FILE,
    include_failed: bool = False,
) -> LlamaFactorySFTExportResult:
    """Write a LlamaFactory SFT dataset from Terrarium job outputs."""
    job_dir = Path(job_dir)
    output_dir = Path(output_dir)
    if not job_dir.is_dir():
        raise FileNotFoundError(f"Job directory not found: {job_dir}")

    records, summary = load_llamafactory_sft_records(
        job_dir,
        include_failed=include_failed,
    )
    if not records:
        raise ValueError(f"No exportable trajectories found in job directory: {job_dir}")

    dataset_name = dataset_name or _default_dataset_name(job_dir)
    data_path = output_dir / data_file_name
    dataset_info_path = output_dir / LLAMAFACTORY_DATASET_INFO_FILE

    output_dir.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    dataset_info_path.write_text(json.dumps(build_dataset_info(dataset_name, data_file_name=data_file_name), indent=2) + "\n")

    return LlamaFactorySFTExportResult(
        dataset_name=dataset_name,
        output_dir=output_dir,
        data_path=data_path,
        dataset_info_path=dataset_info_path,
        n_trials_seen=summary.n_trials_seen,
        n_records_written=len(records),
        n_failed_trials_skipped=summary.n_failed_trials_skipped,
        n_missing_trajectory_skipped=summary.n_missing_trajectory_skipped,
        n_empty_trajectory_skipped=summary.n_empty_trajectory_skipped,
    )


def _message_to_llamafactory_messages(message: Message) -> list[dict[str, str]]:
    if isinstance(message.content, str):
        content = message.content.strip()
        if not content:
            return []
        return [{"role": _message_role(message.role), "content": content}]

    tool_uses = [block for block in message.content if isinstance(block, ToolUseBlock)]
    if tool_uses:
        return [{"role": "function_call", "content": _tool_use_content(tool_uses)}]

    tool_results = [block for block in message.content if isinstance(block, ToolResultBlock)]
    if tool_results:
        return [{"role": "observation", "content": _tool_result_content(tool_results)}]

    converted: list[dict[str, str]] = []
    text_parts: list[str] = []

    def flush_text() -> None:
        content = "\n\n".join(part for part in text_parts if part.strip()).strip()
        text_parts.clear()
        if content:
            converted.append({"role": _message_role(message.role), "content": content})

    for block in message.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ThinkingBlock):
            continue
        else:
            flush_text()
            converted.append({"role": _message_role(message.role), "content": _unknown_block_content(block)})

    flush_text()
    return converted


def trajectory_to_llamafactory_tools(trajectory: Trajectory) -> list[dict[str, Any]]:
    """Infer a LlamaFactory tools column from tool calls in a trajectory."""
    calls_by_name: dict[str, list[ToolUseBlock]] = {}
    for message in trajectory.messages:
        if isinstance(message.content, str):
            continue
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                calls_by_name.setdefault(block.name, []).append(block)
    return [_tool_schema_from_calls(name, calls) for name, calls in calls_by_name.items()]


def trajectory_to_llamafactory_tools_json(trajectory: Trajectory) -> str:
    """Return the JSON string LlamaFactory expects in the tools column."""
    tools = trajectory_to_llamafactory_tools(trajectory)
    return json.dumps(tools, ensure_ascii=False) if tools else ""


def _tool_schema_from_calls(name: str, calls: list[ToolUseBlock]) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    required_names: set[str] = set(calls[0].input) if calls else set()
    for call in calls:
        required_names &= set(call.input)
        for arg_name, value in call.input.items():
            schema = _json_schema_for_value(value)
            if arg_name in properties:
                properties[arg_name] = _merge_json_schemas(properties[arg_name], schema)
            else:
                properties[arg_name] = schema

    return {
        "name": name,
        "description": f"Tool captured from Terrarium trajectory: {name}",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": [arg_name for arg_name in properties if arg_name in required_names],
        },
    }


def _json_schema_for_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        item_schema = _json_schema_for_value(value[0]) if value else {}
        return {"type": "array", "items": item_schema}
    if isinstance(value, dict):
        return {"type": "object"}
    if value is None:
        return {"type": "null"}
    return {}


def _merge_json_schemas(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left == right:
        return left

    left_type = left.get("type")
    right_type = right.get("type")
    if left_type == right_type:
        if left_type == "array":
            return {
                "type": "array",
                "items": _merge_json_schemas(left.get("items", {}), right.get("items", {})),
            }
        return left

    options: list[dict[str, Any]] = []
    for schema in (left, right):
        nested = schema.get("anyOf")
        if isinstance(nested, list):
            candidates = [candidate for candidate in nested if isinstance(candidate, dict)]
        else:
            candidates = [schema]
        for candidate in candidates:
            if candidate not in options:
                options.append(candidate)
    return {"anyOf": options}


def _message_role(role: str) -> str:
    normalized = role.lower()
    if normalized in {"system", "user", "assistant"}:
        return normalized
    if normalized in {"tool", "tool_result", "observation"}:
        return "observation"
    if normalized in {"function", "function_call", "tool_use"}:
        return "function_call"
    return normalized


def _tool_use_content(blocks: list[ToolUseBlock]) -> str:
    calls = [
        {"name": block.name, "arguments": block.input}
        for block in blocks
    ]
    content: dict[str, Any] | list[dict[str, Any]] = calls[0] if len(calls) == 1 else calls
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def _tool_result_content(blocks: list[ToolResultBlock]) -> str:
    return "\n</tool_response>\n<tool_response>\n".join(block.content or "" for block in blocks)


def _unknown_block_content(block: ContentBlock) -> str:
    if hasattr(block, "model_dump_json"):
        return block.model_dump_json()
    return str(block)


def _has_trainable_assistant_turn(messages: list[dict[str, str]]) -> bool:
    return any(message["role"] in {"assistant", "function_call"} for message in messages)


def _normalize_message_sequence(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    leading_system_parts: list[str] = []
    normalized_body: list[dict[str, str]] = []
    for message in messages:
        if message["role"] == "system":
            if not normalized_body and message["content"]:
                leading_system_parts.append(message["content"])
            continue

        if not _is_user_side(message) and not _is_assistant_side(message):
            continue

        if not normalized_body:
            if _is_user_side(message):
                normalized_body.append(message)
            continue

        expected_assistant_side = len(normalized_body) % 2 == 1
        if _is_assistant_side(message) == expected_assistant_side:
            normalized_body.append(message)
        else:
            normalized_body[-1] = _merge_same_side_messages(normalized_body[-1], message)

    if normalized_body and _is_user_side(normalized_body[-1]):
        normalized_body.pop()

    if not normalized_body:
        return []

    if leading_system_parts:
        return [{"role": "system", "content": "\n\n".join(leading_system_parts)}] + normalized_body
    return normalized_body


def _merge_same_side_messages(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    if left["role"] == "function_call" and right["role"] == "function_call":
        return {
            "role": "function_call",
            "content": _merge_json_message_content(left["content"], right["content"]),
        }
    if left["role"] == "function_call":
        return left
    if right["role"] == "function_call":
        return right
    if left["role"] == "observation" or right["role"] == "observation":
        parts = [part for part in (left["content"], right["content"]) if part]
        return {"role": "observation", "content": "\n</tool_response>\n<tool_response>\n".join(parts)}

    return {
        "role": left["role"],
        "content": "\n\n".join(part for part in (left["content"], right["content"]) if part),
    }


def _merge_json_message_content(left: str, right: str) -> str:
    calls: list[Any] = []
    for content in (left, right):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = content
        if isinstance(parsed, list):
            calls.extend(parsed)
        else:
            calls.append(parsed)
    return json.dumps(calls, ensure_ascii=False, sort_keys=True)


def _is_user_side(message: dict[str, str]) -> bool:
    return message["role"] in {"user", "observation"}


def _is_assistant_side(message: dict[str, str]) -> bool:
    return message["role"] in {"assistant", "function_call"}


def _default_dataset_name(job_dir: Path) -> str:
    name = re.sub(r"[^0-9A-Za-z_]+", "_", job_dir.name).strip("_").lower()
    return name or "terrarium_sft"
