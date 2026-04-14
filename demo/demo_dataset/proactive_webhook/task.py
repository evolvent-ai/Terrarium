"""Proactive Webhook

Agent monitors Alex's inbox and acts on incoming emails autonomously.
The task only sends a webhook notification — the agent decides what
to do on its own.
"""
import json
from datetime import datetime
from pathlib import Path

from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers, aggregate_results

EMAILS_PATH = Path(__file__).resolve().parent / "resources" / "emails.json"


def _webhook(email: dict) -> str:
    payload = {
        "event": "inbound_email",
        "timestamp": email["date"],
        "from": email["from"],
        "to": email["to"],
        "subject": email["subject"],
    }
    return f"[webhook] {json.dumps(payload)}"


@entry(capabilities=["email"])
def proactive_webhook(env, agent):

    # =====================================================================
    # Setup — tell the agent to monitor Alex's inbox and act accordingly.
    # =====================================================================

    email_info = env.email.connection_info

    agent.act(
        "[2025-06-10 09:00] "
        "Hey, I'm Alex. You're my personal assistant. I've set up a webhook "
        "that will notify you whenever a new email arrives. When you receive "
        "a webhook, read the email and take the appropriate action — reply "
        "if needed, or just note it if no reply is necessary.\n\n"
        f"My email: alex@university.edu\n"
        f"IMAP at {email_info['imap_host']}:{email_info['imap_port']}, "
        f"SMTP at {email_info['smtp_host']}:{email_info['smtp_port']}, no password"
    )

    # =====================================================================
    # Send emails one by one, trigger webhook, check result.
    # =====================================================================

    emails = json.loads(EMAILS_PATH.read_text())
    checks = []

    for email in emails:
        env.email.send(
            from_addr=email["from"],
            to=email["to"],
            subject=email["subject"],
            body=email["body"],
            date=datetime.fromisoformat(email["date"]),
        )

        agent.act(_webhook(email))

        if email["expect_reply"]:
            checks.append(run_checkers({
                f"replied_to_{email['from']}": lambda addr=email["from"]: env.email.count_inbox(addr) > 0,
            }))
        else:
            checks.append(run_checkers({
                f"did_not_reply_to_{email['from']}": lambda addr=email["from"]: env.email.count_inbox(addr) == 0,
            }))

    return aggregate_results(*checks)
