import pytest
from unittest.mock import MagicMock
from terrarium.environment.sandbox import ExecResult, SandboxSpec, Sandbox
from terrarium.environment.capability import BaseCapability, FileSystemService, ShellService


class FakeSandbox(Sandbox):
    def __init__(self):
        self.exec_result = ExecResult(exit_code=0, stdout="ok", stderr="")

    def exec(self, command, timeout=None):
        return self.exec_result

    def read_file(self, path):
        return b"file content"

    def write_file(self, path, content):
        pass

    def upload(self, local_path, sandbox_path):
        pass

    def download(self, sandbox_path, local_path):
        pass

    def get_host(self, port):
        return ("localhost", 15432)

    def hostname(self):
        return "fake-container"

    def stop(self):
        pass


class FakeSandboxCapability(BaseCapability):
    @classmethod
    def sandbox_spec(cls, config=None) -> SandboxSpec:
        return SandboxSpec(image="test:latest", ports=[8080])

    def wait_ready(self) -> None:
        pass


class FakeAPICapability(BaseCapability):
    def wait_ready(self) -> None:
        pass


def test_capability_with_sandbox_has_fs_and_shell():
    sandbox = FakeSandbox()
    cap = FakeSandboxCapability(sandbox=sandbox)
    assert isinstance(cap.fs, FileSystemService)
    assert isinstance(cap.shell, ShellService)


def test_capability_without_sandbox_has_no_fs_shell():
    cap = FakeAPICapability()
    assert cap.fs is None
    assert cap.shell is None
    assert cap._sandbox is None


def test_base_capability_teardown_default_noop():
    cap = FakeAPICapability()
    cap.teardown()


def test_filesystem_service_read():
    sandbox = FakeSandbox()
    fs = FileSystemService(sandbox)
    result = fs.read_file("/some/path")
    assert result == b"file content"


def test_filesystem_service_write():
    sandbox = MagicMock(spec=Sandbox)
    fs = FileSystemService(sandbox)
    fs.write_file("/some/path", b"data")
    sandbox.write_file.assert_called_once_with("/some/path", b"data")


def test_shell_service_exec_string():
    sandbox = FakeSandbox()
    shell = ShellService(sandbox)
    result = shell.exec("echo hello")
    assert result.exit_code == 0
    assert result.stdout == "ok"


def test_shell_service_exec_list():
    sandbox = FakeSandbox()
    shell = ShellService(sandbox)
    result = shell.exec(["echo", "hello"])
    assert result.exit_code == 0


def test_shell_service_exec_with_timeout():
    sandbox = MagicMock(spec=Sandbox)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="ok", stderr="")
    shell = ShellService(sandbox)
    result = shell.exec("echo hi", timeout=5)
    assert result.exit_code == 0
    sandbox.exec.assert_called_once_with(["sh", "-c", "echo hi"], timeout=5)


def test_shell_service_exec_no_timeout():
    sandbox = MagicMock(spec=Sandbox)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="ok", stderr="")
    shell = ShellService(sandbox)
    shell.exec("echo hi")
    sandbox.exec.assert_called_once_with(["sh", "-c", "echo hi"], timeout=None)


def test_filesystem_service_exists():
    sandbox = FakeSandbox()
    fs = FileSystemService(sandbox)
    assert fs.exists("/some/path") is True
    sandbox.exec_result = ExecResult(exit_code=1, stdout="", stderr="")
    assert fs.exists("/missing") is False


def test_filesystem_service_remove():
    sandbox = MagicMock(spec=Sandbox)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
    fs = FileSystemService(sandbox)
    fs.remove("/some/path")
    sandbox.exec.assert_called_with(["rm", "-rf", "/some/path"])


def test_filesystem_service_list_dir():
    sandbox = FakeSandbox()
    sandbox.exec_result = ExecResult(exit_code=0, stdout="file1\nfile2\ndir1\n", stderr="")
    fs = FileSystemService(sandbox)
    result = fs.list_dir("/some/dir")
    assert result == ["file1", "file2", "dir1"]


def test_filesystem_service_make_dir():
    sandbox = MagicMock(spec=Sandbox)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
    fs = FileSystemService(sandbox)
    fs.make_dir("/some/new/dir")
    sandbox.exec.assert_called_with(["mkdir", "-p", "/some/new/dir"])


def test_filesystem_service_upload():
    sandbox = MagicMock(spec=Sandbox)
    fs = FileSystemService(sandbox)
    fs.upload("/local/file.txt", "/sandbox/file.txt")
    sandbox.upload.assert_called_once_with("/local/file.txt", "/sandbox/file.txt")


def test_filesystem_service_download():
    sandbox = MagicMock(spec=Sandbox)
    fs = FileSystemService(sandbox)
    fs.download("/sandbox/file.txt", "/local/file.txt")
    sandbox.download.assert_called_once_with("/sandbox/file.txt", "/local/file.txt")


def test_sandbox_spec_default_returns_none():
    assert FakeAPICapability.sandbox_spec() is None


def test_sandbox_spec_override():
    spec = FakeSandboxCapability.sandbox_spec()
    assert spec.image == "test:latest"
    assert spec.ports == [8080]
