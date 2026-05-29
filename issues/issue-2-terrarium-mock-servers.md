# Issue: Unified mock environment server with MySQL-backed namespace isolation

## Overview

A platform-grade mock environment server for Terrarium. Contains 22 business-domain MCP mock servers, deployed as a single k8s-native service, with MySQL row-level namespace isolation for concurrent trial support.

This is a standalone project (terrarium-mock-servers), independent of Terrarium's core. Terrarium connects to it via broker-backed capabilities (see Issue #1).

## Architecture

### Design principles

1. **Single service, multiple domains**: One deployable unit containing 22 domain modules, not 22 independent projects
2. **All domains always resident**: Platform users submit Jobs without managing server lifecycle
3. **Fixed database count**: 22 MySQL databases (one per domain), never created or dropped at runtime
4. **Row-level isolation**: All multi-tenancy via `ns` column, pure DML (INSERT/DELETE), no DDL per trial
5. **Stateless compute**: All Domain Pods are stateless, connect to shared MySQL, scale freely

### System topology

```
                    Terrarium
                       |
                       v
              +--- Ingress ---+
              | mock.internal |
              +-------+-------+
                      v
              +-- Gateway --+        Deployment x1 (stateless)
              |  namespace  |
              |  mgmt + route|
              +------+------+
                     |
        +----+------+------+----+
        v    v      v      v    v
      bank email  cal   ecomm  ...   Deployment x1~N each (stateless)
        |    |      |      |    |
        +----+------+------+----+
                     |
                     v
            +--- MySQL ---+
            | StatefulSet  |         or managed service (RDS/Cloud SQL)
            | or managed   |
            +--------------+

  Database count: always 22 (mock_banking, mock_email, ...)
  PVC: not needed for Domain Pods
```

### Single image, two roles

One Docker image serves both Gateway and Domain roles, selected by startup argument:

```
terrarium-mock --role gateway --port 9100
terrarium-mock --role domain --domain banking --port 8000
```

## Data isolation: row-level namespace

### Schema convention

Every table in every domain includes an `ns` (namespace) column as part of the primary key:

```sql
-- domains/banking/schema.sql
CREATE TABLE accounts (
    ns          VARCHAR(64)    NOT NULL,
    id          VARCHAR(64)    NOT NULL,
    owner_name  VARCHAR(255),
    balance     DECIMAL(15,2),
    created_at  TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ns, id),
    INDEX idx_ns (ns)
);

CREATE TABLE transactions (
    ns          VARCHAR(64)    NOT NULL,
    id          VARCHAR(64)    NOT NULL,
    from_acct   VARCHAR(64),
    to_acct     VARCHAR(64),
    amount      DECIMAL(15,2),
    created_at  TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ns, id),
    INDEX idx_ns_from (ns, from_acct),
    INDEX idx_ns_to (ns, to_acct)
);
```

### Namespace lifecycle (pure DML, no DDL)

```sql
-- 1. Seed creation (once per task)
INSERT INTO mock_banking.accounts (ns, id, owner_name, balance) VALUES
  ('seed_s001', 'acct_001', 'Alice', 10000.00),
  ('seed_s001', 'acct_002', 'Bob',   5000.00);

-- 2. Trial clone (milliseconds, INSERT...SELECT)
INSERT INTO mock_banking.accounts (ns, id, owner_name, balance)
  SELECT 'trial_a8f3', id, owner_name, balance
  FROM mock_banking.accounts WHERE ns = 'seed_s001';

-- 3. Trial execution (all queries scoped by ns)
SELECT * FROM accounts WHERE ns = 'trial_a8f3' AND id = 'acct_001';
UPDATE accounts SET balance = 8000.00 WHERE ns = 'trial_a8f3' AND id = 'acct_001';

-- 4. Trial cleanup (milliseconds, DELETE)
DELETE FROM mock_banking.accounts WHERE ns = 'trial_a8f3';
DELETE FROM mock_banking.transactions WHERE ns = 'trial_a8f3';
```

### Why not per-trial databases

| Concern | Per-trial database | Row-level ns |
|---------|-------------------|--------------|
| DB count at 100 concurrent trials | 2200 | 22 (fixed) |
| DB count at 1000 concurrent trials | 22000 (infeasible) | 22 (fixed) |
| CREATE/DROP frequency | thousands/hour (heavy DDL) | zero DDL |
| Clone mechanism | CREATE TABLE LIKE + INSERT SELECT per table | INSERT...SELECT (one statement/table) |
| Cleanup mechanism | DROP DATABASE (filesystem delete, heavy) | DELETE WHERE ns=? (milliseconds) |
| information_schema pressure | linear with DB count | constant |

## Metadata management

The Gateway maintains a metadata database (`mock_meta`) to track seeds and namespaces:

```sql
-- mock_meta.seeds
CREATE TABLE seeds (
    seed_id       VARCHAR(64)  PRIMARY KEY,
    content_hash  VARCHAR(64)  NOT NULL UNIQUE,  -- for idempotent seed creation
    domains       JSON         NOT NULL,          -- ["banking", "email"]
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- mock_meta.namespaces
CREATE TABLE namespaces (
    namespace_id  VARCHAR(64)  PRIMARY KEY,
    seed_id       VARCHAR(64)  NOT NULL,
    domains       JSON         NOT NULL,
    status        ENUM('active', 'cleaning')  DEFAULT 'active',
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (seed_id) REFERENCES seeds(seed_id)
);
```

This enables:
- Idempotent seed creation (same init SQL -> same seed_id via content_hash)
- Orphan namespace cleanup (query namespaces older than X hours with status='active')
- Audit trail for debugging

## Gateway: Admin API

The Gateway is the only externally exposed endpoint. It handles namespace management and routes MCP requests to domain pods.

### Admin endpoints

```
POST   /admin/seeds
  Request:  { domains: ["banking", "email"], init_sqls: { "banking": "INSERT ...", "email": "INSERT ..." } }
  Response: { seed_id: "s001" }
  Behavior: Compute content hash of init_sqls. If seed exists, return existing seed_id.
            Otherwise, execute init SQLs with ns='seed_{seed_id}' in each domain's database.

POST   /admin/namespaces
  Request:  { seed_id: "s001", trial_id: "trial_a8f3", domains: ["banking", "email"] }
  Response: {
    namespace_id: "trial_a8f3",
    mcp_servers: [
      { name: "banking", transport: "streamable-http", url: "http://mock-gateway:9100/mcp/banking?ns=trial_a8f3" },
      { name: "email",   transport: "streamable-http", url: "http://mock-gateway:9100/mcp/email?ns=trial_a8f3" }
    ]
  }
  Behavior: INSERT...SELECT from seed rows to trial rows, for each domain and each table.
            Record namespace in mock_meta.namespaces.

DELETE /admin/namespaces/{namespace_id}
  Request:  (path param only)
  Response: { deleted: true }
  Behavior: DELETE FROM all tables WHERE ns='{namespace_id}', for each domain.
            Remove record from mock_meta.namespaces.

GET    /admin/registry
  Response: { domains: ["banking", "email", "calendar", ...] }
  Behavior: List all registered domain modules.

GET    /admin/health
  Response: { status: "ok", mysql: "connected", domains: { banking: "ready", email: "ready", ... } }
```

### MCP routing

The Gateway acts as a reverse proxy for MCP streamable-http traffic. Each domain pod runs a standalone FastMCP server on a fixed port.

```
Client request:
  POST /mcp/banking?ns=trial_a8f3
  (MCP streamable-http request body)

Gateway behavior:
  1. Extract domain="banking" and ns="trial_a8f3" from URL
  2. Validate namespace exists in mock_meta.namespaces
  3. Forward the full HTTP request (including SSE stream) to banking domain pod
     via ClusterIP service: http://mock-banking:8000/mcp
  4. The namespace is passed to the domain pod via X-Namespace header
  5. Stream the response back to the client

Domain pod behavior:
  1. Extract namespace from X-Namespace header
  2. Create NamespacedConnection(ns="trial_a8f3")
  3. All MCP tool calls within this request are scoped to this namespace
```

Note: MCP streamable-http involves SSE streams. The Gateway must support streaming proxying (e.g., via httpx streaming or ASGI middleware). This is well-supported by frameworks like FastAPI/Starlette.

## Framework: shared base for all domains

### NamespacedConnection

Transparent multi-tenancy wrapper. Domain business code never sees the `ns` column.

Table and database names are validated against a whitelist (the domain's schema) to prevent SQL injection — they are never derived from user input.

```python
class NamespacedConnection:
    def __init__(self, pool, namespace: str, database: str, known_tables: set[str]):
        self._pool = pool
        self._ns = namespace
        self._db = database
        self._known_tables = known_tables  # validated at startup from schema.sql

    def _validate_table(self, table: str):
        if table not in self._known_tables:
            raise ValueError(f"Unknown table: {table}")

    def query(self, table: str, where: str = "1=1", params: tuple = ()) -> list[dict]:
        self._validate_table(table)
        sql = f"SELECT * FROM `{self._db}`.`{table}` WHERE ns = %s AND ({where})"
        return self._execute(sql, (self._ns, *params))

    def insert(self, table: str, data: dict):
        self._validate_table(table)
        data = {"ns": self._ns, **data}
        cols = ", ".join(f"`{k}`" for k in data)
        placeholders = ", ".join(["%s"] * len(data))
        self._execute(
            f"INSERT INTO `{self._db}`.`{table}` ({cols}) VALUES ({placeholders})",
            tuple(data.values()),
        )

    def update(self, table: str, data: dict, where: str, params: tuple = ()):
        self._validate_table(table)
        set_clause = ", ".join(f"`{k}` = %s" for k in data)
        self._execute(
            f"UPDATE `{self._db}`.`{table}` SET {set_clause} WHERE ns = %s AND ({where})",
            (*data.values(), self._ns, *params),
        )

    def delete(self, table: str, where: str = "1=1", params: tuple = ()):
        self._validate_table(table)
        self._execute(
            f"DELETE FROM `{self._db}`.`{table}` WHERE ns = %s AND ({where})",
            (self._ns, *params),
        )
```

### BaseDomainServer

```python
class BaseDomainServer(ABC):
    def __init__(self, domain_name: str):
        self._domain = domain_name

    def create_mcp(self, namespace: str, db_pool, known_tables: set[str]) -> FastMCP:
        conn = NamespacedConnection(db_pool, namespace, f"mock_{self._domain}", known_tables)
        mcp = FastMCP(f"{self._domain}-mock")
        services = self.create_services(conn)
        self.register_tools(mcp, services)
        return mcp

    @abstractmethod
    def schema_sql(self) -> str:
        """Return the DDL for this domain's tables (with ns column)."""

    @abstractmethod
    def create_services(self, conn: NamespacedConnection):
        """Instantiate service objects using the namespaced connection."""

    @abstractmethod
    def register_tools(self, mcp: FastMCP, services):
        """Register MCP tools on the FastMCP instance."""
```

### Domain implementation (3 files per domain)

```sql
-- domains/banking/schema.sql
CREATE TABLE IF NOT EXISTS accounts (
    ns          VARCHAR(64)   NOT NULL,
    id          VARCHAR(64)   NOT NULL,
    owner_name  VARCHAR(255),
    balance     DECIMAL(15,2) DEFAULT 0.00,
    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ns, id),
    INDEX idx_ns (ns)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

```python
# domains/banking/services.py
class AccountService:
    def __init__(self, db: NamespacedConnection):
        self._db = db

    def get(self, account_id: str) -> dict | None:
        rows = self._db.query("accounts", "id = %s", (account_id,))
        return rows[0] if rows else None

    def transfer(self, from_id: str, to_id: str, amount: float):
        sender = self.get(from_id)
        if sender is None or sender["balance"] < amount:
            raise ValueError("Insufficient balance")
        self._db.update("accounts", {"balance": sender["balance"] - amount}, "id = %s", (from_id,))
        receiver = self.get(to_id)
        self._db.update("accounts", {"balance": receiver["balance"] + amount}, "id = %s", (to_id,))
        self._db.insert("transactions", {
            "id": gen_id(), "from_acct": from_id, "to_acct": to_id, "amount": amount,
        })
```

```python
# domains/banking/tools.py
def register_banking_tools(mcp: FastMCP, services):
    @mcp.tool()
    async def get_account(account_id: str) -> dict:
        """Get account details by ID."""
        return services.account.get(account_id)

    @mcp.tool()
    async def transfer(from_id: str, to_id: str, amount: float) -> dict:
        """Transfer money between accounts."""
        services.account.transfer(from_id, to_id, amount)
        return {"status": "ok"}
```

## Project structure

```
terrarium-mock-servers/
├── pyproject.toml
├── Dockerfile                      # Single image, --role selects gateway/domain
├── docker-compose.yml              # Local dev (gateway + all domains + mysql)
│
├── framework/
│   ├── __init__.py
│   ├── base_server.py              # BaseDomainServer ABC
│   ├── namespaced_connection.py    # Multi-tenant DB wrapper
│   ├── namespace_manager.py        # Seed CRUD + trial clone/cleanup
│   ├── admin_api.py                # /admin/* HTTP endpoints
│   ├── gateway.py                  # MCP request routing (streaming reverse proxy)
│   ├── registry.py                 # Domain auto-discovery
│   └── db.py                       # MySQL connection pool (e.g., aiomysql)
│
├── domains/
│   ├── banking/
│   │   ├── schema.sql
│   │   ├── services.py
│   │   └── tools.py
│   ├── email/
│   │   ├── schema.sql
│   │   ├── services.py
│   │   └── tools.py
│   ├── ecommerce/
│   ├── calendar/
│   ├── ... (22 domains total)
│   └── __init__.py                 # Domain auto-registration
│
├── seeds/                          # Pre-built seed SQL files (optional)
│   ├── banking/
│   │   └── default.sql
│   └── email/
│       └── default.sql
│
└── k8s/
    ├── namespace.yaml
    ├── mysql.yaml                  # StatefulSet (or pointer to managed service)
    ├── gateway.yaml                # Deployment + Service
    ├── domains.yaml                # 22 x Deployment + Service (template-generated)
    └── ingress.yaml                # Single external entry point
```

## Migration from vibe-agent/servers

The 22 existing mock servers in `vibe-agent/servers/` share an identical architecture (SQLite + FastMCP + init.sql). Migration steps:

1. **Extract shared code** into `framework/` (connection management, error handling, ID generation, CLI parsing — currently duplicated 22 times)
2. **Convert SQLite to MySQL** per domain: mainly `?` -> `%s` placeholders, `AUTOINCREMENT` -> `AUTO_INCREMENT`, `sqlite3.Row` -> dict cursor
3. **Add `ns` column** to all table schemas, adjust PRIMARY KEY to include `ns`
4. **Reduce each domain** to 3 files: `schema.sql`, `services.py`, `tools.py` (remove duplicated boilerplate)
5. **Remove per-server Dockerfile** — single shared image
6. **Convert init.sql files**: Add `ns` column values (e.g., replace `INSERT INTO accounts (id, ...) VALUES (...)` with `INSERT INTO accounts (ns, id, ...) VALUES ('__NAMESPACE__', ...)`) — the framework substitutes `__NAMESPACE__` at seed creation time

## k8s deployment

### Minimal (dev/small scale)

```yaml
# docker-compose.yml
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: terrarium
    ports: ["3306:3306"]
    volumes:
      - mysql_data:/var/lib/mysql

  gateway:
    build: .
    command: ["terrarium-mock", "--role", "gateway", "--port", "9100"]
    environment:
      MYSQL_HOST: mysql
      MYSQL_USER: root
      MYSQL_PASSWORD: terrarium
    ports: ["9100:9100"]
    depends_on: [mysql]

  banking:
    build: .
    command: ["terrarium-mock", "--role", "domain", "--domain", "banking"]
    environment:
      MYSQL_HOST: mysql
      MYSQL_USER: root
      MYSQL_PASSWORD: terrarium
    depends_on: [mysql]

  email:
    build: .
    command: ["terrarium-mock", "--role", "domain", "--domain", "email"]
    environment:
      MYSQL_HOST: mysql
      MYSQL_USER: root
      MYSQL_PASSWORD: terrarium
    depends_on: [mysql]

  # ... remaining domains

volumes:
  mysql_data:
```

### Production (k8s)

- MySQL: StatefulSet with PVC, or managed service (RDS / Cloud SQL / PlanetScale)
- Gateway: Deployment x1, Service (ClusterIP), Ingress
- Domains: Deployment x1 each (22 total), Service (ClusterIP) each
- All Domain Pods stateless, no PVC needed
- Liveness/readiness probes on each Pod
- HorizontalPodAutoscaler per domain if needed
- MySQL credentials via Secret, mounted as env vars
