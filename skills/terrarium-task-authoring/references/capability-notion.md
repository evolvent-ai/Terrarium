# Notion Capability API

API-based (no sandbox). Uses the official Notion Integration API. Requires a `NOTION_TOKEN` environment variable or `auth_token` in config.

Each task session gets an isolated page under a root page named "Terrarium" in the Notion workspace. All pages/databases created without an explicit `parent_id` are nested under this session page. The session page is archived on teardown.

## connection_info

```python
info = env.notion.connection_info
# {
#     "api_url": "https://api.notion.com",
#     "bot_name": "Terrarium Integration",
#     "session_page_id": "abc123...",
#     "secrets": {"env": {"NOTION_TOKEN": "..."}},
# }
```

The `secrets` field is handled automatically — the token is injected into the workspace container.

## Search

### search()

```python
env.notion.search(query: str, filter_type: str | None = None) -> list[dict]
```

Search pages and databases in the Notion workspace.

**Parameters:**
- `query` — search query string
- `filter_type` — optional filter: `"page"` or `"database"`. If omitted, returns both.

**Returns:** list of Notion page/database objects (raw API response).

## Page Methods

### create_page()

```python
env.notion.create_page(
    title: str,
    parent_id: str | None = None,
    properties: dict | None = None,
    children: list[dict] | None = None,
) -> dict
```

Create a new page.

**Parameters:**
- `title` — page title
- `parent_id` — ID of the parent page. Defaults to the session page if omitted.
- `properties` — optional additional Notion page properties (beyond title)
- `children` — optional list of block objects to include as initial page content

**Returns:** full Notion page object. Use `page["id"]` for subsequent operations.

```python
page = env.notion.create_page(title="Study Notes")
page_id = page["id"]
```

### get_page()

```python
env.notion.get_page(page_id: str) -> dict
```

Retrieve a page.

**Parameters:**
- `page_id` — the page ID (from `create_page()` or `search()`)

**Returns:** full Notion page object.

### update_page()

```python
env.notion.update_page(page_id: str, properties: dict) -> dict
```

Update page properties (e.g., title, custom properties).

**Parameters:**
- `page_id` — the page ID to update
- `properties` — dict of properties to update (Notion property format)

**Returns:** updated Notion page object.

### delete_page()

```python
env.notion.delete_page(page_id: str) -> None
```

Archive (soft-delete) a page.

**Parameters:**
- `page_id` — the page ID to archive

## Block Methods

Blocks are the content within a page — paragraphs, headings, lists, code blocks, etc.

### append_blocks()

```python
env.notion.append_blocks(block_id: str, children: list[dict]) -> list[dict]
```

Append child blocks to a page or block.

**Parameters:**
- `block_id` — the page ID or parent block ID to append to
- `children` — list of Notion block objects

**Returns:** list of created block objects.

```python
env.notion.append_blocks(page_id, [
    {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "Hello world"}}]
        }
    },
    {
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "Section Title"}}]
        }
    },
])
```

### list_blocks()

```python
env.notion.list_blocks(block_id: str) -> list[dict]
```

List all child blocks of a page or block. Auto-paginates to return all results.

**Parameters:**
- `block_id` — the page ID or parent block ID to list children of

**Returns:** list of Notion block objects. Useful for reading page content:

```python
blocks = env.notion.list_blocks(page_id)
for block in blocks:
    block_type = block.get("type", "")
    rich_texts = block.get(block_type, {}).get("rich_text", [])
    text = "".join(rt.get("plain_text", "") for rt in rich_texts)
```

### get_block()

```python
env.notion.get_block(block_id: str) -> dict
```

Retrieve a single block.

**Parameters:**
- `block_id` — the block ID

**Returns:** Notion block object.

### update_block()

```python
env.notion.update_block(block_id: str, **content) -> dict
```

Update a block's content.

**Parameters:**
- `block_id` — the block ID to update
- `**content` — keyword arguments matching the block's type structure (e.g., `paragraph={"rich_text": [...]}`)

**Returns:** updated Notion block object.

### delete_block()

```python
env.notion.delete_block(block_id: str) -> None
```

Delete a block.

**Parameters:**
- `block_id` — the block ID to delete

## Database Methods

### create_database()

```python
env.notion.create_database(
    title: str,
    properties: dict,
    parent_id: str | None = None,
) -> dict
```

Create a database (structured table).

**Parameters:**
- `title` — database title
- `properties` — property schema defining the columns (Notion property definition format)
- `parent_id` — ID of the parent page. Defaults to the session page if omitted.

**Returns:** full Notion database object. Use `db["id"]` for subsequent operations.

### get_database()

```python
env.notion.get_database(database_id: str) -> dict
```

Retrieve a database.

**Parameters:**
- `database_id` — the database ID

**Returns:** full Notion database object.

### update_database()

```python
env.notion.update_database(
    database_id: str,
    title: str | None = None,
    properties: dict | None = None,
) -> dict
```

Update a database's title and/or property schema.

**Parameters:**
- `database_id` — the database ID to update
- `title` — optional new title
- `properties` — optional property schema updates

**Returns:** updated database or data source object.

### delete_database()

```python
env.notion.delete_database(database_id: str) -> None
```

Trash a database.

**Parameters:**
- `database_id` — the database ID to delete

### add_database_record()

```python
env.notion.add_database_record(database_id: str, properties: dict) -> dict
```

Add a record (row) to a database.

**Parameters:**
- `database_id` — the database ID to add the record to
- `properties` — property values for the new record (must match the database schema)

**Returns:** the created page object (each database record is a Notion page).

### query_database()

```python
env.notion.query_database(
    database_id: str,
    filter: dict | None = None,
    sorts: list[dict] | None = None,
) -> list[dict]
```

Query a database with optional filtering and sorting. Auto-paginates to return all results.

**Parameters:**
- `database_id` — the database ID to query
- `filter` — optional Notion filter object (see Notion API docs for filter syntax)
- `sorts` — optional list of sort objects, e.g. `[{"property": "Name", "direction": "ascending"}]`

**Returns:** list of page objects (database records).
