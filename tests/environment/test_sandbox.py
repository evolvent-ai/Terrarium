from terrarium.environment.sandbox import ExecResult, SandboxSpec, Sandbox, SandboxProvider


def test_exec_result_fields():
    r = ExecResult(exit_code=0, stdout="hello", stderr="")
    assert r.exit_code == 0
    assert r.stdout == "hello"
    assert r.stderr == ""


def test_sandbox_spec_defaults():
    spec = SandboxSpec(image="postgres:16")
    assert spec.image == "postgres:16"
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


def test_sandbox_is_abstract():
    import pytest
    with pytest.raises(TypeError, match="abstract"):
        Sandbox()


def test_sandbox_provider_is_abstract():
    import pytest
    with pytest.raises(TypeError, match="abstract"):
        SandboxProvider()
