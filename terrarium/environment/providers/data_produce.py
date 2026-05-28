"""Data-produce API sandbox provider — connects to remote MCP server Pods."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import requests
from loguru import logger

from terrarium.environment.sandbox import ExecResult, Sandbox, SandboxProvider, SandboxSpec


class DataProduceSandbox(Sandbox):
    """Proxy sandbox backed by a remote MCP server Pod managed by the data-produce API."""

    def __init__(
        self,
        api_url: str,
        session_id: str,
        server_key: str,
        token: str,
        pod_host: str,
        mcp_port: int,
    ):
        self._api_url = api_url
        self._session_id = session_id
        self._server_key = server_key
        self._token = token
        self._pod_host = pod_host
        self._mcp_port = mcp_port

    def exec(
        self,
        command: str | list[str],
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        raise NotImplementedError(
            "exec() not supported for DataProduceSandbox. "
            "Use MCP tools via connection_info instead."
        )

    def read_file(self, path: str) -> bytes:
        raise NotImplementedError(
            "read_file() not supported for DataProduceSandbox."
        )

    def write_file(self, path: str, content: bytes) -> None:
        raise NotImplementedError(
            "write_file() not supported for DataProduceSandbox."
        )

    def upload(self, local_path: str, sandbox_path: str) -> None:
        raise NotImplementedError(
            "upload() not supported for DataProduceSandbox."
        )

    def download(self, sandbox_path: str, local_path: str) -> None:
        raise NotImplementedError(
            "download() not supported for DataProduceSandbox."
        )

    def get_host(self, port: int) -> tuple[str, int]:
        parsed = urlparse(self._api_url)
        hostname = parsed.hostname or "localhost"
        if parsed.port:
            resolved_port = parsed.port
        elif parsed.scheme == "https":
            resolved_port = 443
        else:
            resolved_port = 80
        return (hostname, resolved_port)

    def hostname(self) -> str:
        return self._pod_host

    def stop(self) -> None:
        # No-op: session-level teardown is handled by the provider.
        pass


class DataProduceSandboxProvider(SandboxProvider):
    """Provider that delegates sandbox lifecycle to the data-produce API."""

    def __init__(
        self,
        api_url: str,
        token: str,
        session_id: str | None = None,
        servers: list[dict] | None = None,
        max_ttl_seconds: int = 7200,
    ):
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._session_id = session_id
        self._servers = servers
        self._max_ttl_seconds = max_ttl_seconds
        self._session_data: dict | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _wait_ready(self, timeout: int = 300) -> None:
        """Poll GET session until status == 'ready'."""
        deadline = time.monotonic() + timeout
        while True:
            resp = requests.get(
                f"{self._api_url}/sessions/{self._session_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "ready":
                self._session_data = data
                return
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Session {self._session_id} did not become ready within {timeout}s"
                )
            time.sleep(2)

    def setup(self) -> None:
        if self._session_id:
            # Attach to an existing session.
            resp = requests.get(
                f"{self._api_url}/sessions/{self._session_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            self._session_data = resp.json()
            logger.info("Attached to existing session {}", self._session_id)
        elif self._servers:
            # Create a new session.
            payload = {
                "servers": self._servers,
                "max_ttl_seconds": self._max_ttl_seconds,
            }
            resp = requests.post(
                f"{self._api_url}/sessions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            self._session_id = data["session_id"]
            logger.info("Created session {}", self._session_id)
            self._wait_ready()
        else:
            raise ValueError(
                "DataProduceSandboxProvider requires either 'session_id' or 'servers'."
            )

    def create(self, spec: SandboxSpec) -> Sandbox:
        if self._session_data is None:
            raise ValueError("Provider not set up; call setup() first.")

        server_key = spec.name
        endpoints = self._session_data.get("endpoints", {})
        if server_key not in endpoints:
            raise ValueError(
                f"Server key '{server_key}' not found in session endpoints. "
                f"Available: {list(endpoints.keys())}"
            )

        endpoint = endpoints[server_key]
        return DataProduceSandbox(
            api_url=self._api_url,
            session_id=self._session_id,
            server_key=server_key,
            token=self._token,
            pod_host=endpoint.get("host", ""),
            mcp_port=endpoint.get("port", 0),
        )

    def teardown(self) -> None:
        if self._session_id:
            try:
                requests.delete(
                    f"{self._api_url}/sessions/{self._session_id}",
                    headers=self._headers(),
                )
                logger.info("Deleted session {}", self._session_id)
            except Exception as e:
                logger.warning("Failed to delete session {}: {}", self._session_id, e)
