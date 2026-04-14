from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=[])
def sample_task(env, agent):
    agent.act(instruction="Do something")
    return run_checkers({"always_pass": lambda: True})
