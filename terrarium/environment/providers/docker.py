"""Docker-based sandbox provider using docker-py."""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import tarfile
import uuid
from pathlib import Path

import docker
import docker.errors
from loguru import logger

from terrarium.environment.exceptions import ProviderError, SandboxError
from terrarium.environment.sandbox import BuildSpec, ExecResult, Sandbox, SandboxSpec, SandboxProvider


class DockerSandbox(Sandbox):
    """Sandbox implemented with a Docker container."""

    def __init__(self, container):
        self._container = container

    def exec(self, command: str | list[str], timeout: float | None = None) -> ExecResult:
        if timeout is None:
            exit_code, (stdout_bytes, stderr_bytes) = self._container.exec_run(command, demux=True)
            return ExecResult(
                exit_code=exit_code,
                stdout=(stdout_bytes or b"").decode(),
                stderr=(stderr_bytes or b"").decode(),
            )

        import concurrent.futures
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._container.exec_run, command, demux=True)
        pool.shutdown(wait=False)
        try:
            exit_code, (stdout_bytes, stderr_bytes) = future.result(timeout=timeout)
            return ExecResult(
                exit_code=exit_code,
                stdout=(stdout_bytes or b"").decode(),
                stderr=(stderr_bytes or b"").decode(),
            )
        except concurrent.futures.TimeoutError:
            raise SandboxError(f"Command timed out after {timeout}s")

    def read_file(self, path: str) -> bytes:
        try:
            stream, _ = self._container.get_archive(path)
        except Exception as e:
            raise SandboxError(f"Failed to read {path}: {e}") from e

        tar_bytes = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            member = tar.getmembers()[0]
            extracted = tar.extractfile(member)
            if extracted is None:
                raise SandboxError(f"Failed to read {path}: not a regular file")
            return extracted.read()

    def write_file(self, path: str, content: bytes) -> None:
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            info = tarfile.TarInfo(name=posixpath.basename(path))
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        tar_stream.seek(0)
        self._container.put_archive(posixpath.dirname(path) or "/", tar_stream)

    def upload(self, local_path: str, sandbox_path: str) -> None:
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            arcname = posixpath.basename(sandbox_path)
            tar.add(local_path, arcname=arcname)
        tar_stream.seek(0)

        dest_dir = posixpath.dirname(sandbox_path) or "/"
        self._container.put_archive(dest_dir, tar_stream)

    def download(self, sandbox_path: str, local_path: str) -> None:
        try:
            stream, _ = self._container.get_archive(sandbox_path)
        except Exception as e:
            raise SandboxError(f"Failed to download {sandbox_path}: {e}") from e

        tar_bytes = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
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

    def get_host(self, port: int) -> tuple[str, int]:
        self._container.reload()
        port_key = f"{port}/tcp"
        ports = self._container.ports
        if port_key not in ports or not ports[port_key]:
            raise SandboxError(f"Port {port} not mapped for container")
        mapping = ports[port_key][0]
        return mapping["HostIp"], int(mapping["HostPort"])

    def hostname(self) -> str:
        return self._container.name

    def stop(self) -> None:
        try:
            self._container.stop(timeout=0)
        except Exception:
            pass
        try:
            self._container.remove(force=True)
        except Exception:
            pass


class DockerSandboxProvider(SandboxProvider):
    """Docker backend — manages containers and networks via docker-py."""

    def __init__(self, external_network: str | None = None):
        self._client = None
        self._network = None
        self._external_network = external_network
        self._sandboxes: list[DockerSandbox] = []
        self._session_id = uuid.uuid4().hex[:12]

    def setup(self) -> None:
        try:
            self._client = docker.from_env()
            self._client.ping()
        except docker.errors.DockerException as e:
            raise ProviderError(f"Cannot connect to Docker daemon: {e}") from e

        if self._external_network:
            logger.info("Joining Docker network: {}", self._external_network)
            self._network = self._client.networks.get(self._external_network)
        else:
            network_name = f"terrarium-{self._session_id}"
            logger.info("Creating Docker network: {}", network_name)
            self._network = self._client.networks.create(network_name, driver="bridge")

    def create(self, spec: SandboxSpec) -> Sandbox:
        image_name = (
            self._ensure_built(spec.build, spec.image) if spec.build else spec.image
        )
        port_bindings = {f"{p}/tcp": None for p in spec.ports}
        environment = spec.env or {}
        volumes = spec.volumes or {}

        kwargs = {
            "image": image_name,
            "detach": True,
            "ports": port_bindings,
            "environment": environment,
            "network": self._network.name if self._network else None,
        }
        if spec.name:
            # External network names don't carry session_id; add it to avoid
            # collisions across environment instances sharing the same network.
            # Own network names already embed session_id, so reuse them as-is.
            if self._external_network:
                prefix = f"{self._network.name}-{self._session_id}"
            else:
                prefix = self._network.name
            kwargs["name"] = f"{prefix}-{spec.name}"
        if volumes:
            kwargs["volumes"] = {
                host: {"bind": container, "mode": "rw"}
                for host, container in volumes.items()
            }
        if spec.command is not None:
            kwargs["command"] = spec.command

        logger.info("Starting container: image={} name={}", image_name, kwargs.get("name"))
        try:
            container = self._client.containers.run(**kwargs)
        except docker.errors.DockerException as e:
            raise ProviderError(f"Failed to start container {image_name}: {e}") from e

        sandbox = DockerSandbox(container)
        self._sandboxes.append(sandbox)
        return sandbox

    def _ensure_built(self, build: BuildSpec, tag: str | None) -> str:
        tag = tag or _auto_tag(build)
        try:
            self._client.images.get(tag)
            logger.debug("Build cache hit: {}", tag)
            return tag
        except docker.errors.ImageNotFound:
            pass

        logger.info("Building image: tag={} context={}", tag, build.context)
        try:
            self._client.images.build(
                path=build.context,
                dockerfile=build.dockerfile,
                tag=tag,
                rm=True,
            )
        except docker.errors.DockerException as e:
            raise ProviderError(f"Failed to build image from {build.context}: {e}") from e
        return tag

    def teardown(self) -> None:
        for sandbox in reversed(self._sandboxes):
            try:
                sandbox.stop()
            except Exception as e:
                logger.warning("Error stopping sandbox: {}", e)
        self._sandboxes.clear()

        if self._network and not self._external_network:
            try:
                self._network.remove()
                logger.info("Removed Docker network")
            except Exception as e:
                logger.warning("Error removing network: {}", e)
            self._network = None


def _auto_tag(build: BuildSpec) -> str:
    """Deterministic tag derived from a hash of the build context."""
    ctx = Path(build.context)
    h = hashlib.sha256()
    h.update(build.dockerfile.encode())
    h.update(b"\0")
    for f in sorted(ctx.rglob("*")):
        if not f.is_file():
            continue
        h.update(f.relative_to(ctx).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
    return f"terrarium-built:{h.hexdigest()[:16]}"
