# Google Sheets Capability API

API-based (no sandbox). Uses gspread + Google Drive API with OAuth authentication. Requires a credentials file via `GOOGLE_SHEETS_CREDENTIALS_FILE` env var or `credentials_file` in config.

Each task session gets an isolated Google Drive folder under a root folder named "Terrarium". All spreadsheets are created within this session folder. The session folder is deleted on teardown.

## connection_info

```python
info = env.google_sheets.connection_info
# {
#     "session_folder_id": "abc123...",
#     "session_folder_name": "_session_a1b2c3d4",
#     "secrets": {"file": {"google_credentials": "/path/to/credentials.json"}},
# }
```

The `secrets` field is handled automatically — the credentials file is uploaded to the workspace container.

## Spreadsheet Methods

### create_spreadsheet()

```python
env.google_sheets.create_spreadsheet(title: str) -> dict
```

Create a spreadsheet in the session folder.

**Parameters:**
- `title` — spreadsheet title

**Returns:** `{"id": str, "title": str, "url": str}`. Use `id` for all subsequent operations.

```python
sheet = env.google_sheets.create_spreadsheet("Sales Report")
sheet_id = sheet["id"]
```

### list_spreadsheets()

```python
env.google_sheets.list_spreadsheets() -> list[dict]
```

List all spreadsheets in the session folder.

**Returns:** list of dicts, each with `{"id": str, "title": str, "url": str}`.

### update_spreadsheet()

```python
env.google_sheets.update_spreadsheet(spreadsheet_id: str, title: str) -> None
```

Update a spreadsheet's title.

**Parameters:**
- `spreadsheet_id` — the spreadsheet ID
- `title` — new title

### delete_spreadsheet()

```python
env.google_sheets.delete_spreadsheet(spreadsheet_id: str) -> None
```

Delete a spreadsheet.

**Parameters:**
- `spreadsheet_id` — the spreadsheet ID to delete

## Worksheet Methods

Each spreadsheet contains one or more worksheets (tabs).

### add_worksheet()

```python
env.google_sheets.add_worksheet(
    spreadsheet_id: str,
    title: str,
    rows: int = 1000,
    cols: int = 26,
) -> dict
```

Add a worksheet to a spreadsheet.

**Parameters:**
- `spreadsheet_id` — the spreadsheet to add the worksheet to
- `title` — worksheet tab name
- `rows` — initial row count (default: 1000)
- `cols` — initial column count (default: 26)

**Returns:** `{"title": str, "id": int, "rows": int, "cols": int}`.

### list_worksheets()

```python
env.google_sheets.list_worksheets(spreadsheet_id: str) -> list[dict]
```

List all worksheets in a spreadsheet.

**Parameters:**
- `spreadsheet_id` — the spreadsheet to list worksheets from

**Returns:** list of dicts, each with `{"title": str, "id": int, "rows": int, "cols": int}`.

### update_worksheet()

```python
env.google_sheets.update_worksheet(
    spreadsheet_id: str,
    worksheet_title: str,
    new_title: str | None = None,
    rows: int | None = None,
    cols: int | None = None,
) -> None
```

Update a worksheet's title and/or dimensions.

**Parameters:**
- `spreadsheet_id` — the spreadsheet containing the worksheet
- `worksheet_title` — current title of the worksheet to update
- `new_title` — optional new title
- `rows` — optional new row count (resizes the sheet)
- `cols` — optional new column count

### delete_worksheet()

```python
env.google_sheets.delete_worksheet(spreadsheet_id: str, worksheet_title: str) -> None
```

Delete a worksheet from a spreadsheet.

**Parameters:**
- `spreadsheet_id` — the spreadsheet containing the worksheet
- `worksheet_title` — title of the worksheet to delete

## Data Read/Write

### read_range()

```python
env.google_sheets.read_range(spreadsheet_id: str, range: str) -> list[list]
```

Read a range of cells.

**Parameters:**
- `spreadsheet_id` — the spreadsheet to read from
- `range` — A1 notation range, e.g. `"Sheet1!A1:B3"` or `"A1:B3"` (defaults to first sheet)

**Returns:** 2D list of cell values (strings). Empty cells may be omitted from trailing positions.

```python
data = env.google_sheets.read_range(sheet_id, "Sheet1!A1:C3")
# [["Name", "Age", "City"], ["Alice", "25", "NYC"], ["Bob", "30", "LA"]]
```

### write_range()

```python
env.google_sheets.write_range(spreadsheet_id: str, range: str, values: list[list]) -> None
```

Write values to a range. Uses `USER_ENTERED` value input option (formulas and number formats are parsed).

**Parameters:**
- `spreadsheet_id` — the spreadsheet to write to
- `range` — A1 notation range
- `values` — 2D list of values to write

```python
env.google_sheets.write_range(sheet_id, "Sheet1!A1:C2", [
    ["Name", "Age", "City"],
    ["Alice", "25", "NYC"],
])
```

### append_rows()

```python
env.google_sheets.append_rows(spreadsheet_id: str, worksheet_title: str, rows: list[list]) -> None
```

Append rows to the end of a worksheet.

**Parameters:**
- `spreadsheet_id` — the spreadsheet
- `worksheet_title` — the worksheet tab name
- `rows` — 2D list of row values to append

```python
env.google_sheets.append_rows(sheet_id, "Sheet1", [
    ["Charlie", "28", "Chicago"],
    ["Diana", "35", "Boston"],
])
```

### insert_rows()

```python
env.google_sheets.insert_rows(
    spreadsheet_id: str,
    worksheet_title: str,
    rows: list[list],
    index: int = 1,
) -> None
```

Insert rows at a specific position.

**Parameters:**
- `spreadsheet_id` — the spreadsheet
- `worksheet_title` — the worksheet tab name
- `rows` — 2D list of row values to insert
- `index` — 1-based row position to insert at (default: 1, top of sheet)

### delete_rows()

```python
env.google_sheets.delete_rows(spreadsheet_id: str, worksheet_title: str, start: int, end: int) -> None
```

Delete a range of rows.

**Parameters:**
- `spreadsheet_id` — the spreadsheet
- `worksheet_title` — the worksheet tab name
- `start` — first row to delete (1-based, inclusive)
- `end` — last row to delete (1-based, inclusive)

### clear_range()

```python
env.google_sheets.clear_range(spreadsheet_id: str, range: str) -> None
```

Clear cell values in a range. Formatting is preserved.

**Parameters:**
- `spreadsheet_id` — the spreadsheet
- `range` — A1 notation range to clear

### get_all_records()

```python
env.google_sheets.get_all_records(spreadsheet_id: str, worksheet_title: str) -> list[dict]
```

Read all rows as dicts, using the first row as column headers.

**Parameters:**
- `spreadsheet_id` — the spreadsheet
- `worksheet_title` — the worksheet tab name

**Returns:** list of dicts, one per data row. Keys are the header values from row 1.

```python
records = env.google_sheets.get_all_records(sheet_id, "Sheet1")
# [{"Name": "Alice", "Age": "25", "City": "NYC"}, ...]
```

### find()

```python
env.google_sheets.find(spreadsheet_id: str, worksheet_title: str, query: str) -> list[dict]
```

Find all cells matching a query string.

**Parameters:**
- `spreadsheet_id` — the spreadsheet
- `worksheet_title` — the worksheet tab name
- `query` — string to search for (exact match)

**Returns:** list of matching cells, each with `{"row": int, "col": int, "value": str}`. Row and col are 1-based.

```python
matches = env.google_sheets.find(sheet_id, "Sheet1", "Alice")
# [{"row": 2, "col": 1, "value": "Alice"}]
```
