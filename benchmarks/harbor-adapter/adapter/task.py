"""Harbor task format adapter.

Runs Harbor-formatted tasks (task.toml + instruction.md + tests/) on Terrarium.
Point HARBOR_DATASET_DIR at a directory of Harbor tasks; each subdirectory that
has a task.toml becomes a Terrarium task instance via @task.parameterize.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import tomllib
from pathlib import Path

from loguru import logger

from terrarium.models.checker import CheckerResults
from terrarium.task.decorator import entry


@entry(capabilities=["workspace"])
def harbor_task(env, agent, *, task_dir: str):
    td = Path(task_dir)
    instruction = (td / "instruction.md").read_text()
    cfg = tomllib.loads((td / "task.toml").read_text())

    env.workspace.fs.upload(str(td / "tests"), "/tests")

    skills_dir = cfg.get("environment", {}).get("skills_dir")
    if skills_dir:
        _register_skills(env.workspace, agent, skills_dir)

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
        task_name = td.name

        required = {
            "instruction.md": td / "instruction.md",
            "tests/test.sh": td / "tests" / "test.sh",
        }
        missing = [n for n, p in required.items() if not p.exists()]
        if missing:
            logger.warning("[harbor:{}] skipping: missing {}", task_name, missing)
            continue

        if (td / "environment" / "docker-compose.yaml").exists():
            logger.warning("[harbor:{}] skipping: docker-compose.yaml not supported currently", task_name)
            continue

        cfg = tomllib.loads((td / "task.toml").read_text())
        env_cfg = cfg.get("environment", {})
        image_name = env_cfg.get("docker_image")
        has_dockerfile = (td / "environment" / "Dockerfile").exists()
        if not image_name and not has_dockerfile:
            logger.warning(
                "[harbor:{}] skipping: no [environment].docker_image and no environment/Dockerfile",
                task_name,
            )
            continue

        for field in (
            "gpus", "gpu_types", "allow_internet", "mcp_servers",
            "build_timeout_sec", "healthcheck",
        ):
            if field in env_cfg:
                logger.warning("[harbor:{}] ignoring [environment].{}", task_name, field)

        for field in ("timeout_sec", "user"):
            if field in cfg.get("agent", {}):
                logger.warning("[harbor:{}] ignoring [agent].{}", task_name, field)

        for field in ("timeout_sec", "user", "env"):
            if field in cfg.get("verifier", {}):
                logger.warning("[harbor:{}] ignoring [verifier].{}", task_name, field)

        if "solution" in cfg or (td / "solution").exists():
            logger.warning("[harbor:{}] ignoring [solution]", task_name)

        templated = [k for k, v in env_cfg.get("env", {}).items()
                     if isinstance(v, str) and re.search(r"\$\{[^}]+\}", v)]
        if templated:
            logger.warning("[harbor:{}] ignoring ${{VAR}} templates in [environment].env: {}", task_name, templated)

        metadata = [k for k in ("schema_version", "task", "metadata") if k in cfg]
        if metadata:
            logger.warning("[harbor:{}] ignoring metadata sections: {}", task_name, metadata)

        workspace: dict = {"env": env_cfg.get("env", {})}
        if image_name:
            workspace["image"] = {"name": image_name}
        else:
            workspace["image"] = {"build": {"context": str(td / "environment")}}
        resources: dict = {}
        if "cpus" in env_cfg:
            resources["cpus"] = env_cfg["cpus"]
        if "memory_mb" in env_cfg:
            resources["memory"] = f"{env_cfg['memory_mb']}M"
        elif "memory" in env_cfg:
            resources["memory"] = env_cfg["memory"]
        if "storage_mb" in env_cfg:
            resources["storage"] = f"{env_cfg['storage_mb']}M"
        elif "storage" in env_cfg:
            resources["storage"] = env_cfg["storage"]
        if resources:
            workspace["resources"] = resources
        if "workdir" in env_cfg:
            workspace["workdir"] = env_cfg["workdir"]

        yield {
            "name": task_name,
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


def _register_skills(workspace, agent, skills_dir: str) -> None:
    dest = agent.skills_dir
    if dest is None:
        logger.warning(
            "[harbor] agent '{}' does not support skills; ignoring skills_dir={}",
            agent.name(), skills_dir,
        )
        return
    src = shlex.quote(skills_dir)
    dst = shlex.quote(dest)
    workspace.shell.exec(
        f"mkdir -p {dst} && cp -r {src}/* {dst}/ 2>/dev/null || true"
    )
