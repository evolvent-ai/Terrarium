import io
import tarfile

import pytest
from unittest.mock import MagicMock, patch

import docker.errors

from terrarium.environment.exceptions import ProviderError
from terrarium.environment.providers.docker import DockerSandbox, DockerSandboxProvider
from terrarium.environment.sandbox import BuildSpec, ImageSpec, ResourceLimits, SandboxSpec


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
            "echo hello", demux=True, environment=None, user="",
        )

    def test_exec_list(self):
        sandbox = self._make_sandbox()
        sandbox._container.exec_run.return_value = (0, (b"out", b"err"))
        result = sandbox.exec(["echo", "hello"])
        sandbox._container.exec_run.assert_called_once_with(
            ["echo", "hello"], demux=True, environment=None, user="",
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

    def test_exec_forwards_env(self):
        sandbox = self._make_sandbox()
        sandbox.exec("echo hello", env={"FOO": "1", "BAR": "x"})
        sandbox._container.exec_run.assert_called_once_with(
            "echo hello", demux=True, environment={"FOO": "1", "BAR": "x"}, user="",
        )

    def test_exec_forwards_user(self):
        sandbox = self._make_sandbox()
        sandbox.exec("echo hello", user="root")
        sandbox._container.exec_run.assert_called_once_with(
            "echo hello", demux=True, environment=None, user="root",
        )

    def test_exec_forwards_user_int(self):
        sandbox = self._make_sandbox()
        sandbox.exec("echo hello", user=1000)
        sandbox._container.exec_run.assert_called_once_with(
            "echo hello", demux=True, environment=None, user="1000",
        )

    def test_upload_strips_host_ownership(self, tmp_path):
        (tmp_path / "script.sh").write_text("echo hi\n")
        sandbox = self._make_sandbox()
        sandbox.upload(str(tmp_path / "script.sh"), "/app/script.sh")

        dest_dir, tar_stream = sandbox._container.put_archive.call_args.args
        assert dest_dir == "/app"
        with tarfile.open(fileobj=io.BytesIO(tar_stream.getvalue()), mode="r") as tar:
            for member in tar.getmembers():
                assert member.uid == 0
                assert member.gid == 0
                assert member.uname == ""
                assert member.gname == ""
                assert member.mtime == 0


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
        spec = SandboxSpec(image=ImageSpec(name="test:latest"))
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
        provider.create(SandboxSpec(image=ImageSpec(build=BuildSpec(context=str(tmp_path)))))

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
        provider.create(SandboxSpec(image=ImageSpec(build=BuildSpec(context=str(tmp_path)))))

        client.images.build.assert_not_called()

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_with_build_honors_caller_tag(self, mock_from_env, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        client = self._make_client()
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(image=ImageSpec(name="custom:v1", build=BuildSpec(context=str(tmp_path)))))

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
            provider.create(SandboxSpec(image=ImageSpec(build=BuildSpec(context=str(tmp_path)))))

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_omits_resource_kwargs_by_default(self, mock_from_env):
        client = self._make_client(image_cached=True)
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(image=ImageSpec(name="alpine:3.19")))

        run_kwargs = client.containers.run.call_args.kwargs
        assert "nano_cpus" not in run_kwargs
        assert "mem_limit" not in run_kwargs
        assert "storage_opt" not in run_kwargs
        assert "working_dir" not in run_kwargs

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_forwards_cpus_as_nano_cpus(self, mock_from_env):
        client = self._make_client(image_cached=True)
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(
            image=ImageSpec(name="alpine:3.19"),
            resources=ResourceLimits(cpus=1.5),
        ))

        assert client.containers.run.call_args.kwargs["nano_cpus"] == 1_500_000_000

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_forwards_memory(self, mock_from_env):
        client = self._make_client(image_cached=True)
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(
            image=ImageSpec(name="alpine:3.19"),
            resources=ResourceLimits(memory="2G"),
        ))

        assert client.containers.run.call_args.kwargs["mem_limit"] == "2G"

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_forwards_storage_as_storage_opt(self, mock_from_env):
        client = self._make_client(image_cached=True)
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(
            image=ImageSpec(name="alpine:3.19"),
            resources=ResourceLimits(storage="10G"),
        ))

        assert client.containers.run.call_args.kwargs["storage_opt"] == {"size": "10G"}

    @patch("terrarium.environment.providers.docker.docker.from_env")
    def test_create_forwards_workdir_as_working_dir(self, mock_from_env):
        client = self._make_client(image_cached=True)
        mock_from_env.return_value = client

        provider = DockerSandboxProvider()
        provider.setup()
        provider.create(SandboxSpec(image=ImageSpec(name="alpine:3.19"), workdir="/app"))

        assert client.containers.run.call_args.kwargs["working_dir"] == "/app"


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
