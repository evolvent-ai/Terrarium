"""Multi-instance integration tests — require running Docker daemon."""

import pytest
from tests.conftest import skip_no_docker
from terrarium.environment.environment import ComposableEnvironment


@skip_no_docker
@pytest.mark.timeout(180)
class TestMultiInstanceIntegration:
    def test_two_workspaces_are_isolated(self):
        with ComposableEnvironment(["workspace:dev", "workspace:test"]) as env:
            dev = env.workspace("dev")
            test = env.workspace("test")

            dev.shell.exec("touch /tmp/marker-dev")
            test.shell.exec("touch /tmp/marker-test")

            assert dev.fs.exists("/tmp/marker-dev")
            assert not dev.fs.exists("/tmp/marker-test")
            assert test.fs.exists("/tmp/marker-test")
            assert not test.fs.exists("/tmp/marker-dev")

    def test_two_postgres_instances_have_isolated_data(self):
        with ComposableEnvironment(
            ["postgres:main", "postgres:replica"],
            config={
                "postgres:main": {"db_name": "main"},
                "postgres:replica": {"db_name": "replica"},
            },
        ) as env:
            env.postgres("main").execute("CREATE TABLE items (id SERIAL, name TEXT)")
            env.postgres("main").execute("INSERT INTO items (name) VALUES ('alpha')")

            rows = env.postgres("main").query("SELECT name FROM items")
            assert len(rows) == 1
            assert rows[0]["name"] == "alpha"

            assert not env.postgres("replica").table_exists("items")

    def test_dynamic_acquire_and_release_workspace(self):
        with ComposableEnvironment(["workspace:base"]) as env:
            env.workspace("base").shell.exec("touch /tmp/base-marker")

            extra = env.acquire("workspace:extra")
            extra.shell.exec("touch /tmp/extra-marker")

            assert extra.fs.exists("/tmp/extra-marker")
            assert not env.workspace("base").fs.exists("/tmp/extra-marker")
            assert env.workspace("extra") is extra
            assert len(env.workspace) == 2

            env.release("workspace:extra")

            assert len(env.workspace) == 1
            with pytest.raises(KeyError):
                env.workspace("extra")
            assert env.workspace("base").fs.exists("/tmp/base-marker")
