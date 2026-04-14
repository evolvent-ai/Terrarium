"""LLM-based user simulator for tau2-bench tasks."""
from __future__ import annotations

import textwrap

import litellm

SIMULATION_GUIDELINES = """\
# User Simulation Guidelines
You are playing the role of a customer contacting a customer service representative. \
Your goal is to simulate realistic customer interactions while following specific scenario instructions.

## Core Principles
- Generate one message at a time, maintaining natural conversation flow.
- Strictly follow the scenario instructions you have received.
- Never make up or hallucinate information not provided in the scenario instructions. \
Information that is not provided in the scenario instructions should be considered unknown or unavailable.
- Avoid repeating the exact instructions verbatim. Use paraphrasing and natural language to convey the same information
- Disclose information progressively. Wait for the agent to ask for specific information before providing it.

## Task Completion
- The goal is to continue the conversation until the task is complete.
- If the instruction goal is satisified, generate the '###STOP###' token to end the conversation.
- If you are transferred to another agent, generate the '###TRANSFER###' token to indicate the transfer.
- If you find yourself in a situation in which the scenario does not provide enough information \
for you to continue the conversation, generate the '###OUT-OF-SCOPE###' token to end the conversation.
Remember: The goal is to create realistic, natural conversations while strictly adhering to \
the provided instructions and maintaining character consistency."""

SYSTEM_PROMPT_TEMPLATE = """\
{guidelines}

<scenario>
{instructions}
</scenario>"""


def _format_instructions(instructions: str | dict) -> str:
    """Format tau2 task instructions into a string for the user simulator."""
    if isinstance(instructions, str):
        return instructions
    lines = []
    lines.append(f"Domain: {instructions['domain']}")
    lines.append(f"Reason for call:\n{textwrap.indent(instructions['reason_for_call'], chr(9))}")
    if instructions.get("known_info"):
        lines.append(f"Known info:\n{textwrap.indent(instructions['known_info'], chr(9))}")
    if instructions.get("unknown_info"):
        lines.append(f"Unknown info:\n{textwrap.indent(instructions['unknown_info'], chr(9))}")
    lines.append(f"Task instructions:\n{textwrap.indent(instructions['task_instructions'], chr(9))}")
    return "\n".join(lines)


class UserSimulator:
    """LLM-based user simulator using litellm."""

    def __init__(self, model: str, temperature: float = 1.0):
        self._model = model
        self._temperature = temperature
        self._system_prompt: str = ""
        self._messages: list[dict] = []

    def set_task(self, instructions: str | dict) -> None:
        """Set the task for the user simulator."""
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            guidelines=SIMULATION_GUIDELINES,
            instructions=_format_instructions(instructions),
        )
        self._messages = []

    def respond(self, agent_message: str) -> str:
        """Generate a user response to the agent's message.

        The agent's message enters as "user" role (from the simulator LLM's
        perspective), and the simulator's response comes back as "assistant".
        This mirrors tau2's UserState.flip_roles() convention.
        """
        self._messages.append({"role": "user", "content": agent_message})

        response = litellm.completion(
            model=self._model,
            messages=[{"role": "system", "content": self._system_prompt}] + self._messages,
            temperature=self._temperature,
        )

        text = response.choices[0].message.content or ""
        self._messages.append({"role": "assistant", "content": text})
        return text

    def reset(self) -> None:
        """Clear conversation history."""
        self._messages = []

    @staticmethod
    def is_stop(text: str) -> bool:
        """Check if the user simulator wants to end the conversation."""
        return (
            "###STOP###" in text
            or "###TRANSFER###" in text
            or "###OUT-OF-SCOPE###" in text
        )
