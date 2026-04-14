from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=["workspace"])
def task_b(env, agent):
    agent.act(instruction="Do task B")
    return run_checkers({"b_pass": lambda: True, "b_extra": lambda: False})
