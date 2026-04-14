import pytest
from unittest.mock import MagicMock, patch
from terrarium.environment.providers.docker import DockerSandbox, DockerSandboxProvider
from terrarium.environment.sandbox import SandboxSpec


class TestDockerSandbox:
    def _make_sandbox(self):
        container = MagicMock()
        container.exec_run.return_value = (0, (b"hello\nworld", b""))
        container.ports = {"5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "15432"}]}
        return DockerSandbox(container)

    def test_exec_string(self):
        sandbox = self._make_sandbox()
        result = sandbox.exec("echo hello")
        sandbox._container.exec_run.assert_called_once_with(
            "echo hello", demux=True
        )

    def test_exec_list(self):
        sandbox = self._make_sandbox()
        sandbox._container.exec_run.return_value = (0, (b"out", b"err"))
        result = sandbox.exec(["echo", "hello"])
        sandbox._container.exec_run.assert_called_once_with(
            ["echo", "hello"], demux=True
        )

    def test_get_host(self):
        sandbox = self._make_sandbox()
        host, port = sandbox.get_host(5432)
        assert host == "0.0.0.0"
        assert port == 15432

    def test_stop(self):
        sandbox = self._make_sandbox()
        sandbox.stop()
        sandbox._container.stop.assert_called_once()
        sandbox._container.remove.assert_called_once()


class TestDockerSandboxProvider:
    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_setup_creates_network(self, mock_from_env):
        client = MagicMock()
        mock_from_env.return_value = client
        provider = DockerSandboxProvider()
        provider.setup()
        client.networks.create.assert_called_once()

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_teardown_removes_containers_and_network(self, mock_from_env):
        client = MagicMock()
        mock_from_env.return_value = client
        provider = DockerSandboxProvider()
        provider.setup()

        container = MagicMock()
        container.exec_run.return_value = (0, b"")
        container.ports = {}
        client.containers.run.return_value = container
        spec = SandboxSpec(image="test:latest")
        provider.create(spec)

        provider.teardown()
        container.stop.assert_called_once()
        container.remove.assert_called_once()
