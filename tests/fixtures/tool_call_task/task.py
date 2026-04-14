from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers
from terrarium.models.trajectory import TextBlock, ToolUseBlock


def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: First addend.
        b: Second addend.
    """
    return a + b


@entry(capabilities=[])
def tool_call_task(env, agent):
    agent.register_tools(add)
    result = agent.act(
        instruction="Use the add tool to compute 123 + 456, then tell me the answer."
    )

    def called_add() -> bool:
        for msg in result.messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock) and block.name == "add":
                        return True
        return False

    def mentions_answer() -> bool:
        final = result.messages[-1]
        if not isinstance(final.content, list):
            return False
        for block in final.content:
            if isinstance(block, TextBlock) and "579" in block.text:
                return True
        return False

    return run_checkers({
        "called_add": called_add,
        "mentions_answer": mentions_answer,
    })
