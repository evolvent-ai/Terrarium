"""Branch and Loop

Agent is Alex's personal assistant. Alex is a PhD student studying
reinforcement learning. The agent helps Alex prepare for the upcoming
RL final exam: checking email, organizing study notes, managing calendar.
"""
from datetime import datetime
from pathlib import Path

from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers, aggregate_results

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"

EXAM_EMAIL = """\
Hi Alex,

This is a reminder that the RL final exam is scheduled for:

Date: June 20, 2025 (Friday)
Time: 2:00 PM - 4:00 PM
Location: Room 301, CS Building

Good luck!

Best,
Prof. Zhang
"""

EXAM_RESCHEDULE_EMAIL = """\
Hi Alex,

Important update: the RL final exam has been rescheduled.

New date: June 23, 2025 (Monday)
Time: 10:00 AM - 12:00 PM
Location: Room 301, CS Building (unchanged)

Sorry for the late change.

Best,
Prof. Zhang
"""

TOPICS = ["MDP", "Policy Gradient", "Q-Learning", "Model-Based"]


def _get_notion_text(env, page_id):
    """Extract all text content from a Notion page's blocks."""
    blocks = env.notion.list_blocks(page_id)
    texts = []
    for block in blocks:
        block_type = block.get("type", "")
        type_data = block.get(block_type, {})
        rich_texts = type_data.get("rich_text", [])
        for rt in rich_texts:
            texts.append(rt.get("plain_text", ""))
    return "\n".join(texts)


def _has_exam_event(env):
    calendars = env.calendar.list_calendars()
    for cal in calendars:
        events = env.calendar.list_events(
            cal["id"], datetime(2025, 6, 1), datetime(2025, 7, 1),
        )
        if any("exam" in e.get("summary", "").lower() or "rl" in e.get("summary", "").lower() for e in events):
            return True
    return False


def _calendar_has_new_date(env):
    calendars = env.calendar.list_calendars()
    for cal in calendars:
        events = env.calendar.list_events(
            cal["id"], datetime(2025, 6, 1), datetime(2025, 7, 1),
        )
        for e in events:
            dt = e.get("dtstart")
            if dt and hasattr(dt, "day") and dt.day == 23 and dt.month == 6:
                return True
    return False


@entry(capabilities=["email", "notion", "calendar"])
def branch_and_loop(env, agent):

    # =====================================================================
    # Stage 0 — Setup
    # Upload lecture notes to workspace, create an empty Notion page for
    # the study guide, and send Alex an exam notification email.
    # =====================================================================

    env.workspace.fs.upload(str(RESOURCES_DIR / "notes"), "/root/notes")

    notion_page = env.notion.create_page(title="RL Study Notes")
    notion_page_id = notion_page["id"]

    env.email.send(
        from_addr="zhang@university.edu",
        to="alex@university.edu",
        subject="RL Final Exam Reminder",
        body=EXAM_EMAIL,
        date=datetime(2025, 6, 13, 9, 0),
    )

    # =====================================================================
    # Stage 0 — Agent reads the exam email and creates a calendar event.
    # Checkers: did a calendar event get created?
    # =====================================================================

    email_info = env.email.connection_info
    cal_info = env.calendar.connection_info

    agent.act(
        "[2025-06-13 10:00] "
        "Hey, I'm Alex, a PhD student studying reinforcement learning. "
        "I have an RL exam coming up. Can you check my email "
        "for the exam details and create a calendar event for it?\n\n"
        "Here's how to access my stuff:\n"
        f"- Email: my address is alex@university.edu, "
        f"IMAP at {email_info['imap_host']}:{email_info['imap_port']}, "
        f"SMTP at {email_info['smtp_host']}:{email_info['smtp_port']}, no password\n"
        f"- Calendar: CalDAV at {cal_info['caldav_url']} (user: {cal_info['username']})\n"
        f"- Notion: I created a page 'RL Study Notes' (page ID: {notion_page_id})\n"
        f"- My lecture notes are in /root/notes/"
    )

    check_stage0 = run_checkers({
        "calendar_event_created": lambda: _has_exam_event(env),
    }, tags=["stage0"])

    # =====================================================================
    # Stage 1 — Agent reads all lecture notes and writes a study guide
    # in Notion. Then we loop: if the guide is shorter than 5x the
    # original length, ask the agent to expand it (max 5 attempts).
    # Checkers: notes exist and cover all four topics.
    # =====================================================================

    agent.act(
        "[2025-06-14 09:00] "
        "My lecture notes from this semester are in /root/notes/. Can you read "
        "through them and put together a consolidated study guide in my "
        "Notion page 'RL Study Notes'? Make sure to cover the key concepts "
        "from each lecture."
    )

    original_length = len(_get_notion_text(env, notion_page_id))
    for _ in range(5):
        if len(_get_notion_text(env, notion_page_id)) >= original_length * 5:
            break
        agent.act(
            "[2025-06-15 10:00] "
            "The study guide is too brief. Expand it with more details, "
            "examples, and explanations from the lecture notes."
        )

    notes = _get_notion_text(env, notion_page_id)

    check_stage1 = run_checkers({
        "notes_created": lambda: len(notes) > 100,
        "all_topics_covered": lambda: all(
            t.lower() in notes.lower() for t in TOPICS
        ),
    }, tags=["stage1"])

    # =====================================================================
    # Stage 2 — Branch based on environment state.
    # If the study guide mentions "Bellman equation", Alex is well
    # prepared. A reschedule email arrives (environment self-change)
    # and the agent must update the calendar.
    # Otherwise, Alex asks the agent to email Prof. Zhang requesting
    # a deadline extension.
    # =====================================================================

    if "bellman" in notes.lower():
        # Stage 2a: well prepared — exam gets rescheduled
        env.email.send(
            from_addr="zhang@university.edu",
            to="alex@university.edu",
            subject="RL Final Exam Rescheduled",
            body=EXAM_RESCHEDULE_EMAIL,
            date=datetime(2025, 6, 16, 14, 0),
        )

        agent.act(
            "[2025-06-16 15:00] "
            "Hey I just got a new email. Read it and act accordingly."
        )

        check_stage2 = run_checkers({
            "calendar_updated": lambda: _calendar_has_new_date(env),
        }, tags=["stage2"])
    else:
        # Stage 2b: not prepared — request extension
        agent.act(
            "[2025-06-18 11:00] "
            "I'm not confident about my preparation at all, key concepts are "
            "still missing from my notes. Send an email to Prof. Zhang "
            "requesting a deadline extension for the exam. "
            "Explain that I need more time to prepare."
        )

        check_stage2 = run_checkers({
            "delay_email_sent": lambda: env.email.count_inbox("zhang@university.edu") > 0,
        }, tags=["stage2"])

    return aggregate_results(check_stage0, check_stage1, check_stage2)
