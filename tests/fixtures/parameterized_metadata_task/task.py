from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=["workspace"])
def task(env, agent, *, variant: str):
    return run_checkers({"ok": lambda: True})


@task.parameterize
def params():
    yield {"name": "inherits", "params": {"variant": "a"}}
    yield {
        "name": "overrides",
        "params": {"variant": "b"},
        "metadata": {"difficulty": "hard", "tags": ["edge", "regression"]},
    }
