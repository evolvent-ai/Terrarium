"""Harbor task format adapter.

Runs Harbor-formatted tasks (task.toml + instruction.md + tests/) on Terrarium.
Point HARBOR_DATASET_DIR at a directory of Harbor tasks; each subdirectory that
has a task.toml becomes a Terrarium task instance via @task.parameterize.

Out of scope for v0 (skipped with an explanatory branch where relevant):
    docker-compose.yaml (multi-container)
    MCP servers
    user switching (agent.user / verifier.user)
    resource limits (cpus / memory / storage / gpus)
    healthcheck
    allow_internet
    timeouts from task.toml (falls back to TrialConfig defaults)
    skills_dir, workdir, env templating
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from terrarium.models.checker import CheckerResults
from terrarium.task.decorator import entry


@entry(capabilities=["workspace"])
def harbor_task(env, agent, *, task_dir: str):
    td = Path(task_dir)
    instruction = (td / "instruction.md").read_text()

    tests_src = td / "tests"
    if tests_src.exists():
        env.workspace.fs.upload(str(tests_src), "/tests")

    agent.act(instruction)

    env.workspace.shell.exec("mkdir -p /logs/verifier")
    env.workspace.shell.exec("bash /tests/test.sh")

    return CheckerResults(checks=[], score=_read_reward(env.workspace))


@harbor_task.parameterize
def params():
    dataset_dir = os.environ.get("HARBOR_DATASET_DIR")
    if not dataset_dir:
        raise RuntimeError("HARBOR_DATASET_DIR environment variable is not set")

    for td in sorted(Path(dataset_dir).iterdir()):
        if not (td / "task.toml").exists():
            continue
        # v0 skips multi-container tasks.
        if (td / "environment" / "docker-compose.yaml").exists():
            continue

        cfg = tomllib.loads((td / "task.toml").read_text())
        env_cfg = cfg.get("environment", {})

        workspace: dict = {"env": env_cfg.get("env", {})}
        if image := env_cfg.get("docker_image"):
            workspace["image"] = {"name": image}
        elif (td / "environment" / "Dockerfile").exists():
            workspace["image"] = {"build": {"context": str(td / "environment")}}
        else:
            continue

        yield {
            "name": td.name,
            "params": {"task_dir": str(td)},
            "capabilities_config": {"workspace": workspace},
        }


def _read_reward(workspace) -> float:
    """Return the score Harbor's verifier wrote to /logs/verifier/."""
    if workspace.fs.exists("/logs/verifier/reward.txt"):
        content = workspace.fs.read_file("/logs/verifier/reward.txt").decode()
        rewards = {"reward": float(content)}
    elif workspace.fs.exists("/logs/verifier/reward.json"):
        content = workspace.fs.read_file("/logs/verifier/reward.json").decode()
        rewards = json.loads(content)
    else:
        raise FileNotFoundError(
            "No reward file at /logs/verifier/reward.{txt,json}"
        )

    if len(rewards.keys()) != 1:
        raise ValueError(
            f"Expected exactly one key in reward dict, got {len(rewards.keys())}: "
            f"{sorted(rewards.keys())}"
        )
    return float(next(iter(rewards.values())))
