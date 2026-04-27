from __future__ import annotations

import http.server
import socketserver
import webbrowser
from functools import partial
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from terrarium.cli.utils import console


def view_command(
    port: Annotated[int | None, typer.Option(
        "--port", "-p",
        help="TCP port to bind.",
    )] = None,
    host: Annotated[str, typer.Option(
        "--host",
        help="Host to bind.",
    )] = "127.0.0.1",
    no_open: Annotated[bool, typer.Option(
        "--no-open",
        help="Skip opening the browser.",
    )] = False,
) -> None:
    """Browse trial results in a web UI."""
    http.server.SimpleHTTPRequestHandler.log_message = lambda *_: None
    viewer_dir = Path(__file__).parent / "viewer"
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(viewer_dir))

    with socketserver.TCPServer((host, port or 0), handler) as httpd:
        bound_host, bound_port = httpd.server_address
        url = f"http://{bound_host}:{bound_port}/"

        info = Table(show_header=False, box=None, pad_edge=False, padding=(0, 3))
        info.add_column(style="bold")
        info.add_column()
        info.add_row("URL", f"[link={url}][cyan]{url}[/cyan][/link]")
        console.print(Panel(
            info,
            title="Terrarium Viewer",
            title_align="left",
            border_style="blue",
            subtitle="[dim]press Ctrl-C to stop[/dim]",
            subtitle_align="right",
        ))

        if not no_open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
