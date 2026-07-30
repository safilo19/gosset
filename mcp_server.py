"""Entry point: the Gosset MCP server (stdio transport)."""

from analytics_mcp.app import mcp
from analytics_mcp import tools  # noqa: F401  (import registers the tools on `mcp`)

if __name__ == "__main__":
    mcp.run(transport="stdio")
