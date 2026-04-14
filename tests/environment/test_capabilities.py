from terrarium.environment.capabilities import get_capability_class, list_capabilities
from terrarium.environment.exceptions import CapabilityNotFoundError
import pytest


def test_list_capabilities():
    caps = list_capabilities()
    assert "postgres" in caps
    assert "email" in caps


def test_get_capability_class_valid():
    cls = get_capability_class("postgres")
    assert cls.__name__ == "PostgresCapability"


def test_get_capability_class_invalid():
    with pytest.raises(CapabilityNotFoundError, match="redis"):
        get_capability_class("redis")
