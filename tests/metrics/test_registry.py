"""Tests for metric registry."""
import pytest
from terrarium.metrics.builtins import Mean, Max, PassAtK
from terrarium.metrics.registry import create_metric


def test_mean():
    metric = create_metric("mean")
    assert isinstance(metric, Mean)


def test_max():
    metric = create_metric("max")
    assert isinstance(metric, Max)


def test_pass_at_k():
    metric = create_metric("pass@1")
    assert isinstance(metric, PassAtK)
    assert metric.name == "pass@1"


def test_pass_at_k_large():
    metric = create_metric("pass@10")
    assert isinstance(metric, PassAtK)
    assert metric.name == "pass@10"


def test_pass_at_0_raises():
    with pytest.raises(ValueError, match="k >= 1"):
        create_metric("pass@0")


def test_unknown_raises():
    with pytest.raises(ValueError, match="Unknown metric"):
        create_metric("nonexistent_metric_xyz")
