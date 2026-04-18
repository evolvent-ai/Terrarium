import pytest
from unittest.mock import MagicMock, patch

import docker.errors

from terrarium.environment.exceptions import ProviderError
from terrarium.environment.providers.docker import DockerSandbox, DockerSandboxProvider
from terrarium.environment.sandbox import BuildSpec, SandboxSpec


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
    def _make_client(self, image_cached: bool = False):
        client = MagicMock()
        if not image_cached:
            client.images.get.side_effect = docker.errors.ImageNotFound("")
        container = MagicMock()
        container.ports = {}
        client.containers.run.return_value = container
        return client

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

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_with_build_builds_and_runs(self, mock_from_env, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        client = self._make_client()
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(build=BuildSpec(context=str(tmp_path))))

        build_kwargs = client.images.build.call_args.kwargs
        assert build_kwargs["path"] == str(tmp_path)
        assert build_kwargs["dockerfile"] == "Dockerfile"
        assert build_kwargs["tag"].startswith("terrarium-built:")
        assert client.containers.run.call_args.kwargs["image"] == build_kwargs["tag"]

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_with_build_uses_cache_when_tag_exists(self, mock_from_env, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        client = self._make_client(image_cached=True)
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(build=BuildSpec(context=str(tmp_path))))

        client.images.build.assert_not_called()

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_with_build_honors_caller_tag(self, mock_from_env, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        client = self._make_client()
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(image="custom:v1", build=BuildSpec(context=str(tmp_path))))

        assert client.images.build.call_args.kwargs["tag"] == "custom:v1"
        assert client.containers.run.call_args.kwargs["image"] == "custom:v1"

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_with_build_propagates_build_errors(self, mock_from_env, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        client = self._make_client()
        mock_from_env.return_value = client
        client.images.build.side_effect = docker.errors.BuildError("bad syntax", build_log=[])

        provider = DockerSandboxProvider()
        provider.setup()
        with pytest.raises(ProviderError, match="Failed to build"):
            provider.create(SandboxSpec(build=BuildSpec(context=str(tmp_path))))


class TestDeriveTag:
    def test_same_context_yields_same_tag(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        (tmp_path / "script.sh").write_text("echo hello\n")
        tag1 = DockerSandboxProvider._derive_tag(BuildSpec(context=str(tmp_path)))
        tag2 = DockerSandboxProvider._derive_tag(BuildSpec(context=str(tmp_path)))
        assert tag1 == tag2
        assert tag1.startswith("terrarium-built:")

    def test_different_content_yields_different_tag(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        tag1 = DockerSandboxProvider._derive_tag(BuildSpec(context=str(tmp_path)))
        (tmp_path / "Dockerfile").write_text("FROM debian\n")
        tag2 = DockerSandboxProvider._derive_tag(BuildSpec(context=str(tmp_path)))
        assert tag1 != tag2
