# Proactive Heartbeat

Alex is running a long RL training experiment. His personal assistant receives periodic heartbeat signals and checks the workspace for new result files. When new results appear, the agent reads them and emails Alex a summary.

## Capabilities

email

## Task Flow

The agent is told to monitor `/root/results/` on each heartbeat. Four heartbeats follow:

1. **Heartbeat 1** — no result files yet. Agent should do nothing.
2. **Heartbeat 2** — `result_epoch_50.txt` has appeared (environment self-change). Agent should read it and email Alex.
3. **Heartbeat 3** — `result_epoch_100.txt` has appeared. Agent should read it and email Alex.
4. **Heartbeat 4** — no new files. Agent should do nothing.

The heartbeat instruction is always the same:

```
[heartbeat] Periodic check-in. Inspect the environment for any changes and act accordingly.
```

## Checkers


| Check                 | What it verifies                                        |
| --------------------- | ------------------------------------------------------- |
| `no_email_when_empty` | No email sent when results directory is empty           |
| `emailed_epoch_50`    | Email sent after first result file appeared             |
| `emailed_epoch_100`   | Email sent after second result file appeared            |
| `no_extra_email`      | No extra email sent when nothing new on final heartbeat |


