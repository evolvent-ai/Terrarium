from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=["workspace"])
def task(env, agent, *, variant: str):
    return run_checkers({"ok": lambda: True})


@task.parameterize
def params():
    yield {"name": "basic", "params": {"variant": "basic"}}
    yield {"name": "with_db", "params": {"variant": "with_db"}, "capabilities": ["workspace", "postgres"]}
