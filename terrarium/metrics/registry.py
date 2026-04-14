"""Metric registry."""
from __future__ import annotations

import re

from terrarium.metrics.base import BaseMetric
from terrarium.metrics.builtins import Mean, Max, Min, Sum, PassAtK

_REGISTRY: dict[str, type[BaseMetric]] = {
    "mean": Mean, "max": Max, "min": Min, "sum": Sum, "pass@k": PassAtK,
}

_PASS_AT_K = re.compile(r"^pass@(\d+)$")


def create_metric(name: str) -> BaseMetric:
    m = _PASS_AT_K.match(name)
    if m is not None:
        k = int(m.group(1))
        if k < 1:
            raise ValueError("pass@k requires k >= 1")
        return PassAtK(k=k)

    cls = _REGISTRY.get(name)
    if cls is not None:
        return cls()

    raise ValueError(f"Unknown metric: '{name}'. Available: {list(_REGISTRY.keys())}")
