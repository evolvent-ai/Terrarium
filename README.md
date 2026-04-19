# Terrarium: Multi-turn data engine for evaluating and optimizing LLM agents in living environments.



[Evolvent AI](https://evolvent.co)
[Blog](https://evolvent.co/en/research/terrarium)
[Discord](https://discord.gg/RCFuy6wttC)
[X](https://x.com/Evolvent_AI)
[LinkedIn](https://www.linkedin.com/company/evolvent-ai)
[Hugging Face](https://huggingface.co/EvolventAI)
[Star](https://github.com/evolvent-ai/Terrarium/stargazers)
[License](https://github.com/evolvent-ai/Terrarium/blob/main/LICENSE)



Terrarium is a framework for generating rich, multi-turn agent rollouts across living and evolving environments. You write task programs in pure Python that orchestrate a living environment — sending emails, populating databases, uploading files — drive LLM agents through it, and evaluate the outcomes. Think of it as a terrarium for agents — a contained world that lives and breathes while you watch how your agents behave.

Use it to benchmark agents, collect training trajectories, or build evaluation datasets that capture the complexity of real-world workflows.

[https://github.com/user-attachments/assets/eeaf0af8-4915-4482-ae2f-917870f09f11](https://github.com/user-attachments/assets/eeaf0af8-4915-4482-ae2f-917870f09f11)

[[video link]](https://oss.evolvent.co/articles/terrarium-1.mp4)

## News

- [2026-04-19] — Terrarium is now compatible with the [Harbor](https://www.harborframework.com/) task format via the bundled adapter at [`benchmarks/harbor-adapter/`](benchmarks/harbor-adapter/).

## Motivation

The way we evaluate and train agents has evolved through three phases:


|                  | Phase 1: Static QA                                                                                                                       | Phase 2: Single-turn Agents                          | Phase 3: Multi-turn Agents & Living Environments |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| Representative   | [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness), [lmms-eval](https://github.com/EvolvingLMMs-Lab/lmms-eval) | [Harbor](https://github.com/harbor-framework/harbor) | **Terrarium**                                    |
| Interaction      | Single-turn                                                                                                                              | Single-turn, multi-step                              | Multi-turn, multi-step                           |
| Environment      | None                                                                                                                                     | Static sandboxes                                     | Composable, mutates between turns                |
| Control flow     | —                                                                                                                                        | Linear                                               | Loops & branches                                 |
| Verification     | Ground-truth matching                                                                                                                    | Final test script                                    | Programmatic checkers at any stage               |
| Proactive agents | —                                                                                                                                        | —                                                    | Supported                                        |


Existing frameworks stop at Phase 2. They have limited support for environments that change mid-task, multi-turn agent interactions, or task logic with loops and branches. As agents move beyond coding into personal assistance, workflow automation, and proactive monitoring, these limitations become blocking. We built Terrarium to close this gap.

## Core Features

- **Living environments** — task programs mutate the environment between agent turns (new emails arrive, database records change, files appear), creating dynamic scenarios that static benchmarks can't express
- **Composable capabilities** — mix and match capabilities (`email`, `calendar`, `postgres`, `notion`, ...) in a single task. The framework handles provisioning, networking, and teardown. Sandbox-backed and API-based capabilities are treated uniformly.
- **Complex control flow** — loops, conditional branches, and stage-level checks, all in plain Python. No YAML schemas, no configuration languages.
- **Multi-turn formulation** — tasks drive agents through evolving worlds over many interactions, capturing context maintenance and adaptation across turns
- **Proactive agent support** — heartbeat and webhook patterns for agents that monitor, anticipate, and act on their own initiative

## Demo

A Claude Code agent running the **Branch & Loop** task — checking email, writing study notes in Notion, looping to expand content, and adapting to a mid-task schedule change.

[https://github.com/user-attachments/assets/6c2bcd92-b7a6-4baa-8e59-475e3c800eb1](https://github.com/user-attachments/assets/6c2bcd92-b7a6-4baa-8e59-475e3c800eb1)

[[video link]](https://oss.evolvent.co/articles/terrarium.mp4)

## Quick Start

```bash
git clone https://github.com/evolvent-ai/Terrarium.git
cd Terrarium
uv sync
```

### Setup Environment Variables

```bash
# .env
ANTHROPIC_API_KEY=sk-...
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://...
NOTION_TOKEN=ntn_...                          # if using notion capability
GOOGLE_SHEETS_CREDENTIALS_FILE=creds.json     # if using google_sheets capability
```

### Build Docker Images (optional)

Sandbox-based agents (claude_code, openclaw, codex) run inside containers. Build the images you need:

```bash
docker build -t terrarium/claude-code -f docker/claude-code.Dockerfile docker/
docker build -t terrarium/openclaw -f docker/openclaw.Dockerfile docker/
docker build -t terrarium/codex -f docker/codex.Dockerfile docker/
```

### Try It

```bash
terrarium run -c demo/run_config.toml
```

## Built-in Agents

Four agents are provided out of the box:


| Agent         | Runs in    | Description                                                                         |
| ------------- | ---------- | ----------------------------------------------------------------------------------- |
| `claude_code` | Docker     | Claude Code CLI, stream-json output, multi-turn via session ID                      |
| `openclaw`    | Docker     | OpenClaw CLI, session JSONL output                                                  |
| `codex`       | Docker     | OpenAI Codex CLI, session JSONL output, multi-turn via session ID                   |
| `mini`        | In-process | Lightweight agent via litellm, supports tool registration and custom system prompts |


Bring your own agent by implementing `BaseAgent` and loading via import path:

```python
AgentConfig(name="my_agent", import_path="my_package.agent:MyAgent")
```

## Benchmark Integration

### Writing a Task

A task is a directory with a Python script and metadata:

```
my_task/
  task.py         # @entry function — the task program
  task.toml       # metadata (name, tags, description)
  resources/      # optional files to upload into the environment
```

**task.toml:**

```toml
[metadata]
name = "my_task"
author = "your_name"
difficulty = "medium"
category = "data_processing"
tags = ["email", "postgres"]
description = "Agent reads email and imports data into PostgreSQL."
```

The `task.py` is where everything happens. Declare what capabilities you need, set up the environment, drive the agent, and verify the results:

```python
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers

@entry(capabilities=["postgres", "email"])
def my_task(env, agent):
    # 1. Set up the world
    env.email.send(from_addr="hr@co.com", to="agent@co.com",
                   subject="Data", body="Please import the attached CSV.")

    # 2. Drive the agent
    email_info = env.email.connection_info
    agent.act(
        "Check your email and import the data into PostgreSQL.\n\n"
        f"Email: agent@co.com, "
        f"IMAP at {email_info['imap_host']}:{email_info['imap_port']}, "
        f"SMTP at {email_info['smtp_host']}:{email_info['smtp_port']}, no password"
    )

    # 3. Verify the outcome
    return run_checkers({
        "data_imported": lambda: env.postgres.query("SELECT count(*) FROM t")[0]["count"] == 5,
        "reply_sent": lambda: env.email.count_inbox("hr@co.com") > 0,
    })
```

### Organizing into a Dataset

A dataset groups tasks together with shared metric configuration. Tasks are discovered recursively.

```
my_benchmark/
  dataset.toml
  import_task/
    task.toml
    task.py
  monitoring/
    heartbeat_task/
      task.toml
      task.py
    webhook_task/
      task.toml
      task.py
```

**dataset.toml:**

```toml
[metadata]
name = "my_benchmark"

[metrics]
types = ["mean", "max", "pass@5"]
```

Built-in metrics: `mean`, `max`, `min`, `sum`, `pass@k`.

### Parameterized Tasks

When many tasks share the same logic and differ only in data (tau2-bench, Harbor-style benchmarks, etc.), one `task.py` can expand into N independent task instances via `@task.parameterize`:

```python
@entry(capabilities=["workspace"])
def task(env, agent, *, task_index: int):
    task_data = _load_tasks()[task_index]
    # ... shared logic using task_data ...

@task.parameterize
def params():
    for i in range(len(_load_tasks())):
        yield {"name": f"retail_task_{i}", "params": {"task_index": i}}
```

Each yielded item becomes a full `Task` instance with its own name, metrics, and trial results. Optionally override `capabilities` or `capabilities_config` per instance:

```python
yield {"name": "with_db", "params": {...}, "capabilities": ["workspace", "postgres"]}
yield {"name": "alt_db", "params": {...}, "capabilities_config": {"postgres": {"db_name": "alt"}}}
```

The directory layout stays minimal — **one directory, one `task.py`** — instead of N near-identical directories.

## Running Jobs

**CLI** — point at a job config and go:

```bash
terrarium run -c job.toml
```

```toml
# job.toml
job_name = "my_eval"
datasets = ["my_benchmark"]
n_attempts = 3
n_concurrent_trials = 4

[[agents]]
name = "claude_code"
model_name = "claude-sonnet-4-6"
```

**Python API** — for programmatic control:

```python
import asyncio
from terrarium import Job, JobConfig, AgentConfig

result = asyncio.run(Job(JobConfig(
    agents=[AgentConfig(name="claude_code", model_name="claude-sonnet-4-6")],
    datasets=["my_benchmark"],
    n_attempts=3,
    n_concurrent_trials=4,
)).run())

for tr in result.trial_results:
    print(f"{tr.trial_name}: {tr.checker_result.score}")
```

The engine expands `agents x tasks x attempts` into individual trials, runs them concurrently, and aggregates metrics (`mean`, `max`, `min`, `sum`, `pass@k`).

## Checking Job Results

Every trial produces a `TrialResult` with the full trajectory, checker pass/fail, token usage, and timing. Results are persisted as JSON:

```
outputs/{job_name}/
  result.json                    # aggregated stats and metrics
  {trial_name}/result.json       # full trajectory, checks, timing
```

Drag any `result.json` into `demo/viewer.html` to explore interactively.

## Design Highlights

### Living Environments

Real-world environments don't sit still. New emails arrive, files appear, schedules change — often while the agent is working. Terrarium lets the task program mutate the environment between agent turns, creating scenarios that static benchmarks simply can't express.

```python
@entry(capabilities=["postgres"])
def order_monitoring(env, agent):
    env.postgres.execute("CREATE TABLE orders (id SERIAL, status TEXT, item TEXT)")
    env.postgres.execute("INSERT INTO orders (status, item) VALUES ('shipped', 'laptop')")

    agent.act("Check the orders table and summarize any pending orders.")
    # No pending orders — agent reports nothing to do.

    # A new order arrives between turns
    env.postgres.execute("INSERT INTO orders (status, item) VALUES ('pending', 'keyboard')")

    agent.act("Check again for any updates.")
    # Agent should find the new pending order and report it.
```

### Composable Environments

Agent tasks in the real world span multiple services — email, calendars, databases, file systems, cloud APIs. Like assembling a terrarium from soil, water, and plants, you compose an environment from capabilities — declare what you need, and the framework provisions, networks, and tears down everything automatically.

```python
@entry(capabilities=["email", "calendar", "notion", "postgres"])
def composable_capabilities(env, agent):
    env.email.send(...)          # GreenMail container
    env.calendar.add_event(...)  # Radicale CalDAV container
    env.notion.create_page(...)  # Notion API
    env.postgres.execute(...)    # PostgreSQL container
```

Six capabilities are built-in. Sandbox-backed and API-based capabilities are treated uniformly — tasks use them through the same interface:


| Capability    | Type    | Backend                              |
| ------------- | ------- | ------------------------------------ |
| workspace     | Sandbox | Linux container (shell + filesystem) |
| email         | Sandbox | GreenMail (SMTP/IMAP)                |
| postgres      | Sandbox | PostgreSQL 16                        |
| calendar      | Sandbox | Radicale (CalDAV)                    |
| notion        | API     | Notion API                           |
| google_sheets | API     | Google API                           |


### Complex Control Flow

Task definitions are pure Python functions. Loops, conditional branches, intermediate checks, dynamic stage generation — anything you can express in Python, you can use to define a task.

```python
@entry(capabilities=["email", "notion", "calendar"])
def branch_and_loop(env, agent):
    # Stage 0: agent reads email, creates calendar event
    env.email.send(from_addr="prof@uni.edu", to="alex@uni.edu", subject="Exam Reminder", body=EXAM_EMAIL)
    agent.act("Check my email and create a calendar event for the exam.")

    # Stage 1: agent writes study guide, loop until it's detailed enough
    agent.act("Read my lecture notes and write a study guide in Notion.")
    original_length = len(get_text(env, page_id))
    for _ in range(5):
        if len(get_text(env, page_id)) >= original_length * 5:
            break
        agent.act("The guide is too brief. Expand it with more details.")

    # Stage 2: branch based on what the agent actually wrote
    if "bellman equation" in get_text(env, page_id).lower():
        env.email.send(from_addr="prof@uni.edu", to="alex@uni.edu", subject="Rescheduled", body=RESCHEDULE_EMAIL)
        agent.act("Check my email for updates.")
    else:
        agent.act("I'm not ready for the exam. Email the professor requesting an extension.")

    return aggregate_results(check_stage0, check_stage1, check_stage2)
```

### Multi-Turn Formulation

Terrarium introduces a programmatic DSL for multi-turn agent tasks: each `agent.act()` call is a turn, each task is a program that drives the agent through an evolving world. This formulation captures what single-turn benchmarks miss — the ability to maintain context, adapt to changes, and execute plans across diverse tools over many interactions.

```python
@entry(capabilities=["email", "notion", "calendar"])
def multi_turn_task(env, agent):
    agent.act("Check my email for the exam details and create a calendar event.")
    # ... environment changes ...
    agent.act("Read my lecture notes and put together a study guide in Notion.")
    # ... check intermediate results, branch ...
    agent.act("I just got a new email. Read it and act accordingly.")
```

### Infrastructure for Proactive Agents

Most benchmarks target reactive agents — give a prompt, get a response. Terrarium is the first data infrastructure designed for **proactive agents**: agents that monitor, anticipate, and act on their own initiative in response to environmental changes.

```python
# Heartbeat pattern: agent receives periodic signals and must decide what to do
@entry(capabilities=["workspace"])
def proactive_heartbeat(env, agent):
    agent.act("You'll receive periodic heartbeat signals. Check /root/results/ for new files each time.")
    agent.act("[09:30] Heartbeat: check for changes.")  # nothing — agent should do nothing
    env.workspace.fs.upload(...)                          # file appears
    agent.act("[10:00] Heartbeat: check for changes.")  # agent should notice and act

# Webhook pattern: agent receives event notifications and decides how to respond
@entry(capabilities=["email"])
def proactive_webhook(env, agent):
    agent.act("You'll receive email webhook notifications. Decide whether each needs a reply.")

    env.email.send(from_addr="boss@co.com", to="agent@co.com", subject="Urgent: client meeting", body="...")
    agent.act('{"event": "new_email", "from": "boss@co.com", "subject": "Urgent: client meeting"}')
    # Agent should read the email and reply.

    env.email.send(from_addr="newsletter@spam.com", to="agent@co.com", subject="Weekly digest", body="...")
    agent.act('{"event": "new_email", "from": "newsletter@spam.com", "subject": "Weekly digest"}')
    # Agent should ignore this one.
```

## Roadmap

- **More environment capabilities** — browser automation, Slack, MySQL/SQLite, cloud storage, and more
- **More agent adapters** — Anthropic SDK, OpenAI, LangChain, local models, and others
- **More sandbox providers** — support sandbox backends beyond Docker (e.g., cloud VMs, lightweight runtimes)
- **Benchmark integrations** — integrate more existing benchmarks beyond tau2-bench
- **CLI enhancements** — `terrarium init`, `terrarium validate`, result comparison, and richer output
- **Execution engine** — async task submission, distributed execution, and scalable orchestration
- **Documentation site** — full API reference, tutorials, and contributor guide

## Acknowledgements

Terrarium's CLI and execution infrastructure draws inspiration from [Harbor](https://github.com/harbor-framework/harbor). We thank the Harbor team for their pioneering work on agent evaluation tooling.

## License

This project is licensed under the [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) license. See [LICENSE](LICENSE) for details.