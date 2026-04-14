"""Exception hierarchy for the environment module."""


class ComposableEnvironmentError(Exception):
    """Base exception for all environment errors."""


class ProviderError(ComposableEnvironmentError):
    """Backend/provider failures (Docker not running, image pull failed, port conflict)."""


class SandboxError(ComposableEnvironmentError):
    """Sandbox-level failures (exec failed, file not found in sandbox)."""


class CapabilityError(ComposableEnvironmentError):
    """Capability-level failures (query failed, SMTP error, timeout)."""


class CapabilityNotFoundError(ComposableEnvironmentError):
    """Requested capability name not found in registry."""

    def __init__(self, name: str, available: list[str]):
        self.name = name
        self.available = available
        super().__init__(
            f"Capability '{name}' not found. Available: {', '.join(available)}"
        )
