import pytest
from unittest.mock import MagicMock, patch
from terrarium.environment.environment import ComposableEnvironment, _parse_spec
from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityNotFoundError
from terrarium.environment.capabilities import _REGISTRY
from terrarium.environment.sandbox import ExecResult, SandboxSpec


class FakeApiCap(BaseCapability):
    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self.torn_down = False

    @classmethod
    def sandbox_spec(cls, config=None):
        return None

    def wait_ready(self):
        pass

    def teardown(self):
        self.torn_down = True

    @property
    def marker(self):
        return self._config.get("marker", "default-marker")


class FakeSandboxCap(BaseCapability):
    @classmethod
    def sandbox_spec(cls, config=None):
        return SandboxSpec(image={"name": "fake:latest"}, ports=[1234])

    def wait_ready(self):
        pass

    @property
    def marker(self):
        return self._config.get("marker", "default-marker")


_REGISTRY["fake_api"] = FakeApiCap
_REGISTRY["fake_sb"] = FakeSandboxCap


def _mock_provider():
    provider = MagicMock()
    sandbox = MagicMock()
    sandbox.get_host.return_value = ("localhost", 12345)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
    provider.create.return_value = sandbox
    return provider


def test_parse_spec_bare_name_normalizes_to_default():
    assert _parse_spec("postgres") == ("postgres", "default")


def test_parse_spec_with_instance():
    assert _parse_spec("workspace:dev") == ("workspace", "dev")


def test_parse_spec_only_first_colon_is_separator():
    assert _parse_spec("workspace:dev:extra") == ("workspace", "dev:extra")


def test_single_instance_attribute_passthrough():
    with ComposableEnvironment(["fake_api"], config={"fake_api": {"marker": "alone"}}) as env:
        assert env.fake_api.marker == "alone"


def test_explicit_default_form_normalizes():
    with ComposableEnvironment(["fake_api:default"], config={"fake_api": {"marker": "X"}}) as env:
        assert env.fake_api.marker == "X"


def test_named_single_instance_passthrough():
    with ComposableEnvironment(["fake_api:only"], config={"fake_api:only": {"marker": "Y"}}) as env:
        assert env.fake_api.marker == "Y"


def test_multiple_instances_pick_by_name():
    config = {"fake_api:a": {"marker": "AAA"}, "fake_api:b": {"marker": "BBB"}}
    with ComposableEnvironment(["fake_api:a", "fake_api:b"], config=config) as env:
        assert env.fake_api("a").marker == "AAA"
        assert env.fake_api("b").marker == "BBB"


def test_multiple_instances_default_fallback():
    config = {"fake_api": {"marker": "MAIN"}, "fake_api:extra": {"marker": "EXTRA"}}
    with ComposableEnvironment(["fake_api", "fake_api:extra"], config=config) as env:
        assert env.fake_api.marker == "MAIN"
        assert env.fake_api("default").marker == "MAIN"
        assert env.fake_api("extra").marker == "EXTRA"


def test_multiple_instances_no_default_raises_attributeerror():
    config = {"fake_api:a": {"marker": "AAA"}, "fake_api:b": {"marker": "BBB"}}
    with ComposableEnvironment(["fake_api:a", "fake_api:b"], config=config) as env:
        with pytest.raises(AttributeError, match="no 'default' fallback"):
            _ = env.fake_api.marker
        assert env.fake_api("a").marker == "AAA"


def test_selector_unknown_instance_raises_keyerror():
    with ComposableEnvironment(["fake_api:a", "fake_api:b"], config={"fake_api:a": {}, "fake_api:b": {}}) as env:
        with pytest.raises(KeyError, match="No fake_api instance named 'nonexistent'"):
            env.fake_api("nonexistent")


def test_duplicate_string_is_deduped():
    with ComposableEnvironment(["fake_api:a", "fake_api:a"]) as env:
        assert len(env.fake_api) == 1


def test_two_forms_of_default_are_deduped():
    with ComposableEnvironment(["fake_api", "fake_api:default"]) as env:
        assert len(env.fake_api) == 1


def test_config_bare_key_works_for_default():
    with ComposableEnvironment(["fake_api"], config={"fake_api": {"marker": "Z"}}) as env:
        assert env.fake_api.marker == "Z"


def test_config_explicit_default_key_works_for_bare_declaration():
    with ComposableEnvironment(["fake_api"], config={"fake_api:default": {"marker": "Z"}}) as env:
        assert env.fake_api.marker == "Z"


def test_config_bare_key_works_for_explicit_default_declaration():
    with ComposableEnvironment(["fake_api:default"], config={"fake_api": {"marker": "Z"}}) as env:
        assert env.fake_api.marker == "Z"


def test_selector_iter_visits_all_instances():
    config = {"fake_api:a": {"marker": "A"}, "fake_api:b": {"marker": "B"}}
    with ComposableEnvironment(["fake_api:a", "fake_api:b"], config=config) as env:
        markers = sorted(cap.marker for cap in env.fake_api)
        assert markers == ["A", "B"]


def test_selector_len_reports_instance_count():
    config = {"fake_api:a": {}, "fake_api:b": {}, "fake_api:c": {}}
    with ComposableEnvironment(["fake_api:a", "fake_api:b", "fake_api:c"], config=config) as env:
        assert len(env.fake_api) == 3


def test_multi_instance_sandbox_creates_provider_per_instance():
    provider = _mock_provider()
    env = ComposableEnvironment(["fake_sb:dev", "fake_sb:test"], provider=provider)
    env.start()
    try:
        assert provider.create.call_count == 2
        names = sorted(call.args[0].name for call in provider.create.call_args_list)
        assert names == ["fake_sb-dev", "fake_sb-test"]
    finally:
        env.stop()
    provider.teardown.assert_called_once()


def test_multi_instance_teardown_called_for_each():
    provider = _mock_provider()
    teardown_calls: list[str] = []

    class TrackingFakeCap(BaseCapability):
        @classmethod
        def sandbox_spec(cls, config=None):
            return SandboxSpec(image={"name": "fake:latest"})
        def wait_ready(self):
            pass
        def teardown(self):
            teardown_calls.append(self._config.get("marker", "?"))

    _REGISTRY["tracking"] = TrackingFakeCap
    try:
        env = ComposableEnvironment(
            ["tracking:a", "tracking:b"],
            provider=provider,
            config={"tracking:a": {"marker": "A"}, "tracking:b": {"marker": "B"}},
        )
        env.start()
        env.stop()
        assert sorted(teardown_calls) == ["A", "B"]
    finally:
        del _REGISTRY["tracking"]


def test_unknown_capability_type_raises_on_start():
    env = ComposableEnvironment(["fake_nonexistent"])
    with pytest.raises(CapabilityNotFoundError, match="fake_nonexistent"):
        env.start()


def test_acquire_returns_registered_instance():
    with ComposableEnvironment(["fake_api"]) as env:
        extra = env.acquire("fake_api:extra", config={"marker": "EXTRA"})
        assert extra.marker == "EXTRA"
        assert env.fake_api("extra") is extra


def test_acquire_sandbox_capability_uses_provider():
    provider = _mock_provider()
    env = ComposableEnvironment(["fake_api"], provider=provider)
    env.start()
    try:
        cap = env.acquire("fake_sb:dynamic")
        assert cap is env.fake_sb("dynamic")
        provider.create.assert_called_once()
        created_spec = provider.create.call_args[0][0]
        assert created_spec.name == "fake_sb-dynamic"
    finally:
        env.stop()


def test_acquire_duplicate_raises_valueerror():
    with ComposableEnvironment(["fake_api"]) as env:
        with pytest.raises(ValueError, match="already exists"):
            env.acquire("fake_api")


def test_acquire_before_start_raises_runtimeerror():
    env = ComposableEnvironment(["fake_api"])
    with pytest.raises(RuntimeError, match="not started"):
        env.acquire("fake_api:extra")


def test_acquire_after_stop_raises_runtimeerror():
    env = ComposableEnvironment(["fake_api"])
    env.start()
    env.stop()
    with pytest.raises(RuntimeError, match="not started"):
        env.acquire("fake_api:extra")


def test_release_removes_and_tears_down():
    with ComposableEnvironment(["fake_api", "fake_api:extra"]) as env:
        extra = env.fake_api("extra")
        assert not extra.torn_down
        env.release("fake_api:extra")
        assert extra.torn_down
        assert len(env.fake_api) == 1
        with pytest.raises(KeyError):
            env.fake_api("extra")


def test_release_last_instance_removes_type_from_selector():
    with ComposableEnvironment(["fake_api"]) as env:
        env.release("fake_api")
        with pytest.raises(CapabilityNotFoundError):
            _ = env.fake_api


def test_release_nonexistent_raises_keyerror():
    with ComposableEnvironment(["fake_api"]) as env:
        with pytest.raises(KeyError, match="nonexistent"):
            env.release("fake_api:nonexistent")


def test_release_before_start_raises_runtimeerror():
    env = ComposableEnvironment(["fake_api"])
    with pytest.raises(RuntimeError, match="not started"):
        env.release("fake_api")


def test_acquire_after_release_succeeds():
    with ComposableEnvironment(["fake_api"]) as env:
        env.release("fake_api")
        new = env.acquire("fake_api", config={"marker": "RELOADED"})
        assert new.marker == "RELOADED"
        assert env.fake_api.marker == "RELOADED"


def test_acquire_lazy_initializes_provider_for_sandbox_cap():
    mock_provider = _mock_provider()
    mock_provider_cls = MagicMock(return_value=mock_provider)
    with patch(
        "terrarium.environment.providers.docker.DockerSandboxProvider",
        mock_provider_cls,
    ):
        with ComposableEnvironment(["fake_api"]) as env:
            mock_provider_cls.assert_not_called()
            env.acquire("fake_sb:lazy")
            mock_provider_cls.assert_called_once()
            mock_provider.setup.assert_called_once()
            mock_provider.create.assert_called_once()
