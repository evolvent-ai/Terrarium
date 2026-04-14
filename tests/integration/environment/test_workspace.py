"""Workspace integration tests — require running Docker daemon."""

import pytest
from tests.conftest import skip_no_docker
from terrarium.environment.environment import ComposableEnvironment


@skip_no_docker
@pytest.mark.timeout(120)
class TestWorkspaceIntegration:
    def test_shell_exec(self):
        with ComposableEnvironment(["workspace"]) as env:
            result = env.workspace.shell.exec("echo hello")
            assert result.exit_code == 0
            assert "hello" in result.stdout

    def test_fs_read_write(self):
        with ComposableEnvironment(["workspace"]) as env:
            env.workspace.fs.write_file("/tmp/test.txt", b"workspace test")
            content = env.workspace.fs.read_file("/tmp/test.txt")
            assert content == b"workspace test"

    def test_fs_operations(self):
        with ComposableEnvironment(["workspace"]) as env:
            env.workspace.fs.make_dir("/tmp/mydir")
            env.workspace.fs.write_file("/tmp/mydir/a.txt", b"a")
            assert env.workspace.fs.exists("/tmp/mydir/a.txt")
            entries = env.workspace.fs.list_dir("/tmp/mydir")
            assert "a.txt" in entries
            env.workspace.fs.remove("/tmp/mydir")
            assert not env.workspace.fs.exists("/tmp/mydir")

    def test_custom_image(self):
        with ComposableEnvironment(
            ["workspace"],
            config={"workspace": {"image": "python:3.12-slim"}},
        ) as env:
            result = env.workspace.shell.exec("python3 --version")
            assert result.exit_code == 0
            assert "Python 3.12" in result.stdout

    def test_connection_info(self):
        with ComposableEnvironment(["workspace"]) as env:
            info = env.workspace.connection_info
            assert info["hostname"]
            assert info["image"] == "ubuntu:24.04"

    def test_shell_timeout(self):
        from terrarium.environment.exceptions import SandboxError
        with ComposableEnvironment(["workspace"]) as env:
            with pytest.raises(SandboxError, match="timed out"):
                env.workspace.shell.exec("sleep 100", timeout=1)
