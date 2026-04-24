"""Composable environment — manages capability lifecycle and sandbox orchestration."""

from __future__ import annotations

from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityNotFoundError
from terrarium.environment.capabilities import resolve_capability_class
from terrarium.environment.sandbox import SandboxProvider


class CapabilitySelector:
    """Handle for one or more instances of a capability type."""

    __slots__ = ("_type_name", "_instances")

    def __init__(self, type_name: str, instances: dict[str, BaseCapability]):
        self._type_name = type_name
        self._instances = instances

    def __call__(self, instance_name: str) -> BaseCapability:
        try:
            return self._instances[instance_name]
        except KeyError:
            raise KeyError(
                f"No {self._type_name} instance named {instance_name!r}. "
                f"Available: {sorted(self._instances)}"
            ) from None

    def __getattr__(self, attr: str):
        # Single instance: transparent passthrough regardless of name.
        if len(self._instances) == 1:
            return getattr(next(iter(self._instances.values())), attr)
        # Multiple instances: fall back to "default" if it exists.
        if "default" in self._instances:
            return getattr(self._instances["default"], attr)
        raise AttributeError(
            f"{self._type_name!r} has {len(self._instances)} instances "
            f"({sorted(self._instances)}) and no 'default' fallback. "
            f"Use env.{self._type_name}('<name>').{attr} to pick one."
        )

    def __iter__(self):
        return iter(self._instances.values())

    def __len__(self):
        return len(self._instances)

    def __repr__(self):
        return f"<{self._type_name} selector: {sorted(self._instances)}>"


def _parse_spec(spec: str) -> tuple[str, str]:
    """Parse 'type[:instance]' into (type, instance); bare type means instance='default'."""
    type_name, sep, instance_name = spec.partition(":")
    return (type_name, instance_name) if sep else (type_name, "default")


class ComposableEnvironment:
    """Main entry point. Manages capability lifecycle."""

    def __init__(
        self,
        capabilities: list[str],
        provider: SandboxProvider | None = None,
        config: dict[str, dict] | None = None,
    ):
        self._capability_specs = capabilities
        self._provider = provider
        self._config = config or {}
        self._capabilities: dict[str, dict[str, BaseCapability]] = {}
        self._started = False

    def start(self) -> None:
        parsed = {_parse_spec(s) for s in self._capability_specs}
        config = {_parse_spec(k): v for k, v in self._config.items()}

        capability_classes = {
            (t, i): resolve_capability_class(t, config.get((t, i)))
            for t, i in parsed
        }

        # Lazy provider init: only if at least one instance needs a sandbox.
        needs_provider = any(
            capability_classes[(t, i)].sandbox_spec(config.get((t, i))) is not None
            for t, i in parsed
        )
        if needs_provider:
            if self._provider is None:
                from terrarium.environment.providers.docker import DockerSandboxProvider
                self._provider = DockerSandboxProvider()
            self._provider.setup()

        # Start workspace last so we can inject secrets from other capabilities.
        non_workspace_specs = [(t, i) for t, i in parsed if t != "workspace"]
        workspace_specs = [(t, i) for t, i in parsed if t == "workspace"]

        started: list[tuple[str, str]] = []
        try:
            # Phase 1: start all non-workspace capabilities
            for type_name, instance_name in non_workspace_specs:
                cls = capability_classes[(type_name, instance_name)]
                cap_config = config.get((type_name, instance_name))
                sandbox_spec = cls.sandbox_spec(cap_config)

                if sandbox_spec:
                    sandbox_spec.name = f"{type_name}-{instance_name}"
                    logger.info("Starting capability: {}:{} (sandbox)", type_name, instance_name)
                    sandbox = self._provider.create(sandbox_spec)
                    cap = cls(config=cap_config, sandbox=sandbox)
                else:
                    logger.info("Starting capability: {}:{}", type_name, instance_name)
                    cap = cls(config=cap_config)

                cap.wait_ready()
                self._capabilities.setdefault(type_name, {})[instance_name] = cap
                started.append((type_name, instance_name))
                logger.info("Capability ready: {}:{}", type_name, instance_name)

            # Phase 2: collect secrets, start workspace with them injected
            secrets_env, secrets_file = self._collect_secrets(self._capabilities)

            for type_name, instance_name in workspace_specs:
                cls = capability_classes[(type_name, instance_name)]
                cap_config = config.get((type_name, instance_name))
                sandbox_spec = cls.sandbox_spec(cap_config)

                if sandbox_spec:
                    sandbox_spec.name = f"{type_name}-{instance_name}"
                    if secrets_env:
                        sandbox_spec.env = {**sandbox_spec.env, **secrets_env}
                    logger.info("Starting capability: {}:{} (sandbox)", type_name, instance_name)
                    sandbox = self._provider.create(sandbox_spec)
                    cap = cls(config=cap_config, sandbox=sandbox)

                    for name, host_path in secrets_file.items():
                        sandbox.upload(host_path, f"/run/secrets/{name}")
                else:
                    logger.info("Starting capability: {}:{}", type_name, instance_name)
                    cap = cls(config=cap_config)

                cap.wait_ready()
                self._capabilities.setdefault(type_name, {})[instance_name] = cap
                started.append((type_name, instance_name))
                logger.info("Capability ready: {}:{}", type_name, instance_name)

        except Exception:
            for type_name, instance_name in reversed(started):
                try:
                    self._capabilities[type_name][instance_name].teardown()
                except Exception as e:
                    logger.warning(
                        "Error during rollback teardown of {}:{}: {}",
                        type_name, instance_name, e,
                    )
            self._capabilities.clear()
            if self._provider:
                self._provider.teardown()
            raise

        self._started = True

    def stop(self) -> None:
        for type_name, instances in self._capabilities.items():
            for instance_name, cap in instances.items():
                try:
                    logger.info("Stopping capability: {}:{}", type_name, instance_name)
                    cap.teardown()
                except Exception as e:
                    logger.warning(
                        "Error tearing down {}:{}: {}", type_name, instance_name, e
                    )

        self._capabilities.clear()

        if self._provider:
            self._provider.teardown()

        self._started = False

    def __enter__(self) -> ComposableEnvironment:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def acquire(self, spec: str, config: dict | None = None) -> BaseCapability:
        if not self._started:
            raise RuntimeError("ComposableEnvironment not started")

        type_name, instance_name = _parse_spec(spec)
        if instance_name in self._capabilities.get(type_name, {}):
            raise ValueError(
                f"Capability instance already exists: {type_name}:{instance_name}"
            )

        cap_config = config or {}
        cls = resolve_capability_class(type_name, cap_config)
        sandbox_spec = cls.sandbox_spec(cap_config)

        if sandbox_spec:
            self._ensure_provider()
            sandbox_spec.name = f"{type_name}-{instance_name}"
            logger.info("Acquiring capability: {}:{} (sandbox)", type_name, instance_name)
            sandbox = self._provider.create(sandbox_spec)
            cap = cls(config=cap_config, sandbox=sandbox)
        else:
            logger.info("Acquiring capability: {}:{}", type_name, instance_name)
            cap = cls(config=cap_config)

        cap.wait_ready()
        self._capabilities.setdefault(type_name, {})[instance_name] = cap
        logger.info("Capability ready: {}:{}", type_name, instance_name)
        return cap

    def release(self, spec: str) -> None:
        if not self._started:
            raise RuntimeError("ComposableEnvironment not started")

        type_name, instance_name = _parse_spec(spec)
        instances = self._capabilities.get(type_name)
        if not instances or instance_name not in instances:
            raise KeyError(f"No {type_name} instance named {instance_name!r}")

        cap = instances.pop(instance_name)
        if not instances:
            del self._capabilities[type_name]
        try:
            logger.info("Releasing capability: {}:{}", type_name, instance_name)
            cap.teardown()
        except Exception as e:
            logger.warning("Error releasing {}:{}: {}", type_name, instance_name, e)

    def _collect_secrets(
        self, capabilities: dict[str, dict[str, BaseCapability]],
    ) -> tuple[dict[str, str], dict[str, str]]:
        env = {}
        file = {}
        for instances in capabilities.values():
            for cap in instances.values():
                if not hasattr(cap, "connection_info"):
                    continue
                secrets = cap.connection_info.get("secrets", {})
                env.update(secrets.get("env", {}))
                file.update(secrets.get("file", {}))
        return env, file

    def _ensure_provider(self) -> None:
        if self._provider is None:
            from terrarium.environment.providers.docker import DockerSandboxProvider
            self._provider = DockerSandboxProvider()
            self._provider.setup()

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        caps = self.__dict__.get("_capabilities", {})
        if name in caps:
            return CapabilitySelector(name, caps[name])
        raise CapabilityNotFoundError(name, list(caps.keys()))
