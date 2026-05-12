"""MCP server configuration models."""
from __future__ import annotations
from typing import Literal, Self
from pydantic import BaseModel, Field, model_validator


class MCPServerConfig(BaseModel):
    """An MCP server available to the agent."""
    name: str
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> Self:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio transport requires `command`")
            if self.url or self.headers:
                raise ValueError("stdio transport does not accept `url`/`headers`")
        else:
            if not self.url:
                raise ValueError(f"{self.transport} transport requires `url`")
            if self.command or self.args or self.env:
                raise ValueError(f"{self.transport} transport does not accept `command`/`args`/`env`")
        return self
