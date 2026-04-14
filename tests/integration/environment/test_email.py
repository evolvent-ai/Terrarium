"""Email integration tests — require running Docker daemon."""

import time
from datetime import datetime

import pytest
from tests.conftest import skip_no_docker
from terrarium.environment.environment import ComposableEnvironment


@skip_no_docker
@pytest.mark.timeout(120)
class TestEmailIntegration:
    def test_send_and_list_inbox(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="bob@test.local",
                to="alice@test.local",
                subject="Integration Test",
                body="Hello from test!",
            )
            time.sleep(1)
            inbox = env.email.list_inbox("alice@test.local")
            assert len(inbox) == 1
            assert inbox[0]["subject"] == "Integration Test"
            assert inbox[0]["body"] == "Hello from test!"

    def test_send_and_get_message(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="bob@test.local",
                to="alice@test.local",
                subject="Get Test",
                body="Get this message",
            )
            time.sleep(1)
            msg = env.email.get_message("alice@test.local", 0)
            assert msg["subject"] == "Get Test"
            assert msg["from"] == "bob@test.local"

    def test_count_inbox(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="a@test.local",
                to="counter@test.local",
                subject="One",
                body="1",
            )
            time.sleep(1)
            assert env.email.count_inbox("counter@test.local") == 1
            env.email.send(
                from_addr="a@test.local",
                to="counter@test.local",
                subject="Two",
                body="2",
            )
            time.sleep(1)
            assert env.email.count_inbox("counter@test.local") == 2

    def test_delete_message(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="a@test.local",
                to="del@test.local",
                subject="To Delete",
                body="gone",
            )
            time.sleep(1)
            assert env.email.count_inbox("del@test.local") == 1
            env.email.delete_message("del@test.local", 0)
            assert env.email.count_inbox("del@test.local") == 0

    def test_send_multiple_recipients(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="sender@test.local",
                to=["alice@test.local", "bob@test.local"],
                subject="Multi",
                body="To both",
            )
            time.sleep(1)
            alice = env.email.list_inbox("alice@test.local")
            bob = env.email.list_inbox("bob@test.local")
            assert len(alice) == 1
            assert len(bob) == 1

    def test_send_with_html(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="a@test.local",
                to="b@test.local",
                subject="HTML Test",
                body="plain",
                html="<b>bold</b>",
            )
            time.sleep(1)
            msg = env.email.get_message("b@test.local", 0)
            assert msg["body"] == "plain"
            assert msg.get("html") == "<b>bold</b>"

    def test_send_with_attachment(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="a@test.local",
                to="b@test.local",
                subject="Attachment Test",
                body="see attached",
                attachments=[("hello.txt", b"file content")],
            )
            time.sleep(1)
            msg = env.email.get_message("b@test.local", 0)
            assert "attachments" in msg
            assert msg["attachments"][0]["filename"] == "hello.txt"
            assert msg["attachments"][0]["size"] > 0

    def test_mailbox_isolation(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="a@test.local",
                to="alice@test.local",
                subject="For Alice",
                body="alice only",
            )
            env.email.send(
                from_addr="a@test.local",
                to="bob@test.local",
                subject="For Bob",
                body="bob only",
            )
            time.sleep(1)
            alice = env.email.list_inbox("alice@test.local")
            bob = env.email.list_inbox("bob@test.local")
            assert len(alice) == 1
            assert alice[0]["subject"] == "For Alice"
            assert len(bob) == 1
            assert bob[0]["subject"] == "For Bob"

    def test_connection_info(self):
        with ComposableEnvironment(["email"]) as env:
            info = env.email.connection_info
            assert "smtp_host" in info
            assert "imap_host" in info
            assert info["smtp_port"] == 3025
            assert info["imap_port"] == 3143
            assert info["pop3_port"] == 3110

    def test_send_with_custom_date(self):
        with ComposableEnvironment(["email"]) as env:
            env.email.send(
                from_addr="a@test.local",
                to="b@test.local",
                subject="Date Test",
                body="past email",
                date=datetime(2025, 6, 13, 9, 0),
            )
            time.sleep(1)
            msg = env.email.get_message("b@test.local", 0)
            assert msg["subject"] == "Date Test"
            assert "13 Jun 2025" in msg["date"]
