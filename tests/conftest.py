"""Shared test fixtures and skip markers."""

import os

import docker
import pytest
from dotenv import load_dotenv

load_dotenv()


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


skip_no_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available",
)

skip_no_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

skip_no_anthropic_base_url = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_BASE_URL"),
    reason="ANTHROPIC_BASE_URL not set",
)

skip_no_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)

skip_no_openrouter_key = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)

skip_no_notion_token = pytest.mark.skipif(
    not os.environ.get("NOTION_TOKEN"),
    reason="NOTION_TOKEN not set",
)

skip_no_gsheets_creds = pytest.mark.skipif(
    not (
        os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE")
        or os.path.exists("oauth_credentials.json")
    ),
    reason="Google Sheets OAuth credentials not available",
)
