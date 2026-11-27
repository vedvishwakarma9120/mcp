"""Minimal stdio MCP client demo — no paid app required."""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main() -> None:
    load_dotenv()
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "github_mcp.server"],
        env=dict(os.environ),
    )

    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        print("Tools:", [t.name for t in tools.tools])

        if os.getenv("GITHUB_TOKEN"):
            result = await session.call_tool("search_repositories", {"query": "mcp", "limit": 2})
            print("Sample search_repositories result:")
            for item in result.content:
                print(item.text)
        else:
            print("Set GITHUB_TOKEN in .env to run a live search_repositories call.")


if __name__ == "__main__":
    asyncio.run(main())
