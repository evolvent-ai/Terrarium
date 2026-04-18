"""Email capability backed by GreenMail."""

from __future__ import annotations

import email
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import imaplib
import mimetypes
import smtplib
import time
from datetime import datetime
from email.utils import format_datetime

from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.logging import log_capability_call
from terrarium.environment.sandbox import SandboxSpec

DEFAULT_IMAGE = "greenmail/standalone:2.1.8"
DEFAULT_SMTP_PORT = 3025
DEFAULT_IMAP_PORT = 3143
DEFAULT_POP3_PORT = 3110


class EmailCapability(BaseCapability):
    """Email capability backed by GreenMail.

    GreenMail is a zero-config test mail server supporting SMTP/IMAP/POP3.
    In auth.disabled mode, any username/password is accepted.
    Mailboxes are auto-created per recipient address on delivery.

    Config options (all optional):
        image:     Docker image (default: "greenmail/standalone:2.1.8")
        smtp_port: Container SMTP port (default: 3025)
        imap_port: Container IMAP port (default: 3143)
        pop3_port: Container POP3 port (default: 3110)
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self._smtp_sandbox_port = self._config.get("smtp_port", DEFAULT_SMTP_PORT)
        self._imap_sandbox_port = self._config.get("imap_port", DEFAULT_IMAP_PORT)
        self._pop3_sandbox_port = self._config.get("pop3_port", DEFAULT_POP3_PORT)
        self._smtp_host = None
        self._smtp_port = None
        self._imap_host = None
        self._imap_port = None

    @classmethod
    def sandbox_spec(cls, config=None) -> SandboxSpec:
        config = config or {}
        smtp = config.get("smtp_port", DEFAULT_SMTP_PORT)
        imap = config.get("imap_port", DEFAULT_IMAP_PORT)
        pop3 = config.get("pop3_port", DEFAULT_POP3_PORT)
        return SandboxSpec(
            image=config.get("image") or {"name": DEFAULT_IMAGE},
            ports=[smtp, imap, pop3],
        )

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Wait for SMTP port to be ready. GreenMail needs no initialization."""
        self._smtp_host, self._smtp_port = self._sandbox.get_host(self._smtp_sandbox_port)
        self._imap_host, self._imap_port = self._sandbox.get_host(self._imap_sandbox_port)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=2) as s:
                    s.noop()
                logger.info(
                    "Email capability ready: SMTP={}:{}, IMAP={}:{}",
                    self._smtp_host, self._smtp_port,
                    self._imap_host, self._imap_port,
                )
                return
            except (ConnectionRefusedError, OSError, smtplib.SMTPException):
                time.sleep(0.5)
        raise CapabilityError(f"Email SMTP not ready after {timeout}s")

    @property
    def connection_info(self) -> dict:
        """Connection details on the sandbox network."""
        host = self._sandbox.hostname()
        return {
            "smtp_host": host,
            "smtp_port": self._smtp_sandbox_port,
            "imap_host": host,
            "imap_port": self._imap_sandbox_port,
            "pop3_host": host,
            "pop3_port": self._pop3_sandbox_port,
        }

    @log_capability_call
    def send(
        self,
        from_addr: str,
        to: str | list[str],
        subject: str,
        body: str,
        html: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        attachments: list[tuple[str, bytes]] | None = None,
        date: datetime | None = None,
    ) -> None:
        """Send an email via SMTP.

        Args:
            from_addr: Sender address.
            to: Recipient(s).
            subject: Subject line.
            body: Plain text body.
            html: Optional HTML body.
            cc: Optional CC recipient(s).
            bcc: Optional BCC recipient(s).
            attachments: Optional list of (filename, bytes) tuples.
            date: Optional send date. Defaults to current time.
        """
        has_attachments = attachments and len(attachments) > 0
        has_html = html is not None

        if has_attachments or has_html:
            msg = email.mime.multipart.MIMEMultipart()
            msg.attach(email.mime.text.MIMEText(body, "plain"))
            if has_html:
                msg.attach(email.mime.text.MIMEText(html, "html"))
            for filename, data in attachments or []:
                mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                maintype, subtype = mime_type.split("/", 1)
                part = email.mime.base.MIMEBase(maintype, subtype)
                part.set_payload(data)
                email.encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(part)
        else:
            msg = email.mime.text.MIMEText(body)

        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to if isinstance(to, str) else ", ".join(to)
        if cc:
            msg["Cc"] = cc if isinstance(cc, str) else ", ".join(cc)
        if bcc:
            msg["Bcc"] = bcc if isinstance(bcc, str) else ", ".join(bcc)
        if date:
            msg["Date"] = format_datetime(date)

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
            smtp.send_message(msg)

    @log_capability_call
    def count_inbox(self, address: str) -> int:
        """Return the number of messages in the inbox."""
        mailbox = imaplib.IMAP4(self._imap_host, self._imap_port)
        try:
            mailbox.login(address, "any")
            mailbox.select("INBOX")
            _, message_numbers = mailbox.search(None, "ALL")
            nums = message_numbers[0].split()
            return len(nums) if nums and nums[0] else 0
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    @log_capability_call
    def get_message(self, address: str, index: int) -> dict:
        """Get a single message by index (0-based)."""
        mailbox = imaplib.IMAP4(self._imap_host, self._imap_port)
        try:
            mailbox.login(address, "any")
            mailbox.select("INBOX")
            _, message_numbers = mailbox.search(None, "ALL")
            nums = message_numbers[0].split()
            if not nums or not nums[0] or index < 0 or index >= len(nums):
                raise CapabilityError(f"Message index {index} out of range")
            _, data = mailbox.fetch(nums[index], "(RFC822)")
            raw = data[0]
            if isinstance(raw, tuple):
                raw = raw[1]
            msg = email.message_from_bytes(raw)
            return self._parse_message(msg)
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    @log_capability_call
    def delete_message(self, address: str, index: int) -> None:
        """Delete a message by index (0-based)."""
        mailbox = imaplib.IMAP4(self._imap_host, self._imap_port)
        try:
            mailbox.login(address, "any")
            mailbox.select("INBOX")
            _, message_numbers = mailbox.search(None, "ALL")
            nums = message_numbers[0].split()
            if not nums or not nums[0] or index >= len(nums):
                raise CapabilityError(f"Message index {index} out of range")
            mailbox.store(nums[index], "+FLAGS", "\\Deleted")
            mailbox.expunge()
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    @log_capability_call
    def list_inbox(self, address: str) -> list[dict]:
        """Read inbox for the given address via IMAP.

        GreenMail isolates mailboxes by recipient address automatically.
        """
        mailbox = imaplib.IMAP4(self._imap_host, self._imap_port)
        try:
            mailbox.login(address, "any")
            mailbox.select("INBOX")
            _, message_numbers = mailbox.search(None, "ALL")
            messages = []
            for num in message_numbers[0].split():
                if not num:
                    continue
                _, data = mailbox.fetch(num, "(RFC822)")
                if not data or not data[0]:
                    continue
                raw = data[0]
                if isinstance(raw, tuple):
                    raw = raw[1]
                msg = email.message_from_bytes(raw)
                messages.append(self._parse_message(msg))
            return messages
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    @staticmethod
    def _parse_message(msg) -> dict:
        """Parse an email.message.Message into a dict."""
        body = ""
        html = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in disposition:
                    filename = part.get_filename() or "unnamed"
                    payload = part.get_payload(decode=True) or b""
                    attachments.append({"filename": filename, "size": len(payload)})
                elif content_type == "text/plain" and not body:
                    payload = part.get_payload(decode=True)
                    body = payload.decode() if payload else ""
                elif content_type == "text/html" and not html:
                    payload = part.get_payload(decode=True)
                    html = payload.decode() if payload else ""
        else:
            payload = msg.get_payload(decode=True)
            body = payload.decode() if payload else ""

        result = {
            "from": msg.get("From", ""),
            "to": msg.get("To", ""),
            "cc": msg.get("Cc", ""),
            "subject": msg.get("Subject", ""),
            "date": msg.get("Date", ""),
            "body": body,
        }
        if html:
            result["html"] = html
        if attachments:
            result["attachments"] = attachments
        return result
