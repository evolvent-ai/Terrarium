---
name: terrarium-user-guide
description: Guide for running agent tasks with Terrarium. Use this skill when the user wants to configure a job, choose agents, run tasks via CLI or Python API, understand results and metrics, or troubleshoot execution issues. Activate whenever someone mentions running tasks, configuring agents, job TOML files, trial results, evaluation scores, or anything related to using Terrarium.
---

# Terrarium User Guide

Terrarium is a Python framework for building living environments and running LLM agents through multi-stage, multi-turn tasks. Task scripts (pure Python) orchestrate capabilities like email, databases, calendars, and workspaces, while collecting structured results and metrics.

## Prerequisites

```bash
uv sync                  # install dependencies
```

For sandbox-based agents (claude_code, openclaw, codex), build the Docker image:

```bash
docker build -t terrarium/claude-code -f docker/claude-code.Dockerfile docker/
docker build -t terrarium/openclaw -f docker/openclaw.Dockerfile docker/
docker build -t terrarium/codex -f docker/codex.Dockerfile docker/
```

Set environment variables in `.env` at the project root:

```
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://api.anthropic.com  # optional
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com        # optional
```

## Two Ways to Run

### Option 1: CLI

```bash
terrarium run -c job.toml
```

The CLI shows a live execution log, per-trial results with pass/fail checks, and aggregated metrics.

### Option 2: Python API

Run a batch job:

```python
import asyncio
from terrarium import Job, JobConfig, AgentConfig

config = JobConfig(
    agents=[AgentConfig(name="claude_code")],
    datasets=["demo/demo_dataset"],
    n_attempts=1,
)
result = asyncio.run(Job(config).run())

for tr in result.trial_results:
    print(f"{tr.trial_name}: {tr.checker_result.score}")
```

Run a single trial:

```python
from terrarium import Trial, TrialConfig, TaskConfig, AgentConfig

config = TrialConfig(
    task=TaskConfig(path="demo/demo_dataset/branch_and_loop"),
    agent=AgentConfig(name="claude_code"),
)
result = await Trial(config).run()
print(result.checker_result.score)
```

## Job Configuration (TOML)

A complete job config:

```toml
job_name = "my_eval"
datasets = ["demo/demo_dataset", "benchmarks/tau2"]
tasks = ["path/to/standalone_task"]     # optional, for tasks not in a dataset
n_attempts = 3                          # repeat each agent x task combo
n_concurrent_trials = 4                 # parallel execution slots

[[agents]]
name = "claude_code"
model_name = "claude-sonnet-4-6"        # optional, overrides default model

[[agents]]
name = "openclaw"
model_name = "terrarium/anthropic/claude-sonnet-4.6"

[retry]
max_retries = 1
min_wait_sec = 1.0
max_wait_sec = 60.0
wait_multiplier = 2.0
```

Equivalent Python:

```python
JobConfig(
    job_name="my_eval",
    agents=[
        AgentConfig(name="claude_code", model_name="claude-sonnet-4-6"),
        AgentConfig(name="openclaw", model_name="terrarium/anthropic/claude-sonnet-4.6"),
    ],
    datasets=["demo/demo_dataset", "benchmarks/tau2"],
    tasks=["path/to/standalone_task"],
    n_attempts=3,
    n_concurrent_trials=4,
    retry=RetryConfig(max_retries=1),
)
```

### Key fields

| Field | Default | Description |
|-------|---------|-------------|
| `agents` | (required) | List of agent configs, each with `name` and optional `model_name`, `kwargs` |
| `job_name` | timestamp | Name for the output directory |
| `datasets` | `[]` | Paths to dataset directories (each containing `dataset.toml`) |
| `tasks` | `[]` | Paths to individual task directories (ad-hoc, no dataset) |
| `n_attempts` | `1` | How many times to repeat each agent x task combination |
| `n_concurrent_trials` | `4` | Max parallel trial executions |
| `agent_setup_timeout_sec` | None | Timeout for agent setup phase |
| `agent_exec_timeout_sec` | None | Timeout for task execution phase |
| `retry` | no retries | Retry config: `max_retries`, `min_wait_sec`, `max_wait_sec`, `wait_multiplier` |

### Execution expansion

The job engine expands `agents x (datasets + tasks) x n_attempts` into individual trials. For example, 2 agents, 1 dataset with 3 tasks, 2 attempts = 12 trials.

## Agents

### Built-in agents

| Name | Runs in | Description |
|------|---------|-------------|
| `claude_code` | Docker | Claude Code CLI with stream-json output |
| `openclaw` | Docker | OpenClaw CLI with session JSONL output |
| `codex` | Docker | OpenAI Codex CLI with session JSONL output |
| `mini` | In-process | Lightweight agent using litellm, for testing |

### Agent configuration

**claude_code** — runs Claude Code CLI in Docker (`terrarium/claude-code`). Requires `ANTHROPIC_API_KEY` in `.env`.

```toml
[[agents]]
name = "claude_code"
model_name = "claude-sonnet-4-6"
kwargs = { max_turns = 50 }          # optional
```

| kwarg | type | default | description |
|-------|------|---------|-------------|
| `api_key` | str | from `ANTHROPIC_API_KEY` env | API key override |
| `max_turns` | int | None (unlimited) | Max tool-call turns per `act()` |

**openclaw** — runs OpenClaw CLI in Docker (`terrarium/openclaw`). Requires a models config JSON file.

```toml
[[agents]]
name = "openclaw"
model_name = "terrarium/anthropic/claude-sonnet-4.6"
kwargs = { models_config_path = "./models.json" }
```

| kwarg | type | default | description |
|-------|------|---------|-------------|
| `models_config_path` | str | `""` (required) | Path to models provider config JSON |

**codex** — runs OpenAI Codex CLI in Docker (`terrarium/codex`). Requires `OPENAI_API_KEY` in `.env`.

```toml
[[agents]]
name = "codex"
model_name = "gpt-5.4"                       # or "openai/gpt-5" via OpenRouter
```

| kwarg | type | default | description |
|-------|------|---------|-------------|
| `api_key` | str | from `OPENAI_API_KEY` env | API key override |

**mini** — in-process agent using litellm. No Docker needed. Supports tool registration and custom system prompts from task code.

```toml
[[agents]]
name = "mini"
model_name = "gpt-4o-mini"
kwargs = { temperature = 0.0, max_tool_calls = 100 }
```

| kwarg | type | default | description |
|-------|------|---------|-------------|
| `temperature` | float | 0.0 | LLM sampling temperature |
| `max_tool_calls` | int | None (unlimited) | Max total tool calls per `act()` |
| `system_prompt` | str | None | System prompt (can also be set from task code) |
| `tools` | list | None | Tool callables (typically set from task code via `register_tools()`) |

**Custom agent** — import any class implementing `BaseAgent`:

```toml
[[agents]]
name = "my_agent"
import_path = "my_package.agent:MyAgent"
```

`model_name` is passed as the `model` kwarg to the agent constructor. All other `kwargs` are passed through directly.

## Dataset Configuration

A dataset is a directory with `dataset.toml` and subdirectories each containing a task:

```
my_dataset/
  dataset.toml
  task_a/
    task.toml
    task.py
  task_b/
    task.toml
    task.py
```

The `dataset.toml` configures metrics:

```toml
[metadata]
name = "my_benchmark"

[metrics]
types = ["mean", "max", "pass@5"]   # default: ["mean"]
```

Tasks are discovered recursively — nested directories like `domain/subdomain/task/` work.

### Available metrics

| Metric | Description |
|--------|-------------|
| `mean` | Average score across trials |
| `max` | Highest score |
| `min` | Lowest score |
| `sum` | Total score |
| `pass@k` | Probability at least 1 of k random picks scores 1.0 (averaged per task) |

## Output Structure

Results are persisted as JSON:

```
outputs/
  {job_name}/
    config.json        # JobConfig
    result.json        # JobResult (all trials + aggregated stats)
    {trial_name}/
      config.json      # TrialConfig
      result.json      # TrialResult (trajectory, checks, timing)
```

### Trial naming

Trial directories follow the pattern: `{agent}__{model}__{source}__{task}[__attemptN]`

For example: `claude_code__claude-sonnet-4-6__demo__branch_and_loop__attempt0`

### Result viewer

Open `demo/viewer.html` in a browser and drag in any `result.json` (job-level or trial-level) to explore:
- Job overview with stats and score distribution
- Per-trial details with full trajectory (tool calls, thinking blocks)
- Timing analysis and checker results

## Understanding Results

### Scores

Each task defines checkers — boolean predicates that verify expected outcomes. The trial score is `n_passed / n_total` (0.0 to 1.0).

### JobResult

A `JobResult` is the top-level output of a job run:

| Field | Description |
|-------|-------------|
| `trial_results` | List of `TrialResult`, one per trial execution |
| `stats` | `JobStats` — aggregated statistics (see below) |
| `timing` | Wall-clock start/end/duration for the entire job |

### TrialResult

Each trial produces a `TrialResult`:

| Field | Description |
|-------|-------------|
| `trial_name` | Identifier following `{agent}__{model}__{source}__{task}` pattern |
| `task_info` | Task name, path, and source (dataset name or "adhoc") |
| `agent_info` | Agent name, model, version |
| `checker_result.score` | 0.0–1.0, fraction of checks passed |
| `checker_result.checks` | Individual check names, pass/fail, and tags |
| `trajectory.messages` | All messages exchanged (user instructions, agent responses, tool calls) |
| `trajectory.metrics` | Token usage (input, output, cache read/creation), LLM calls, tool calls |
| `exception_info` | Error details if the trial failed (treated as score 0.0 in metrics) |
| `timing` | Wall-clock duration for the entire trial |
| `setup_timing` | Duration for agent setup phase |
| `execution_timing` | Duration for task execution phase |

### JobStats

Trial results are grouped by `{agent}__{model}__{source}`. Each group gets an `AgentDatasetStats`:

| Field | Description |
|-------|-------------|
| `n_trials` | Total trials in this group |
| `n_errors` | Trials that raised exceptions |
| `metrics` | Computed metrics from dataset config, e.g. `{"mean": 0.85, "max": 1.0}` |
| `score_stats` | Score distribution — maps score to trial names, e.g. `{1.0: ["trial_a"], 0.5: ["trial_b"]}` |
| `exception_stats` | Error distribution — maps exception type to trial names |

The top-level `JobStats` also has `n_trials` and `n_errors` summed across all groups.
