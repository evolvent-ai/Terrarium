# Issue: Support external MCP mock server with namespace isolation

## Problem

Currently, every Trial in Terrarium creates and destroys all Docker containers (DB, email, calendar, MCP mock servers) from scratch. This design provides isolation but introduces significant overhead:

- Container cold-start cost (3-10s per trial) accumulates at scale
- The same seed data (init SQL, seed emails, etc.) is re-created from scratch every time
- MCP mock servers that are functionally stateless still pay the full container lifecycle cost

When Terrarium operates as a platform product with a dedicated mock environment server (see: terrarium-mock-servers), there is no integration path to delegate MCP mock environment management to an external service.

## Current architecture constraints

The current `SandboxProvider` interface is designed for container lifecycle management:

```python
class SandboxProvider(ABC):
    def setup(self): ...                     # Create network
    def create(self, spec: SandboxSpec) -> Sandbox: ...  # Create container
    def teardown(self): ...                  # Destroy all containers
```

`Sandbox` exposes container-level operations (`exec`, `read_file`, `upload`, etc.). An external namespace broker does not manage containers — it manages **data namespaces**. These are fundamentally different concerns:

- **Workspace sandbox**: Still needs a real Docker container for the agent to run in
- **Data services** (DB, email, calendar): Can be replaced by a remote broker with namespace isolation
- **MCP mock servers**: Can be replaced by remote resident services with namespace routing

Therefore, the integration point should NOT be at the `SandboxProvider` level. It should be at the **Capability** level and the **MCP server configuration** level.

## Proposal

### 1. Broker-backed capabilities

Add a new capability type that delegates to the external broker instead of creating a local sandbox:

```python
class BrokerBackedCapability(BaseCapability):
    """
    A capability backed by an external namespace broker.
    Returns sandbox_spec() = None (no local container needed).
    Communicates with the broker to create/clone namespaced data.
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox=None)  # No sandbox
        self._broker_url = config["broker_url"]
        self._domain = config["domain"]
        self._namespace = None

    @classmethod
    def sandbox_spec(cls, config=None) -> None:
        return None  # No local container

    def wait_ready(self):
        # Clone namespace from seed via broker API
        resp = httpx.post(f"{self._broker_url}/admin/namespaces", json={
            "seed_id": self._config["seed_id"],
            "trial_id": self._config["trial_id"],
            "domains": [self._domain],
        })
        self._namespace = resp.json()["namespace_id"]
        self._mcp_url = resp.json()["mcp_servers"][0]["url"]

    @property
    def connection_info(self) -> dict:
        return {
            "mcp_url": self._mcp_url,
            "namespace": self._namespace,
        }

    def teardown(self):
        httpx.delete(f"{self._broker_url}/admin/namespaces/{self._namespace}")
```

This works with the existing `ComposableEnvironment` — broker-backed capabilities coexist with container-backed ones (workspace still uses `DockerSandboxProvider`).

### 2. MCP server injection from broker

When the broker returns MCP server URLs, the Trial passes them to the agent via the existing `add_mcp_server()` interface:

```python
# In Trial._setup_agent(), after broker capabilities are ready:
for cap_name in broker_capabilities:
    cap = getattr(env, cap_name)
    mcp_config = MCPServerConfig(
        name=cap_name,
        transport="streamable-http",
        url=cap.connection_info["mcp_url"],
    )
    agent.add_mcp_server(mcp_config)
```

### 3. Seed registration

Two mechanisms, depending on the data source:

**A. From init.sql files (vibe-agent/servers pattern)**:
```
Job start:
  POST /admin/seeds
  { domains: ["banking", "email"], init_sqls: { "banking": "INSERT ...", "email": "INSERT ..." } }
  -> { seed_id: "s001" }
```

**B. From task entry function (current Terrarium pattern)**:
The task's `@entry` function currently initializes data via Python calls (`env.postgres.execute(...)`). To support broker mode, introduce an optional `@task.seed` decorator that separates initialization from execution:

```python
@entry(capabilities=["workspace"], mcp_domains=["banking", "email"])
def my_task(env, agent):
    agent.act("Check the latest bank transaction")

@my_task.seed
def init(broker_env):
    """Runs once per task to create seed data. Only called in broker mode."""
    broker_env.banking.execute("INSERT INTO accounts VALUES ...")
    broker_env.email.send(from_addr="boss@co.com", ...)
```

When using `DockerSandboxProvider` (default), `@task.seed` is ignored and init happens in `@entry` as before. When using broker mode, `@task.seed` runs once at Job start, and `@entry` skips initialization.

This is **optional** — tasks without `@task.seed` work in both modes, they just can't leverage seed caching in broker mode.

### Configuration

```toml
# Job config — opt-in to broker mode
[job]
mock_broker = { url = "http://mock-gateway:9100" }

# Per-task MCP domains are declared in @entry(mcp_domains=[...])
# or in task.toml
```

## Scope

- New: `terrarium/environment/capabilities/broker.py` — `BrokerBackedCapability`
- New: `terrarium/environment/broker_client.py` — thin HTTP client for `/admin/*` API
- Update: `Trial._setup_agent()` — inject broker MCP servers into agent config
- Update: `@entry` decorator — support `mcp_domains` parameter
- New (optional): `@task.seed` decorator for separating init from execution
- Update: `JobConfig` / `TrialConfig` — support `mock_broker` config

## Non-goals

- Managing the lifecycle of the external mock environment server (that belongs to terrarium-mock-servers)
- Changing `SandboxProvider` interface or `DockerSandboxProvider` behavior
- Requiring the broker for any existing workflow

## Backward compatibility

Fully backward compatible:
- `DockerSandboxProvider` remains the default
- `mock_broker` config is optional
- Tasks without `mcp_domains` or `@task.seed` work exactly as before
- Existing capabilities (postgres, email, calendar) are unaffected — they still create local containers unless broker mode is enabled
