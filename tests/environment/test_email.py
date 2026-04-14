from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch
from terrarium.environment.capabilities.email import EmailCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.sandbox import ExecResult


# ---------------------------------------------------------------------------
# Raw email fixtures for IMAP mock responses
# ---------------------------------------------------------------------------

PLAIN_EMAIL = (
    b"From: bob@test.local\r\n"
    b"To: alice@test.local\r\n"
    b"Cc: carol@test.local\r\n"
    b"Subject: Hello\r\n"
    b"Date: Mon, 24 Mar 2026 10:00:00 +0000\r\n"
    b"\r\n"
    b"Plain body"
)

MULTIPART_EMAIL = (
    b"From: bob@test.local\r\n"
    b"To: alice@test.local\r\n"
    b"Subject: Multipart\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="boundary123"\r\n'
    b"\r\n"
    b"--boundary123\r\n"
    b"Content-Type: text/plain\r\n"
    b"\r\n"
    b"Plain part\r\n"
    b"--boundary123\r\n"
    b"Content-Type: text/html\r\n"
    b"\r\n"
    b"<b>HTML part</b>\r\n"
    b"--boundary123\r\n"
    b"Content-Type: application/octet-stream\r\n"
    b'Content-Disposition: attachment; filename="doc.pdf"\r\n'
    b"Content-Transfer-Encoding: base64\r\n"
    b"\r\n"
    b"ZmFrZWRhdGE=\r\n"
    b"--boundary123--\r\n"
)

EMPTY_BODY_EMAIL = (
    b"From: x@t.local\r\n"
    b"To: y@t.local\r\n"
    b"Subject: Empty\r\n"
    b"\r\n"
)


def _imap_fetch_response(*raw_emails):
    """Build mock IMAP fetch return value from raw bytes."""
    return ("OK", [(b"1 (RFC822 {0})", raw) for raw in raw_emails])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestEmailCapabilityUnit:
    def _make_sandbox(self):
        sandbox = MagicMock()
        sandbox.get_host.side_effect = lambda port: {
            3025: ("localhost", 10025),
            3143: ("localhost", 10143),
            3110: ("localhost", 10110),
        }[port]
        sandbox.hostname.return_value = "email-container"
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
        return sandbox

    def _make_smtp_cap(self, mock_smtplib):
        sandbox = self._make_sandbox()
        cap = EmailCapability(sandbox=sandbox)
        cap._smtp_host = "localhost"
        cap._smtp_port = 10025
        mock_smtp = MagicMock()
        mock_smtplib.SMTP.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtplib.SMTP.return_value.__exit__ = MagicMock(return_value=False)
        return cap, mock_smtp

    def _make_imap_cap(self, mock_imaplib):
        sandbox = self._make_sandbox()
        cap = EmailCapability(sandbox=sandbox)
        cap._imap_host = "localhost"
        cap._imap_port = 10143
        mock_imap = MagicMock()
        mock_imaplib.IMAP4.return_value = mock_imap
        return cap, mock_imap

    # -------------------------------------------------------------------
    # sandbox_spec + config
    # -------------------------------------------------------------------

    def test_sandbox_spec_defaults(self):
        spec = EmailCapability.sandbox_spec()
        assert spec.image == "greenmail/standalone:2.1.8"
        assert 3025 in spec.ports
        assert 3143 in spec.ports
        assert 3110 in spec.ports

    def test_sandbox_spec_custom_config(self):
        spec = EmailCapability.sandbox_spec({
            "image": "greenmail/standalone:2.2.0",
            "smtp_port": 4025,
            "imap_port": 4143,
            "pop3_port": 4110,
        })
        assert spec.image == "greenmail/standalone:2.2.0"
        assert 4025 in spec.ports
        assert 4143 in spec.ports
        assert 4110 in spec.ports

    # -------------------------------------------------------------------
    # connection_info
    # -------------------------------------------------------------------

    def test_connection_info(self):
        sandbox = self._make_sandbox()
        cap = EmailCapability(sandbox=sandbox)
        info = cap.connection_info
        assert info["smtp_host"] == "email-container"
        assert info["smtp_port"] == 3025
        assert info["imap_host"] == "email-container"
        assert info["imap_port"] == 3143
        assert info["pop3_host"] == "email-container"
        assert info["pop3_port"] == 3110

    # -------------------------------------------------------------------
    # send: basic
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_plain(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="bob@t.local", to="alice@t.local",
                 subject="Hi", body="Hello")
        smtp.send_message.assert_called_once()
        sent = smtp.send_message.call_args[0][0]
        assert sent["From"] == "bob@t.local"
        assert sent["To"] == "alice@t.local"
        assert sent["Subject"] == "Hi"
        assert sent.get_content_type() == "text/plain"

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_no_cc_bcc_headers_when_omitted(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text")
        sent = smtp.send_message.call_args[0][0]
        assert sent["Cc"] is None
        assert sent["Bcc"] is None

    # -------------------------------------------------------------------
    # send: multiple recipients
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_multiple_to(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to=["b@t.local", "c@t.local"],
                 subject="Hi", body="text")
        sent = smtp.send_message.call_args[0][0]
        assert sent["To"] == "b@t.local, c@t.local"

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_single_to_string(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text")
        sent = smtp.send_message.call_args[0][0]
        assert sent["To"] == "b@t.local"

    # -------------------------------------------------------------------
    # send: CC / BCC
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_cc_string(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text", cc="c@t.local")
        sent = smtp.send_message.call_args[0][0]
        assert sent["Cc"] == "c@t.local"

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_cc_list(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text", cc=["c@t.local", "d@t.local"])
        sent = smtp.send_message.call_args[0][0]
        assert sent["Cc"] == "c@t.local, d@t.local"

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_bcc_list(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text", bcc=["d@t.local", "e@t.local"])
        sent = smtp.send_message.call_args[0][0]
        assert sent["Bcc"] == "d@t.local, e@t.local"

    # -------------------------------------------------------------------
    # send: HTML
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_html(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="plain", html="<b>bold</b>")
        sent = smtp.send_message.call_args[0][0]
        assert sent.is_multipart()
        parts = list(sent.walk())
        types = [p.get_content_type() for p in parts]
        assert "text/plain" in types
        assert "text/html" in types

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_html_body_content(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="plain text", html="<p>html text</p>")
        sent = smtp.send_message.call_args[0][0]
        payloads = []
        for part in sent.walk():
            if part.get_content_type() == "text/plain":
                payloads.append(part.get_payload())
            elif part.get_content_type() == "text/html":
                payloads.append(part.get_payload())
        assert "plain text" in payloads
        assert "<p>html text</p>" in payloads

    # -------------------------------------------------------------------
    # send: attachments
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_single_attachment(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="see attached", attachments=[("report.txt", b"data")])
        sent = smtp.send_message.call_args[0][0]
        filenames = [p.get_filename() for p in sent.walk() if p.get_filename()]
        assert filenames == ["report.txt"]

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_multiple_attachments(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="files", attachments=[
                     ("a.txt", b"aaa"),
                     ("b.pdf", b"bbb"),
                 ])
        sent = smtp.send_message.call_args[0][0]
        filenames = [p.get_filename() for p in sent.walk() if p.get_filename()]
        assert filenames == ["a.txt", "b.pdf"]

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_attachment_without_html(self, mock_smtplib):
        """Attachment alone should create multipart."""
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="text", attachments=[("f.bin", b"\x00\x01")])
        sent = smtp.send_message.call_args[0][0]
        assert sent.is_multipart()
        types = [p.get_content_type() for p in sent.walk()]
        assert "text/html" not in types

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_html_and_attachment(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="text", html="<b>h</b>",
                 attachments=[("f.txt", b"data")])
        sent = smtp.send_message.call_args[0][0]
        types = [p.get_content_type() for p in sent.walk()]
        assert "text/plain" in types
        assert "text/html" in types
        filenames = [p.get_filename() for p in sent.walk() if p.get_filename()]
        assert "f.txt" in filenames

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_empty_attachments_list(self, mock_smtplib):
        """Empty attachments list should send plain text."""
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local", subject="Hi",
                 body="text", attachments=[])
        sent = smtp.send_message.call_args[0][0]
        assert sent.get_content_type() == "text/plain"

    # -------------------------------------------------------------------
    # count_inbox
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_count_inbox(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1 2 3"])
        assert cap.count_inbox("alice@test.local") == 3

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_count_inbox_single(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        assert cap.count_inbox("alice@test.local") == 1

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_count_inbox_empty(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b""])
        assert cap.count_inbox("alice@test.local") == 0

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_count_inbox_logs_out(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        cap.count_inbox("alice@test.local")
        mock_imap.logout.assert_called_once()

    # -------------------------------------------------------------------
    # get_message
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_plain(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = _imap_fetch_response(PLAIN_EMAIL)
        msg = cap.get_message("alice@test.local", 0)
        assert msg["from"] == "bob@test.local"
        assert msg["to"] == "alice@test.local"
        assert msg["cc"] == "carol@test.local"
        assert msg["subject"] == "Hello"
        assert msg["date"] == "Mon, 24 Mar 2026 10:00:00 +0000"
        assert msg["body"] == "Plain body"
        assert "html" not in msg
        assert "attachments" not in msg

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_multipart(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = _imap_fetch_response(MULTIPART_EMAIL)
        msg = cap.get_message("alice@test.local", 0)
        assert msg["body"] == "Plain part"
        assert msg["html"] == "<b>HTML part</b>"
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["filename"] == "doc.pdf"
        assert msg["attachments"][0]["size"] > 0

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_empty_body(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = _imap_fetch_response(EMPTY_BODY_EMAIL)
        msg = cap.get_message("alice@test.local", 0)
        assert msg["body"] == ""

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_second_index(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1 2 3"])
        mock_imap.fetch.return_value = _imap_fetch_response(PLAIN_EMAIL)
        cap.get_message("alice@test.local", 2)
        mock_imap.fetch.assert_called_once_with(b"3", "(RFC822)")

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_out_of_range(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        with pytest.raises(CapabilityError, match="out of range"):
            cap.get_message("alice@test.local", 1)

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_negative_index_out_of_range(self, mock_imaplib):
        """Negative index should be out of range (no Python-style negative indexing)."""
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        with pytest.raises(CapabilityError, match="out of range"):
            cap.get_message("alice@test.local", -1)

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_get_message_empty_inbox(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b""])
        with pytest.raises(CapabilityError, match="out of range"):
            cap.get_message("alice@test.local", 0)

    # -------------------------------------------------------------------
    # delete_message
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_delete_message(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1 2 3"])
        cap.delete_message("alice@test.local", 1)
        mock_imap.store.assert_called_once_with(b"2", "+FLAGS", "\\Deleted")
        mock_imap.expunge.assert_called_once()

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_delete_message_first(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1 2"])
        cap.delete_message("alice@test.local", 0)
        mock_imap.store.assert_called_once_with(b"1", "+FLAGS", "\\Deleted")

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_delete_message_out_of_range(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        with pytest.raises(CapabilityError, match="out of range"):
            cap.delete_message("alice@test.local", 5)

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_delete_message_empty_inbox(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b""])
        with pytest.raises(CapabilityError, match="out of range"):
            cap.delete_message("alice@test.local", 0)

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_delete_message_logs_out(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        cap.delete_message("alice@test.local", 0)
        mock_imap.logout.assert_called_once()

    # -------------------------------------------------------------------
    # list_inbox
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_list_inbox_single(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = _imap_fetch_response(PLAIN_EMAIL)
        inbox = cap.list_inbox("alice@test.local")
        assert len(inbox) == 1
        assert inbox[0]["subject"] == "Hello"
        assert inbox[0]["from"] == "bob@test.local"
        assert inbox[0]["cc"] == "carol@test.local"

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_list_inbox_empty(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b""])
        inbox = cap.list_inbox("alice@test.local")
        assert inbox == []

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_list_inbox_multipart(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = _imap_fetch_response(MULTIPART_EMAIL)
        inbox = cap.list_inbox("alice@test.local")
        assert inbox[0]["body"] == "Plain part"
        assert inbox[0]["html"] == "<b>HTML part</b>"
        assert inbox[0]["attachments"][0]["filename"] == "doc.pdf"

    @patch("terrarium.environment.capabilities.email.imaplib")
    def test_list_inbox_logs_out(self, mock_imaplib):
        cap, mock_imap = self._make_imap_cap(mock_imaplib)
        mock_imap.search.return_value = ("OK", [b""])
        cap.list_inbox("alice@test.local")
        mock_imap.logout.assert_called_once()

    # -------------------------------------------------------------------
    # _parse_message edge cases
    # -------------------------------------------------------------------

    def test_parse_message_no_cc_returns_empty_string(self):
        import email as email_mod
        msg = email_mod.message_from_bytes(
            b"From: a@t.local\r\nTo: b@t.local\r\nSubject: Hi\r\n\r\nBody"
        )
        result = EmailCapability._parse_message(msg)
        assert result["cc"] == ""

    def test_parse_message_plain_only(self):
        import email as email_mod
        msg = email_mod.message_from_bytes(PLAIN_EMAIL)
        result = EmailCapability._parse_message(msg)
        assert result["body"] == "Plain body"
        assert "html" not in result
        assert "attachments" not in result

    def test_parse_message_multipart_full(self):
        import email as email_mod
        msg = email_mod.message_from_bytes(MULTIPART_EMAIL)
        result = EmailCapability._parse_message(msg)
        assert result["body"] == "Plain part"
        assert result["html"] == "<b>HTML part</b>"
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["filename"] == "doc.pdf"

    def test_parse_message_empty_body(self):
        import email as email_mod
        msg = email_mod.message_from_bytes(EMPTY_BODY_EMAIL)
        result = EmailCapability._parse_message(msg)
        assert result["body"] == ""

    # -------------------------------------------------------------------
    # send: custom date
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_with_date(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text",
                 date=datetime(2025, 6, 13, 9, 0))
        sent = smtp.send_message.call_args[0][0]
        assert "13 Jun 2025" in sent["Date"]

    @patch("terrarium.environment.capabilities.email.smtplib")
    def test_send_without_date(self, mock_smtplib):
        cap, smtp = self._make_smtp_cap(mock_smtplib)
        cap.send(from_addr="a@t.local", to="b@t.local",
                 subject="Hi", body="text")
        sent = smtp.send_message.call_args[0][0]
        assert sent["Date"] is None
