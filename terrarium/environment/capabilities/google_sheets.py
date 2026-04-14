"""Google Sheets capability — API-based, no sandbox required."""

from __future__ import annotations

import os
import uuid

import gspread
from googleapiclient.discovery import build
from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.logging import log_capability_call

DEFAULT_ROOT_FOLDER_NAME = "Terrarium"


class GoogleSheetsCapability(BaseCapability):
    """Google Sheets capability via gspread + Drive API.

    API-based capability — no sandbox needed. Uses OAuth for authentication
    and Drive folders for session isolation.

    Config options:
        credentials_file:    OAuth credentials JSON path (falls back to GOOGLE_SHEETS_CREDENTIALS_FILE env)
        authorized_user_file: Token cache path (default: "authorized_user.json")
        root_folder_name:    Drive folder name for isolation (default: "Terrarium")
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self._credentials_file = (
            self._config.get("credentials_file")
            or os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE")
        )
        self._authorized_user_file = self._config.get("authorized_user_file", "authorized_user.json")
        self._root_folder_name = self._config.get("root_folder_name", DEFAULT_ROOT_FOLDER_NAME)
        self._gc: gspread.Client | None = None
        self._drive = None
        self._session_folder_id: str | None = None
        self._session_folder_name: str = ""

    def wait_ready(self) -> None:
        """Authenticate, find root folder, create session folder."""
        if not self._credentials_file:
            raise CapabilityError(
                "Google Sheets credentials not found. "
                "Set config['credentials_file'] or GOOGLE_SHEETS_CREDENTIALS_FILE env var."
            )
        try:
            self._gc = gspread.oauth(
                credentials_filename=self._credentials_file,
                authorized_user_filename=self._authorized_user_file,
            )
            self._drive = build("drive", "v3", credentials=self._gc.http_client.auth)
        except Exception as e:
            raise CapabilityError(f"Google Sheets auth failed: {e}") from e

        root_folder_id = self._find_root_folder()
        self._session_folder_name = f"_session_{uuid.uuid4().hex[:8]}"
        try:
            folder = self._drive.files().create(body={
                "name": self._session_folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [root_folder_id],
            }).execute()
            self._session_folder_id = folder["id"]
            logger.info("Google Sheets session folder created: {} ({})",
                        self._session_folder_name, self._session_folder_id)
        except Exception as e:
            raise CapabilityError(f"Failed to create session folder: {e}") from e

        logger.info("Google Sheets capability ready")

    def teardown(self) -> None:
        """Delete the session folder and all its contents."""
        if self._session_folder_id and self._drive:
            try:
                self._drive.files().delete(fileId=self._session_folder_id).execute()
                logger.info("Google Sheets session folder deleted: {}", self._session_folder_id)
            except Exception as e:
                logger.warning("Failed to delete session folder: {}", e)

    @property
    def connection_info(self) -> dict:
        """Session info."""
        return {
            "session_folder_id": self._session_folder_id,
            "session_folder_name": self._session_folder_name,
            "secrets": {
                "file": {"google_credentials": self._credentials_file},
            },
        }

    def _find_root_folder(self) -> str:
        """Find the root Drive folder by name."""
        try:
            results = self._drive.files().list(
                q=f"mimeType='application/vnd.google-apps.folder' "
                  f"and name='{self._root_folder_name}' and trashed=false",
                fields="files(id,name)",
            ).execute()
            files = results.get("files", [])
            if files:
                return files[0]["id"]
        except Exception as e:
            raise CapabilityError(f"Failed to search for root folder: {e}") from e

        raise CapabilityError(
            f"Root folder '{self._root_folder_name}' not found in Google Drive. "
            f"Create a folder named '{self._root_folder_name}' in your Drive."
        )

    def _get_gc(self) -> gspread.Client:
        if self._gc is None:
            raise CapabilityError("Google Sheets not connected")
        return self._gc

    # -------------------------------------------------------------------
    # Spreadsheet CRUD
    # -------------------------------------------------------------------

    @log_capability_call
    def create_spreadsheet(self, title: str) -> dict:
        """Create a spreadsheet in the session folder."""
        try:
            gc = self._get_gc()
            sh = gc.create(title, folder_id=self._session_folder_id)
            return {"id": sh.id, "title": sh.title, "url": sh.url}
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to create spreadsheet: {e}") from e

    @log_capability_call
    def update_spreadsheet(self, spreadsheet_id: str, title: str) -> None:
        """Update a spreadsheet's title."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            sh.update_title(title)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to update spreadsheet: {e}") from e

    @log_capability_call
    def delete_spreadsheet(self, spreadsheet_id: str) -> None:
        """Delete a spreadsheet."""
        try:
            self._get_gc().del_spreadsheet(spreadsheet_id)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete spreadsheet: {e}") from e

    @log_capability_call
    def list_spreadsheets(self) -> list[dict]:
        """List spreadsheets in the session folder."""
        try:
            results = self._drive.files().list(
                q=f"'{self._session_folder_id}' in parents "
                  f"and mimeType='application/vnd.google-apps.spreadsheet' "
                  f"and trashed=false",
                fields="files(id,name,webViewLink)",
            ).execute()
            return [
                {"id": f["id"], "title": f["name"], "url": f.get("webViewLink", "")}
                for f in results.get("files", [])
            ]
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to list spreadsheets: {e}") from e

    # -------------------------------------------------------------------
    # Worksheet CRUD
    # -------------------------------------------------------------------

    @log_capability_call
    def add_worksheet(self, spreadsheet_id: str, title: str,
                      rows: int = 1000, cols: int = 26) -> dict:
        """Add a worksheet to a spreadsheet."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.add_worksheet(title=title, rows=rows, cols=cols)
            return {"title": ws.title, "id": ws.id, "rows": ws.row_count, "cols": ws.col_count}
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to add worksheet: {e}") from e

    @log_capability_call
    def list_worksheets(self, spreadsheet_id: str) -> list[dict]:
        """List worksheets in a spreadsheet."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            return [
                {"title": ws.title, "id": ws.id, "rows": ws.row_count, "cols": ws.col_count}
                for ws in sh.worksheets()
            ]
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to list worksheets: {e}") from e

    @log_capability_call
    def update_worksheet(self, spreadsheet_id: str, worksheet_title: str,
                         new_title: str | None = None,
                         rows: int | None = None,
                         cols: int | None = None) -> None:
        """Update a worksheet's title and/or size."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            if new_title is not None:
                ws.update_title(new_title)
            if rows is not None or cols is not None:
                ws.resize(rows=rows or ws.row_count, cols=cols or ws.col_count)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to update worksheet: {e}") from e

    @log_capability_call
    def delete_worksheet(self, spreadsheet_id: str, worksheet_title: str) -> None:
        """Delete a worksheet from a spreadsheet."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            sh.del_worksheet(ws)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete worksheet: {e}") from e

    # -------------------------------------------------------------------
    # Data read/write
    # -------------------------------------------------------------------

    @log_capability_call
    def read_range(self, spreadsheet_id: str, range: str) -> list[list]:
        """Read a range of cells. Range format: 'Sheet1!A1:B3' or 'A1:B3'."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            return sh.values_get(range).get("values", [])
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to read range: {e}") from e

    @log_capability_call
    def write_range(self, spreadsheet_id: str, range: str, values: list[list]) -> None:
        """Write values to a range. Range format: 'Sheet1!A1:B3' or 'A1:B3'."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            sh.values_update(range, params={"valueInputOption": "USER_ENTERED"},
                             body={"values": values})
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to write range: {e}") from e

    @log_capability_call
    def append_rows(self, spreadsheet_id: str, worksheet_title: str,
                    rows: list[list]) -> None:
        """Append rows to the end of a worksheet."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            ws.append_rows(rows)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to append rows: {e}") from e

    @log_capability_call
    def insert_rows(self, spreadsheet_id: str, worksheet_title: str,
                    rows: list[list], index: int = 1) -> None:
        """Insert rows at a specific position (1-based index)."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            ws.insert_rows(rows, row=index)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to insert rows: {e}") from e

    @log_capability_call
    def delete_rows(self, spreadsheet_id: str, worksheet_title: str,
                    start: int, end: int) -> None:
        """Delete rows (1-based, inclusive)."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            ws.delete_rows(start, end)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete rows: {e}") from e

    @log_capability_call
    def clear_range(self, spreadsheet_id: str, range: str) -> None:
        """Clear a range of cells (keep formatting, remove values)."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            sh.values_clear(range)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to clear range: {e}") from e

    @log_capability_call
    def get_all_records(self, spreadsheet_id: str, worksheet_title: str) -> list[dict]:
        """Read all rows as dicts (first row as header)."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            return ws.get_all_records()
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to get records: {e}") from e

    @log_capability_call
    def find(self, spreadsheet_id: str, worksheet_title: str,
             query: str) -> list[dict]:
        """Find cells matching a query string."""
        try:
            gc = self._get_gc()
            sh = gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_title)
            cells = ws.findall(query)
            return [{"row": c.row, "col": c.col, "value": c.value} for c in cells]
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to find: {e}") from e
