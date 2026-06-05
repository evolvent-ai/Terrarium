import io
import tarfile

import pytest
from unittest.mock import MagicMock, patch

from terrarium.environment.exceptions import ProviderError, SandboxError
from terrarium.environment.providers.k8s import KubernetesSandbox, KubernetesSandboxProvider
from terrarium.environment.sandbox import (
    BuildSpec, ImageSpec, ResourceLimits, SandboxSpec, VolumeMount,
)


class _FakeWSResp:
    """Mocks kubernetes.stream.stream() WSClient for one exec call."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, subprotocol="v5.channel.k8s.io"):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.subprotocol = subprotocol
        self._open = True
        self.stdin_writes: list[bytes] = []
        self.closed_channels: list[int] = []

    def is_open(self):
        was, self._open = self._open, False
        return was

    def update(self, timeout=None):
        pass

    def peek_stdout(self):
        return self._stdout

    def read_stdout(self):
        out, self._stdout = self._stdout, b""
        return out

    def peek_stderr(self):
        return self._stderr

    def read_stderr(self):
        err, self._stderr = self._stderr, b""
        return err

    def write_stdin(self, data: bytes) -> None:
        self.stdin_writes.append(data)

    def close_channel(self, channel: int) -> None:
        self.closed_channels.append(channel)

    def close(self):
        self._open = False


def _make_pod(name="terrarium-abc-cap", namespace="terrarium", hostname="cap", subdomain="terrarium-abc"):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.spec.hostname = hostname
    pod.spec.subdomain = subdomain
    pod.status.phase = "Running"
    return pod


class TestKubernetesSandbox:
    def _make_sandbox(self):
        v1 = MagicMock()
        return KubernetesSandbox(v1, _make_pod()), v1

    def test_hostname_combines_pod_spec(self):
        sandbox, _ = self._make_sandbox()
        assert sandbox.hostname() == "cap.terrarium-abc.terrarium.svc"

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_str_uses_shlex_split(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp(stdout=b"out")
        sandbox.exec("echo hello world")
        assert mock_exec.call_args.kwargs["command"] == ["echo", "hello", "world"]

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_list_passes_through(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp()
        sandbox.exec(["python", "-c", "print(1)"])
        assert mock_exec.call_args.kwargs["command"] == ["python", "-c", "print(1)"]

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_env_prefixes_env_binary(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp()
        sandbox.exec(["app"], env={"A": "1", "B": "2"})
        cmd = mock_exec.call_args.kwargs["command"]
        assert cmd[0] == "env"
        assert "A=1" in cmd and "B=2" in cmd
        assert cmd[-1] == "app"

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_user_uses_runuser(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp()
        sandbox.exec(["whoami"], user="root")
        assert mock_exec.call_args.kwargs["command"] == ["runuser", "-u", "root", "--", "whoami"]

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_user_int_stringified(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp()
        sandbox.exec(["whoami"], user=1000)
        assert mock_exec.call_args.kwargs["command"][:4] == ["runuser", "-u", "1000", "--"]

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_decodes_stdout_stderr(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp(stdout=b"out\n", stderr=b"err\n", returncode=3)
        result = sandbox.exec(["x"])
        assert result.stdout == "out\n"
        assert result.stderr == "err\n"
        assert result.exit_code == 3

    @patch("terrarium.environment.providers.k8s.stream")
    def test_exec_timeout_raises(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        forever = _FakeWSResp()
        forever.is_open = lambda: True   # never finish
        mock_exec.return_value = forever
        with pytest.raises(SandboxError, match="timed out"):
            sandbox.exec(["sleep", "10"], timeout=0.01)

    @patch("terrarium.environment.providers.k8s.stream")
    def test_read_file(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp(stdout=b"file-content")
        data = sandbox.read_file("/tmp/x")
        assert data == b"file-content"
        assert mock_exec.call_args.kwargs["command"] == ["cat", "/tmp/x"]

    @patch("terrarium.environment.providers.k8s.stream")
    def test_read_file_nonzero_raises(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp(stderr=b"no such file", returncode=1)
        with pytest.raises(SandboxError, match="Failed to read"):
            sandbox.read_file("/missing")

    @patch("terrarium.environment.providers.k8s.stream")
    def test_write_file_sends_stdin_and_closes_channel(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        resp = _FakeWSResp()
        mock_exec.return_value = resp
        sandbox.write_file("/tmp/w", b"payload")

        assert mock_exec.call_args.kwargs["command"] == ["install", "-D", "-m", "644", "/dev/stdin", "/tmp/w"]
        assert mock_exec.call_args.kwargs["stdin"] is True
        assert resp.stdin_writes == [b"payload"]
        assert resp.closed_channels == [0]

    @patch("terrarium.environment.providers.k8s.stream")
    def test_write_file_raises_when_subprotocol_not_v5(self, mock_exec):
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp(subprotocol="v4.channel.k8s.io")
        with pytest.raises(SandboxError, match="v5.channel.k8s.io"):
            sandbox.write_file("/tmp/x", b"data")

    @patch("terrarium.environment.providers.k8s.stream")
    def test_upload_streams_tar(self, mock_exec, tmp_path):
        (tmp_path / "script.sh").write_text("echo hi\n")
        sandbox, _ = self._make_sandbox()
        resp = _FakeWSResp()
        mock_exec.return_value = resp

        sandbox.upload(str(tmp_path / "script.sh"), "/app/script.sh")

        assert mock_exec.call_args.kwargs["command"] == ["tar", "xf", "-", "-C", "/app"]
        tar_bytes = resp.stdin_writes[0]
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            members = tar.getmembers()
            assert len(members) == 1
            assert members[0].name == "script.sh"
            assert members[0].uid == 0
            assert members[0].uname == ""

    @patch("terrarium.environment.providers.k8s.stream")
    def test_download_extracts_file(self, mock_exec, tmp_path):
        # Build a tar archive as if produced by pod-side `tar cf - -C /src file.txt`
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            data = b"downloaded\n"
            info = tarfile.TarInfo(name="file.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        sandbox, _ = self._make_sandbox()
        mock_exec.return_value = _FakeWSResp(stdout=tar_stream.getvalue())

        local_path = tmp_path / "out.txt"
        sandbox.download("/src/file.txt", str(local_path))

        assert local_path.read_bytes() == b"downloaded\n"
        assert mock_exec.call_args.kwargs["command"] == ["tar", "cf", "-", "-C", "/src", "file.txt"]

    def test_stop_deletes_pod(self):
        sandbox, v1 = self._make_sandbox()
        sandbox.stop()
        v1.delete_namespaced_pod.assert_called_once_with(
            name="terrarium-abc-cap", namespace="terrarium", grace_period_seconds=0,
        )

    def test_stop_swallows_errors(self):
        sandbox, v1 = self._make_sandbox()
        v1.delete_namespaced_pod.side_effect = RuntimeError("boom")
        sandbox.stop()  # should not raise


class TestKubernetesSandboxProvider:
    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_setup_loads_kubeconfig(self, mock_client, mock_config):
        provider = KubernetesSandboxProvider(namespace="terrarium", kubeconfig="/tmp/kc")
        provider.setup()
        mock_config.load_config.assert_called_once_with(config_file="/tmp/kc")

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_setup_raises_on_kubeconfig_failure(self, mock_client, mock_config):
        mock_config.load_config.side_effect = RuntimeError("bad config")
        with pytest.raises(ProviderError, match="Kubernetes config"):
            KubernetesSandboxProvider(namespace="terrarium", kubeconfig="/tmp/kc").setup()

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_setup_raises_when_namespace_missing(self, mock_client, mock_config):
        v1 = MagicMock()
        v1.read_namespace.side_effect = RuntimeError("not found")
        mock_client.CoreV1Api.return_value = v1
        with pytest.raises(ProviderError, match="not accessible"):
            KubernetesSandboxProvider(namespace="missing").setup()

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_setup_creates_headless_service(self, mock_client, mock_config):
        v1 = MagicMock()
        mock_client.CoreV1Api.return_value = v1
        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()

        v1.create_namespaced_service.assert_called_once()
        ns = v1.create_namespaced_service.call_args.kwargs["namespace"]
        assert ns == "terrarium"

        svc_spec_kwargs = mock_client.V1ServiceSpec.call_args.kwargs
        assert svc_spec_kwargs["cluster_ip"] == "None"
        assert svc_spec_kwargs["publish_not_ready_addresses"] is True
        assert svc_spec_kwargs["selector"] == {"terrarium-session": provider._session_id}

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_create_raises_when_image_has_build(self, mock_client, mock_config, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        with pytest.raises(ProviderError, match="ImageSpec.build"):
            provider.create(SandboxSpec(image=ImageSpec(build=BuildSpec(context=str(tmp_path)))))

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_create_raises_on_volumes(self, mock_client, mock_config):
        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        with pytest.raises(ProviderError, match="volumes"):
            provider.create(SandboxSpec(
                image=ImageSpec(name="alpine"),
                volumes=[VolumeMount(source="/host", target="/mnt")],
            ))

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_create_sets_hostname_subdomain_and_labels(self, mock_client, mock_config):
        v1 = MagicMock()
        v1.read_namespaced_pod.return_value = _make_pod()
        mock_client.CoreV1Api.return_value = v1

        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        provider.create(SandboxSpec(name="postgres", image=ImageSpec(name="postgres:16")))

        pod_spec_kwargs = mock_client.V1PodSpec.call_args.kwargs
        assert pod_spec_kwargs["hostname"] == "postgres"
        assert pod_spec_kwargs["subdomain"] == f"terrarium-{provider._session_id}"
        assert pod_spec_kwargs["restart_policy"] == "Never"

        pod_meta_kwargs = mock_client.V1ObjectMeta.call_args_list[-1].kwargs
        assert pod_meta_kwargs["labels"] == {
            "terrarium-session": provider._session_id,
            "terrarium-capability": "postgres",
        }

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_create_sanitizes_capability_name_for_k8s(self, mock_client, mock_config):
        v1 = MagicMock()
        v1.read_namespaced_pod.return_value = _make_pod()
        mock_client.CoreV1Api.return_value = v1

        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        provider.create(SandboxSpec(
            name="workspace-dev:extra",
            image=ImageSpec(name="alpine"),
        ))

        pod_spec_kwargs = mock_client.V1PodSpec.call_args.kwargs
        assert pod_spec_kwargs["hostname"] == "workspace-dev-extra"

        pod_meta_kwargs = mock_client.V1ObjectMeta.call_args_list[-1].kwargs
        assert pod_meta_kwargs["name"] == f"terrarium-{provider._session_id}-workspace-dev-extra"
        assert pod_meta_kwargs["labels"]["terrarium-capability"] == "workspace-dev-extra"

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_create_forwards_resources(self, mock_client, mock_config):
        v1 = MagicMock()
        v1.read_namespaced_pod.return_value = _make_pod()
        mock_client.CoreV1Api.return_value = v1

        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        provider.create(SandboxSpec(
            image=ImageSpec(name="alpine"),
            resources=ResourceLimits(cpus=1.5, memory="2G", storage="10G"),
        ))

        limits = mock_client.V1ResourceRequirements.call_args.kwargs["limits"]
        assert limits == {"cpu": "1.5", "memory": "2G", "ephemeral-storage": "10G"}

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_create_raises_when_pod_phase_terminal(self, mock_client, mock_config):
        v1 = MagicMock()
        failed_pod = _make_pod()
        failed_pod.status.phase = "Failed"
        v1.read_namespaced_pod.return_value = failed_pod
        mock_client.CoreV1Api.return_value = v1

        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        with pytest.raises(ProviderError, match="terminal phase"):
            provider.create(SandboxSpec(name="default", image=ImageSpec(name="alpine")))
        v1.delete_namespaced_pod.assert_called_once_with(
            name=f"terrarium-{provider._session_id}-default", namespace="terrarium", grace_period_seconds=0,
        )

    @patch("terrarium.environment.providers.k8s.config")
    @patch("terrarium.environment.providers.k8s.client")
    def test_teardown_deletes_pods_and_service(self, mock_client, mock_config):
        v1 = MagicMock()
        v1.read_namespaced_pod.return_value = _make_pod()
        mock_client.CoreV1Api.return_value = v1

        provider = KubernetesSandboxProvider(namespace="terrarium")
        provider.setup()
        provider.create(SandboxSpec(name="cap", image=ImageSpec(name="alpine")))

        provider.teardown()
        v1.delete_namespaced_pod.assert_called_once()
        v1.delete_namespaced_service.assert_called_once_with(
            name=f"terrarium-{provider._session_id}", namespace="terrarium",
        )
