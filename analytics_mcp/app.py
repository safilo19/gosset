"""Shared FastMCP server instance. Tool modules import `mcp` from here and register on it."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Gosset",
    instructions=(
        "Phase 1 tools for loading and exploring your own datasets (CSV, Excel, or a public "
        "Google Sheet): load_dataset, list_datasets, describe_dataset, compute_correlation. "
        "Always load_dataset first to obtain a dataset_id before calling the other tools."
    ),
)
