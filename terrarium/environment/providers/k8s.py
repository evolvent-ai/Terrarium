"""Kubernetes-based sandbox provider using kubernetes client."""

from __future__ import annotations

import io
import os
import posixpath
import re
import shlex
import socket
import socketserver
import tarfile
import threading
import time
import uuid

from kubernetes import client, config
from kubernetes.stream import stream, portforward
from loguru import logger

from terrarium.environment.exceptions import ProviderError, SandboxError
from terrarium.environment.sandbox import ExecResult, ImageSpec, Sandbox, SandboxProvider, SandboxSpec


class KubernetesSandbox(Sandbox):
    """Sandbox implemented with a Kubernetes Pod."""

    def __init__(self, v1: client.CoreV1Api, pod):
        self._v1 = v1
        self._pod = pod

        self._portforwards: list[_PortForward] = []

    def exec(self, command: str | list[str], timeout: float | None = None, env: dict[str, str] | None = None, user: str | int | None = None) -> ExecResult:
        argv = shlex.split(command) if isinstance(command, str) else command
        if env:
            argv = ["env", *(f"{k}={v}" for k, v in env.items()), *argv]
        if user is not None:
            argv = ["runuser", "-u", str(user), "--", *argv]

        rc, stdout, stderr = self._exec_capture(argv, timeout=timeout)
        return ExecResult(
            exit_code=rc,
            stdout=stdout.decode("utf-8", "replace"),
            stderr=stderr.decode("utf-8", "replace"),
        )

    def read_file(self, path: str) -> bytes:
        rc, stdout, stderr = self._exec_capture(["cat", path])
        if rc != 0:
            raise SandboxError(f"Failed to read {path}: {stderr.decode('utf-8', 'replace')}")
        return stdout

    def write_file(self, path: str, content: bytes) -> None:
        rc, _, stderr = self._exec_capture(
            ["install", "-D", "-m", "644", "/dev/stdin", path],
            stdin=content,
        )
        if rc != 0:
            raise SandboxError(f"Failed to write {path}: {stderr.decode('utf-8', 'replace')}")

    def upload(self, local_path: str, sandbox_path: str) -> None:
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            arcname = posixpath.basename(sandbox_path)
            tar.add(
                local_path,
                arcname=arcname,
                filter=lambda ti: ti.replace(uid=0, gid=0, uname="", gname="", mtime=0),
            )

        dest_dir = posixpath.dirname(sandbox_path) or "/"
        rc, _, stderr = self._exec_capture(
            ["tar", "xf", "-", "-C", dest_dir],
            stdin=tar_stream.getvalue(),
        )
        if rc != 0:
            raise SandboxError(f"Failed to upload to {sandbox_path}: {stderr.decode('utf-8', 'replace')}")

    def download(self, sandbox_path: str, local_path: str) -> None:
        parent = posixpath.dirname(sandbox_path) or "/"
        name = posixpath.basename(sandbox_path)
        rc, stdout, stderr = self._exec_capture(["tar", "cf", "-", "-C", parent, name])
        if rc != 0:
            raise SandboxError(f"Failed to download {sandbox_path}: {stderr.decode('utf-8', 'replace')}")

        with tarfile.open(fileobj=io.BytesIO(stdout), mode="r") as tar:
            members = tar.getmembers()
            if len(members) == 1 and members[0].isfile():
                extracted = tar.extractfile(members[0])
                if extracted is None:
                    raise SandboxError(f"Failed to read {sandbox_path} from archive")
                os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(extracted.read())
            else:
                os.makedirs(local_path, exist_ok=True)
                tar.extractall(local_path, filter="data")

    def _exec_capture(self, argv: list[str], stdin: bytes | None = None, timeout: float | None = None) -> tuple[int, bytes, bytes]:
        """Run argv in the pod, capture stdout/stderr as bytes, optionally piping stdin."""
        resp = stream(
            self._v1.connect_get_namespaced_pod_exec,
            self._pod.metadata.name, self._pod.metadata.namespace,
            command=argv,
            stderr=True, stdin=stdin is not None, stdout=True, tty=False,
            _preload_content=False, binary=True,
        )
        if stdin is not None:
            # Half-closing the stdin channel for EOF requires v5.channel.k8s.io (k8s 1.30+).
            if resp.subprotocol != "v5.channel.k8s.io":
                resp.close()
                raise SandboxError(f"Piping stdin requires k8s 1.30+ (v5.channel.k8s.io); got '{resp.subprotocol}'")
            resp.write_stdin(stdin)
            resp.close_channel(0)

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        deadline = time.monotonic() + timeout if timeout else None
        try:
            while resp.is_open():
                if deadline is not None and time.monotonic() > deadline:
                    raise SandboxError(f"Command timed out after {timeout}s")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout_chunks.append(resp.read_stdout())
                if resp.peek_stderr():
                    stderr_chunks.append(resp.read_stderr())
        finally:
            resp.close()
        return resp.returncode, b"".join(stdout_chunks), b"".join(stderr_chunks)

    def get_host(self, port: int) -> tuple[str, int]:
        for pf in self._portforwards:
            if pf.remote_port == port:
                return "127.0.0.1", pf.local_port
        pf = _PortForward(self._v1, self._pod, port)
        pf.start()
        self._portforwards.append(pf)
        return "127.0.0.1", pf.local_port

    def hostname(self) -> str:
        return f"{self._pod.spec.hostname}.{self._pod.spec.subdomain}.{self._pod.metadata.namespace}.svc"

    def stop(self) -> None:
        for pf in self._portforwards:
            try:
                pf.stop()
            except Exception as e:
                logger.warning("Failed to stop port-forward: {}", e)
        self._portforwards.clear()
        try:
            self._v1.delete_namespaced_pod(name=self._pod.metadata.name, namespace=self._pod.metadata.namespace, grace_period_seconds=0)
        except Exception as e:
            logger.warning("Failed to delete pod {}: {}", self._pod.metadata.name, e)


class _PortForward:
    """Bridges a local TCP listener to a pod port via the k8s portforward websocket."""

    def __init__(self, v1: client.CoreV1Api, pod, remote_port: int):
        self._v1 = v1
        self._pod = pod
        self._remote_port = remote_port

        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def remote_port(self) -> int:
        return self._remote_port

    @property
    def local_port(self) -> int:
        assert self._server is not None
        return self._server.server_address[1]

    def start(self) -> None:
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                pf = portforward(
                    outer._v1.connect_get_namespaced_pod_portforward,
                    outer._pod.metadata.name, outer._pod.metadata.namespace,
                    ports=str(outer.remote_port),
                )
                outer._bridge(self.request, pf.socket(outer.remote_port))

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"pf-{self._pod.metadata.name}-{self.remote_port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @staticmethod
    def _bridge(a: socket.socket, b) -> None:
        """Pump bytes both directions between two sockets until either side closes."""
        def relay(src, dst):
            try:
                while True:
                    data = src.recv(4096)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=relay, args=(a, b), daemon=True)
        t2 = threading.Thread(target=relay, args=(b, a), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()


class KubernetesSandboxProvider(SandboxProvider):
    """Kubernetes backend — one Pod per sandbox, one headless Service per session."""

    def __init__(self, namespace: str, kubeconfig: str | None = None, image_pull_secrets: list[str] | None = None):
        self._v1: client.CoreV1Api | None = None
        self._namespace = namespace
        self._kubeconfig = kubeconfig
        self._image_pull_secrets = image_pull_secrets
        self._sandboxes: list[KubernetesSandbox] = []
        self._session_id = uuid.uuid4().hex[:12]

    def setup(self) -> None:
        try:
            if self._kubeconfig:
                config.load_config(config_file=self._kubeconfig)
            else:
                config.load_config()
        except Exception as e:
            raise ProviderError(f"Failed to load Kubernetes config: {e}") from e
        self._v1 = client.CoreV1Api()

        try:
            self._v1.read_namespace(name=self._namespace)
        except Exception as e:
            raise ProviderError(f"Namespace '{self._namespace}' is not accessible: {e}") from e

        service_name = f"terrarium-{self._session_id}"
        logger.info("Creating headless Service: {}/{}", self._namespace, service_name)
        svc = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                labels={"terrarium-session": self._session_id},
            ),
            spec=client.V1ServiceSpec(
                cluster_ip="None",
                selector={"terrarium-session": self._session_id},
                # Headless services still need a port to publish A records.
                ports=[client.V1ServicePort(port=1, target_port=1)],
                publish_not_ready_addresses=True,
            ),
        )
        try:
            self._v1.create_namespaced_service(namespace=self._namespace, body=svc)
        except Exception as e:
            raise ProviderError(f"Failed to create session Service: {e}") from e

    def create(self, spec: SandboxSpec) -> Sandbox:
        image_name = self._resolve_image(spec.image)
        if spec.name:
            capability_name = re.sub(r"[^a-z0-9-]+", "-", spec.name.lower())
        else:
            capability_name = uuid.uuid4().hex[:6]
        pod_name = f"terrarium-{self._session_id}-{capability_name}"

        ports = [client.V1ContainerPort(container_port=p) for p in spec.ports]
        env = [client.V1EnvVar(name=k, value=v) for k, v in (spec.env or {}).items()]
        if spec.volumes:
            raise ProviderError(
                "K8s provider does not support SandboxSpec.volumes; "
                "use sandbox.upload() after the pod starts instead"
            )
        args: list[str] | None = None
        if isinstance(spec.command, str):
            args = shlex.split(spec.command)
        elif isinstance(spec.command, list):
            args = spec.command

        resources: dict[str, str] = {}
        if spec.resources.cpus is not None:
            resources["cpu"] = str(spec.resources.cpus)
        if spec.resources.memory is not None:
            resources["memory"] = spec.resources.memory
        if spec.resources.storage is not None:
            resources["ephemeral-storage"] = spec.resources.storage

        container = client.V1Container(
            name="main",
            image=image_name,
            args=args,
            env=env,
            ports=ports,
            resources=client.V1ResourceRequirements(limits=resources),
            working_dir=spec.workdir,
        )
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={
                    "terrarium-session": self._session_id,
                    "terrarium-capability": capability_name,
                },
            ),
            spec=client.V1PodSpec(
                hostname=capability_name,
                subdomain=f"terrarium-{self._session_id}",
                containers=[container],
                restart_policy="Never",
                image_pull_secrets=[
                    client.V1LocalObjectReference(name=s) for s in self._image_pull_secrets
                ] if self._image_pull_secrets else None,
            ),
        )

        logger.info("Starting pod: image={} name={}", image_name, pod_name)
        try:
            self._v1.create_namespaced_pod(namespace=self._namespace, body=pod)
        except Exception as e:
            raise ProviderError(f"Failed to start pod {pod_name}: {e}") from e

        try:
            deadline = time.monotonic() + 300.0
            while True:
                created = self._v1.read_namespaced_pod(name=pod_name, namespace=self._namespace)
                phase = created.status.phase
                if phase == "Running":
                    break
                elif phase in ("Failed", "Succeeded", "Unknown"):
                    raise ProviderError(f"Pod {pod_name} reached terminal phase '{phase}'")
                elif time.monotonic() > deadline:
                    raise ProviderError(f"Pod {pod_name} did not reach Running within 300s")
                else:
                    time.sleep(0.5)
        except Exception:
            try:
                self._v1.delete_namespaced_pod(name=pod_name, namespace=self._namespace, grace_period_seconds=0)
            except Exception as e:
                logger.warning("Failed to delete pod {} after startup failure: {}", pod_name, e)
            raise

        sandbox = KubernetesSandbox(self._v1, created)
        self._sandboxes.append(sandbox)
        return sandbox

    def teardown(self) -> None:
        for sandbox in reversed(self._sandboxes):
            try:
                sandbox.stop()
            except Exception as e:
                logger.warning("Error stopping sandbox: {}", e)
        self._sandboxes.clear()

        if self._v1 is not None:
            try:
                self._v1.delete_namespaced_service(name=f"terrarium-{self._session_id}", namespace=self._namespace)
                logger.info("Removed headless Service")
            except Exception as e:
                logger.warning("Error removing Service: {}", e)

    def _resolve_image(self, image: ImageSpec) -> str:
        if image.build is not None:
            raise ProviderError(
                "K8s provider does not support ImageSpec.build; push the image to a registry "
                "reachable from your cluster and pass it via ImageSpec(name=...)"
            )
        return image.name
