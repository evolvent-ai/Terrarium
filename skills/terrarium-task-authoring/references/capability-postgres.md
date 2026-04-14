# PostgreSQL Capability API

Backed by PostgreSQL 16 in Docker. Connection uses autocommit mode.

## connection_info

```python
info = env.postgres.connection_info
# {
#     "host": "<sandbox_hostname>",
#     "port": 5432,
#     "dbname": "main",
#     "user": "postgres",
#     "password": "terrarium",
# }
```

## Methods

### query()

```python
env.postgres.query(sql: str, params=None) -> list[dict]
```

Execute a SELECT query.

**Parameters:**
- `sql` — SQL query string. Use `%s` placeholders for parameterized queries.
- `params` — optional list of parameter values to substitute into `%s` placeholders. Prevents SQL injection.

**Returns:** list of dicts, one per row. Keys are column names.

```python
rows = env.postgres.query("SELECT * FROM users WHERE age > %s", [18])
# [{"id": 1, "name": "Alice", "age": 25}, ...]

count = env.postgres.query("SELECT count(*) FROM users")[0]["count"]
```

### execute()

```python
env.postgres.execute(sql: str, params=None) -> None
```

Execute a non-SELECT statement (CREATE, INSERT, UPDATE, DELETE, etc.). Runs in autocommit mode — no explicit commit needed.

**Parameters:**
- `sql` — SQL statement. Use `%s` placeholders for parameterized queries.
- `params` — optional list of parameter values

```python
env.postgres.execute("""
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        age INT
    )
""")
env.postgres.execute("INSERT INTO users (name, age) VALUES (%s, %s)", ["Alice", 25])
```

### table_exists()

```python
env.postgres.table_exists(name: str, schema: str = "public") -> bool
```

Check if a table exists.

**Parameters:**
- `name` — table name
- `schema` — schema to check in (default: `"public"`)

**Returns:** `True` if the table exists, `False` otherwise.

```python
if env.postgres.table_exists("users"):
    rows = env.postgres.query("SELECT * FROM users")
```

### list_tables()

```python
env.postgres.list_tables(schema: str = "public") -> list[str]
```

List all table names in a schema.

**Parameters:**
- `schema` — schema to list (default: `"public"`)

**Returns:** sorted list of table name strings.

```python
tables = env.postgres.list_tables()
# ["orders", "products", "users"]
```

### create_database()

```python
env.postgres.create_database(name: str) -> None
```

Create a new database.

**Parameters:**
- `name` — database name. Must be a valid Python identifier (alphanumeric + underscore). This constraint exists to prevent SQL injection since database names cannot be parameterized.

```python
env.postgres.create_database("analytics")
```
