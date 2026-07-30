"""PyInstaller hook for this repo's own packages.

The spec names `backend.api` as a hidden import, but `backend` is a plain directory package with
~30 sibling modules that reach each other through `from backend.core import x as x_core` inside
function bodies (the dispatch tables are built lazily). Collecting the tree here rather than listing
modules in the spec means adding a new procedure module never needs a build change.

`analytics_mcp` comes along for `analytics_mcp.models`, which holds the pydantic response models that
backend/api.py imports and which therefore must exist for the API to even define its routes.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("backend") + collect_submodules("analytics_mcp")
