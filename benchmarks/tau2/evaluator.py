"""Evaluation logic for tau2-bench tasks.

Implements action matching, DB hash comparison, and communication checking,
aligned with tau2-bench's evaluation semantics.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from loguru import logger

from terrarium.models.checker import Check, CheckerResults
from terrarium.models.trajectory import (
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Trajectory,
)


def _extract_tool_calls(trajectory: Trajectory) -> list[tuple[str, dict]]:
    """Extract (name, arguments) from all ToolUseBlocks in the trajectory."""
    tool_calls = []
    for msg in trajectory.messages:
        if msg.role != "assistant" or not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                tool_calls.append((block.name, block.input))
    return tool_calls


def _extract_tool_calls_with_results(
    trajectory: Trajectory,
) -> list[tuple[str, dict, str | None]]:
    """Extract (name, arguments, result_content) by pairing ToolUseBlocks with ToolResultBlocks.

    Mirrors tau2's get_actions_from_messages: each tool call is paired with its
    corresponding tool result via matching IDs.
    """
    # Collect all tool use blocks with their IDs
    tool_uses: list[tuple[str, str, dict]] = []  # (id, name, args)
    for msg in trajectory.messages:
        if msg.role != "assistant" or not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                tool_uses.append((block.id, block.name, block.input))

    # Collect all tool result blocks keyed by tool_use_id
    tool_results: dict[str, str] = {}
    for msg in trajectory.messages:
        if msg.role != "user" or not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                tool_results[block.tool_use_id] = block.content

    return [
        (name, args, tool_results.get(tool_id))
        for tool_id, name, args in tool_uses
    ]


def _extract_agent_texts(trajectory: Trajectory) -> list[str]:
    """Extract all text content from assistant messages."""
    texts = []
    for msg in trajectory.messages:
        if msg.role != "assistant" or not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if isinstance(block, TextBlock):
                texts.append(block.text)
    return texts


def _action_matches(expected: dict, actual_name: str, actual_args: dict) -> bool:
    """Check if an actual tool call matches an expected action.

    Mirrors tau2's Action.compare_with_tool_call logic:
    - Name must match
    - If compare_args is None, compare all keys from actual_args
    - If compare_args is empty list, name match suffices
    - Otherwise compare only the specified keys
    """
    if expected["name"] != actual_name:
        return False
    compare_args = expected.get("compare_args")
    if compare_args is None:
        compare_args = list(actual_args.keys())
    if len(compare_args) == 0:
        return True
    tool_subset = {k: v for k, v in actual_args.items() if k in compare_args}
    expected_subset = {k: v for k, v in expected["arguments"].items() if k in compare_args}
    return tool_subset == expected_subset


def evaluate_actions(
    expected_actions: list[dict],
    actual_tool_calls: list[tuple[str, dict]],
) -> float:
    """Evaluate action matching. Returns 1.0 if all expected actions found, else 0.0."""
    if not expected_actions:
        return 1.0
    for action in expected_actions:
        found = any(
            _action_matches(action, name, args) for name, args in actual_tool_calls
        )
        if not found:
            return 0.0
    return 1.0


def evaluate_db(predicted_hash: str, gold_hash: str) -> float:
    """Evaluate DB state match. Returns 1.0 if hashes match, else 0.0."""
    return 1.0 if predicted_hash == gold_hash else 0.0


def evaluate_communication(
    expected_info: list[str],
    agent_texts: list[str],
) -> float:
    """Evaluate communication. Returns 1.0 if all info found in agent texts, else 0.0.

    Matching is case-insensitive with commas removed, aligned with tau2.
    """
    if not expected_info:
        return 1.0
    for info_str in expected_info:
        found = False
        for text in agent_texts:
            if info_str.lower() in text.lower().replace(",", ""):
                found = True
                break
        if not found:
            return 0.0
    return 1.0


NL_ASSERTION_SYSTEM_PROMPT = """
TASK
- You will be given a list of expected outcomes and a conversation that was collected during a test case run.
- The conversation is between an agent and a customer.
- Your job is to evaluate whether the agent satisfies each of the expected outcomes.
- Grade each expected outcome individually.

FORMAT
- Your response should be a JSON object with the following fields:
- `reasoning`: a short explanation for your classification
- `metExpectation`: `true` if the agent satisfies the expected outcomes, `false` otherwise
- `expectedOutcome`: repeat the expectation from the input that you are grading

Example response structure:
{
    "results": [
        {
            "expectedOutcome": "<one of the expected outcomes from the input>",
            "reasoning": "<reasoning trace>",
            "metExpectation": <false or true>,
        }
    ]
}
""".strip()

NL_ASSERTION_MODEL = "gpt-4.1-2025-04-14"
NL_ASSERTION_TEMPERATURE = 0.0


def evaluate_nl_assertions(
    nl_assertions: list[str],
    trajectory: Trajectory,
) -> float:
    """Evaluate NL assertions using an LLM judge. Returns 1.0 if all met, else 0.0.

    Mirrors tau2's NLAssertionsEvaluator: sends the full conversation + assertions
    to an LLM which judges each assertion individually.
    """
    import litellm

    if not nl_assertions:
        return 1.0

    trajectory_str = "\n".join(
        f"{msg.role}: {block.text}"
        for msg in trajectory.messages
        if isinstance(msg.content, list)
        for block in msg.content
        if isinstance(block, TextBlock)
    )

    user_prompt = f"""
conversation:
{trajectory_str}

expectedOutcomes:
{nl_assertions}
"""

    response = litellm.completion(
        model=NL_ASSERTION_MODEL,
        messages=[
            {"role": "system", "content": NL_ASSERTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=NL_ASSERTION_TEMPERATURE,
    )

    try:
        result_data = json.loads(response.choices[0].message.content)
        results = result_data.get("results", [])
        return 1.0 if all(r.get("metExpectation", False) for r in results) else 0.0
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("NL assertion LLM response parse failed: {}", e)
        return 0.0


def _to_json_str(resp: Any) -> str:
    """Convert a tool response to a JSON string, matching tau2's Environment.to_json_str."""
    from pydantic import BaseModel

    def _process(resp: Any) -> Any:
        if isinstance(resp, BaseModel):
            return resp.model_dump()
        elif isinstance(resp, str):
            return resp
        elif resp is None:
            return resp
        elif isinstance(resp, (int, float, bool)):
            return str(resp)
        elif isinstance(resp, list):
            return [_process(item) for item in resp]
        elif isinstance(resp, dict):
            return {k: _process(v) for k, v in resp.items()}
        else:
            return str(resp)

    if isinstance(resp, str):
        return resp
    return json.dumps(_process(resp), default=str)


def replay_tool_calls(
    tool_calls: list[tuple[str, dict, str | None]],
    tools_instance: Any,
    mutating_tools: set[str],
) -> None:
    """Replay mutating tool calls on a tools instance to reconstruct DB state.

    Mirrors tau2's Environment.set_state: skips non-mutating tools, executes
    mutating tools, and validates that the response matches the expected response
    from the original trajectory.
    """
    for name, args, expected_content in tool_calls:
        if name not in mutating_tools:
            continue
        try:
            resp = getattr(tools_instance, name)(**args)
        except Exception as e:
            logger.warning("Replay tool {} failed: {}", name, e)
            continue

        if expected_content is not None:
            actual_str = _to_json_str(resp)
            try:
                actual = json.loads(actual_str)
            except json.JSONDecodeError:
                actual = actual_str
            try:
                expected = json.loads(expected_content)
            except json.JSONDecodeError:
                expected = expected_content
            if actual != expected:
                raise ValueError(
                    f"Replay mismatch for {name}:\n"
                    f"  Returned: {actual_str}\n"
                    f"  Expected: {expected_content}"
                )


def evaluate(
    task_data: dict,
    trajectory: Trajectory,
    tools_cls: type,
    db_cls: type,
    db_path: str | None = None,
    stopped_normally: bool = True,
) -> CheckerResults:
    """Run tau2-bench evaluation and return CheckerResults.

    Args:
        task_data: Raw task dict from tasks.json
        trajectory: Agent trajectory from MiniAgent.get_trajectory()
        tools_cls: RetailTools class (for creating fresh instances)
        db_cls: RetailDB class (for loading fresh DB)
        db_path: Path to db.json (auto-detected if None)
        stopped_normally: Whether the conversation ended via ###STOP### (True)
            or was cut off by max_steps/error (False). tau2 returns 0.0
            for non-normal terminations.
    """
    if not stopped_normally:
        return CheckerResults(
            checks=[Check(name="termination", passed=False, tags=["termination"])],
            score=0.0,
        )

    criteria = task_data.get("evaluation_criteria")
    if criteria is None:
        return CheckerResults(checks=[], score=1.0)

    reward_basis = set(criteria.get("reward_basis", ["DB", "COMMUNICATE"]))
    supported_types = {"ACTION", "DB", "NL_ASSERTION", "COMMUNICATE"}
    unsupported = reward_basis - supported_types
    if unsupported:
        raise ValueError(
            f"Task reward_basis includes {unsupported} but these evaluation "
            f"types are not implemented."
        )

    actual_tool_calls = _extract_tool_calls(trajectory)
    actual_tool_calls_with_results = _extract_tool_calls_with_results(trajectory)
    agent_texts = _extract_agent_texts(trajectory)
    checks: list[Check] = []
    component_rewards: dict[str, float] = {}

    # Action evaluation
    if "ACTION" in reward_basis:
        actions = criteria.get("actions") or []
        reward = evaluate_actions(actions, actual_tool_calls)
        checks.append(Check(name="action_match", passed=(reward == 1.0), tags=["ACTION"]))
        component_rewards["ACTION"] = reward

    # DB evaluation
    if "DB" in reward_basis:
        if db_path is None:
            from pathlib import Path
            db_path = str(Path(__file__).parent / "retail" / "data" / "db.json")

        init_data = None
        if task_data.get("initial_state") and task_data["initial_state"].get("initialization_data"):
            init_data = task_data["initial_state"]["initialization_data"].get("agent_data")

        # Predicted: fresh DB + replay actual tool calls from trajectory
        predicted_db = db_cls.load(db_path)
        if init_data:
            predicted_db = db_cls.model_validate({**predicted_db.model_dump(), **init_data})
        predicted_tools = tools_cls(predicted_db)
        replay_tool_calls(actual_tool_calls_with_results, predicted_tools, tools_cls.MUTATING_TOOLS)

        # Gold: fresh DB + replay expected actions
        gold_db = db_cls.load(db_path)
        if init_data:
            gold_db = db_cls.model_validate({**gold_db.model_dump(), **init_data})
        gold_tools = tools_cls(gold_db)
        expected_actions = criteria.get("actions") or []
        gold_calls = [(a["name"], a["arguments"], None) for a in expected_actions]
        replay_tool_calls(gold_calls, gold_tools, tools_cls.MUTATING_TOOLS)

        reward = evaluate_db(predicted_tools.db.get_hash(), gold_tools.db.get_hash())
        checks.append(Check(name="db_match", passed=(reward == 1.0), tags=["DB"]))
        component_rewards["DB"] = reward

    # NL assertion evaluation
    if "NL_ASSERTION" in reward_basis:
        nl_list = criteria.get("nl_assertions") or []
        reward = evaluate_nl_assertions(nl_list, trajectory)
        checks.append(Check(name="nl_assertion", passed=(reward == 1.0), tags=["NL_ASSERTION"]))
        component_rewards["NL_ASSERTION"] = reward

    # Communication evaluation
    if "COMMUNICATE" in reward_basis:
        info_list = criteria.get("communicate_info") or []
        reward = evaluate_communication(info_list, agent_texts)
        checks.append(Check(name="communicate", passed=(reward == 1.0), tags=["COMMUNICATE"]))
        component_rewards["COMMUNICATE"] = reward

    # Combined score = product of all component rewards
    score = 1.0
    for r in component_rewards.values():
        score *= r

    return CheckerResults(checks=checks, score=score)
