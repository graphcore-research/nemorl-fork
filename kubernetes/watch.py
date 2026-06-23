#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "typer",
#     "rich",
# ]
# ///


import re
import subprocess
import time
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
err_console = Console(stderr=True)


def parse_timespan(time_str: str) -> int:
    """Parse time strings like '3m36s', '1h', '2d' into seconds."""
    units = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 60 * 60 * 24,
        "w": 60 * 60 * 24 * 7,
    }
    total_seconds = 0
    for match in re.finditer(r"(\d+)([a-zA-Z]+)", time_str):
        value, unit = match.groups()
        if unit not in units:
            raise ValueError(f"Invalid time unit: {unit}")
        total_seconds += int(value) * units[unit]
    return total_seconds


@dataclass
class Pod:
    name: str
    status: str
    age: str


def get_pods(kube_job_name: str) -> list[Pod]:
    cmd = "kubectl get pods"
    result = subprocess.run(
        cmd.split(),
        capture_output=True,
        text=True,
        check=False,
    )
    retcode, stdout = result.returncode, result.stdout

    if retcode != 0:
        err_console.print(f"[red]Failed to run `{cmd}`. Exit code: {retcode}[/red]")
        raise typer.Exit(retcode)

    pods = []
    for line in stdout.splitlines():
        if kube_job_name in line:
            pod_name, _ready, status, _restarts, age = line.strip().split()
            pods.append(Pod(name=pod_name, status=status, age=age))

    # oldest first
    pods.sort(key=lambda p: parse_timespan(p.age), reverse=True)
    return pods


def create_pod_table(pods: list[Pod]) -> Table:
    table = Table()
    table.add_column("Pod Name", style="white", no_wrap=True)
    table.add_column("Age", justify="center")
    table.add_column("Status", justify="center")

    if not pods:
        table.add_row("No pods found", "[yellow]N/A[/yellow]")
        return table

    for pod in pods:
        name = pod.name
        status = pod.status
        age = pod.age

        if status == "Running":
            status = "[green]Running[/green]"
        elif status in ["Failed", "Error", "CrashLoopBackOff"]:
            status = f"[red]{status}[/red]"
        else:
            status = f"[blue]{status}[/blue]"

        table.add_row(name, age, status)

    return table


@app.command()
def main(kube_job_name: str):
    """Monitor Kubernetes pods for a specific job."""
    console.print(f"[cyan bold]Monitoring pods for job: {kube_job_name}[/cyan bold]")
    console.print("Follow logs with: kubectl logs -f [pod name]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    def get_table():
        pods = get_pods(kube_job_name)
        return create_pod_table(pods)

    try:
        with Live(get_table(), console=console, refresh_per_second=0.2) as live:
            while True:
                live.update(get_table())
                time.sleep(5)

    except KeyboardInterrupt:
        err_console.print("\n[yellow]Monitoring stopped.[/yellow]")
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
