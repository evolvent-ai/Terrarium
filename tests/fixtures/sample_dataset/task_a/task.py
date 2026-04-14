from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=["workspace"])
def task_a(env, agent):
    agent.act(instruction="Do task A")
    return run_checkers({"a_pass": lambda: True})
