import pytest

from terrarium.environment.sandbox import (
    BuildSpec,
    ExecResult,
    Sandbox,
    SandboxProvider,
    SandboxSpec,
)


def test_exec_result_fields():
    r = ExecResult(exit_code=0, stdout="hello", stderr="")
    assert r.exit_code == 0
    assert r.stdout == "hello"
    assert r.stderr == ""


def test_sandbox_spec_defaults():
    spec = SandboxSpec(image="postgres:16")
    assert spec.image == "postgres:16"
    assert spec.build is None
    assert spec.ports == []
    assert spec.env == {}
    assert spec.volumes == {}
    assert spec.command is None


def test_sandbox_spec_full():
    spec = SandboxSpec(
        image="postgres:16",
        ports=[5432],
        env={"POSTGRES_DB": "main"},
        volumes={"/tmp/data": "/data"},
        command=["postgres", "-c", "max_connections=100"],
    )
    assert spec.ports == [5432]
    assert spec.env["POSTGRES_DB"] == "main"
    assert spec.volumes["/tmp/data"] == "/data"
    assert spec.command == ["postgres", "-c", "max_connections=100"]


def test_sandbox_spec_with_build():
    spec = SandboxSpec(build=BuildSpec(context="/path/to/ctx"))
    assert spec.image is None
    assert spec.build.context == "/path/to/ctx"
    assert spec.build.dockerfile == "Dockerfile"
    assert spec.build.tag is None


def test_sandbox_spec_rejects_both_image_and_build():
    with pytest.raises(ValueError, match="exactly one"):
        SandboxSpec(image="x:1", build=BuildSpec(context="/ctx"))


def test_sandbox_spec_rejects_neither():
    with pytest.raises(ValueError, match="exactly one"):
        SandboxSpec()


def test_build_spec_defaults():
    b = BuildSpec(context="/ctx")
    assert b.context == "/ctx"
    assert b.dockerfile == "Dockerfile"
    assert b.tag is None


def test_build_spec_custom_dockerfile_and_tag():
    b = BuildSpec(context="/ctx", dockerfile="custom.Dockerfile", tag="my-image:1")
    assert b.dockerfile == "custom.Dockerfile"
    assert b.tag == "my-image:1"


def test_sandbox_is_abstract():
    import pytest
    with pytest.raises(TypeError, match="abstract"):
        Sandbox()


def test_sandbox_provider_is_abstract():
    import pytest
    with pytest.raises(TypeError, match="abstract"):
        SandboxProvider()
