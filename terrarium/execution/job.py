"""Job — batch execution engine."""
from __future__ import annotations

import shutil
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from terrarium.dataset.dataset import Dataset
from terrarium.execution.events import EventBus, JobEvent, JobEventPayload, JobFinishedPayload, JobStartedPayload, TrialEvent
from terrarium.execution.queue import TrialQueue
from terrarium.metrics.base import BaseMetric
from terrarium.metrics.builtins import Mean
from terrarium.models.config import JobConfig, TaskConfig, TrialConfig
from terrarium.models.result import AgentDatasetStats, JobResult, JobStats, TimingInfo, TrialResult
from terrarium.task.task import Task


class Job:
    """Batch execution engine.

    Expands agents x (datasets + tasks) x n_attempts into TrialConfigs,
    runs them concurrently via TrialQueue, then aggregates stats.
    """

    def __init__(self, config: JobConfig) -> None:
        self._config = config
        self._datasets: dict[str, Dataset] = {}
        self._events = EventBus()

    def on(self, event: TrialEvent | JobEvent, handler: Callable[[Any], None]) -> Job:
        self._events.subscribe(event, handler)
        return self

    async def run(self) -> JobResult:
        cfg = self._config
        started_at = datetime.now(timezone.utc)

        if not cfg.resume and cfg.job_dir.exists():
            shutil.rmtree(cfg.job_dir)
        self._save_config()

        sink_id = logger.add(
            cfg.job_dir / "job.log",
            mode="a" if cfg.resume else "w",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        )
        try:
            trial_configs = self._expand_trials()

            self._events.emit(JobEventPayload(
                event=JobEvent.STARTED,
                job_name=cfg.job_name,
                payload=JobStartedPayload(n_trials=len(trial_configs)),
            ))

            queue = TrialQueue(
                n_concurrent=cfg.n_concurrent_trials,
                retry_config=cfg.retry,
                events=self._events,
            )
            trial_results = await queue.run(trial_configs)

            job_result = JobResult(
                trial_results=trial_results,
                stats=self._build_stats(trial_results),
                timing=TimingInfo(started_at=started_at, finished_at=datetime.now(timezone.utc)),
            )
            self._save_result(job_result)

            self._events.emit(JobEventPayload(
                event=JobEvent.FINISHED,
                job_name=cfg.job_name,
                payload=JobFinishedPayload(),
            ))
            return job_result
        finally:
            logger.remove(sink_id)

    def _save_config(self) -> None:
        job_dir = self._config.job_dir
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "config.json").write_text(self._config.model_dump_json(indent=2))

    def _save_result(self, result: JobResult) -> None:
        job_dir = self._config.job_dir
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "result.json").write_text(result.model_dump_json(indent=2))

    def _expand_trials(self) -> list[TrialConfig]:
        task_configs = self._resolve_tasks()
        trial_configs: list[TrialConfig] = []

        for agent_cfg in self._config.agents:
            for task_cfg in task_configs:
                for attempt_idx in range(self._config.n_attempts):
                    model_name = agent_cfg.model_name or ""
                    trial_name = f"{agent_cfg.name}__{model_name.replace('/', '_')}__{task_cfg.source}__{task_cfg.name}"
                    if self._config.n_attempts > 1:
                        trial_name += f"__attempt{attempt_idx}"
                    trial_configs.append(TrialConfig(
                        task=task_cfg,
                        agent=agent_cfg,
                        trial_name=trial_name,
                        trial_dir=self._config.job_dir / trial_name,
                        agent_setup_timeout_sec=self._config.agent_setup_timeout_sec,
                        agent_exec_timeout_sec=self._config.agent_exec_timeout_sec,
                    ))
        return trial_configs

    def _resolve_tasks(self) -> list[TaskConfig]:
        task_configs: list[TaskConfig] = []

        for ds_path in self._config.datasets:
            dataset = Dataset(ds_path)
            self._datasets[dataset.name] = dataset
            for task in dataset.tasks:
                task_configs.append(TaskConfig(path=str(task.dir), name=task.name, source=dataset.name, instance=task))

        for task_path in self._config.tasks:
            for task in Task.resolve(task_path):
                task_configs.append(TaskConfig(path=str(task.dir), name=task.name, source="adhoc", instance=task))

        return task_configs

    def _build_stats(self, trial_results: list[TrialResult]) -> JobStats:
        groups = self._group_results(trial_results)
        stats = JobStats(n_trials=len(trial_results))

        for key, results in groups.items():
            group_stats = self._build_group_stats(results)
            stats.n_errors += group_stats.n_errors
            stats.agent_dataset_stats[key] = group_stats

        return stats

    def _group_results(self, trial_results: list[TrialResult]) -> dict[str, list[TrialResult]]:
        groups: dict[str, list[TrialResult]] = defaultdict(list)
        for result in trial_results:
            source = result.task_info.source
            model = result.agent_info.model_name or ""
            key = f"{result.agent_info.name}__{model}__{source}"
            groups[key].append(result)
        return groups

    def _build_group_stats(self, results: list[TrialResult]) -> AgentDatasetStats:
        group_stats = AgentDatasetStats(n_trials=len(results))

        for r in results:
            if r.exception_info is not None:
                group_stats.n_errors += 1
                group_stats.exception_stats.setdefault(r.exception_info.exception_type, []).append(r.trial_name)
            group_stats.score_stats.setdefault(r.checker_result.score, []).append(r.trial_name)

        source = results[0].task_info.source
        metrics = self._get_metrics(source)
        for metric in metrics:
            group_stats.metrics[metric.name] = metric.compute(results)

        return group_stats

    def _get_metrics(self, source_name: str) -> list[BaseMetric]:
        ds = self._datasets.get(source_name)
        return ds.metrics if ds else [Mean()]
