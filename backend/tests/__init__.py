"""Gosset's statistical validation suite.

Tests call the CORE functions in `backend/core/*.py` directly. That is deliberate: the REST API,
the browser UI and the MCP server are all thin layers over the same `compute()` entry points, so
validating the core validates every interface at once. A test that went through HTTP would be
slower, would need a server, and would prove nothing extra about the arithmetic.
"""
