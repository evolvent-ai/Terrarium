"""Multi-capability integration tests — require running Docker daemon."""

import time
import pytest
from tests.conftest import skip_no_docker
from terrarium.environment.environment import ComposableEnvironment


@skip_no_docker
@pytest.mark.timeout(180)
class TestMultiCapabilityIntegration:
    def test_postgres_and_email_together(self):
        with ComposableEnvironment(["postgres", "email"]) as env:
            env.postgres.execute("CREATE TABLE users (id SERIAL, name TEXT)")
            env.postgres.execute("INSERT INTO users (name) VALUES ('Alice')")
            rows = env.postgres.query("SELECT * FROM users")
            assert len(rows) == 1

            env.email.send(
                from_addr="system@test.local",
                to="admin@test.local",
                subject="User Report",
                body=f"Found {len(rows)} users",
            )
            time.sleep(1)
            inbox = env.email.list_inbox("admin@test.local")
            assert len(inbox) == 1
            assert "1 users" in inbox[0]["body"]
