"""Postgres integration tests — require running Docker daemon."""

import pytest
from tests.conftest import skip_no_docker
from terrarium.environment.environment import ComposableEnvironment


@skip_no_docker
@pytest.mark.timeout(120)
class TestPostgresIntegration:
    def test_create_and_query(self):
        with ComposableEnvironment(["postgres"]) as env:
            env.postgres.execute("CREATE TABLE test_tbl (id SERIAL, val TEXT)")
            env.postgres.execute("INSERT INTO test_tbl (val) VALUES ('hello')")
            rows = env.postgres.query("SELECT * FROM test_tbl")
            assert len(rows) == 1
            assert rows[0]["val"] == "hello"

    def test_shell_access(self):
        with ComposableEnvironment(["postgres"]) as env:
            result = env.postgres.shell.exec("pg_isready -U postgres")
            assert result.exit_code == 0

    def test_fs_read_write(self):
        with ComposableEnvironment(["postgres"]) as env:
            env.postgres.fs.write_file("/tmp/test.txt", b"hello from test")
            content = env.postgres.fs.read_file("/tmp/test.txt")
            assert content == b"hello from test"

    def test_fs_exists_and_remove(self):
        with ComposableEnvironment(["postgres"]) as env:
            env.postgres.fs.write_file("/tmp/exists_test.txt", b"data")
            assert env.postgres.fs.exists("/tmp/exists_test.txt")
            env.postgres.fs.remove("/tmp/exists_test.txt")
            assert not env.postgres.fs.exists("/tmp/exists_test.txt")

    def test_fs_make_dir_and_list_dir(self):
        with ComposableEnvironment(["postgres"]) as env:
            env.postgres.fs.make_dir("/tmp/testdir")
            env.postgres.fs.write_file("/tmp/testdir/a.txt", b"a")
            env.postgres.fs.write_file("/tmp/testdir/b.txt", b"b")
            entries = env.postgres.fs.list_dir("/tmp/testdir")
            assert sorted(entries) == ["a.txt", "b.txt"]

    def test_table_exists(self):
        with ComposableEnvironment(["postgres"]) as env:
            assert not env.postgres.table_exists("test_te")
            env.postgres.execute("CREATE TABLE test_te (id INT)")
            assert env.postgres.table_exists("test_te")

    def test_list_tables(self):
        with ComposableEnvironment(["postgres"]) as env:
            env.postgres.execute("CREATE TABLE aaa (id INT)")
            env.postgres.execute("CREATE TABLE bbb (id INT)")
            tables = env.postgres.list_tables()
            assert "aaa" in tables
            assert "bbb" in tables

    def test_create_database(self):
        with ComposableEnvironment(["postgres"]) as env:
            env.postgres.create_database("testdb")
            rows = env.postgres.query(
                "SELECT datname FROM pg_database WHERE datname = %s",
                ["testdb"],
            )
            assert len(rows) == 1

    def test_connection_info(self):
        with ComposableEnvironment(["postgres"]) as env:
            info = env.postgres.connection_info
            assert "host" in info
            assert info["port"] == 5432
            assert info["dbname"] == "main"
