"""tau2-bench retail task 0: Exchange items in a delivered order."""
from __future__ import annotations

import json
from pathlib import Path

from terrarium.task.decorator import entry
from terrarium.models.trajectory import TextBlock

from benchmarks.tau2.retail.data_model import RetailDB
from benchmarks.tau2.retail.tools import RetailTools
from benchmarks.tau2.user_simulator import UserSimulator
from benchmarks.tau2.evaluator import evaluate

TASK_INDEX = 0
MAX_STEPS = 100
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

AGENT_INSTRUCTION = """
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Always make sure you generate valid JSON only.
""".strip()

AGENT_SYSTEM_PROMPT_TEMPLATE = """
<instructions>
{agent_instruction}
</instructions>
<policy>
{domain_policy}
</policy>
""".strip()


def _load_tasks() -> list[dict]:
    return json.loads((DATA_DIR / "tasks.json").read_text())


def _load_db() -> RetailDB:
    return RetailDB.load(DATA_DIR / "db.json")


def _load_policy() -> str:
    return (DATA_DIR / "policy.md").read_text()


def _extract_last_text(act_result) -> str:
    for msg in reversed(act_result.messages):
        if isinstance(msg.content, list):
            for block in reversed(msg.content):
                if isinstance(block, TextBlock):
                    return block.text
    return ""


def _is_agent_stop(text: str) -> bool:
    return "###STOP###" in text


@entry(capabilities=[])
def task(env, agent):
    task_data = _load_tasks()[TASK_INDEX]

    # Apply initialization_data to DB if present
    db = _load_db()
    init_state = task_data.get("initial_state")
    if init_state and init_state.get("initialization_data"):
        agent_data = init_state["initialization_data"].get("agent_data")
        if agent_data:
            db = RetailDB.model_validate({**db.model_dump(), **agent_data})

    tools = RetailTools(db)

    # System prompt: <instructions>...</instructions><policy>...</policy>
    agent.system_prompt = AGENT_SYSTEM_PROMPT_TEMPLATE.format(
        agent_instruction=AGENT_INSTRUCTION,
        domain_policy=_load_policy(),
    )
    agent.register_tools(*tools.get_tool_callables())

    user_sim = UserSimulator(model=agent._model)
    user_sim.set_task(task_data["user_scenario"]["instructions"])

    # Conversation loop (aligned with tau2 orchestrator)
    agent_text = "Hi! How can I help you today?"
    stopped_normally = False
    for _ in range(MAX_STEPS):
        user_msg = user_sim.respond(agent_text)
        if UserSimulator.is_stop(user_msg):
            stopped_normally = True
            break
        result = agent.act(user_msg)
        agent_text = _extract_last_text(result)
        if _is_agent_stop(agent_text):
            stopped_normally = True
            break

    return evaluate(
        task_data,
        agent.get_trajectory(),
        RetailTools,
        RetailDB,
        db_path=str(DATA_DIR / "db.json"),
        stopped_normally=stopped_normally,
    )
