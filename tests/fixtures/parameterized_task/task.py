from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=["workspace"])
def task(env, agent, *, task_index: int, label: str = "default"):
    return run_checkers({
        f"check_{label}": lambda: task_index >= 0,
    })


@task.parameterize
def params():
    for i in range(3):
        yield {
            "name": f"param_task_{i}",
            "params": {"task_index": i, "label": f"item_{i}"},
        }
