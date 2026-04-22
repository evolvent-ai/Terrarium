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
    verifier_env = _resolve_env_vars(cfg.get("verifier", {}).get("env", {}))
    env.workspace.shell.exec("bash /tests/test.sh", env=verifier_env)

    return CheckerResults(checks=[], score=_read_reward(env.workspace))


@harbor_task.parameterize
def params():
    dataset_dir = os.environ.get("HARBOR_DATASET_DIR")
    if not dataset_dir:
        logger.warning("[harbor] environment variable HARBOR_DATASET_DIR is not set")
        return

    for td in sorted(Path(dataset_dir).iterdir()):
        if not (td / "task.toml").exists():
            continue
        cfg = tomllib.loads((td / "task.toml").read_text())
        task_cfg = cfg.get("task", {})
        task_name = (task_cfg.get("name") or td.name).replace("/", "_")

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

        metadata_cfg = cfg.get("metadata", {})
        authors = task_cfg.get("authors", [])
        author = ", ".join(a["name"] for a in authors) or None
        task_metadata = {
            "author": author,
            "difficulty": metadata_cfg.get("difficulty"),
            "category": metadata_cfg.get("category"),
            "tags": task_cfg.get("keywords", []),
            "description": task_cfg.get("description"),
        }

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
        try:
            resolved_env = _resolve_env_vars(env_cfg.get("env", {}))
        except ValueError as e:
            logger.warning("[harbor:{}] skipping: failed to resolve [environment].env: {}", task_name, e)
            continue

        workspace: dict = {"env": resolved_env}
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

        for field in ("timeout_sec", "user"):
            if field in cfg.get("agent", {}):
                logger.warning("[harbor:{}] ignoring [agent].{}", task_name, field)
        for field in ("timeout_sec", "user"):
            if field in cfg.get("verifier", {}):
                logger.warning("[harbor:{}] ignoring [verifier].{}", task_name, field)
        if "solution" in cfg or (td / "solution").exists():
            logger.warning("[harbor:{}] ignoring [solution]", task_name)

        yield {
            "name": task_name,
            "params": {"task_dir": str(td)},
            "capabilities_config": {"workspace": workspace},
            "metadata": task_metadata,
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
    """Copy skills from the image-provided path into the agent's skills config dir."""
    dest = agent.skills_dir
    if dest is None:
        logger.warning(
            "[harbor] agent '{}' does not support skills; ignoring skills_dir={}",
            agent.name(), skills_dir,
        )
        return
    src = shlex.quote(skills_dir)
    dst = shlex.quote(dest)
    workspace.shell.exec(f"mkdir -p {dst} && cp -r {src}/* {dst}/")


_TEMPLATE_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*))?\}")


def _resolve_env_vars(env_dict: dict[str, str]) -> dict[str, str]:
    """Expand ${VAR} and ${VAR:-default} templates in env values using host env."""
    resolved: dict[str, str] = {}
    for key, value in env_dict.items():
        match = _TEMPLATE_PATTERN.fullmatch(value)
        if match:
            var_name = match.group(1)
            default = match.group(2)
            if var_name in os.environ:
                resolved[key] = os.environ[var_name]
            elif default is not None:
                resolved[key] = default
            else:
                raise ValueError(f"Environment variable '{var_name}' not found in host environment")
        else:
            resolved[key] = value
    return resolved
