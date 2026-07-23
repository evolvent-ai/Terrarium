from importlib.metadata import version
from typing import Annotated, Optional

import typer
from typer import Typer

from terrarium.cli.export import export_app
from terrarium.cli.run import run_command
from terrarium.cli.view import view_command

app = Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def version_callback(value: bool) -> None:
    if value:
        print(f"terrarium {version('terrarium')}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[Optional[bool], typer.Option(
        "--version", "-v",
        callback=version_callback,
        is_eager=True,
    )] = None,
) -> None:
    pass


app.command(name="run", help="Run a job from a TOML config file.")(run_command)
app.command(name="view", help="Browse trial results in a web UI.")(view_command)
app.add_typer(export_app, name="export", help="Export Terrarium outputs.")
