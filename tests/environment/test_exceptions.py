from terrarium.environment.exceptions import (
    ComposableEnvironmentError,
    ProviderError,
    SandboxError,
    CapabilityError,
    CapabilityNotFoundError,
)


def test_exception_hierarchy():
    assert issubclass(ProviderError, ComposableEnvironmentError)
    assert issubclass(SandboxError, ComposableEnvironmentError)
    assert issubclass(CapabilityError, ComposableEnvironmentError)
    assert issubclass(CapabilityNotFoundError, ComposableEnvironmentError)


def test_capability_not_found_message():
    err = CapabilityNotFoundError("redis", ["postgres", "email"])
    assert "redis" in str(err)
    assert "postgres" in str(err)
    assert "email" in str(err)
