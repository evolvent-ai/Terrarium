"""Notion integration tests — require a valid NOTION_TOKEN env var."""

import pytest
from terrarium.environment.environment import ComposableEnvironment
from tests.conftest import skip_no_notion_token


@skip_no_notion_token
@pytest.mark.timeout(30)
class TestNotionIntegration:
    """Integration tests against real Notion API.

    Requires NOTION_TOKEN env var (or .env file).
    Uses auto-created session page for isolation — cleaned up on teardown.
    """

    @pytest.fixture(autouse=True)
    def setup_runtime(self):
        with ComposableEnvironment(["notion"]) as env:
            self.env = env
            yield

    def test_search(self):
        results = self.env.notion.search("test")
        assert isinstance(results, list)

    def test_create_and_get_page(self):
        page = self.env.notion.create_page("Integration Test Page")
        assert page["id"]
        fetched = self.env.notion.get_page(page["id"])
        assert fetched["id"] == page["id"]

    def test_update_page(self):
        page = self.env.notion.create_page("Update Test")
        self.env.notion.update_page(
            page["id"],
            properties={"title": {"title": [{"text": {"content": "Updated Title"}}]}},
        )
        fetched = self.env.notion.get_page(page["id"])
        title = fetched["properties"]["title"]["title"][0]["text"]["content"]
        assert title == "Updated Title"

    def test_delete_page(self):
        page = self.env.notion.create_page("Delete Test")
        self.env.notion.delete_page(page["id"])
        fetched = self.env.notion.get_page(page["id"])
        assert fetched["archived"] is True

    def test_create_and_query_database(self):
        db = self.env.notion.create_database(
            "Test DB",
            {"Name": {"title": {}}, "Score": {"number": {}}},
        )
        assert db["id"]
        rows = self.env.notion.query_database(db["id"])
        assert isinstance(rows, list)

    def test_get_database(self):
        db = self.env.notion.create_database("Get DB Test", {"Name": {"title": {}}})
        fetched = self.env.notion.get_database(db["id"])
        assert fetched["id"] == db["id"]

    def test_append_and_list_blocks(self):
        page = self.env.notion.create_page("Block Test")
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Hello"}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "Title"}}]}},
        ]
        self.env.notion.append_blocks(page["id"], blocks)
        children = self.env.notion.list_blocks(page["id"])
        assert len(children) >= 2

    def test_get_and_delete_block(self):
        page = self.env.notion.create_page("Block CRUD")
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "temp"}}]}}]
        appended = self.env.notion.append_blocks(page["id"], blocks)
        block_id = appended[0]["id"]
        block = self.env.notion.get_block(block_id)
        assert block["id"] == block_id
        self.env.notion.delete_block(block_id)

    def test_connection_info(self):
        info = self.env.notion.connection_info
        assert info["api_url"] == "https://api.notion.com"
        assert isinstance(info["bot_name"], str)
        assert info["session_page_id"] is not None
