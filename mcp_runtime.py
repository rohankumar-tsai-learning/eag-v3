from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import Settings


@asynccontextmanager
async def mcp_session(settings: Settings):
    server_params = StdioServerParameters(
        command=settings.mcp_server_command,
        args=settings.mcp_args,
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def load_tools(session: Any) -> list[dict[str, Any]]:
    listed = await session.list_tools()
    tools = []
    for tool in listed.tools:
        input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        tools.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": input_schema,
            }
        )
    return tools
