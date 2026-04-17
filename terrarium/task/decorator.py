"""@entry decorator for task definition."""
from __future__ import annotations
import copy
import functools
from typing import Callable


def entry(
    capabilities: list[str],
    config: dict[str, dict] | None = None,
) -> Callable:
    """Mark a function as the task entry point.

    Args:
        capabilities: Capability specs the environment should provision
            (e.g. ``["postgres", "email"]`` or ``["postgres:primary"]``).
        config: Optional per-capability configuration forwarded to
            ``ComposableEnvironment``. Keys follow the same ``"type[:instance]"``
            shape as ``capabilities``. Example:
            ``config={"postgres": {"db_name": "shop", "port": 5433}}``.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._terrarium_entry = True
        wrapper._terrarium_capabilities = capabilities
        wrapper._terrarium_config = copy.deepcopy(config) if config else {}
        wrapper._terrarium_parameterize = None

        def parameterize(gen_fn: Callable) -> Callable:
            wrapper._terrarium_parameterize = gen_fn
            return gen_fn

        wrapper.parameterize = parameterize
        return wrapper
    return decorator
