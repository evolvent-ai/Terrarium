import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from terrarium.environment.environment import ComposableEnvironment
from terrarium.environment.exceptions import CapabilityNotFoundError
from terrarium.environment.sandbox import ExecResult


def _mock_provider():
    provider = MagicMock()
    sandbox = MagicMock()
    sandbox.get_host.return_value = ("localhost", 15432)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
    provider.create.return_value = sandbox
    return provider


@patch("terrarium.environment.capabilities.postgres.psycopg2")
def test_runtime_start_stop(mock_psycopg2):
    provider = _mock_provider()
    env = ComposableEnvironment(["postgres"], provider=provider)
    env.start()
    provider.setup.assert_called_once()
    provider.create.assert_called_once()
    assert env.postgres is not None
    env.stop()
    provider.teardown.assert_called_once()


@patch("terrarium.environment.capabilities.postgres.psycopg2")
def test_runtime_context_manager(mock_psycopg2):
    provider = _mock_provider()
    with ComposableEnvironment(["postgres"], provider=provider) as env:
        assert env.postgres is not None
    provider.teardown.assert_called_once()


def test_runtime_invalid_capability():
    provider = _mock_provider()
    env = ComposableEnvironment(["redis"], provider=provider)
    with pytest.raises(ValueError, match="redis"):
        env.start()


def test_runtime_getattr_before_start():
    provider = _mock_provider()
    env = ComposableEnvironment(["postgres"], provider=provider)
    with pytest.raises(CapabilityNotFoundError):
        _ = env.postgres


@patch("terrarium.environment.capabilities.postgres.psycopg2")
def test_runtime_cleanup_on_partial_failure(mock_psycopg2):
    provider = MagicMock()
    call_count = 0

    def create_side_effect(spec):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("second capability failed")
        sandbox = MagicMock()
        sandbox.get_host.return_value = ("localhost", 15432)
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
        return sandbox

    provider.create.side_effect = create_side_effect
    env = ComposableEnvironment(["postgres", "postgres:replica"], provider=provider)
    with pytest.raises(RuntimeError, match="second capability failed"):
        env.start()
    provider.teardown.assert_called_once()


@patch("terrarium.environment.capabilities.postgres.psycopg2")
def test_workspace_starts_after_other_capabilities(mock_psycopg2):
    """Workspace is started last so secrets can be injected."""
    provider = _mock_provider()
    start_order = []

    def track_create(spec):
        start_order.append(spec.name)
        sandbox = MagicMock()
        sandbox.get_host.return_value = ("localhost", 15432)
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
        sandbox.hostname.return_value = "mock-host"
        return sandbox

    provider.create.side_effect = track_create
    env = ComposableEnvironment(
        ["workspace", "postgres"],
        provider=provider,
        config={"workspace": {"image": {"name": "ubuntu:24.04"}}},
    )
    env.start()
    assert start_order[-1].startswith("workspace"), f"workspace should start last, got {start_order}"
    env.stop()


@patch("terrarium.environment.capabilities.postgres.psycopg2")
def test_secrets_env_injected_into_workspace(mock_psycopg2):
    """Env secrets from capabilities are passed to workspace sandbox spec."""
    provider = _mock_provider()
    created_specs = []

    def track_create(spec):
        created_specs.append(spec)
        sandbox = MagicMock()
        sandbox.get_host.return_value = ("localhost", 15432)
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
        sandbox.hostname.return_value = "mock-host"
        return sandbox

    provider.create.side_effect = track_create

    with patch(
        "terrarium.environment.capabilities.notion.NotionCapability.connection_info",
        new_callable=PropertyMock,
        return_value={
            "api_url": "https://api.notion.com",
            "session_page_id": "page123",
            "secrets": {"env": {"NOTION_TOKEN": "test_token_123"}},
        },
    ), patch(
        "terrarium.environment.capabilities.notion.NotionCapability.wait_ready",
    ):
        env = ComposableEnvironment(
            ["notion", "workspace"],
            provider=provider,
            config={
                "notion": {"auth_token": "test"},
                "workspace": {"image": {"name": "ubuntu:24.04"}},
            },
        )
        env.start()

    workspace_spec = [s for s in created_specs if s.name and "workspace" in s.name][0]
    assert workspace_spec.env.get("NOTION_TOKEN") == "test_token_123"
    env.stop()


def test_collect_secrets_empty():
    """No secrets when capabilities don't declare any."""
    env = ComposableEnvironment([], provider=MagicMock())
    env._capabilities = {
        "postgres": {"default": MagicMock(connection_info={"host": "localhost"})},
    }
    secrets_env, secrets_file = env._collect_secrets(env._capabilities)
    assert secrets_env == {}
    assert secrets_file == {}


def test_collect_secrets_with_env_and_file():
    cap_with_env = MagicMock(connection_info={
        "secrets": {"env": {"TOKEN": "abc"}},
    })
    cap_with_file = MagicMock(connection_info={
        "secrets": {"file": {"creds": "/path/to/creds.json"}},
    })
    env = ComposableEnvironment([], provider=MagicMock())
    env._capabilities = {
        "notion": {"default": cap_with_env},
        "google_sheets": {"default": cap_with_file},
    }
    secrets_env, secrets_file = env._collect_secrets(env._capabilities)
    assert secrets_env == {"TOKEN": "abc"}
    assert secrets_file == {"creds": "/path/to/creds.json"}
