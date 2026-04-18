"""Workspace capability — a bare sandbox with fs and shell access."""

from __future__ import annotations

import time

from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.sandbox import SandboxSpec

DEFAULT_IMAGE = "ubuntu:24.04"


class WorkspaceCapability(BaseCapability):
    """A bare container environment with fs and shell access.

    No service-specific API — just a sandbox to run commands and
    manage files. User picks the image via config.

    Config options:
        image:   ImageSpec dict (default: {"name": "ubuntu:24.04"})
        command: Override container entrypoint (default: sleep infinity)
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self._image = self._config.get("image", {"name": DEFAULT_IMAGE}).get("name")

    @classmethod
    def sandbox_spec(cls, config=None) -> SandboxSpec:
        config = config or {}
        return SandboxSpec(
            image=config.get("image") or {"name": DEFAULT_IMAGE},
            command=config.get("command", ["tail", "-f", "/dev/null"]),
        )

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Wait until the container is responsive."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._sandbox.exec(["echo", "ready"])
            if result.exit_code == 0:
                logger.info("Workspace ready: image={}", self._image or "<built>")
                return
            time.sleep(0.5)
        raise CapabilityError(f"Workspace not ready after {timeout}s")

    @property
    def connection_info(self) -> dict:
        """Workspace container info."""
        return {
            "hostname": self._sandbox.hostname(),
            "image": self._image,
        }
