from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table
from typer import Typer

from terrarium.adapters.llamafactory import write_llamafactory_sft_dataset
from terrarium.cli.utils import console, print_error

export_app = Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def llamafactory_sft_command(
    job_dir: Annotated[Path, typer.Argument(help="Terrarium job output directory.")],
    output_dir: Annotated[Path | None, typer.Option(
        "--output-dir",
        "-o",
        help="Directory for data.json and dataset_info.json.",
    )] = None,
    dataset_name: Annotated[str | None, typer.Option(
        "--dataset-name",
        help="Dataset name to register in dataset_info.json. Defaults to the job directory name.",
    )] = None,
    include_failed: Annotated[bool, typer.Option(
        "--include-failed",
        help="Include trials with exception_info in their result.json.",
    )] = False,
    include_thinking: Annotated[bool, typer.Option(
        "--include-thinking",
        help="Include ThinkingBlock content in exported assistant messages.",
    )] = False,
) -> None:
    """Export job trajectories as a LlamaFactory SFT dataset."""
    output_dir = output_dir or (job_dir / "llamafactory_sft")
    try:
        result = write_llamafactory_sft_dataset(
            job_dir,
            output_dir,
            dataset_name=dataset_name,
            include_failed=include_failed,
            include_thinking=include_thinking,
        )
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)

    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 3))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Dataset", result.dataset_name)
    table.add_row("Records", str(result.n_records_written))
    table.add_row("Trials seen", str(result.n_trials_seen))
    table.add_row("Data", str(result.data_path))
    table.add_row("Dataset info", str(result.dataset_info_path))
    table.add_row("Skipped failed", str(result.n_failed_trials_skipped))
    table.add_row("Skipped missing trajectory", str(result.n_missing_trajectory_skipped))
    table.add_row("Skipped empty trajectory", str(result.n_empty_trajectory_skipped))
    console.print(Panel(table, title="LlamaFactory SFT Export", title_align="left", border_style="green"))


export_app.command(name="llamafactory-sft", help="Export job trajectories as LlamaFactory SFT data.")(llamafactory_sft_command)
