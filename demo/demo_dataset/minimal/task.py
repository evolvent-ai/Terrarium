"""Minimal multi-turn task.

Stage 1: agent creates a greeting file.
Stage 2: agent appends a second line.
"""
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers, aggregate_results


def _read(env) -> str:
    try:
        return env.workspace.fs.read_file("/root/hello.txt").decode()
    except Exception:
        return ""


@entry(capabilities=[])
def minimal(env, agent):
    agent.act(
        "Create the file /root/hello.txt with exactly this single line: "
        "Hello, World!"
    )

    check1 = run_checkers({
        "file_created": lambda: _read(env).strip() == "Hello, World!",
    }, tags=["stage1"])

    agent.act("Great. Now append a second line to that file: It is a great day.")

    check2 = run_checkers({
        "second_line_added": lambda: (
            _read(env).strip().splitlines() == ["Hello, World!", "It is a great day."]
        ),
    }, tags=["stage2"])

    return aggregate_results(check1, check2)
