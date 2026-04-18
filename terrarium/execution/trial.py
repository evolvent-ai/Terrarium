"""Trial — single agent x task execution."""
from __future__ import annotations

import asyncio
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from loguru import logger

from terrarium.environment.environment import ComposableEnvironment
from terrarium.environment.exceptions import CapabilityNotFoundError
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
        started_at = datetime.now(timezone.utc)

        self._task = cfg.task.instance or Task(cfg.task.path)
        self._agent = create_agent(cfg.agent)
        trial_id = uuid4()
        if cfg.trial_name:
            trial_name = cfg.trial_name
        else:
            model_name = cfg.agent.model_name or ""
            trial_name = f"{cfg.agent.name}__{model_name}__{self._task.name}__{trial_id}"

        if cfg.trial_dir and cfg.trial_dir.exists():
            shutil.rmtree(cfg.trial_dir)
        self._save_config()

        setup_timing, execution_timing = TimingInfo(), TimingInfo()
        checker_result = CheckerResults(checks=[], score=0.0)
        trajectory = Trajectory(messages=[])
        exception_info: ExceptionInfo | None = None

        env = self._create_env()
        try:
            await asyncio.to_thread(env.start)

            conn_info = self._collect_conn_info(env)

            try:
                workspace = env.workspace
            except CapabilityNotFoundError:
                workspace = None
            exception_info = await self._setup_agent(workspace, conn_info, setup_timing)

            if exception_info is None:
                checker_result, exception_info = await self._execute_task(env, execution_timing)

            trajectory = self._collect_trajectory()
            await self._teardown_agent()

        except Exception as e:
            logger.error("ComposableEnvironment failed: {}", e)
            if exception_info is None:
                exception_info = ExceptionInfo.from_exception(e)
        finally:
            await asyncio.to_thread(env.stop)

        trial_result = TrialResult(
            id=trial_id,
            trial_name=trial_name,
            task_info=TaskInfo(
                name=self._task.name,
                path=cfg.task.path,
                source=cfg.task.source,
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

    # ── Private helpers ──────────────────────────────────────────

    def _save_config(self) -> None:
        trial_dir = self._config.trial_dir
        if trial_dir is not None:
            trial_dir.mkdir(parents=True, exist_ok=True)
            (trial_dir / "config.json").write_text(self._config.model_dump_json(indent=2))

    def _save_result(self, result: TrialResult) -> None:
        trial_dir = self._config.trial_dir
        if trial_dir is not None:
            (trial_dir / "result.json").write_text(result.model_dump_json(indent=2))

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

    async def _setup_agent(self, workspace, conn_info: dict, timing: TimingInfo) -> ExceptionInfo | None:
        timing.started_at = datetime.now(timezone.utc)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._agent.setup, workspace, conn_info),
                timeout=self._config.agent_setup_timeout_sec,
            )
            return None
        except Exception as e:
            logger.error("Agent setup failed: {}", e)
            return ExceptionInfo.from_exception(e)
        finally:
            timing.finished_at = datetime.now(timezone.utc)

    async def _execute_task(self, env: ComposableEnvironment, timing: TimingInfo) -> tuple[CheckerResults, ExceptionInfo | None]:
        timing.started_at = datetime.now(timezone.utc)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._task.entry_fn, env, self._agent),
                timeout=self._config.agent_exec_timeout_sec,
            )
            if not isinstance(result, CheckerResults):
                raise TypeError(f"Task must return CheckerResults, got {type(result).__name__}")
            return result, None
        except Exception as e:
            logger.error("Task execution failed: {}", e)
            return CheckerResults(checks=[], score=0.0), ExceptionInfo.from_exception(e)
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
