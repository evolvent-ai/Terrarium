import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from terrarium.environment.capabilities.google_sheets import GoogleSheetsCapability
from terrarium.environment.exceptions import CapabilityError


class TestGoogleSheetsCapabilityUnit:
    def _make_cap(self):
        """Create a capability with mock gspread client and drive service."""
        cap = GoogleSheetsCapability(config={
            "credentials_file": "/fake/creds.json",
        })
        cap._gc = MagicMock()
        cap._drive = MagicMock()
        cap._session_folder_id = "session-folder-id"
        cap._session_folder_name = "_session_test"
        return cap

    # -------------------------------------------------------------------
    # sandbox_spec
    # -------------------------------------------------------------------

    def test_sandbox_spec_returns_none(self):
        assert GoogleSheetsCapability.sandbox_spec() is None

    # -------------------------------------------------------------------
    # init + config
    # -------------------------------------------------------------------

    def test_init_credentials_from_config(self):
        cap = GoogleSheetsCapability(config={"credentials_file": "/my/creds.json"})
        assert cap._credentials_file == "/my/creds.json"

    @patch.dict("os.environ", {"GOOGLE_SHEETS_CREDENTIALS_FILE": "/env/creds.json"})
    def test_init_credentials_from_env(self):
        cap = GoogleSheetsCapability()
        assert cap._credentials_file == "/env/creds.json"

    def test_init_no_sandbox(self):
        cap = GoogleSheetsCapability(config={"credentials_file": "x"})
        assert cap._sandbox is None
        assert cap.fs is None
        assert cap.shell is None

    def test_init_default_root_folder(self):
        cap = GoogleSheetsCapability(config={"credentials_file": "x"})
        assert cap._root_folder_name == "Terrarium"

    def test_init_custom_root_folder(self):
        cap = GoogleSheetsCapability(config={
            "credentials_file": "x",
            "root_folder_name": "My Folder",
        })
        assert cap._root_folder_name == "My Folder"

    # -------------------------------------------------------------------
    # wait_ready
    # -------------------------------------------------------------------

    def test_wait_ready_no_credentials(self):
        cap = GoogleSheetsCapability()
        cap._credentials_file = None
        with pytest.raises(CapabilityError, match="credentials not found"):
            cap.wait_ready()

    @patch("terrarium.environment.capabilities.google_sheets.build")
    @patch("terrarium.environment.capabilities.google_sheets.gspread.oauth")
    def test_wait_ready_success(self, mock_oauth, mock_build):
        mock_gc = MagicMock()
        mock_oauth.return_value = mock_gc
        mock_drive = MagicMock()
        mock_build.return_value = mock_drive
        mock_drive.files().list().execute.return_value = {
            "files": [{"id": "root-id", "name": "Terrarium"}]
        }
        mock_drive.files().create().execute.return_value = {"id": "session-id"}

        cap = GoogleSheetsCapability(config={"credentials_file": "/fake/creds.json"})
        cap.wait_ready()
        assert cap._gc is not None
        assert cap._session_folder_id == "session-id"

    @patch("terrarium.environment.capabilities.google_sheets.build")
    @patch("terrarium.environment.capabilities.google_sheets.gspread.oauth")
    def test_wait_ready_root_folder_not_found(self, mock_oauth, mock_build):
        mock_gc = MagicMock()
        mock_oauth.return_value = mock_gc
        mock_drive = MagicMock()
        mock_build.return_value = mock_drive
        mock_drive.files().list().execute.return_value = {"files": []}

        cap = GoogleSheetsCapability(config={"credentials_file": "/fake/creds.json"})
        with pytest.raises(CapabilityError, match="not found"):
            cap.wait_ready()

    # -------------------------------------------------------------------
    # connection_info
    # -------------------------------------------------------------------

    def test_connection_info(self):
        cap = self._make_cap()
        info = cap.connection_info
        assert info["session_folder_id"] == "session-folder-id"
        assert info["session_folder_name"] == "_session_test"

    # -------------------------------------------------------------------
    # teardown
    # -------------------------------------------------------------------

    def test_teardown_deletes_session_folder(self):
        cap = self._make_cap()
        cap.teardown()
        cap._drive.files().delete.assert_called()

    def test_teardown_no_session(self):
        cap = GoogleSheetsCapability(config={"credentials_file": "x"})
        cap.teardown()  # should not raise

    # -------------------------------------------------------------------
    # Spreadsheet CRUD
    # -------------------------------------------------------------------

    def test_create_spreadsheet(self):
        cap = self._make_cap()
        mock_sh = MagicMock()
        mock_sh.id = "sh-id"
        mock_sh.title = "Test"
        mock_sh.url = "https://..."
        cap._gc.create.return_value = mock_sh

        result = cap.create_spreadsheet("Test")
        assert result["id"] == "sh-id"
        assert result["title"] == "Test"
        cap._gc.create.assert_called_once_with("Test", folder_id="session-folder-id")

    def test_create_spreadsheet_error(self):
        cap = self._make_cap()
        cap._gc.create.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to create"):
            cap.create_spreadsheet("Test")

    def test_update_spreadsheet(self):
        cap = self._make_cap()
        mock_sh = MagicMock()
        cap._gc.open_by_key.return_value = mock_sh
        cap.update_spreadsheet("sh-id", "New Title")
        mock_sh.update_title.assert_called_once_with("New Title")

    def test_update_spreadsheet_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to update"):
            cap.update_spreadsheet("sh-id", "x")

    def test_delete_spreadsheet(self):
        cap = self._make_cap()
        cap.delete_spreadsheet("sh-id")
        cap._gc.del_spreadsheet.assert_called_once_with("sh-id")

    def test_delete_spreadsheet_error(self):
        cap = self._make_cap()
        cap._gc.del_spreadsheet.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to delete"):
            cap.delete_spreadsheet("sh-id")

    def test_list_spreadsheets(self):
        cap = self._make_cap()
        cap._drive.files().list().execute.return_value = {
            "files": [
                {"id": "s1", "name": "Sheet 1", "webViewLink": "https://1"},
                {"id": "s2", "name": "Sheet 2", "webViewLink": "https://2"},
            ]
        }
        result = cap.list_spreadsheets()
        assert len(result) == 2
        assert result[0]["id"] == "s1"

    def test_list_spreadsheets_empty(self):
        cap = self._make_cap()
        cap._drive.files().list().execute.return_value = {"files": []}
        assert cap.list_spreadsheets() == []

    # -------------------------------------------------------------------
    # Worksheet CRUD
    # -------------------------------------------------------------------

    def test_add_worksheet(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        mock_ws.title = "New"
        mock_ws.id = 123
        mock_ws.row_count = 1000
        mock_ws.col_count = 26
        cap._gc.open_by_key.return_value.add_worksheet.return_value = mock_ws

        result = cap.add_worksheet("sh-id", "New")
        assert result["title"] == "New"

    def test_add_worksheet_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.return_value.add_worksheet.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to add"):
            cap.add_worksheet("sh-id", "New")

    def test_list_worksheets(self):
        cap = self._make_cap()
        mock_ws1 = MagicMock(title="Sheet1", id=0, row_count=100, col_count=10)
        mock_ws2 = MagicMock(title="Sheet2", id=1, row_count=50, col_count=5)
        cap._gc.open_by_key.return_value.worksheets.return_value = [mock_ws1, mock_ws2]

        result = cap.list_worksheets("sh-id")
        assert len(result) == 2
        assert result[0]["title"] == "Sheet1"

    def test_update_worksheet_title(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        cap.update_worksheet("sh-id", "Old", new_title="New")
        mock_ws.update_title.assert_called_once_with("New")

    def test_update_worksheet_resize(self):
        cap = self._make_cap()
        mock_ws = MagicMock(row_count=100, col_count=10)
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        cap.update_worksheet("sh-id", "Sheet1", rows=200)
        mock_ws.resize.assert_called_once_with(rows=200, cols=10)

    def test_update_worksheet_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to update"):
            cap.update_worksheet("sh-id", "Sheet1", new_title="x")

    def test_delete_worksheet(self):
        cap = self._make_cap()
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        cap._gc.open_by_key.return_value = mock_sh
        cap.delete_worksheet("sh-id", "Sheet1")
        mock_sh.del_worksheet.assert_called_once_with(mock_ws)

    def test_delete_worksheet_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to delete"):
            cap.delete_worksheet("sh-id", "Sheet1")

    # -------------------------------------------------------------------
    # Data read/write
    # -------------------------------------------------------------------

    def test_read_range(self):
        cap = self._make_cap()
        cap._gc.open_by_key.return_value.values_get.return_value = {
            "values": [["A", "B"], ["1", "2"]]
        }
        result = cap.read_range("sh-id", "Sheet1!A1:B2")
        assert result == [["A", "B"], ["1", "2"]]

    def test_read_range_empty(self):
        cap = self._make_cap()
        cap._gc.open_by_key.return_value.values_get.return_value = {}
        assert cap.read_range("sh-id", "Sheet1!A1:B2") == []

    def test_read_range_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to read"):
            cap.read_range("sh-id", "A1")

    def test_write_range(self):
        cap = self._make_cap()
        cap.write_range("sh-id", "Sheet1!A1:B2", [["A", "B"], ["1", "2"]])
        cap._gc.open_by_key.return_value.values_update.assert_called_once()

    def test_write_range_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to write"):
            cap.write_range("sh-id", "A1", [[1]])

    def test_append_rows(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        cap.append_rows("sh-id", "Sheet1", [["a", "b"]])
        mock_ws.append_rows.assert_called_once_with([["a", "b"]])

    def test_append_rows_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to append"):
            cap.append_rows("sh-id", "Sheet1", [[1]])

    def test_insert_rows(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        cap.insert_rows("sh-id", "Sheet1", [["a"]], index=2)
        mock_ws.insert_rows.assert_called_once_with([["a"]], row=2)

    def test_insert_rows_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to insert"):
            cap.insert_rows("sh-id", "Sheet1", [[1]])

    def test_delete_rows(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        cap.delete_rows("sh-id", "Sheet1", 2, 4)
        mock_ws.delete_rows.assert_called_once_with(2, 4)

    def test_delete_rows_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to delete"):
            cap.delete_rows("sh-id", "Sheet1", 1, 2)

    def test_clear_range(self):
        cap = self._make_cap()
        cap.clear_range("sh-id", "Sheet1!A1:B2")
        cap._gc.open_by_key.return_value.values_clear.assert_called_once_with("Sheet1!A1:B2")

    def test_clear_range_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to clear"):
            cap.clear_range("sh-id", "A1")

    def test_get_all_records(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = [{"Name": "Alice", "Score": 95}]
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        result = cap.get_all_records("sh-id", "Sheet1")
        assert result == [{"Name": "Alice", "Score": 95}]

    def test_get_all_records_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to get"):
            cap.get_all_records("sh-id", "Sheet1")

    def test_find(self):
        cap = self._make_cap()
        mock_cell1 = MagicMock(row=1, col=2, value="Alice")
        mock_cell2 = MagicMock(row=3, col=2, value="Alice")
        mock_ws = MagicMock()
        mock_ws.findall.return_value = [mock_cell1, mock_cell2]
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        result = cap.find("sh-id", "Sheet1", "Alice")
        assert len(result) == 2
        assert result[0] == {"row": 1, "col": 2, "value": "Alice"}

    def test_find_empty(self):
        cap = self._make_cap()
        mock_ws = MagicMock()
        mock_ws.findall.return_value = []
        cap._gc.open_by_key.return_value.worksheet.return_value = mock_ws
        assert cap.find("sh-id", "Sheet1", "nothing") == []

    def test_find_error(self):
        cap = self._make_cap()
        cap._gc.open_by_key.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to find"):
            cap.find("sh-id", "Sheet1", "x")

    # -------------------------------------------------------------------
    # _get_gc
    # -------------------------------------------------------------------

    def test_get_gc_not_connected(self):
        cap = GoogleSheetsCapability(config={"credentials_file": "x"})
        with pytest.raises(CapabilityError, match="not connected"):
            cap._get_gc()
