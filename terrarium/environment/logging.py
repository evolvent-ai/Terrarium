"""Logging utilities."""

from __future__ import annotations

import functools
import time

from loguru import logger


def _sanitize_arg(value, max_len: int = 80) -> str:
    """Truncate long argument values for logging."""
    s = repr(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _format_args(args, kwargs) -> str:
    """Format arguments for log output."""
    parts = [_sanitize_arg(a) for a in args]
    parts.extend(f"{k}={_sanitize_arg(v)}" for k, v in kwargs.items())
    return ", ".join(parts)


def log_capability_call(method):
    """Decorator that logs every capability method call."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        cap_name = self.__class__.__name__
        method_name = method.__name__
        args_str = _format_args(args, kwargs)
        start = time.monotonic()
        try:
            result = method(self, *args, **kwargs)
            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                "[{cap}.{method}] {args} status=ok duration={dur:.0f}ms",
                cap=cap_name,
                method=method_name,
                args=args_str,
                dur=duration_ms,
            )
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "[{cap}.{method}] {args} status=error error={err} duration={dur:.0f}ms",
                cap=cap_name,
                method=method_name,
                args=args_str,
                err=str(e),
                dur=duration_ms,
            )
            raise

    return wrapper
