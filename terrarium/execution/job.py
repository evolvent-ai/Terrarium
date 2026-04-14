"""Job — batch execution engine."""
from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from terrarium.dataset.dataset import Dataset
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

    async def run(self) -> JobResult:
        cfg = self._config
        started_at = datetime.now(timezone.utc)

        job_name = cfg.job_name or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_dir = cfg.job_dir or Path("outputs") / job_name
        if job_dir.exists():
            shutil.rmtree(job_dir)
        self._save_config(job_dir)

        trial_configs = self._expand_trials(job_dir)

        queue = TrialQueue(
            n_concurrent=cfg.n_concurrent_trials,
            retry_config=cfg.retry,
        )
        trial_results = await queue.run(trial_configs)

        job_result = JobResult(
            trial_results=trial_results,
            stats=self._build_stats(trial_results),
            timing=TimingInfo(started_at=started_at, finished_at=datetime.now(timezone.utc)),
        )
        self._save_result(job_dir, job_result)
        return job_result

    # ── Private helpers ──────────────────────────────────────────

    def _save_config(self, job_dir: Path) -> None:
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "config.json").write_text(self._config.model_dump_json(indent=2))

    def _save_result(self, job_dir: Path, result: JobResult) -> None:
        (job_dir / "result.json").write_text(result.model_dump_json(indent=2))

    def _expand_trials(self, job_dir: Path) -> list[TrialConfig]:
        """Resolve tasks from datasets + adhoc paths, then expand into TrialConfigs."""
        task_entries = self._resolve_tasks()
        cfg = self._config
        configs: list[TrialConfig] = []

        for agent_cfg in cfg.agents:
            for task, source in task_entries:
                for attempt_idx in range(cfg.n_attempts):
                    model_name = agent_cfg.model_name or ""
                    trial_name = f"{agent_cfg.name}__{model_name}__{source}__{task.name}"
                    if cfg.n_attempts > 1:
                        trial_name += f"__attempt{attempt_idx}"
                    configs.append(TrialConfig(
                        task=TaskConfig(path=str(task.dir), name=task.name, source=source),
                        agent=agent_cfg,
                        trial_name=trial_name,
                        trial_dir=job_dir / trial_name,
                        agent_setup_timeout_sec=cfg.agent_setup_timeout_sec,
                        agent_exec_timeout_sec=cfg.agent_exec_timeout_sec,
                    ))
        return configs

    def _resolve_tasks(self) -> list[tuple[Task, str]]:
        """Discover tasks from datasets and adhoc paths. Populates _datasets."""
        entries: list[tuple[Task, str]] = []

        for ds_path in self._config.datasets:
            dataset = Dataset(ds_path)
            self._datasets[dataset.name] = dataset
            for task in dataset.tasks:
                entries.append((task, dataset.name))

        for task_path in self._config.tasks:
            task = Task(task_path)
            entries.append((task, "adhoc"))

        return entries

    def _build_stats(self, trial_results: list[TrialResult]) -> JobStats:
        """Aggregate trial results grouped by agent__model__source."""
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
                group_stats.exception_stats.setdefault(
                    r.exception_info.exception_type, []
                ).append(r.trial_name)
            group_stats.score_stats.setdefault(r.checker_result.score, []).append(r.trial_name)

        source = results[0].task_info.source
        metrics = self._get_metrics(source)
        for metric in metrics:
            group_stats.metrics[metric.name] = metric.compute(results)

        return group_stats

    def _get_metrics(self, source_name: str) -> list[BaseMetric]:
        ds = self._datasets.get(source_name)
        return ds.metrics if ds else [Mean()]
