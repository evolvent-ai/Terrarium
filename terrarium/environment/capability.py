"""Base capability and common services (fs, shell)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from loguru import logger

from terrarium.environment.exceptions import SandboxError
from terrarium.environment.sandbox import ExecResult, Sandbox, SandboxSpec


class FileSystemService:
    """Filesystem operations inside a sandbox, delegating to Sandbox."""

    def __init__(self, sandbox: Sandbox):
        self._sandbox = sandbox

    def read_file(self, path: str) -> bytes:
        logger.debug("fs.read_file path={}", path)
        return self._sandbox.read_file(path)

    def write_file(self, path: str, content: bytes) -> None:
        logger.debug("fs.write_file path={} size={}", path, len(content))
        self._sandbox.write_file(path, content)

    def exists(self, path: str) -> bool:
        logger.debug("fs.exists path={}", path)
        result = self._sandbox.exec(["test", "-e", path])
        return result.exit_code == 0

    def remove(self, path: str) -> None:
        logger.debug("fs.remove path={}", path)
        self._sandbox.exec(["rm", "-rf", path])

    def list_dir(self, path: str) -> list[str]:
        logger.debug("fs.list_dir path={}", path)
        result = self._sandbox.exec(["ls", "-1", path])
        if result.exit_code != 0:
            raise SandboxError(f"Failed to list {path}: {result.stderr}")
        return [name for name in result.stdout.strip().split("\n") if name]

    def make_dir(self, path: str) -> None:
        logger.debug("fs.make_dir path={}", path)
        self._sandbox.exec(["mkdir", "-p", path])

    def upload(self, local_path: str, sandbox_path: str) -> None:
        logger.debug("fs.upload {} -> {}", local_path, sandbox_path)
        self._sandbox.upload(local_path, sandbox_path)

    def download(self, sandbox_path: str, local_path: str) -> None:
        logger.debug("fs.download {} -> {}", sandbox_path, local_path)
        self._sandbox.download(sandbox_path, local_path)


class ShellService:
    """Command execution inside a sandbox, delegating to Sandbox."""

    def __init__(self, sandbox: Sandbox):
        self._sandbox = sandbox

    def exec(self, command: str | list[str], timeout: float | None = None, env: dict[str, str] | None = None) -> ExecResult:
        logger.debug("shell.exec command={} timeout={} env={}", command, timeout, env)
        if isinstance(command, list):
            command = " ".join(command)
        return self._sandbox.exec(["sh", "-c", command], timeout=timeout, env=env)


class BaseCapability(ABC):
    """Base class for all capabilities.

    Capabilities that need a sandbox override sandbox_spec() to return a
    SandboxSpec. The environment creates the sandbox and passes it via the
    constructor. Capabilities that don't need a sandbox (e.g., API wrappers)
    leave sandbox_spec() returning None.
    """

    def __init__(self, config: dict | None = None, sandbox: Sandbox | None = None):
        self._config = config or {}
        self._sandbox = sandbox
        self.fs = FileSystemService(sandbox) if sandbox else None
        self.shell = ShellService(sandbox) if sandbox else None

    @classmethod
    def sandbox_spec(cls, config: dict | None = None) -> SandboxSpec | None:
        """Return sandbox spec, or None if no sandbox is needed."""
        return None

    @abstractmethod
    def wait_ready(self) -> None:
        """Wait until the capability's service is ready."""

    def teardown(self) -> None:
        """Clean up capability-level resources. No-op by default.
        Called by environment before sandbox.stop()."""
