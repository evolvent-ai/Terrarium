"""Trial — single agent x task execution."""
from __future__ import annotations

import asyncio
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from loguru import logger

from terrarium.environment.environment import ComposableEnvironment
from terrarium.agent.base import BaseAgent
from terrarium.agent.registry import create_agent
from terrarium.models.checker import CheckerResults
from terrarium.models.config import TrialConfig
from terrarium.models.common import ExceptionInfo
from terrarium.models.result import AgentInfo, TaskInfo, TimingInfo, TrialResult
from terrarium.models.trajectory import Trajectory
from terrarium.task.task import Task


class Trial:
    """A single agent x task execution driven by TrialConfig."""

    def __init__(self, config: TrialConfig) -> None:
        self._config = config

        self._task: Task | None = None
        self._agent: BaseAgent | None = None

    async def run(self) -> TrialResult:
        cfg = self._config

        if (cfg.trial_dir / "result.json").exists():
            try:
                return TrialResult.model_validate_json((cfg.trial_dir / "result.json").read_text())
            except Exception as e:
                logger.warning("Failed to load {}: {}", cfg.trial_dir / "result.json", e)

        started_at = datetime.now(timezone.utc)

        if cfg.trial_dir.exists():
            shutil.rmtree(cfg.trial_dir)
        self._save_config()

        setup_timing, execution_timing = TimingInfo(), TimingInfo()
        checker_result = CheckerResults(checks=[], score=0.0)
        trajectory = Trajectory(messages=[])
        exception_info = None

        sink_id = logger.add(
            cfg.trial_dir / "trial.log",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            filter=lambda r: r["extra"].get("trial_name") == cfg.trial_name,
        )
        try:
            with logger.contextualize(trial_name=cfg.trial_name):
                self._task = cfg.task.instance or Task(cfg.task.path)
                self._agent = create_agent(cfg.agent)
                env = self._create_env()
                try:
                    await asyncio.to_thread(env.start)
                    conn_info = self._collect_conn_info(env)
                    workspace = env.workspace if "workspace" in env else None

                    await self._setup_agent(workspace, conn_info, setup_timing)
                    checker_result = await self._execute_task(env, execution_timing)

                    trajectory = self._collect_trajectory()
                    self._save_trajectory(trajectory)
                    await self._collect_agent_logs()
                    await self._teardown_agent()
                except Exception as e:
                    exception_info = ExceptionInfo.from_exception(e)
                finally:
                    try:
                        await asyncio.to_thread(env.stop)
                    except Exception as e:
                        logger.warning("Environment teardown failed: {}", e)
        finally:
            logger.remove(sink_id)

        trial_result = TrialResult(
            trial_name=cfg.trial_name,
            task_info=TaskInfo(
                name=self._task.name,
                path=cfg.task.path,
                source=cfg.task.source,
                spec=self._task.spec,
                capabilities=self._task.capabilities,
                capabilities_config=self._task.capabilities_config,
            ),
            agent_info=AgentInfo(
                name=self._agent.name(),
                import_path=cfg.agent.import_path,
                version=self._agent.version(),
                model_name=cfg.agent.model_name,
            ),
            checker_result=checker_result,
            trajectory=trajectory,
            exception_info=exception_info,
            timing=TimingInfo(started_at=started_at, finished_at=datetime.now(timezone.utc)),
            setup_timing=setup_timing,
            execution_timing=execution_timing,
        )
        self._save_result(trial_result)
        return trial_result

    def _save_config(self) -> None:
        trial_dir = self._config.trial_dir
        trial_dir.mkdir(parents=True, exist_ok=True)
        (trial_dir / "config.json").write_text(self._config.model_dump_json(indent=2))

    def _save_result(self, result: TrialResult) -> None:
        trial_dir = self._config.trial_dir
        trial_dir.mkdir(parents=True, exist_ok=True)
        (trial_dir / "result.json").write_text(result.model_dump_json(indent=2))

    def _save_trajectory(self, trajectory: Trajectory) -> None:
        trial_dir = self._config.trial_dir
        trial_dir.mkdir(parents=True, exist_ok=True)
        (trial_dir / "trajectory.json").write_text(trajectory.model_dump_json(indent=2))

    async def _collect_agent_logs(self) -> None:
        agent_dir = self._config.trial_dir / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(self._agent.collect_logs, agent_dir)
        except Exception as e:
            logger.warning("Agent log collection failed: {}", e)

    def _create_env(self) -> ComposableEnvironment:
        capabilities = list(self._task.capabilities)
        caps_config: dict[str, dict] = deepcopy(self._task.capabilities_config)
        ws_config = self._agent.workspace_config()
        if ws_config is not None:
            if "workspace" not in capabilities:
                capabilities.append("workspace")
            # Task's workspace config wins; agent's is a fallback default.
            # Agents provision themselves in setup() if the task-chosen image
            # doesn't already have what they need.
            caps_config["workspace"] = {**ws_config, **caps_config.get("workspace", {})}
        return ComposableEnvironment(capabilities=capabilities, config=caps_config)

    def _collect_conn_info(self, env: ComposableEnvironment) -> dict:
        conn_info: dict = {}
        for cap_name in self._task.capabilities:
            cap = getattr(env, cap_name)
            if hasattr(cap, "connection_info"):
                conn_info[cap_name] = cap.connection_info
        return conn_info

    async def _setup_agent(self, workspace, conn_info: dict, timing: TimingInfo) -> None:
        timing.started_at = datetime.now(timezone.utc)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._agent.setup, workspace, conn_info),
                timeout=self._config.agent_setup_timeout_sec,
            )
        except Exception as e:
            logger.error("Agent setup failed: {}", e)
            raise
        finally:
            timing.finished_at = datetime.now(timezone.utc)

    async def _execute_task(self, env: ComposableEnvironment, timing: TimingInfo) -> CheckerResults:
        timing.started_at = datetime.now(timezone.utc)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._task.entry_fn, env, self._agent),
                timeout=self._config.agent_exec_timeout_sec,
            )
            if not isinstance(result, CheckerResults):
                raise TypeError(f"Task must return CheckerResults, got {type(result).__name__}")
            return result
        except Exception as e:
            logger.error("Task execution failed: {}", e)
            raise
        finally:
            timing.finished_at = datetime.now(timezone.utc)

    def _collect_trajectory(self) -> Trajectory:
        try:
            return self._agent.get_trajectory()
        except Exception as e:
            logger.warning("Failed to get trajectory: {}", e)
            return Trajectory(messages=[])

    async def _teardown_agent(self) -> None:
        try:
            await asyncio.to_thread(self._agent.teardown)
        except Exception as e:
            logger.warning("Agent teardown failed: {}", e)
