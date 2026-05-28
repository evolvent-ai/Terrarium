"""Sandbox provider registry — create sandbox providers by name or import path."""
from __future__ import annotations
import importlib

from terrarium.environment.providers.data_produce import DataProduceSandboxProvider
from terrarium.environment.providers.docker import DockerSandboxProvider
from terrarium.environment.providers.k8s import KubernetesSandboxProvider
from terrarium.environment.sandbox import SandboxProvider
from terrarium.models.config import SandboxProviderConfig

_PROVIDERS: dict[str, type[SandboxProvider]] = {
    "docker": DockerSandboxProvider,
    "k8s": KubernetesSandboxProvider,
    "data-produce": DataProduceSandboxProvider,
}


def create_sandbox_provider(config: SandboxProviderConfig) -> SandboxProvider:
    """Create sandbox provider by import_path or name lookup.
    Priority: import_path > built-in registry.
    """
    if config.import_path:
        module_path, class_name = config.import_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        provider_cls = getattr(module, class_name)
    elif config.name in _PROVIDERS:
        provider_cls = _PROVIDERS[config.name]
    else:
        raise ValueError(
            f"Provider '{config.name}' not found. "
            f"Set import_path or use a built-in: {list(_PROVIDERS.keys())}"
        )

    if not issubclass(provider_cls, SandboxProvider):
        raise TypeError(f"{provider_cls!r} is not a SandboxProvider subclass")

    return provider_cls(**config.kwargs)
