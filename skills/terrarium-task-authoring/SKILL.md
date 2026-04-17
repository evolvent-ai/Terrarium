---
name: terrarium-task-authoring
description: Guide for writing Terrarium tasks. Use this skill when the user wants to create a new task.py, define checkers, use capabilities (email, calendar, workspace, postgres, notion, google_sheets), design multi-stage agent workflows, or integrate their own scenario into Terrarium. Activate whenever someone mentions writing tasks, the @entry decorator, agent.act(), run_checkers, environment capabilities, or task directory structure.
---

# Terrarium Task Authoring Guide

This guide covers how to write Terrarium tasks — Python scripts that orchestrate a living environment and drive an agent through multi-stage scenarios with automated checking.

## Task Directory Structure

```
my_task/
  task.py           # required: contains the @entry function
  task.toml         # required: task metadata
  task.md           # optional: human-readable description
  resources/        # optional: files to upload into the environment
```

**task.toml:**

```toml
[metadata]
name = "my_task"                  # recommended, falls back to directory name
author = "your_name"              # optional
difficulty = "medium"             # optional
category = "personal_assistant"   # optional
tags = ["email", "calendar"]      # optional
description = "What this task evaluates."  # recommended
```

## The @entry Decorator

Every task.py has exactly one function decorated with `@entry`. This is the task's entry point.

```python
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers, aggregate_results

@entry(capabilities=["email", "calendar"])
def my_task(env, agent):
    # ... setup, agent.act(), checks ...
    return run_checkers({...})
```

- `capabilities` declares what the environment should provision. Available: `email`, `calendar`, `postgres`, `workspace`, `notion`, `google_sheets`.
- Workspace is always included automatically for sandbox-based agents (claude_code, openclaw) even if not listed.
- The function receives `env` (ComposableEnvironment) and `agent` (BaseAgent).
- It must return a `CheckerResults`. You can use the helper functions `run_checkers()` and `aggregate_results()`, or construct a `CheckerResults` directly.

### Configuring capabilities

Pass per-capability options via the optional `capabilities_config` keyword. Keys match the entries in `capabilities` (`"<type>"` or `"<type>:<instance>"`), values are forwarded to the capability constructor.

```python
@entry(
    capabilities=["postgres", "email"],
    capabilities_config={
        "postgres": {"db_name": "shop", "port": 5433},
        "email": {"smtp_port": 3125},
    },
)
def my_task(env, agent):
    ...
```

Only set keys you want to override — every capability has defaults. See the reference files under `references/` for supported config keys. For multi-instance capabilities, key by the full spec:

```python
@entry(
    capabilities=["postgres:primary", "postgres:analytics"],
    capabilities_config={
        "postgres:primary": {"db_name": "main"},
        "postgres:analytics": {"db_name": "warehouse"},
    },
)
```

The agent's own workspace image always wins over any `workspace` entry the task declares (the image has the agent CLI pre-installed), but other workspace keys pass through.

## Driving the Agent

`agent.act(instruction)` sends a natural language instruction to the agent and waits for completion. Call it multiple times for multi-turn interactions.

```python
agent.act("Check your email for the exam details and create a calendar event.")
# ... environment changes ...
agent.act("I just got a new email. Read it and act accordingly.")
```

Include connection info so the agent knows how to access services:

```python
email_info = env.email.connection_info
agent.act(
    "Hey, I'm Alex. Check my email for new messages.\n\n"
    f"My email: alex@example.com, "
    f"IMAP at {email_info['imap_host']}:{email_info['imap_port']}, "
    f"SMTP at {email_info['smtp_host']}:{email_info['smtp_port']}, no password"
)
```


### Installing skills

Tasks can install skills into the agent before issuing instructions:

```python
from pathlib import Path

agent.install_skill(Path(__file__).parent / "skills" / "db_helper")
agent.act("Use the db_helper skill to import the CSV into PostgreSQL.")
```

The skill directory is uploaded into the agent's skill path (e.g., `~/.claude/skills/` for ClaudeCodeAgent). Not all agents support this — claude_code and openclaw do.

### Agent tools and system prompt

Tasks can register Python callables as tools and set a system prompt on the agent:

```python
agent.system_prompt = "You are a customer service agent for a retail company."
agent.register_tools(*tools.get_all_callables())
```

Currently only MiniAgent supports these methods.

## Checkers

Checkers are boolean predicates that verify expected outcomes after agent actions.

```python
result = run_checkers({
    "email_sent": lambda: env.email.count_inbox("prof@university.edu") > 0,
    "data_imported": lambda: env.postgres.query("SELECT count(*) FROM t")[0]["count"] == 5,
}, tags=["stage1"])
```

- Each checker is a `name: callable` pair. The callable should return a truthy/falsy value.
- `tags` are optional — useful for grouping checks by stage.
- If a checker raises an exception, it counts as failed (not crashed).

Use `aggregate_results()` to merge checks from multiple stages:

```python
check_stage0 = run_checkers({...}, tags=["stage0"])
check_stage1 = run_checkers({...}, tags=["stage1"])
return aggregate_results(check_stage0, check_stage1)
```

The final score is `n_passed / n_total` across all checks.

## Accessing Capabilities

Capabilities are accessed via `env.<capability_name>`:

```python
env.email.send(from_addr="hr@co.com", to="agent@co.com", subject="Hi", body="...")
env.postgres.query("SELECT * FROM users")
env.calendar.create_calendar("Work")
env.workspace.fs.upload("local/file.txt", "/root/file.txt")
```

For complete API reference of each capability, read the corresponding file in `references/`:

| Capability | Reference | Type |
|------------|-----------|------|
| email | [references/capability-email.md](references/capability-email.md) | Sandbox (GreenMail) |
| calendar | [references/capability-calendar.md](references/capability-calendar.md) | Sandbox (Radicale CalDAV) |
| workspace | [references/capability-workspace.md](references/capability-workspace.md) | Sandbox (Docker container) |
| postgres | [references/capability-postgres.md](references/capability-postgres.md) | Sandbox (PostgreSQL 16) |
| notion | [references/capability-notion.md](references/capability-notion.md) | API (Notion Integration) |
| google_sheets | [references/capability-google-sheets.md](references/capability-google-sheets.md) | API (Google Sheets) |

Read only the reference files you need for the task you're writing.

### Multi-instance capabilities

If a task needs multiple instances of the same capability (e.g., two databases), declare them with names:

```python
@entry(capabilities=["postgres:primary", "postgres:analytics"])
def my_task(env, agent):
    env.postgres("primary").execute("CREATE TABLE ...")
    env.postgres("analytics").execute("CREATE TABLE ...")
```

With a single instance, `env.postgres.query(...)` works directly (transparent passthrough).

## Control Flow Patterns

Tasks are just Python — use loops, branches, and environment mutations between agent calls.

### Environment self-change

Modify the environment between agent actions to simulate real-world dynamics:

```python
agent.act("Monitor /root/results/ for new files. Email me when something appears.")

# Nothing there yet
agent.act("[10:00] Heartbeat: check for changes.")

# Now a file appears
env.workspace.fs.upload(str(RESOURCES / "result.txt"), "/root/results/result.txt")
agent.act("[10:30] Heartbeat: check for changes.")
```

### Conditional branching

Branch based on what the agent actually did:

```python
notes = get_notion_text(env, page_id)
if "bellman equation" in notes.lower():
    # Agent covered the topic — proceed to next stage
    env.email.send(from_addr="prof@uni.edu", to="alex@uni.edu",
                   subject="Exam Rescheduled", body="...")
    agent.act("Check your email for updates.")
else:
    # Agent missed it — ask for extension
    agent.act("Send an email to the professor requesting more time.")
```

### Loops

Repeat until a condition is met (with a cap):

```python
agent.act("Write a study guide in my Notion page.")

original_length = len(get_text(env, page_id))
for _ in range(5):
    if len(get_text(env, page_id)) >= original_length * 5:
        break
    agent.act("The guide is too brief. Expand it with more details.")
```

## Using Resources

Place static files in `resources/` and upload them to the workspace:

```python
from pathlib import Path
RESOURCES = Path(__file__).resolve().parent / "resources"

env.workspace.fs.upload(str(RESOURCES / "notes"), "/root/notes")
```

## Organizing Tasks in a Dataset

Group tasks in a dataset directory:

```
my_dataset/
  dataset.toml
  task_a/
    task.toml
    task.py
  category/          # nesting is fine — tasks are discovered recursively
    task_b/
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

## Parameterized Tasks

When a benchmark has many tasks that share the same logic and differ only in data (tau2-bench, Harbor-style suites, etc.), one `task.py` can expand into N independent task instances. Attach a generator to the entry function via `@<entry_fn>.parameterize`:

```python
@entry(capabilities=["workspace"])
def task(env, agent, *, task_index: int):
    task_data = _load_tasks()[task_index]
    # ... shared logic using task_data ...
    return run_checkers({...})

@task.parameterize
def params():
    tasks = _load_tasks()
    for i in range(len(tasks)):
        yield {"name": f"retail_task_{i}", "params": {"task_index": i}}
```

Each yielded dict becomes a full `Task`:

| key | required | purpose |
|---|---|---|
| `name` | yes | Task instance name (shows up in trial names and metrics) |
| `params` | yes | kwargs injected into the entry function |
| `capabilities` | no | Override `@entry(capabilities=...)` for this instance |
| `capabilities_config` | no | Override `@entry(capabilities_config=...)` for this instance |

Each yielded item becomes an independent task (its own trial, its own metrics). Disk layout stays minimal — **one directory, one `task.py`** — instead of N near-identical directories.

## Demo Tasks

The `demo/demo_dataset/` directory contains example tasks that demonstrate key patterns:

- **minimal** — two-stage file task, smallest possible multi-turn demo
- **branch_and_loop** — multi-capability (email, notion, calendar), loop to expand content, conditional branching based on environment state
- **proactive_webhook** — webhook-driven email monitoring, agent decides whether to reply
- **proactive_heartbeat** — periodic heartbeat signals, agent tracks state across turns, environment self-change between heartbeats

Read these for real-world examples of task structure, checker design, and control flow.

## Complete Example

A minimal but complete task:

```python
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers

@entry(capabilities=["email"])
def email_reply(env, agent):
    # Setup: send an email to the agent
    env.email.send(
        from_addr="boss@company.com",
        to="assistant@company.com",
        subject="Meeting Tomorrow",
        body="Can you confirm the 3pm meeting tomorrow?",
    )

    # Agent acts
    email_info = env.email.connection_info
    agent.act(
        "Hey, I'm your assistant. Check my email and reply to confirm.\n\n"
        f"My email: assistant@company.com, "
        f"IMAP at {email_info['imap_host']}:{email_info['imap_port']}, "
        f"SMTP at {email_info['smtp_host']}:{email_info['smtp_port']}, no password"
    )

    # Check: did the agent send a reply?
    return run_checkers({
        "reply_sent": lambda: env.email.count_inbox("boss@company.com") > 0,
    })
```
