"""Tests for sandbox provider registry."""
import pytest

from terrarium.environment.providers.docker import DockerSandboxProvider
from terrarium.environment.providers.registry import create_sandbox_provider
from terrarium.environment.sandbox import SandboxProvider
from terrarium.models.config import SandboxProviderConfig


def test_default_name_is_docker():
    provider = create_sandbox_provider(SandboxProviderConfig())
    assert isinstance(provider, DockerSandboxProvider)


def test_by_name():
    provider = create_sandbox_provider(SandboxProviderConfig(name="docker"))
    assert isinstance(provider, DockerSandboxProvider)


def test_by_import_path():
    config = SandboxProviderConfig(
        import_path="terrarium.environment.providers.docker:DockerSandboxProvider",
    )
    provider = create_sandbox_provider(config)
    assert isinstance(provider, SandboxProvider)


def test_with_kwargs():
    config = SandboxProviderConfig(kwargs={"external_network": "shared-net"})
    provider = create_sandbox_provider(config)
    assert isinstance(provider, DockerSandboxProvider)
    assert provider._external_network == "shared-net"


def test_invalid_import_path():
    config = SandboxProviderConfig(import_path="nonexistent.module:NoProvider")
    with pytest.raises(ModuleNotFoundError):
        create_sandbox_provider(config)


def test_no_import_path_no_builtin():
    config = SandboxProviderConfig(name="unknown_provider_xyz")
    with pytest.raises(ValueError, match="not found"):
        create_sandbox_provider(config)
