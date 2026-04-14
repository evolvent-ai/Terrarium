"""PostgreSQL database capability."""

from __future__ import annotations

import time

import psycopg2
import psycopg2.extensions
from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.logging import log_capability_call
from terrarium.environment.sandbox import SandboxSpec

DEFAULT_IMAGE = "postgres:16"
DEFAULT_PORT = 5432
DEFAULT_DB_NAME = "main"
DEFAULT_DB_USER = "postgres"
DEFAULT_DB_PASSWORD = "terrarium"


class PostgresCapability(BaseCapability):
    """PostgreSQL database capability.

    Config options (all optional):
        image:    Docker image (default: "postgres:16")
        port:     Container port (default: 5432)
        db_name:  Database name (default: "main")
        user:     Username (default: "postgres")
        password: Password (default: "terrarium")
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self._port = self._config.get("port", DEFAULT_PORT)
        self._db_name = self._config.get("db_name", DEFAULT_DB_NAME)
        self._db_user = self._config.get("user", DEFAULT_DB_USER)
        self._db_password = self._config.get("password", DEFAULT_DB_PASSWORD)
        self._conn = None

    @classmethod
    def sandbox_spec(cls, config=None) -> SandboxSpec:
        config = config or {}
        return SandboxSpec(
            image=config.get("image", DEFAULT_IMAGE),
            ports=[config.get("port", DEFAULT_PORT)],
            env={
                "POSTGRES_PASSWORD": config.get("password", DEFAULT_DB_PASSWORD),
                "POSTGRES_DB": config.get("db_name", DEFAULT_DB_NAME),
            },
        )

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Poll pg_isready, then establish psycopg2 connection."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._sandbox.exec(["pg_isready", "-U", self._db_user])
            if result.exit_code == 0:
                break
            time.sleep(0.5)
        else:
            raise CapabilityError(f"Postgres not ready after {timeout}s")

        host, port = self._sandbox.get_host(self._port)
        # pg_isready passed inside container, but host port may need a moment
        while time.monotonic() < deadline:
            try:
                self._conn = psycopg2.connect(
                    host=host,
                    port=port,
                    dbname=self._db_name,
                    user=self._db_user,
                    password=self._db_password,
                    connect_timeout=3,
                )
                self._conn.set_isolation_level(
                    psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
                )
                logger.info("Postgres connection established at {}:{}", host, port)
                return
            except psycopg2.OperationalError:
                time.sleep(0.5)
        raise CapabilityError(f"Postgres not ready after {timeout}s")

    @property
    def connection_info(self) -> dict:
        """Connection details on the sandbox network."""
        return {
            "host": self._sandbox.hostname(),
            "port": self._port,
            "dbname": self._db_name,
            "user": self._db_user,
            "password": self._db_password,
        }

    @log_capability_call
    def query(self, sql: str, params=None) -> list[dict]:
        """Execute a SELECT-like query. Returns rows as list of dicts."""
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    @log_capability_call
    def execute(self, sql: str, params=None) -> None:
        """Execute a non-SELECT statement."""
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    @log_capability_call
    def table_exists(self, name: str, schema: str = "public") -> bool:
        """Check if a table exists."""
        rows = self.query(
            "SELECT 1 FROM pg_tables WHERE schemaname = %s AND tablename = %s",
            [schema, name],
        )
        return len(rows) > 0

    @log_capability_call
    def list_tables(self, schema: str = "public") -> list[str]:
        """List all table names in the given schema."""
        rows = self.query(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
            [schema],
        )
        return [row["tablename"] for row in rows]

    @log_capability_call
    def create_database(self, name: str) -> None:
        """Create a new database."""
        # Database names can't be parameterized, validate to prevent injection
        if not name.isidentifier():
            raise CapabilityError(f"Invalid database name: {name}")
        self.execute(f'CREATE DATABASE "{name}"')

    def close(self) -> None:
        """Close the psycopg2 connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def teardown(self) -> None:
        self.close()
