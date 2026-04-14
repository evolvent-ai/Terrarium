# Proactive Webhook

Alex's personal assistant monitors his inbox via webhooks and handles incoming emails autonomously. The agent receives a JSON webhook payload each time a new email arrives — it must read the email and decide whether to reply.

## Capabilities

email

## Task Flow

The agent is told once that a webhook has been set up to notify it of new emails. Then three emails arrive one by one:

1. **Colleague sends slides** — asks Alex to confirm receipt (reply expected)
2. **arXiv newsletter** — automated digest, no action needed (no reply expected)
3. **Advisor found Alex's key card** — asks Alex to acknowledge (reply expected)

Each time, the agent receives the same webhook format:

```json
{
  "event": "inbound_email",
  "timestamp": "2025-06-10T10:30:00",
  "from": "li.wei@university.edu",
  "to": "alex@university.edu",
  "subject": "Slides from today's talk"
}
```

The webhook contains metadata only — the agent must read the full email to decide what to do.

## Checkers


| Check                        | What it verifies                      |
| ---------------------------- | ------------------------------------- |
| `replied_to_li.wei@...`      | Agent replied to the slides email     |
| `did_not_reply_to_noreply@…` | Agent did not reply to the newsletter |
| `replied_to_zhang@...`       | Agent replied to the key card email   |


