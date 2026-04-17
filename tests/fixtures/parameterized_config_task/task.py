from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(
    capabilities=["postgres"],
    capabilities_config={"postgres": {"db_name": "default_db"}},
)
def task(env, agent, *, variant: str):
    return run_checkers({"ok": lambda: True})


@task.parameterize
def params():
    yield {"name": "inherits", "params": {"variant": "a"}}
    yield {
        "name": "overrides",
        "params": {"variant": "b"},
        "capabilities_config": {"postgres": {"db_name": "shop", "port": 6000}},
    }
