"""Tests for the data-produce sandbox provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from terrarium.environment.providers.data_produce import (
    DataProduceSandbox,
    DataProduceSandboxProvider,
)
from terrarium.environment.sandbox import ImageSpec, SandboxSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sandbox(**overrides) -> DataProduceSandbox:
    defaults = dict(
        api_url="https://api.example.com",
        session_id="sess-123",
        server_key="banking",
        token="tok",
        pod_host="banking-pod.default.svc.cluster.local",
        mcp_port=8080,
    )
    defaults.update(overrides)
    return DataProduceSandbox(**defaults)


def _make_spec(name: str = "banking") -> SandboxSpec:
    return SandboxSpec(image=ImageSpec(name="dummy"), name=name)


_SESSION_RESPONSE = {
    "session_id": "sess-123",
    "status": "ready",
    "endpoints": {
        "banking": {
            "host": "banking-pod.default.svc.cluster.local",
            "port": 8080,
        },
    },
}


# ---------------------------------------------------------------------------
# TestDataProduceSandbox
# ---------------------------------------------------------------------------

class TestDataProduceSandbox:
    def test_hostname(self):
        sb = _make_sandbox()
        assert sb.hostname() == "banking-pod.default.svc.cluster.local"

    def test_get_host_returns_api_host(self):
        sb = _make_sandbox(api_url="https://api.example.com")
        host, port = sb.get_host(8080)
        assert host == "api.example.com"
        assert port == 443

    def test_get_host_http(self):
        sb = _make_sandbox(api_url="http://api.example.com")
        host, port = sb.get_host(8080)
        assert host == "api.example.com"
        assert port == 80

    def test_exec_raises(self):
        sb = _make_sandbox()
        with pytest.raises(NotImplementedError):
            sb.exec("ls")

    def test_read_file_raises(self):
        sb = _make_sandbox()
        with pytest.raises(NotImplementedError):
            sb.read_file("/tmp/foo")

    def test_stop_is_noop(self):
        sb = _make_sandbox()
        sb.stop()  # should not raise


# ---------------------------------------------------------------------------
# TestDataProduceSandboxProvider
# ---------------------------------------------------------------------------

@patch("terrarium.environment.providers.data_produce.requests")
class TestDataProduceSandboxProvider:
    def test_init_requires_session_or_servers(self, mock_requests):
        provider = DataProduceSandboxProvider(
            api_url="https://api.example.com",
            token="tok",
        )
        with pytest.raises(ValueError, match="requires either"):
            provider.setup()

    def test_setup_with_existing_session(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _SESSION_RESPONSE
        mock_requests.get.return_value = mock_resp

        provider = DataProduceSandboxProvider(
            api_url="https://api.example.com",
            token="tok",
            session_id="sess-123",
        )
        provider.setup()

        mock_requests.get.assert_called_once()
        assert provider._session_data == _SESSION_RESPONSE

    def test_create_sandbox(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _SESSION_RESPONSE
        mock_requests.get.return_value = mock_resp

        provider = DataProduceSandboxProvider(
            api_url="https://api.example.com",
            token="tok",
            session_id="sess-123",
        )
        provider.setup()

        sandbox = provider.create(_make_spec("banking"))
        assert isinstance(sandbox, DataProduceSandbox)
        assert sandbox.hostname() == "banking-pod.default.svc.cluster.local"

    def test_create_unknown_server_raises(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _SESSION_RESPONSE
        mock_requests.get.return_value = mock_resp

        provider = DataProduceSandboxProvider(
            api_url="https://api.example.com",
            token="tok",
            session_id="sess-123",
        )
        provider.setup()

        with pytest.raises(ValueError, match="not found in session endpoints"):
            provider.create(_make_spec("nonexistent"))

    def test_teardown_calls_delete(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _SESSION_RESPONSE
        mock_requests.get.return_value = mock_resp

        provider = DataProduceSandboxProvider(
            api_url="https://api.example.com",
            token="tok",
            session_id="sess-123",
        )
        provider.setup()
        provider.teardown()

        mock_requests.delete.assert_called_once_with(
            "https://api.example.com/sessions/sess-123",
            headers={"Authorization": "Bearer tok"},
        )
