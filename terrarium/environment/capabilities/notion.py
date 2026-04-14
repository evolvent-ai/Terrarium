"""Notion capability — API-based, no sandbox required."""

from __future__ import annotations

import os
import uuid

import notion_client
from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.logging import log_capability_call

DEFAULT_TIMEOUT_MS = 60_000


class NotionCapability(BaseCapability):
    """Notion capability via the official Notion API.

    This is an API-based capability — no sandbox/container is needed.
    sandbox_spec() returns None.

    Config options:
        auth_token:       Notion integration token (falls back to NOTION_TOKEN env var)
        timeout_ms:       Request timeout in milliseconds (default: 60000)
        root_page_name: Name of an existing page to create session page under (default: "Terrarium")
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self._token = self._config.get("auth_token") or os.environ.get("NOTION_TOKEN")
        self._timeout_ms = self._config.get("timeout_ms", DEFAULT_TIMEOUT_MS)
        self._client: notion_client.Client | None = None
        self._bot_name: str = ""
        self._session_page_id: str | None = None

    def wait_ready(self) -> None:
        """Verify token, then create session page for isolation."""
        if not self._token:
            raise CapabilityError(
                "Notion auth token not found. Set config['auth_token'] or NOTION_TOKEN env var."
            )
        try:
            self._client = notion_client.Client(
                auth=self._token,
                timeout_ms=self._timeout_ms,
            )
            me = self._client.users.me()
            self._bot_name = me.get("name", "unknown")
        except Exception as e:
            raise CapabilityError(f"Notion auth failed: {e}") from e

        parent_id = self._find_root_page()
        name = f"_terrarium_{uuid.uuid4().hex[:8]}"
        try:
            page = self._client.pages.create(
                parent={"page_id": parent_id},
                properties={"title": {"title": [{"text": {"content": name}}]}},
            )
            self._session_page_id = page["id"]
            logger.info("Notion session page created: {} ({})", name, self._session_page_id)
        except Exception as e:
            raise CapabilityError(f"Failed to create session page: {e}") from e

        logger.info("Notion capability ready: bot={}", self._bot_name)

    def teardown(self) -> None:
        """Archive the session page."""
        if self._session_page_id and self._client:
            try:
                self._client.pages.update(page_id=self._session_page_id, archived=True)
                logger.info("Notion session page archived: {}", self._session_page_id)
            except Exception as e:
                logger.warning("Failed to archive session page: {}", e)

    @property
    def connection_info(self) -> dict:
        """API connection details."""
        return {
            "api_url": "https://api.notion.com",
            "bot_name": self._bot_name,
            "session_page_id": self._session_page_id,
            "secrets": {
                "env": {"NOTION_TOKEN": self._token},
            },
        }

    def _find_root_page(self) -> str:
        """Find the root page by name for creating the session page under it."""
        root_name = self._config.get("root_page_name", "Terrarium")
        try:
            response = self._client.search(
                query=root_name,
                filter={"value": "page", "property": "object"},
            )
            for result in response.get("results", []):
                title_parts = result.get("properties", {}).get("title", {}).get("title", [])
                page_title = "".join(t.get("plain_text", "") for t in title_parts)
                if page_title == root_name:
                    return result["id"]
        except Exception as e:
            raise CapabilityError(f"Failed to search for root page: {e}") from e

        raise CapabilityError(
            f"Root page '{root_name}' not found. "
            f"Create a page named '{root_name}' in Notion and grant access to your integration."
        )

    def _get_client(self) -> notion_client.Client:
        if self._client is None:
            raise CapabilityError("Notion not connected")
        return self._client

    # -------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------

    @log_capability_call
    def search(self, query: str, filter_type: str | None = None) -> list[dict]:
        """Search pages and databases.

        Args:
            query: Search query string.
            filter_type: Optional "page" or "database" to filter results.
        """
        try:
            client = self._get_client()
            kwargs: dict = {"query": query}
            if filter_type:
                kwargs["filter"] = {"value": filter_type, "property": "object"}
            response = client.search(**kwargs)
            return response.get("results", [])
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Search failed: {e}") from e

    # -------------------------------------------------------------------
    # Page CRUD
    # -------------------------------------------------------------------

    @log_capability_call
    def create_page(
        self,
        title: str,
        parent_id: str | None = None,
        properties: dict | None = None,
        children: list[dict] | None = None,
    ) -> dict:
        """Create a page. Defaults to session page as parent."""
        try:
            client = self._get_client()
            pid = parent_id or self._session_page_id
            if not pid:
                raise CapabilityError("No parent_id and no session page available")
            parent = {"page_id": pid}
            props = properties or {}
            props["title"] = {"title": [{"text": {"content": title}}]}

            kwargs: dict = {"parent": parent, "properties": props}
            if children:
                kwargs["children"] = children
            return client.pages.create(**kwargs)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to create page: {e}") from e

    @log_capability_call
    def get_page(self, page_id: str) -> dict:
        """Retrieve a page."""
        try:
            return self._get_client().pages.retrieve(page_id=page_id)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to get page: {e}") from e

    @log_capability_call
    def update_page(self, page_id: str, properties: dict) -> dict:
        """Update page properties."""
        try:
            return self._get_client().pages.update(page_id=page_id, properties=properties)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to update page: {e}") from e

    @log_capability_call
    def delete_page(self, page_id: str) -> None:
        """Archive (delete) a page."""
        try:
            self._get_client().pages.update(page_id=page_id, archived=True)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete page: {e}") from e

    # -------------------------------------------------------------------
    # Database CRUD
    # -------------------------------------------------------------------

    @log_capability_call
    def create_database(self, title: str, properties: dict, parent_id: str | None = None) -> dict:
        """Create a database. Defaults to session page as parent."""
        try:
            client = self._get_client()
            pid = parent_id or self._session_page_id
            if not pid:
                raise CapabilityError("No parent_id and no session page available")
            return client.databases.create(
                parent={"type": "page_id", "page_id": pid},
                title=[{"text": {"content": title}}],
                initial_data_source={"properties": properties},
            )
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to create database: {e}") from e

    @log_capability_call
    def get_database(self, database_id: str) -> dict:
        """Retrieve a database."""
        try:
            return self._get_client().databases.retrieve(database_id=database_id)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to get database: {e}") from e

    @log_capability_call
    def update_database(
        self,
        database_id: str,
        title: str | None = None,
        properties: dict | None = None,
    ) -> dict:
        """Update a database title and/or schema properties."""
        try:
            client = self._get_client()
            result = None
            if title is not None:
                result = client.databases.update(
                    database_id=database_id,
                    title=[{"text": {"content": title}}],
                )
            if properties is not None:
                db = client.databases.retrieve(database_id=database_id)
                ds_list = db.get("data_sources", [])
                if not ds_list:
                    raise CapabilityError(f"Database {database_id} has no data sources")
                result = client.data_sources.update(
                    data_source_id=ds_list[0]["id"],
                    properties=properties,
                )
            return result
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to update database: {e}") from e

    @log_capability_call
    def delete_database(self, database_id: str) -> None:
        """Archive (delete) a database."""
        try:
            self._get_client().databases.update(database_id=database_id, in_trash=True)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete database: {e}") from e

    @log_capability_call
    def add_database_record(self, database_id: str, properties: dict) -> dict:
        """Add a record (page) to a database."""
        try:
            client = self._get_client()
            db = client.databases.retrieve(database_id=database_id)
            ds_list = db.get("data_sources", [])
            if not ds_list:
                raise CapabilityError(f"Database {database_id} has no data sources")
            return client.pages.create(
                parent={"data_source_id": ds_list[0]["id"]},
                properties=properties,
            )
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to add record: {e}") from e

    @log_capability_call
    def query_database(
        self,
        database_id: str,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
    ) -> list[dict]:
        """Query a database with optional filter and sorts. Auto-paginates."""
        try:
            client = self._get_client()

            # Notion API 2025-09-03: query via data_sources, not databases
            db = client.databases.retrieve(database_id=database_id)
            ds_list = db.get("data_sources", [])
            if not ds_list:
                raise CapabilityError(f"Database {database_id} has no data sources")
            data_source_id = ds_list[0]["id"]

            results = []
            kwargs: dict = {"data_source_id": data_source_id}
            if filter:
                kwargs["filter"] = filter
            if sorts:
                kwargs["sorts"] = sorts

            while True:
                response = client.data_sources.query(**kwargs)
                results.extend(response.get("results", []))
                if not response.get("has_more"):
                    break
                kwargs["start_cursor"] = response["next_cursor"]
            return results
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to query database: {e}") from e

    # -------------------------------------------------------------------
    # Block CRUD
    # -------------------------------------------------------------------

    @log_capability_call
    def append_blocks(self, block_id: str, children: list[dict]) -> list[dict]:
        """Append child blocks to a page or block."""
        try:
            client = self._get_client()
            response = client.blocks.children.append(block_id=block_id, children=children)
            return response.get("results", [])
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to append blocks: {e}") from e

    @log_capability_call
    def list_blocks(self, block_id: str) -> list[dict]:
        """List child blocks of a page or block. Auto-paginates."""
        try:
            client = self._get_client()
            results = []
            kwargs: dict = {"block_id": block_id}

            while True:
                response = client.blocks.children.list(**kwargs)
                results.extend(response.get("results", []))
                if not response.get("has_more"):
                    break
                kwargs["start_cursor"] = response["next_cursor"]
            return results
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to list blocks: {e}") from e

    @log_capability_call
    def get_block(self, block_id: str) -> dict:
        """Retrieve a single block."""
        try:
            return self._get_client().blocks.retrieve(block_id=block_id)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to get block: {e}") from e

    @log_capability_call
    def update_block(self, block_id: str, **content) -> dict:
        """Update a block's content."""
        try:
            return self._get_client().blocks.update(block_id=block_id, **content)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to update block: {e}") from e

    @log_capability_call
    def delete_block(self, block_id: str) -> None:
        """Delete a block."""
        try:
            self._get_client().blocks.delete(block_id=block_id)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete block: {e}") from e
