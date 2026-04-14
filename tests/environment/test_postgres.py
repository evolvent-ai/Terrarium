import pytest
from unittest.mock import MagicMock, patch, call
from terrarium.environment.capabilities.postgres import PostgresCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.sandbox import ExecResult


class TestPostgresCapabilityUnit:
    def _make_sandbox(self):
        sandbox = MagicMock()
        sandbox.get_host.return_value = ("localhost", 15432)
        sandbox.hostname.return_value = "pg-container"
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
        return sandbox

    @patch("terrarium.environment.capabilities.postgres.psycopg2")
    def _make_cap(self, mock_psycopg2):
        """Helper: create a ready capability with mocked psycopg2."""
        sandbox = self._make_sandbox()
        cap = PostgresCapability(sandbox=sandbox)
        cap.wait_ready(timeout=5.0)
        mock_cursor = cap._conn.cursor.return_value.__enter__.return_value
        return cap, mock_cursor

    # -------------------------------------------------------------------
    # sandbox_spec + config
    # -------------------------------------------------------------------

    def test_sandbox_spec_defaults(self):
        spec = PostgresCapability.sandbox_spec()
        assert spec.image == "postgres:16"
        assert 5432 in spec.ports
        assert spec.env["POSTGRES_PASSWORD"] == "terrarium"
        assert spec.env["POSTGRES_DB"] == "main"

    def test_sandbox_spec_custom_config(self):
        spec = PostgresCapability.sandbox_spec({
            "image": "postgres:15",
            "db_name": "mydb",
            "password": "secret",
        })
        assert spec.image == "postgres:15"
        assert spec.env["POSTGRES_PASSWORD"] == "secret"
        assert spec.env["POSTGRES_DB"] == "mydb"

    def test_init_reads_config(self):
        sandbox = self._make_sandbox()
        cap = PostgresCapability(
            config={"db_name": "custom", "user": "admin", "password": "pw"},
            sandbox=sandbox,
        )
        assert cap._db_name == "custom"
        assert cap._db_user == "admin"
        assert cap._db_password == "pw"

    def test_init_defaults(self):
        sandbox = self._make_sandbox()
        cap = PostgresCapability(sandbox=sandbox)
        assert cap._db_name == "main"
        assert cap._db_user == "postgres"
        assert cap._db_password == "terrarium"

    # -------------------------------------------------------------------
    # connection_info
    # -------------------------------------------------------------------

    def test_connection_info(self):
        sandbox = self._make_sandbox()
        cap = PostgresCapability(sandbox=sandbox)
        info = cap.connection_info
        assert info["host"] == "pg-container"
        assert info["port"] == 5432
        assert info["dbname"] == "main"
        assert info["user"] == "postgres"
        assert info["password"] == "terrarium"

    def test_connection_info_custom(self):
        sandbox = self._make_sandbox()
        cap = PostgresCapability(
            config={"db_name": "mydb", "user": "admin", "password": "pw"},
            sandbox=sandbox,
        )
        info = cap.connection_info
        assert info["dbname"] == "mydb"
        assert info["user"] == "admin"
        assert info["password"] == "pw"

    # -------------------------------------------------------------------
    # wait_ready
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.postgres.psycopg2")
    def test_wait_ready_connects(self, mock_psycopg2):
        sandbox = self._make_sandbox()
        cap = PostgresCapability(sandbox=sandbox)
        cap.wait_ready(timeout=5.0)
        mock_psycopg2.connect.assert_called_once()
        assert cap._conn is not None

    @patch("terrarium.environment.capabilities.postgres.psycopg2")
    def test_wait_ready_polls_pg_isready(self, mock_psycopg2):
        sandbox = self._make_sandbox()
        # First two calls fail, third succeeds
        sandbox.exec.side_effect = [
            ExecResult(exit_code=2, stdout="", stderr=""),
            ExecResult(exit_code=2, stdout="", stderr=""),
            ExecResult(exit_code=0, stdout="", stderr=""),
        ]
        cap = PostgresCapability(sandbox=sandbox)
        cap.wait_ready(timeout=10.0)
        assert sandbox.exec.call_count == 3

    @patch("terrarium.environment.capabilities.postgres.psycopg2")
    @patch("terrarium.environment.capabilities.postgres.time")
    def test_wait_ready_timeout(self, mock_time, mock_psycopg2):
        sandbox = self._make_sandbox()
        sandbox.exec.return_value = ExecResult(exit_code=2, stdout="", stderr="")
        # Simulate time passing beyond deadline
        mock_time.monotonic.side_effect = [0, 0, 100]
        mock_time.sleep = MagicMock()
        cap = PostgresCapability(sandbox=sandbox)
        with pytest.raises(CapabilityError, match="not ready"):
            cap.wait_ready(timeout=5.0)

    # -------------------------------------------------------------------
    # query
    # -------------------------------------------------------------------

    def test_query_returns_dicts(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]

        rows = cap.query("SELECT * FROM users")
        assert rows == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    def test_query_empty(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("id",)]
        mock_cursor.fetchall.return_value = []

        rows = cap.query("SELECT * FROM empty")
        assert rows == []

    def test_query_with_params(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("id",)]
        mock_cursor.fetchall.return_value = [(1,)]

        cap.query("SELECT * FROM users WHERE id = %s", [1])
        mock_cursor.execute.assert_called_with("SELECT * FROM users WHERE id = %s", [1])

    def test_query_single_column(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("count",)]
        mock_cursor.fetchall.return_value = [(42,)]

        rows = cap.query("SELECT count(*) FROM users")
        assert rows == [{"count": 42}]

    # -------------------------------------------------------------------
    # execute
    # -------------------------------------------------------------------

    def test_execute(self):
        cap, mock_cursor = self._make_cap()
        cap.execute("CREATE TABLE test (id INT)")
        mock_cursor.execute.assert_called_with("CREATE TABLE test (id INT)", None)

    def test_execute_with_params(self):
        cap, mock_cursor = self._make_cap()
        cap.execute("INSERT INTO users (name) VALUES (%s)", ["Alice"])
        mock_cursor.execute.assert_called_with(
            "INSERT INTO users (name) VALUES (%s)", ["Alice"]
        )

    # -------------------------------------------------------------------
    # table_exists
    # -------------------------------------------------------------------

    def test_table_exists_true(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("?column?",)]
        mock_cursor.fetchall.return_value = [(1,)]

        assert cap.table_exists("users") is True

    def test_table_exists_false(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("?column?",)]
        mock_cursor.fetchall.return_value = []

        assert cap.table_exists("nonexistent") is False

    def test_table_exists_custom_schema(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("?column?",)]
        mock_cursor.fetchall.return_value = [(1,)]

        cap.table_exists("my_table", schema="custom")
        mock_cursor.execute.assert_called_with(
            "SELECT 1 FROM pg_tables WHERE schemaname = %s AND tablename = %s",
            ["custom", "my_table"],
        )

    # -------------------------------------------------------------------
    # list_tables
    # -------------------------------------------------------------------

    def test_list_tables(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("tablename",)]
        mock_cursor.fetchall.return_value = [("users",), ("orders",)]

        tables = cap.list_tables()
        assert tables == ["users", "orders"]

    def test_list_tables_empty(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("tablename",)]
        mock_cursor.fetchall.return_value = []

        assert cap.list_tables() == []

    def test_list_tables_custom_schema(self):
        cap, mock_cursor = self._make_cap()
        mock_cursor.description = [("tablename",)]
        mock_cursor.fetchall.return_value = []

        cap.list_tables(schema="custom")
        mock_cursor.execute.assert_called_with(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
            ["custom"],
        )

    # -------------------------------------------------------------------
    # create_database
    # -------------------------------------------------------------------

    def test_create_database(self):
        cap, mock_cursor = self._make_cap()
        cap.create_database("testdb")
        mock_cursor.execute.assert_called_with('CREATE DATABASE "testdb"', None)

    def test_create_database_invalid_name(self):
        cap, mock_cursor = self._make_cap()
        with pytest.raises(CapabilityError, match="Invalid database name"):
            cap.create_database("bad-name")

    def test_create_database_invalid_name_spaces(self):
        cap, mock_cursor = self._make_cap()
        with pytest.raises(CapabilityError, match="Invalid database name"):
            cap.create_database("has spaces")

    def test_create_database_invalid_name_sql_injection(self):
        cap, mock_cursor = self._make_cap()
        with pytest.raises(CapabilityError, match="Invalid database name"):
            cap.create_database('"; DROP TABLE users; --')

    # -------------------------------------------------------------------
    # teardown
    # -------------------------------------------------------------------

    def test_teardown_closes_connection(self):
        cap, _ = self._make_cap()
        conn_ref = cap._conn
        cap.teardown()
        conn_ref.close.assert_called_once()
        assert cap._conn is None

    def test_teardown_no_connection(self):
        sandbox = self._make_sandbox()
        cap = PostgresCapability(sandbox=sandbox)
        cap.teardown()  # should not raise

    def test_close_idempotent(self):
        cap, _ = self._make_cap()
        cap.close()
        cap.close()  # second call should not raise
