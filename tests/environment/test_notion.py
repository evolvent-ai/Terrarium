import pytest
from unittest.mock import MagicMock, patch
from terrarium.environment.capabilities.notion import NotionCapability
from terrarium.environment.exceptions import CapabilityError


class TestNotionCapabilityUnit:
    def _make_cap(self):
        """Create a capability with a mock client and session page already set."""
        cap = NotionCapability(config={"auth_token": "fake-token"})
        cap._client = MagicMock()
        cap._session_page_id = "session-page-id"
        return cap, cap._client

    # -------------------------------------------------------------------
    # sandbox_spec
    # -------------------------------------------------------------------

    def test_sandbox_spec_returns_none(self):
        assert NotionCapability.sandbox_spec() is None

    # -------------------------------------------------------------------
    # init + config
    # -------------------------------------------------------------------

    def test_init_token_from_config(self):
        cap = NotionCapability(config={"auth_token": "my-token"})
        assert cap._token == "my-token"

    @patch.dict("os.environ", {"NOTION_TOKEN": "env-token"})
    def test_init_token_from_env(self):
        cap = NotionCapability()
        assert cap._token == "env-token"

    def test_init_config_overrides_env(self):
        with patch.dict("os.environ", {"NOTION_TOKEN": "env-token"}):
            cap = NotionCapability(config={"auth_token": "config-token"})
            assert cap._token == "config-token"

    def test_init_no_sandbox(self):
        cap = NotionCapability(config={"auth_token": "t"})
        assert cap._sandbox is None
        assert cap.fs is None
        assert cap.shell is None

    def test_init_custom_timeout(self):
        cap = NotionCapability(config={"auth_token": "t", "timeout_ms": 30000})
        assert cap._timeout_ms == 30000

    # -------------------------------------------------------------------
    # wait_ready
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.notion.notion_client.Client")
    def test_wait_ready_success(self, mock_client_class):
        mock_client = MagicMock()
        mock_client.users.me.return_value = {"name": "Test Bot"}
        mock_client.search.return_value = {"results": [{
            "id": "root-page-found-id",
            "properties": {"title": {"title": [{"plain_text": "Terrarium"}]}},
        }]}
        mock_client.pages.create.return_value = {"id": "auto-session-id"}
        mock_client_class.return_value = mock_client

        cap = NotionCapability(config={"auth_token": "fake-token"})
        cap.wait_ready()
        assert cap._client is not None
        assert cap._session_page_id == "auto-session-id"

    def test_wait_ready_no_token(self):
        cap = NotionCapability()
        cap._token = None
        with pytest.raises(CapabilityError, match="token not found"):
            cap.wait_ready()

    @patch("terrarium.environment.capabilities.notion.notion_client.Client")
    def test_wait_ready_auth_failed(self, mock_client_class):
        mock_client_class.return_value.users.me.side_effect = Exception("invalid token")
        cap = NotionCapability(config={"auth_token": "bad-token"})
        with pytest.raises(CapabilityError, match="auth failed"):
            cap.wait_ready()

    # -------------------------------------------------------------------
    # connection_info
    # -------------------------------------------------------------------

    def test_connection_info(self):
        cap, client = self._make_cap()
        cap._bot_name = "My Bot"
        info = cap.connection_info
        assert info["api_url"] == "https://api.notion.com"
        assert info["bot_name"] == "My Bot"
        assert info["session_page_id"] == "session-page-id"

    # -------------------------------------------------------------------
    # session page + teardown
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.notion.notion_client.Client")
    def test_wait_ready_creates_session_page(self, mock_client_class):
        mock_client = MagicMock()
        mock_client.users.me.return_value = {"name": "Bot"}
        mock_client.search.return_value = {"results": [{
            "id": "root-page-found-id",
            "properties": {"title": {"title": [{"plain_text": "Terrarium"}]}},
        }]}
        mock_client.pages.create.return_value = {"id": "auto-session-id"}
        mock_client_class.return_value = mock_client

        cap = NotionCapability(config={"auth_token": "token"})
        cap.wait_ready()
        assert cap._session_page_id == "auto-session-id"
        assert "session_page_id" not in cap._config
        mock_client.pages.create.assert_called_once()

    @patch("terrarium.environment.capabilities.notion.notion_client.Client")
    def test_wait_ready_root_page_not_found(self, mock_client_class):
        mock_client = MagicMock()
        mock_client.users.me.return_value = {"name": "Bot"}
        mock_client.search.return_value = {"results": []}
        mock_client_class.return_value = mock_client

        cap = NotionCapability(config={"auth_token": "token"})
        with pytest.raises(CapabilityError, match="not found"):
            cap.wait_ready()

    def test_teardown_archives_session_page(self):
        cap = NotionCapability(config={"auth_token": "t"})
        cap._client = MagicMock()
        cap._session_page_id = "auto-session-id"
        cap.teardown()
        cap._client.pages.update.assert_called_once_with(page_id="auto-session-id", archived=True)

    def test_teardown_no_session_page(self):
        cap = NotionCapability(config={"auth_token": "t"})
        cap._client = MagicMock()
        cap.teardown()  # no session page, should not call anything
        cap._client.pages.update.assert_not_called()

    def test_teardown_no_client(self):
        cap = NotionCapability(config={"auth_token": "t"})
        cap.teardown()  # should not raise

    # -------------------------------------------------------------------
    # _get_client
    # -------------------------------------------------------------------

    def test_get_client_not_connected(self):
        cap = NotionCapability(config={"auth_token": "t"})
        with pytest.raises(CapabilityError, match="not connected"):
            cap._get_client()

    # -------------------------------------------------------------------
    # search
    # -------------------------------------------------------------------

    def test_search(self):
        cap, client = self._make_cap()
        client.search.return_value = {"results": [{"id": "p1", "object": "page"}]}
        results = cap.search("test")
        assert len(results) == 1
        client.search.assert_called_once_with(query="test")

    def test_search_filter_page(self):
        cap, client = self._make_cap()
        client.search.return_value = {"results": []}
        cap.search("test", filter_type="page")
        client.search.assert_called_once_with(
            query="test",
            filter={"value": "page", "property": "object"},
        )

    def test_search_filter_database(self):
        cap, client = self._make_cap()
        client.search.return_value = {"results": []}
        cap.search("test", filter_type="database")
        client.search.assert_called_once_with(
            query="test",
            filter={"value": "database", "property": "object"},
        )

    def test_search_empty(self):
        cap, client = self._make_cap()
        client.search.return_value = {"results": []}
        assert cap.search("nothing") == []

    def test_search_error(self):
        cap, client = self._make_cap()
        client.search.side_effect = Exception("api error")
        with pytest.raises(CapabilityError, match="Search failed"):
            cap.search("test")

    # -------------------------------------------------------------------
    # Page CRUD
    # -------------------------------------------------------------------

    def test_create_page_default_parent(self):
        cap, client = self._make_cap()
        client.pages.create.return_value = {"id": "new-page-id"}
        result = cap.create_page("My Page")
        assert result["id"] == "new-page-id"
        call_kwargs = client.pages.create.call_args[1]
        assert call_kwargs["parent"] == {"page_id": "session-page-id"}

    def test_create_page_explicit_parent(self):
        cap, client = self._make_cap()
        client.pages.create.return_value = {"id": "new-page-id"}
        result = cap.create_page("My Page", parent_id="custom-parent")
        call_kwargs = client.pages.create.call_args[1]
        assert call_kwargs["parent"] == {"page_id": "custom-parent"}

    def test_create_page_with_children(self):
        cap, client = self._make_cap()
        client.pages.create.return_value = {"id": "p1"}
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "hi"}}]}}]
        cap.create_page("Title", children=blocks)
        call_kwargs = client.pages.create.call_args[1]
        assert call_kwargs["children"] == blocks

    def test_create_page_error(self):
        cap, client = self._make_cap()
        client.pages.create.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to create page"):
            cap.create_page("Title")

    def test_get_page(self):
        cap, client = self._make_cap()
        client.pages.retrieve.return_value = {"id": "p1", "object": "page"}
        result = cap.get_page("p1")
        assert result["id"] == "p1"

    def test_get_page_error(self):
        cap, client = self._make_cap()
        client.pages.retrieve.side_effect = Exception("not found")
        with pytest.raises(CapabilityError, match="Failed to get page"):
            cap.get_page("missing")

    def test_update_page(self):
        cap, client = self._make_cap()
        client.pages.update.return_value = {"id": "p1"}
        props = {"Status": {"select": {"name": "Done"}}}
        result = cap.update_page("p1", props)
        assert result["id"] == "p1"
        client.pages.update.assert_called_once_with(page_id="p1", properties=props)

    def test_update_page_error(self):
        cap, client = self._make_cap()
        client.pages.update.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to update page"):
            cap.update_page("p1", {})

    def test_delete_page(self):
        cap, client = self._make_cap()
        client.pages.update.return_value = {}
        cap.delete_page("p1")
        client.pages.update.assert_called_once_with(page_id="p1", archived=True)

    def test_delete_page_error(self):
        cap, client = self._make_cap()
        client.pages.update.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to delete page"):
            cap.delete_page("p1")

    # -------------------------------------------------------------------
    # Database CRUD
    # -------------------------------------------------------------------

    def test_create_database_default_parent(self):
        cap, client = self._make_cap()
        client.databases.create.return_value = {"id": "db1"}
        props = {"Name": {"title": {}}, "Price": {"number": {}}}
        result = cap.create_database("Products", props)
        assert result["id"] == "db1"
        call_kwargs = client.databases.create.call_args[1]
        assert call_kwargs["parent"] == {"type": "page_id", "page_id": "session-page-id"}

    def test_create_database_explicit_parent(self):
        cap, client = self._make_cap()
        client.databases.create.return_value = {"id": "db1"}
        cap.create_database("Products", {"Name": {"title": {}}}, parent_id="custom")
        call_kwargs = client.databases.create.call_args[1]
        assert call_kwargs["parent"] == {"type": "page_id", "page_id": "custom"}

    def test_create_database_error(self):
        cap, client = self._make_cap()
        client.databases.create.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to create database"):
            cap.create_database("DB", {})

    def test_get_database(self):
        cap, client = self._make_cap()
        client.databases.retrieve.return_value = {"id": "db1", "title": []}
        result = cap.get_database("db1")
        assert result["id"] == "db1"

    def test_get_database_error(self):
        cap, client = self._make_cap()
        client.databases.retrieve.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to get database"):
            cap.get_database("missing")

    def test_update_database(self):
        cap, client = self._make_cap()
        client.databases.update.return_value = {"id": "db1"}
        result = cap.update_database("db1", title="New Title")
        assert result["id"] == "db1"
        call_kwargs = client.databases.update.call_args[1]
        assert call_kwargs["title"] == [{"text": {"content": "New Title"}}]

    def test_update_database_properties(self):
        cap, client = self._make_cap()
        client.databases.retrieve.return_value = {"data_sources": [{"id": "ds1"}]}
        client.data_sources.update.return_value = {"id": "ds1"}
        props = {"Price": {"number": {"format": "euro"}}}
        cap.update_database("db1", properties=props)
        call_kwargs = client.data_sources.update.call_args[1]
        assert call_kwargs["data_source_id"] == "ds1"
        assert call_kwargs["properties"] == props

    def test_update_database_error(self):
        cap, client = self._make_cap()
        client.databases.update.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to update database"):
            cap.update_database("db1", title="x")

    def test_delete_database(self):
        cap, client = self._make_cap()
        client.databases.update.return_value = {}
        cap.delete_database("db1")
        client.databases.update.assert_called_once_with(database_id="db1", in_trash=True)

    def test_delete_database_error(self):
        cap, client = self._make_cap()
        client.databases.update.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to delete database"):
            cap.delete_database("db1")

    def test_add_database_record(self):
        cap, client = self._make_cap()
        client.databases.retrieve.return_value = {"data_sources": [{"id": "ds1"}]}
        client.pages.create.return_value = {"id": "record1"}
        props = {"Name": {"title": [{"text": {"content": "Buy milk"}}]}}
        result = cap.add_database_record("db1", props)
        assert result["id"] == "record1"
        call_kwargs = client.pages.create.call_args[1]
        assert call_kwargs["parent"] == {"data_source_id": "ds1"}
        assert call_kwargs["properties"] == props

    def test_add_database_record_error(self):
        cap, client = self._make_cap()
        client.pages.create.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to add record"):
            cap.add_database_record("db1", {})

    def test_query_database(self):
        cap, client = self._make_cap()
        client.databases.retrieve.return_value = {
            "data_sources": [{"id": "ds1"}],
        }
        client.data_sources.query.return_value = {
            "results": [{"id": "r1"}, {"id": "r2"}],
            "has_more": False,
        }
        results = cap.query_database("db1")
        assert len(results) == 2

    def test_query_database_with_filter(self):
        cap, client = self._make_cap()
        client.databases.retrieve.return_value = {"data_sources": [{"id": "ds1"}]}
        client.data_sources.query.return_value = {"results": [], "has_more": False}
        f = {"property": "Status", "select": {"equals": "Active"}}
        cap.query_database("db1", filter=f)
        call_kwargs = client.data_sources.query.call_args[1]
        assert call_kwargs["filter"] == f

    def test_query_database_pagination(self):
        cap, client = self._make_cap()
        client.databases.retrieve.return_value = {"data_sources": [{"id": "ds1"}]}
        client.data_sources.query.side_effect = [
            {"results": [{"id": "r1"}], "has_more": True, "next_cursor": "cursor1"},
            {"results": [{"id": "r2"}], "has_more": False},
        ]
        results = cap.query_database("db1")
        assert len(results) == 2
        assert client.data_sources.query.call_count == 2

    def test_query_database_error(self):
        cap, client = self._make_cap()
        client.databases.retrieve.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to query database"):
            cap.query_database("db1")

    # -------------------------------------------------------------------
    # Block CRUD
    # -------------------------------------------------------------------

    def test_append_blocks(self):
        cap, client = self._make_cap()
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "hi"}}]}}]
        client.blocks.children.append.return_value = {"results": blocks}
        result = cap.append_blocks("page-id", blocks)
        assert len(result) == 1

    def test_append_blocks_error(self):
        cap, client = self._make_cap()
        client.blocks.children.append.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to append blocks"):
            cap.append_blocks("page-id", [])

    def test_list_blocks(self):
        cap, client = self._make_cap()
        client.blocks.children.list.return_value = {
            "results": [{"id": "b1"}, {"id": "b2"}],
            "has_more": False,
        }
        results = cap.list_blocks("page-id")
        assert len(results) == 2

    def test_list_blocks_pagination(self):
        cap, client = self._make_cap()
        client.blocks.children.list.side_effect = [
            {"results": [{"id": "b1"}], "has_more": True, "next_cursor": "c1"},
            {"results": [{"id": "b2"}], "has_more": False},
        ]
        results = cap.list_blocks("page-id")
        assert len(results) == 2
        assert client.blocks.children.list.call_count == 2

    def test_list_blocks_error(self):
        cap, client = self._make_cap()
        client.blocks.children.list.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to list blocks"):
            cap.list_blocks("page-id")

    def test_get_block(self):
        cap, client = self._make_cap()
        client.blocks.retrieve.return_value = {"id": "b1", "type": "paragraph"}
        result = cap.get_block("b1")
        assert result["id"] == "b1"

    def test_get_block_error(self):
        cap, client = self._make_cap()
        client.blocks.retrieve.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to get block"):
            cap.get_block("missing")

    def test_update_block(self):
        cap, client = self._make_cap()
        client.blocks.update.return_value = {"id": "b1"}
        result = cap.update_block("b1", paragraph={"rich_text": [{"text": {"content": "updated"}}]})
        assert result["id"] == "b1"
        client.blocks.update.assert_called_once_with(
            block_id="b1",
            paragraph={"rich_text": [{"text": {"content": "updated"}}]},
        )

    def test_update_block_error(self):
        cap, client = self._make_cap()
        client.blocks.update.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to update block"):
            cap.update_block("b1", paragraph={})

    def test_delete_block(self):
        cap, client = self._make_cap()
        client.blocks.delete.return_value = {}
        cap.delete_block("b1")
        client.blocks.delete.assert_called_once_with(block_id="b1")

    def test_delete_block_error(self):
        cap, client = self._make_cap()
        client.blocks.delete.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to delete block"):
            cap.delete_block("missing")
