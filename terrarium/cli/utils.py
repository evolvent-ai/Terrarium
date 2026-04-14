from rich.console import Console
from rich.panel import Panel

console = Console()


def print_error(message: str) -> None:
    console.print(Panel(str(message), title="Error", title_align="left", border_style="red"))
