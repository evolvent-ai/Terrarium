import pytest

from terrarium.environment.sandbox import (
    BuildSpec,
    ExecResult,
    ImageSpec,
    Sandbox,
    SandboxProvider,
    SandboxSpec,
)


def test_exec_result_fields():
    r = ExecResult(exit_code=0, stdout="hello", stderr="")
    assert r.exit_code == 0
    assert r.stdout == "hello"
    assert r.stderr == ""


def test_image_spec_name_only():
    img = ImageSpec(name="postgres:16")
    assert img.name == "postgres:16"
    assert img.build is None


def test_image_spec_build_only():
    img = ImageSpec(build=BuildSpec(context="/ctx"))
    assert img.name is None
    assert img.build.context == "/ctx"


def test_image_spec_name_and_build():
    img = ImageSpec(name="custom:v1", build=BuildSpec(context="/ctx"))
    assert img.name == "custom:v1"
    assert img.build.context == "/ctx"


def test_image_spec_rejects_neither():
    with pytest.raises(ValueError, match="needs 'name' or 'build'"):
        ImageSpec()


def test_sandbox_spec_defaults():
    spec = SandboxSpec(image=ImageSpec(name="postgres:16"))
    assert spec.image.name == "postgres:16"
    assert spec.image.build is None
    assert spec.ports == []
    assert spec.env == {}
    assert spec.volumes == {}
    assert spec.command is None


def test_sandbox_spec_full():
    spec = SandboxSpec(
        image=ImageSpec(name="postgres:16"),
        ports=[5432],
        env={"POSTGRES_DB": "main"},
        volumes={"/tmp/data": "/data"},
        command=["postgres", "-c", "max_connections=100"],
    )
    assert spec.ports == [5432]
    assert spec.env["POSTGRES_DB"] == "main"
    assert spec.volumes["/tmp/data"] == "/data"
    assert spec.command == ["postgres", "-c", "max_connections=100"]


def test_sandbox_spec_accepts_dict():
    spec = SandboxSpec(image={"name": "alpine:3.19"})
    assert isinstance(spec.image, ImageSpec)
    assert spec.image.name == "alpine:3.19"


def test_sandbox_spec_requires_image():
    with pytest.raises(ValueError):
        SandboxSpec()


def test_build_spec_defaults():
    b = BuildSpec(context="/ctx")
    assert b.context == "/ctx"
    assert b.dockerfile == "Dockerfile"


def test_build_spec_custom_dockerfile():
    b = BuildSpec(context="/ctx", dockerfile="custom.Dockerfile")
    assert b.dockerfile == "custom.Dockerfile"


def test_sandbox_is_abstract():
    with pytest.raises(TypeError, match="abstract"):
        Sandbox()


def test_sandbox_provider_is_abstract():
    with pytest.raises(TypeError, match="abstract"):
        SandboxProvider()
