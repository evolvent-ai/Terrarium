import pytest
from unittest.mock import MagicMock, patch
from terrarium.environment.capabilities.workspace import WorkspaceCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.sandbox import ExecResult


class TestWorkspaceCapabilityUnit:
    def _make_sandbox(self):
        sandbox = MagicMock()
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="ready", stderr="")
        sandbox.hostname.return_value = "workspace-container"
        return sandbox

    def _make_cap(self):
        sandbox = self._make_sandbox()
        cap = WorkspaceCapability(sandbox=sandbox)
        return cap, sandbox

    # -------------------------------------------------------------------
    # sandbox_spec
    # -------------------------------------------------------------------

    def test_sandbox_spec_defaults(self):
        spec = WorkspaceCapability.sandbox_spec()
        assert spec.image.name == "ubuntu:24.04"
        assert spec.command == ["tail", "-f", "/dev/null"]

    def test_sandbox_spec_custom_image(self):
        spec = WorkspaceCapability.sandbox_spec({"image": {"name": "python:3.12-slim"}})
        assert spec.image.name == "python:3.12-slim"

    def test_sandbox_spec_build(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        spec = WorkspaceCapability.sandbox_spec({"image": {"build": {"context": str(tmp_path)}}})
        assert spec.image.name is None
        assert spec.image.build.context == str(tmp_path)

    def test_sandbox_spec_custom_command(self):
        spec = WorkspaceCapability.sandbox_spec({"command": ["tail", "-f", "/dev/null"]})
        assert spec.command == ["tail", "-f", "/dev/null"]

    # -------------------------------------------------------------------
    # init
    # -------------------------------------------------------------------

    def test_init_default_image(self):
        sandbox = self._make_sandbox()
        cap = WorkspaceCapability(sandbox=sandbox)
        assert cap._image == "ubuntu:24.04"

    def test_init_custom_image(self):
        sandbox = self._make_sandbox()
        cap = WorkspaceCapability(config={"image": {"name": "alpine:3.19"}}, sandbox=sandbox)
        assert cap._image == "alpine:3.19"

    def test_init_build_only_image_name_is_none(self):
        sandbox = self._make_sandbox()
        cap = WorkspaceCapability(
            config={"image": {"build": {"context": "/ctx"}}}, sandbox=sandbox
        )
        assert cap._image is None

    def test_has_fs_and_shell(self):
        cap, sandbox = self._make_cap()
        assert cap.fs is not None
        assert cap.shell is not None

    # -------------------------------------------------------------------
    # wait_ready
    # -------------------------------------------------------------------

    def test_wait_ready_success(self):
        cap, sandbox = self._make_cap()
        cap.wait_ready(timeout=5.0)
        sandbox.exec.assert_called_with(["echo", "ready"])

    def test_wait_ready_retries(self):
        sandbox = self._make_sandbox()
        sandbox.exec.side_effect = [
            ExecResult(exit_code=1, stdout="", stderr=""),
            ExecResult(exit_code=1, stdout="", stderr=""),
            ExecResult(exit_code=0, stdout="ready", stderr=""),
        ]
        cap = WorkspaceCapability(sandbox=sandbox)
        cap.wait_ready(timeout=10.0)
        assert sandbox.exec.call_count == 3

    @patch("terrarium.environment.capabilities.workspace.time")
    def test_wait_ready_timeout(self, mock_time):
        sandbox = self._make_sandbox()
        sandbox.exec.return_value = ExecResult(exit_code=1, stdout="", stderr="")
        mock_time.monotonic.side_effect = [0, 0, 100]
        mock_time.sleep = MagicMock()
        cap = WorkspaceCapability(sandbox=sandbox)
        with pytest.raises(CapabilityError, match="not ready"):
            cap.wait_ready(timeout=5.0)

    # -------------------------------------------------------------------
    # connection_info
    # -------------------------------------------------------------------

    def test_connection_info(self):
        cap, sandbox = self._make_cap()
        info = cap.connection_info
        assert info["hostname"] == "workspace-container"
        assert info["image"] == "ubuntu:24.04"

    def test_connection_info_custom_image(self):
        sandbox = self._make_sandbox()
        cap = WorkspaceCapability(config={"image": {"name": "node:20"}}, sandbox=sandbox)
        assert cap.connection_info["image"] == "node:20"

    # -------------------------------------------------------------------
    # no specialized methods
    # -------------------------------------------------------------------

    def test_no_teardown_needed(self):
        cap, sandbox = self._make_cap()
        cap.teardown()  # default no-op, should not raise
