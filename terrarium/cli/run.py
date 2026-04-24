from __future__ import annotations

import asyncio
import sys
import tomllib
from collections import deque
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from terrarium.cli.utils import console, print_error
from terrarium.execution.events import JobEvent, JobEventPayload, TrialEvent, TrialEventPayload
from terrarium.execution.job import Job
from terrarium.models.config import JobConfig


class _LogPanel:
    """A Rich renderable that displays the last N log lines in a Panel."""

    def __init__(self, max_lines: int = 15):
        self._lines: deque[str] = deque(maxlen=max_lines)

    def add(self, line: str) -> None:
        self._lines.append(line)

    def __rich__(self) -> Panel:
        if self._lines:
            text = Text("\n".join(self._lines))
        else:
            text = Text("Waiting...", style="dim")
        return Panel(text, title="Execution Log", title_align="left", border_style="yellow")


class _ProgressUI:
    """Live progress display wired to Job lifecycle events."""

    def __init__(self, job: Job) -> None:
        self._main = Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        )
        self._main_task = self._main.add_task("Trials", total=0, start=False)
        self._running = Progress(SpinnerColumn(), TextColumn("{task.description}"))
        self._running_tasks: dict[str, TaskID] = {}
        self._log_panel = _LogPanel()

        job.on(JobEvent.STARTED, self._on_job_started)
        job.on(TrialEvent.STARTED, self._on_trial_started)
        job.on(TrialEvent.SUCCEEDED, self._on_trial_finished)
        job.on(TrialEvent.FAILED, self._on_trial_finished)

    def __rich__(self) -> Group:
        return Group(
            Panel(
                Group(self._main, self._running),
                title="Progress",
                title_align="left",
                border_style="magenta",
            ),
            self._log_panel,
        )

    def _on_job_started(self, p: JobEventPayload) -> None:
        self._main.update(self._main_task, total=p.payload.n_trials)
        self._main.start_task(self._main_task)

    def _on_trial_started(self, p: TrialEventPayload) -> None:
        self._running_tasks[p.trial_name] = self._running.add_task(p.trial_name)

    def _on_trial_finished(self, p: TrialEventPayload) -> None:
        tid = self._running_tasks.pop(p.trial_name, None)
        if tid is not None:
            self._running.remove_task(tid)
        self._main.advance(self._main_task)

    def __enter__(self) -> _ProgressUI:
        logger.remove()
        self._sink_id = logger.add(
            lambda msg: self._log_panel.add(msg.strip()),
            format="{time:HH:mm:ss} | {level:<7} | {message}",
            level="INFO",
        )
        self._live = Live(self, console=console, refresh_per_second=10)
        self._live.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self._live.__exit__(*exc)
        logger.remove(self._sink_id)
        logger.add(sys.stderr)


def run_command(
    config: Annotated[Path, typer.Option("-c", "--config", help="Path to TOML config file.")],
) -> None:
    """Run a job from a TOML config file."""
    if not config.exists():
        print_error(f"Config file not found: {config}")
        raise typer.Exit(1)

    try:
        with open(config, "rb") as f:
            raw = tomllib.load(f)
        job_config = JobConfig.model_validate(raw)
    except Exception as e:
        print_error(f"Invalid config: {e}")
        raise typer.Exit(1)

    # Job info panel
    info = Table(show_header=False, box=None, pad_edge=False, padding=(0, 3))
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Job", job_config.job_name or "(unnamed)")
    info.add_row("Agents", ", ".join(a.name for a in job_config.agents))
    info.add_row("Datasets", ", ".join(job_config.datasets) or "(none)")
    info.add_row("Tasks", ", ".join(job_config.tasks) or "(none)")
    info.add_row("Attempts", str(job_config.n_attempts))
    info.add_row("Concurrent", str(job_config.n_concurrent_trials))
    console.print(Panel(info, title="Terrarium Run", title_align="left", border_style="blue"))

    # Run with live progress UI
    job = Job(job_config)
    with _ProgressUI(job):
        job_result = asyncio.run(job.run())

    # Results table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2), pad_edge=False, expand=True)
    table.add_column("#", style="dim")
    table.add_column("Trial", style="cyan")
    table.add_column("Score", justify="center")
    table.add_column("Checks", justify="left")
    table.add_column("Duration", justify="right")

    for i, tr in enumerate(job_result.trial_results, 1):
        if tr.exception_info:
            score_str = "[bold red]ERR[/bold red]"
            checks_str = f"[red]{tr.exception_info.exception_type}[/red]"
        elif tr.checker_result:
            score_val = tr.checker_result.score
            score_str = f"[bold green]{score_val:.2f}[/bold green]" if score_val >= 1.0 else f"[bold red]{score_val:.2f}[/bold red]"
            checks_parts = []
            for c in tr.checker_result.checks:
                mark = "[green]pass[/green]" if c.passed else "[red]fail[/red]"
                checks_parts.append(f"{c.name}: {mark}")
            checks_str = ", ".join(checks_parts)
        else:
            score_str = "[dim]N/A[/dim]"
            checks_str = ""

        duration = f"{tr.execution_timing.duration_sec:.1f}s" if tr.execution_timing and tr.execution_timing.duration_sec else "-"
        table.add_row(str(i), tr.trial_name, score_str, checks_str, duration)

    console.print(Panel(table, title="Trial Results", title_align="left", border_style="green", padding=(0, 2)))

    # Summary
    stats = job_result.stats
    duration_str = f"{job_result.timing.duration_sec:.1f}s" if job_result.timing.duration_sec else "-"

    summary = Table(show_header=False, box=None, padding=(0, 3), pad_edge=False)
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Trials", str(stats.n_trials))
    summary.add_row("Errors", f"[red]{stats.n_errors}[/red]" if stats.n_errors > 0 else "0")
    summary.add_row("Duration", duration_str)

    metric_panels = []
    for key, group in stats.agent_dataset_stats.items():
        metric_table = Table(show_header=False, box=None, padding=(0, 3), pad_edge=False)
        metric_table.add_column(style="bold")
        metric_table.add_column()
        for metric_name, metric_val in group.metrics.items():
            metric_table.add_row(metric_name, f"{metric_val:.4f}")
        metric_panels.append(Panel(metric_table, title=key, title_align="left", border_style="cyan"))

    parts = [summary]
    if metric_panels:
        parts.extend(metric_panels)

    console.print(Panel(Group(*parts), title="Summary", title_align="left", border_style="bold"))
