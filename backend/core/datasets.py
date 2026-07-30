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
from typing import Any

import numpy as np
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
# worksheet — blank grid creation, manual cell editing, paste, column rename
# ---------------------------------------------------------------------------

BLANK_WORKSHEET_COLUMNS = 20
BLANK_WORKSHEET_ROWS = 50


def create_blank_dataframe(n_columns: int = BLANK_WORKSHEET_COLUMNS, n_rows: int = BLANK_WORKSHEET_ROWS) -> pd.DataFrame:
    """A Minitab-style blank worksheet: C1..Cn columns, all-empty cells, ready for manual entry."""
    columns = [f"C{i + 1}" for i in range(n_columns)]
    return pd.DataFrame({c: pd.array([None] * n_rows, dtype=object) for c in columns})


def _json_safe_scalar(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _reinfer_column_dtype(df: pd.DataFrame, column: str) -> None:
    """After a manual edit, re-derive the column's dtype from its own non-empty values: numeric
    if every filled cell parses as a number, otherwise left as flexible text. This never rejects
    a manual entry the way strict file-import validation might — the column just widens (e.g.
    to text) to accommodate whatever was typed, the way Minitab's worksheet behaves."""
    non_null = df[column].dropna()
    if non_null.empty:
        return
    try:
        pd.to_numeric(non_null)
    except (ValueError, TypeError):
        return
    df[column] = pd.to_numeric(df[column], errors="coerce")


def _widen_to_object(df: pd.DataFrame, column: str) -> None:
    if df[column].dtype != object:
        df[column] = df[column].astype(object)


def set_cell_value(dataset: Dataset, row_index: int, column: str, value: Any) -> Any:
    """Update a single cell in-place. Accepts any value — numeric if it parses as one, text
    otherwise — and widens the column's dtype to fit, rather than rejecting the edit. Returns the
    value actually stored (JSON-safe), for the caller to echo back."""
    df = dataset.df
    if column not in df.columns:
        raise ColumnNotFoundError([column], list(df.columns))
    if row_index < 0 or row_index >= len(df):
        raise ValueError(f"Row index {row_index} is out of range for this dataset (0 to {len(df) - 1}).")

    _widen_to_object(df, column)
    col_idx = df.columns.get_loc(column)
    stored = value if value not in (None, "") else None
    df.iloc[row_index, col_idx] = stored
    _reinfer_column_dtype(df, column)
    return _json_safe_scalar(df.iloc[row_index, col_idx])


def paste_block(dataset: Dataset, start_row: int, start_column: int, values: list[list[Any]]) -> None:
    """Fill a rectangular block starting at (start_row, start_column) with pasted values,
    expanding the grid with blank rows/columns (named C{n+1}, C{n+2}, ...) if the pasted block
    runs past the current size — mirrors pasting a clipboard block into Minitab or Excel."""
    if start_row < 0 or start_column < 0:
        raise ValueError("start_row and start_column must both be 0 or greater.")
    if not values or not any(values):
        return

    df = dataset.df
    needed_rows = start_row + len(values)
    if needed_rows > len(df):
        extra = needed_rows - len(df)
        pad = pd.DataFrame({c: pd.array([None] * extra, dtype=object) for c in df.columns})
        dataset.df = pd.concat([df, pad], ignore_index=True)
        df = dataset.df

    needed_cols = start_column + max((len(row) for row in values), default=0)
    while len(df.columns) < needed_cols:
        df[f"C{len(df.columns) + 1}"] = pd.array([None] * len(df), dtype=object)

    touched_columns: set[str] = set()
    for i, row_values in enumerate(values):
        row_idx = start_row + i
        for j, raw in enumerate(row_values):
            column = df.columns[start_column + j]
            _widen_to_object(df, column)
            df.iloc[row_idx, df.columns.get_loc(column)] = raw if raw not in (None, "") else None
            touched_columns.add(column)

    for column in touched_columns:
        _reinfer_column_dtype(df, column)


def dataframe_from_values(columns: list[str], rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Rebuild a worksheet from explicit column names + row records — the inverse of what
    GET /datasets/{id}/full serves. Used to reopen a saved .baproj project, and to put a
    worksheet back the way it was when undoing a structural edit (a row/column delete or a
    paste that grew the grid)."""
    if not columns:
        raise ValueError("A worksheet needs at least one column.")
    if len(set(columns)) != len(columns):
        raise ValueError("Duplicate column names are not allowed in a worksheet.")

    data = {col: [row.get(col) if isinstance(row, dict) else None for row in rows] for col in columns}
    df = pd.DataFrame(data, columns=columns)
    if df.empty:
        df = pd.DataFrame({c: pd.array([], dtype=object) for c in columns})
    for col in columns:
        _widen_to_object(df, col)
        df[col] = df[col].where(df[col].notna() & (df[col] != ""), None)
        _reinfer_column_dtype(df, col)
    return df


def replace_values(dataset: Dataset, columns: list[str], rows: list[dict[str, Any]]) -> None:
    """Swap a dataset's contents in place, keeping its dataset_id. In-place matters: every open
    result window and the worksheet all reference the same id, so undo must not mint a new one."""
    dataset.df = dataframe_from_values(columns, rows)


def delete_rows(dataset: Dataset, row_indices: list[int]) -> int:
    """Drop whole rows by 0-based index and close the gap. Returns the number of rows removed."""
    df = dataset.df
    unique = sorted({int(i) for i in row_indices})
    if not unique:
        raise ValueError("No rows were selected to delete.")
    out_of_range = [i for i in unique if i < 0 or i >= len(df)]
    if out_of_range:
        raise ValueError(f"Row index/indices {out_of_range} are out of range for this dataset (0 to {len(df) - 1}).")
    if len(unique) >= len(df):
        raise ValueError("Cannot delete every row — use File > New > New Worksheet for an empty grid instead.")

    dataset.df = df.drop(index=df.index[unique]).reset_index(drop=True)
    return len(unique)


def delete_columns(dataset: Dataset, columns: list[str]) -> int:
    """Drop whole columns by name. Returns the number of columns removed."""
    df = dataset.df
    if not columns:
        raise ValueError("No columns were selected to delete.")
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ColumnNotFoundError(missing, list(df.columns))
    if len(set(columns)) >= len(df.columns):
        raise ValueError("Cannot delete every column — use File > New > New Worksheet for an empty grid instead.")

    dataset.df = df.drop(columns=list(dict.fromkeys(columns)))
    return len(set(columns))


def rename_column(dataset: Dataset, column: str, new_name: str) -> str:
    """Rename a column (e.g. the default 'C1' to a descriptive name). Returns the cleaned name
    actually applied."""
    df = dataset.df
    if column not in df.columns:
        raise ColumnNotFoundError([column], list(df.columns))
    cleaned = new_name.strip()
    if not cleaned:
        raise ValueError("New column name cannot be empty.")
    if cleaned != column and cleaned in df.columns:
        raise ValueError(f"Column '{cleaned}' already exists in this dataset.")
    dataset.df = df.rename(columns={column: cleaned})
    return cleaned


# ---------------------------------------------------------------------------
# shared formatting helpers
# ---------------------------------------------------------------------------


def json_safe_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame's rows to JSON-safe records (handles NaN, numpy, Timestamp).

    Date columns are written the way a worksheet cell should read them — '2024-01-01', or
    '2024-01-01 09:30:00' when there is a real time of day — rather than as a full ISO timestamp.
    A date-only column rendered as '2024-01-01T00:00:00.000' is technically correct and unreadable
    in a grid, and it is what a saved project would carry back in.
    """
    out = df
    date_columns = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    if date_columns:
        out = df.copy()
        for column in date_columns:
            series = out[column]
            # Missing entries have no time of day to disagree about, so they must not force the
            # whole column into the long form.
            filled = series.dropna()
            midnight_only = filled.empty or bool(((filled.dt.hour == 0) & (filled.dt.minute == 0) & (filled.dt.second == 0)).all())
            out[column] = series.dt.strftime("%Y-%m-%d" if midnight_only else "%Y-%m-%d %H:%M:%S")
    return json.loads(out.to_json(orient="records", date_format="iso"))


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
