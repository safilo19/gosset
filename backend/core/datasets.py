"""Dataset loading and in-memory cache. Plain Python — no MCP or web-framework code.

Both the MCP server and the REST API create their own DatasetStore() instance
(see the module docstring in mcp_server / api.py) — caches are not shared.
"""

from __future__ import annotations

import io
import itertools
import json
import re
import urllib.error
from dataclasses import dataclass

import pandas as pd

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID_RE = re.compile(r"[?#&]gid=(\d+)")


class DatasetNotFoundError(Exception):
    def __init__(self, dataset_id: str, loaded_ids: list[str]):
        loaded = ", ".join(loaded_ids) if loaded_ids else "(none — call load_dataset first)"
        super().__init__(f"Dataset '{dataset_id}' was not found. Currently loaded datasets: {loaded}")


class ColumnNotFoundError(Exception):
    def __init__(self, missing: list[str], valid_columns: list[str]):
        super().__init__(
            f"Column(s) not found: {', '.join(missing)}. "
            f"Valid columns for this dataset: {', '.join(valid_columns)}"
        )


@dataclass
class Dataset:
    dataset_id: str
    df: pd.DataFrame
    source: str
    source_type: str


class DatasetStore:
    """Simple process-local dict cache of loaded DataFrames."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}
        self._counter = itertools.count(1)

    def add(self, df: pd.DataFrame, source: str, source_type: str) -> Dataset:
        dataset_id = f"ds_{next(self._counter)}"
        dataset = Dataset(dataset_id=dataset_id, df=df, source=source, source_type=source_type)
        self._datasets[dataset_id] = dataset
        return dataset

    def get(self, dataset_id: str) -> Dataset:
        try:
            return self._datasets[dataset_id]
        except KeyError:
            raise DatasetNotFoundError(dataset_id, list(self._datasets.keys())) from None

    def all(self) -> dict[str, Dataset]:
        return self._datasets

    def require_columns(self, dataset: Dataset, columns: list[str]) -> None:
        missing = [c for c in columns if c not in dataset.df.columns]
        if missing:
            raise ColumnNotFoundError(missing, list(dataset.df.columns))


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def gsheet_share_url_to_csv_url(url: str) -> str:
    """Convert a public Google Sheets share URL into its CSV export URL."""
    match = _SHEET_ID_RE.search(url)
    if not match:
        raise ValueError(
            "Could not find a Google Sheets ID in the given URL. Expected something like "
            "'https://docs.google.com/spreadsheets/d/<ID>/edit#gid=<GID>'."
        )
    sheet_id = match.group(1)
    gid_match = _GID_RE.search(url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def load_dataframe(source: str, source_type: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Load from a file path or URL (used by the MCP server, and the API's gsheet path)."""
    if source_type == "csv":
        return pd.read_csv(source)
    if source_type == "xlsx":
        return pd.read_excel(source, sheet_name=sheet_name if sheet_name is not None else 0)
    if source_type == "gsheet":
        csv_url = gsheet_share_url_to_csv_url(source)
        try:
            return pd.read_csv(csv_url)
        except urllib.error.URLError as e:
            raise ValueError(
                f"Could not fetch the Google Sheet as CSV ({e}). Make sure it's shared as "
                f"'Anyone with the link can view' and the URL is correct."
            ) from e
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
            raise ValueError(
                f"The Google Sheet did not return valid CSV data ({e}). This usually means it isn't shared "
                f"as 'Anyone with the link can view' (Google returns a login page instead of the sheet)."
            ) from e
    raise ValueError(f"Unsupported source_type '{source_type}'. Expected one of: csv, xlsx, gsheet.")


def load_dataframe_from_bytes(data: bytes, source_type: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Load from raw file bytes (used by the API's multipart upload endpoint)."""
    buffer = io.BytesIO(data)
    if source_type == "csv":
        return pd.read_csv(buffer)
    if source_type == "xlsx":
        return pd.read_excel(buffer, sheet_name=sheet_name if sheet_name is not None else 0)
    raise ValueError(f"Unsupported source_type '{source_type}' for file upload. Expected 'csv' or 'xlsx'.")


# ---------------------------------------------------------------------------
# shared formatting helpers
# ---------------------------------------------------------------------------


def json_safe_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame's rows to JSON-safe records (handles NaN, numpy, Timestamp)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def column_info(df: pd.DataFrame) -> list[dict]:
    """Return [{"name": ..., "dtype": ...}, ...] for each column."""
    return [{"name": str(col), "dtype": str(dtype)} for col, dtype in df.dtypes.items()]


@dataclass
class LoadSummary:
    row_count: int
    columns: list[dict]
    preview: list[dict]
    summary: str


def summarize_load(dataset: Dataset) -> LoadSummary:
    df = dataset.df
    columns = column_info(df)
    preview = json_safe_records(df.head(5))
    col_list = ", ".join(c["name"] for c in columns)
    summary = (
        f"Loaded dataset '{dataset.dataset_id}' from {dataset.source} ({dataset.source_type}). "
        f"{len(df)} rows, {len(columns)} columns: {col_list}. "
        f"Preview of the first {len(preview)} row(s) is included."
    )
    return LoadSummary(row_count=len(df), columns=columns, preview=preview, summary=summary)


@dataclass
class DatasetSummaryResult:
    dataset_id: str
    source: str
    source_type: str
    row_count: int
    column_count: int
    columns: list[str]


def summarize_all(store: DatasetStore) -> tuple[list[DatasetSummaryResult], str]:
    datasets = [
        DatasetSummaryResult(
            dataset_id=ds.dataset_id,
            source=ds.source,
            source_type=ds.source_type,
            row_count=len(ds.df),
            column_count=len(ds.df.columns),
            columns=[str(c) for c in ds.df.columns],
        )
        for ds in store.all().values()
    ]

    if not datasets:
        summary = "No datasets are currently loaded. Use load_dataset to load a CSV, Excel file, or public Google Sheet."
    else:
        lines = [f"{len(datasets)} dataset(s) currently loaded:"]
        lines += [f"- {d.dataset_id}: {d.row_count} rows x {d.column_count} columns (source: {d.source})" for d in datasets]
        summary = "\n".join(lines)

    return datasets, summary
