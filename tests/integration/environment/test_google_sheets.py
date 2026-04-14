"""Google Sheets integration tests — require OAuth credentials."""

import os
import pytest
from terrarium.environment.environment import ComposableEnvironment
from tests.conftest import skip_no_gsheets_creds


@skip_no_gsheets_creds
@pytest.mark.timeout(60)
class TestGoogleSheetsIntegration:
    """Integration tests against real Google Sheets API.

    Uses auto-created session folder for isolation — cleaned up on teardown.
    """

    @pytest.fixture(autouse=True)
    def setup_runtime(self):
        creds_file = os.environ.get(
            "GOOGLE_SHEETS_CREDENTIALS_FILE", "oauth_credentials.json"
        )
        with ComposableEnvironment(
            ["google_sheets"],
            config={"google_sheets": {"credentials_file": creds_file}},
        ) as env:
            self.env = env
            yield

    def test_create_and_list_spreadsheets(self):
        result = self.env.google_sheets.create_spreadsheet("Integration Test")
        assert result["id"]
        assert result["title"] == "Integration Test"

        sheets = self.env.google_sheets.list_spreadsheets()
        ids = [s["id"] for s in sheets]
        assert result["id"] in ids

    def test_update_spreadsheet(self):
        result = self.env.google_sheets.create_spreadsheet("Before Rename")
        self.env.google_sheets.update_spreadsheet(result["id"], "After Rename")

        sheets = self.env.google_sheets.list_spreadsheets()
        titles = [s["title"] for s in sheets]
        assert "After Rename" in titles

    def test_delete_spreadsheet(self):
        result = self.env.google_sheets.create_spreadsheet("To Delete")
        self.env.google_sheets.delete_spreadsheet(result["id"])

        sheets = self.env.google_sheets.list_spreadsheets()
        ids = [s["id"] for s in sheets]
        assert result["id"] not in ids

    def test_worksheet_crud(self):
        sh = self.env.google_sheets.create_spreadsheet("WS Test")
        sid = sh["id"]

        ws = self.env.google_sheets.add_worksheet(sid, "NewSheet", rows=50, cols=10)
        assert ws["title"] == "NewSheet"

        worksheets = self.env.google_sheets.list_worksheets(sid)
        titles = [w["title"] for w in worksheets]
        assert "NewSheet" in titles

        self.env.google_sheets.update_worksheet(sid, "NewSheet", new_title="Renamed")
        worksheets = self.env.google_sheets.list_worksheets(sid)
        titles = [w["title"] for w in worksheets]
        assert "Renamed" in titles

        self.env.google_sheets.delete_worksheet(sid, "Renamed")
        worksheets = self.env.google_sheets.list_worksheets(sid)
        titles = [w["title"] for w in worksheets]
        assert "Renamed" not in titles

    def test_write_and_read_range(self):
        sh = self.env.google_sheets.create_spreadsheet("RW Test")
        sid = sh["id"]

        worksheets = self.env.google_sheets.list_worksheets(sid)
        ws_title = worksheets[0]["title"]

        self.env.google_sheets.write_range(
            sid, f"{ws_title}!A1:B2", [["Name", "Score"], ["Alice", "95"]]
        )
        data = self.env.google_sheets.read_range(sid, f"{ws_title}!A1:B2")
        assert data == [["Name", "Score"], ["Alice", "95"]]

    def test_append_and_get_all_records(self):
        sh = self.env.google_sheets.create_spreadsheet("Append Test")
        sid = sh["id"]

        worksheets = self.env.google_sheets.list_worksheets(sid)
        ws_title = worksheets[0]["title"]

        self.env.google_sheets.write_range(sid, f"{ws_title}!A1:B1", [["Name", "Score"]])
        self.env.google_sheets.append_rows(sid, ws_title, [["Alice", "95"], ["Bob", "87"]])

        records = self.env.google_sheets.get_all_records(sid, ws_title)
        assert len(records) == 2
        assert records[0]["Name"] == "Alice"

    def test_clear_range(self):
        sh = self.env.google_sheets.create_spreadsheet("Clear Test")
        sid = sh["id"]

        worksheets = self.env.google_sheets.list_worksheets(sid)
        ws_title = worksheets[0]["title"]

        self.env.google_sheets.write_range(sid, f"{ws_title}!A1:B1", [["Hello", "World"]])
        self.env.google_sheets.clear_range(sid, f"{ws_title}!A1:B1")
        data = self.env.google_sheets.read_range(sid, f"{ws_title}!A1:B1")
        assert data == []

    def test_find(self):
        sh = self.env.google_sheets.create_spreadsheet("Find Test")
        sid = sh["id"]

        worksheets = self.env.google_sheets.list_worksheets(sid)
        ws_title = worksheets[0]["title"]

        self.env.google_sheets.write_range(
            sid, f"{ws_title}!A1:B3",
            [["Name", "City"], ["Alice", "NYC"], ["Bob", "NYC"]],
        )
        results = self.env.google_sheets.find(sid, ws_title, "NYC")
        assert len(results) == 2

    def test_connection_info(self):
        info = self.env.google_sheets.connection_info
        assert info["session_folder_id"] is not None
        assert info["session_folder_name"].startswith("_session_")
