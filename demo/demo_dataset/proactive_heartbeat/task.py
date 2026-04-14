"""Proactive Heartbeat

Agent receives periodic heartbeat signals and checks for new experiment
results in the workspace. When new results appear, the agent reads them
and emails a summary to Alex.
"""
from datetime import datetime
from pathlib import Path

from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers, aggregate_results

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"

HEARTBEAT = "[heartbeat] Periodic check-in. Inspect the environment for any changes and act accordingly."


@entry(capabilities=["email"])
def proactive_heartbeat(env, agent):

    # =====================================================================
    # Setup — tell the agent to monitor /root/results/ on each heartbeat
    # and email Alex when new results appear.
    # =====================================================================

    email_info = env.email.connection_info

    agent.act(
        "[2025-06-10 09:00] "
        "Hey, I'm Alex. I'm running a long RL training experiment. "
        "You'll receive periodic heartbeat signals. Each time, check "
        "/root/results/ for any new result files. If you find new ones, "
        "read them and send me a summary email. If nothing new, do nothing.\n\n"
        f"My email: alex@university.edu\n"
        f"IMAP at {email_info['imap_host']}:{email_info['imap_port']}, "
        f"SMTP at {email_info['smtp_host']}:{email_info['smtp_port']}, no password"
    )

    # =====================================================================
    # Heartbeat 1 — no results yet. Agent should find nothing.
    # =====================================================================

    agent.act(f"[2025-06-10 09:30] {HEARTBEAT}")

    check_hb1 = run_checkers({
        "no_email_when_empty": lambda: env.email.count_inbox("alex@university.edu") == 0,
    }, tags=["heartbeat1"])

    # =====================================================================
    # Environment self-change: first result file appears.
    # Heartbeat 2 — agent should find it and email Alex.
    # =====================================================================

    env.workspace.fs.upload(
        str(RESOURCES_DIR / "result_epoch_50.txt"),
        "/root/results/result_epoch_50.txt",
    )

    agent.act(f"[2025-06-10 10:00] {HEARTBEAT}")

    check_hb2 = run_checkers({
        "emailed_epoch_50": lambda: env.email.count_inbox("alex@university.edu") == 1,
    }, tags=["heartbeat2"])

    # =====================================================================
    # Environment self-change: second result file appears.
    # Heartbeat 3 — agent should find the new file and email Alex.
    # =====================================================================

    env.workspace.fs.upload(
        str(RESOURCES_DIR / "result_epoch_100.txt"),
        "/root/results/result_epoch_100.txt",
    )

    agent.act(f"[2025-06-10 10:30] {HEARTBEAT}")

    check_hb3 = run_checkers({
        "emailed_epoch_100": lambda: env.email.count_inbox("alex@university.edu") == 2,
    }, tags=["heartbeat3"])

    # =====================================================================
    # Heartbeat 4 — nothing new. Agent should not send another email.
    # =====================================================================

    agent.act(f"[2025-06-10 11:00] {HEARTBEAT}")

    check_hb4 = run_checkers({
        "no_extra_email": lambda: env.email.count_inbox("alex@university.edu") == 2,
    }, tags=["heartbeat4"])

    return aggregate_results(check_hb1, check_hb2, check_hb3, check_hb4)
