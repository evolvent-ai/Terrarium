"""Tests for export CLI commands."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from terrarium.cli.main import app
from terrarium.models.checker import Check, CheckerResults
from terrarium.models.result import AgentInfo, TaskInfo, TrialResult
from terrarium.models.trajectory import Message, Trajectory


def test_llamafactory_sft_cli_writes_dataset(tmp_path):
    job_dir = tmp_path / "job"
    trial_dir = job_dir / "trial_a"
    out_dir = tmp_path / "sft"
    trial_dir.mkdir(parents=True)

    trial_result = TrialResult(
        trial_name="trial_a",
        task_info=TaskInfo(name="task_a", path="/tmp/task_a"),
        agent_info=AgentInfo(name="mock"),
        checker_result=CheckerResults(checks=[Check(name="ok", passed=True)], score=1.0),
    )
    (trial_dir / "result.json").write_text(trial_result.model_dump_json(indent=2))
    (trial_dir / "trajectory.json").write_text(Trajectory(messages=[
        Message(role="user", content="Hi"),
        Message(role="assistant", content="Hello"),
    ]).model_dump_json(indent=2))

    result = CliRunner().invoke(app, [
        "export",
        "llamafactory-sft",
        str(job_dir),
        "--output-dir",
        str(out_dir),
        "--dataset-name",
        "terrarium_demo",
    ])

    assert result.exit_code == 0
    assert "terrarium_demo" in result.stdout
    assert json.loads((out_dir / "data.json").read_text()) == [
        {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            "tools": "",
        }
    ]
    dataset_info = json.loads((out_dir / "dataset_info.json").read_text())
    assert "terrarium_demo" in dataset_info
    assert dataset_info["terrarium_demo"]["columns"]["tools"] == "tools"
