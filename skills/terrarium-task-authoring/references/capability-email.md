# Email Capability API

Backed by GreenMail (zero-config test mail server). Supports SMTP, IMAP, and POP3. Mailboxes are auto-created per recipient address — no user setup needed. Any username/password is accepted for IMAP login.

## connection_info

```python
info = env.email.connection_info
# {
#     "smtp_host": "<sandbox_hostname>",
#     "smtp_port": 3025,
#     "imap_host": "<sandbox_hostname>",
#     "imap_port": 3143,
#     "pop3_host": "<sandbox_hostname>",
#     "pop3_port": 3110,
# }
```

## Methods

### send()

```python
env.email.send(
    from_addr: str,
    to: str | list[str],
    subject: str,
    body: str,
    html: str | None = None,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
    date: datetime | None = None,
) -> None
```

Send an email via SMTP.

**Parameters:**
- `from_addr` — sender email address
- `to` — recipient address or list of addresses. GreenMail auto-creates a mailbox for each recipient.
- `subject` — subject line
- `body` — plain text body
- `html` — optional HTML body. If provided, the email is sent as multipart (text + HTML).
- `cc` — optional CC recipient(s)
- `bcc` — optional BCC recipient(s)
- `attachments` — optional list of `(filename, bytes)` tuples. Each becomes a MIME attachment.
- `date` — optional custom Date header as a `datetime` object. Useful for simulating emails sent at specific times. Defaults to current time if omitted.

```python
from datetime import datetime

# Simple email
env.email.send(
    from_addr="prof@university.edu",
    to="alex@university.edu",
    subject="Exam Reminder",
    body="The RL exam is on June 20.",
    date=datetime(2025, 6, 13, 9, 0),
)

# Email with attachment
env.email.send(
    from_addr="hr@company.com",
    to="agent@company.com",
    subject="Data File",
    body="Please process the attached CSV.",
    attachments=[("data.csv", Path("resources/data.csv").read_bytes())],
)
```

### count_inbox()

```python
env.email.count_inbox(address: str) -> int
```

Return the number of messages in an inbox.

**Parameters:**
- `address` — the email address whose inbox to check. GreenMail isolates mailboxes by recipient address, so each address has its own independent inbox.

**Returns:** integer count of messages.

```python
assert env.email.count_inbox("alex@university.edu") == 1
assert env.email.count_inbox("prof@university.edu") == 0
```

### list_inbox()

```python
env.email.list_inbox(address: str) -> list[dict]
```

Read all messages in an inbox.

**Parameters:**
- `address` — the email address whose inbox to read

**Returns:** list of message dicts, each with:

```python
{
    "from": "prof@university.edu",
    "to": "alex@university.edu",
    "cc": "",                      # empty string if no CC
    "subject": "Exam Reminder",
    "date": "Fri, 13 Jun 2025 09:00:00 +0000",   # RFC 2822 format string
    "body": "The RL exam is on June 20.",
    "html": "...",             # only present if the email has an HTML body
    "attachments": [           # only present if the email has attachments
        {"filename": "data.csv", "size": 1234},
    ],
}
```

### get_message()

```python
env.email.get_message(address: str, index: int) -> dict
```

Get a single message by index.

**Parameters:**
- `address` — the email address whose inbox to read
- `index` — 0-based message index. Raises `CapabilityError` if out of range.

**Returns:** message dict with the same structure as `list_inbox()`.

```python
msg = env.email.get_message("alex@university.edu", 0)
print(msg["subject"])  # "Exam Reminder"
```

### delete_message()

```python
env.email.delete_message(address: str, index: int) -> None
```

Delete a message from an inbox.

**Parameters:**
- `address` — the email address whose inbox to modify
- `index` — 0-based message index. Raises `CapabilityError` if out of range.
