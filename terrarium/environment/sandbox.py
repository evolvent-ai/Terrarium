"""Sandbox abstractions — primitives for isolated environments."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, model_validator


class ExecResult(BaseModel):
    """Result of executing a command in a sandbox."""

    exit_code: int
    stdout: str
    stderr: str


class BuildSpec(BaseModel):
    """Build parameters for a sandbox image."""

    context: str
    dockerfile: str = "Dockerfile"


class ImageSpec(BaseModel):
    """Image source for a sandbox."""

    name: str | None = None
    build: BuildSpec | None = None

    @model_validator(mode="after")
    def _require_name_or_build(self) -> "ImageSpec":
        if self.name is None and self.build is None:
            raise ValueError("ImageSpec needs 'name' or 'build'")
        return self


class ResourceLimits(BaseModel):
    """Sandbox-level resource limits."""

    cpus: float | None = None
    memory: str | None = None
    storage: str | None = None


class SandboxSpec(BaseModel):
    """Configuration needed to run a sandbox."""

    image: ImageSpec
    ports: list[int] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    volumes: dict[str, str] = Field(default_factory=dict)
    command: str | list[str] | None = None
    name: str | None = None
    resources: ResourceLimits = Field(default_factory=ResourceLimits)
    workdir: str | None = None


class Sandbox(ABC):
    """A running sandbox — the universal environment interface."""

    @abstractmethod
    def exec(self, command: str | list[str], timeout: float | None = None) -> ExecResult:
        """Execute a command inside the sandbox."""

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read a file from the sandbox filesystem."""

    @abstractmethod
    def write_file(self, path: str, content: bytes) -> None:
        """Write a file to the sandbox filesystem."""

    @abstractmethod
    def upload(self, local_path: str, sandbox_path: str) -> None:
        """Upload a file or directory from host to sandbox."""

    @abstractmethod
    def download(self, sandbox_path: str, local_path: str) -> None:
        """Download a file or directory from sandbox to host."""

    @abstractmethod
    def get_host(self, port: int) -> tuple[str, int]:
        """Get (host, port) for connecting from the host machine."""

    @abstractmethod
    def hostname(self) -> str:
        """Hostname of this sandbox on the network."""

    @abstractmethod
    def stop(self) -> None:
        """Stop and clean up the sandbox."""


class SandboxProvider(ABC):
    """Creates sandboxes. Each hosting platform implements this."""

    @abstractmethod
    def setup(self) -> None:
        """One-time initialization (e.g., create Docker network)."""

    @abstractmethod
    def create(self, spec: SandboxSpec) -> Sandbox:
        """Create and start a sandbox from a spec."""

    @abstractmethod
    def teardown(self) -> None:
        """Destroy all sandboxes and clean up resources."""
