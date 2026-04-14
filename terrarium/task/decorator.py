"""@entry decorator for task definition."""
from __future__ import annotations
import functools
from typing import Callable


def entry(capabilities: list[str]) -> Callable:
    """Mark a function as the task entry point and declare required capabilities."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._terrarium_entry = True
        wrapper._terrarium_capabilities = capabilities
        return wrapper
    return decorator
