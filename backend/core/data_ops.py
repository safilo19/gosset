"""Every Data-menu operation, behind one compute() dispatch — the same shape as basic_stats.py
and regression_models.py, so the API keeps one route per menu area rather than one per procedure.

Plain Python: no MCP or web-framework code, and no DatasetStore. An operation that reads another
open worksheet is handed those frames by the caller (`others`), and an operation that *produces*
worksheets returns real DataFrames — the API decides what to do with them (replace the active
worksheet in place, or add new ones to its store).

Result modes:
  none            report only (Worksheet Information, Display Data, a Change Data Type preview)
  in_place        frames[0] replaces the active worksheet, keeping its dataset_id
  other_in_place  frames[0] replaces the worksheet named by `target_id`
  new             frames[0] becomes a new worksheet
  many            every frame becomes a new worksheet (Split Worksheet)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from backend.core.procedures import ProcedureError, g, int_option, json_safe, list_option, option

# ---------------------------------------------------------------------------
# result container
# ---------------------------------------------------------------------------


@dataclass
class DataOpResult:
    mode: str
    frames: list[tuple[str, pd.DataFrame]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    target_id: str | None = None


def _report(summary: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"summary": summary, "conclusion": summary}
    payload.update(extra)
    return json_safe(payload)


# ---------------------------------------------------------------------------
# shared parsing helpers
# ---------------------------------------------------------------------------

_ROW_TOKEN = re.compile(r"^(\d+)\s*(?::|-)\s*(\d+)$")


def parse_row_spec(spec: Any, n_rows: int, *, what: str = "Rows") -> list[int]:
    """Minitab's row list — '1:5 12 20:25' — into sorted, de-duplicated 0-based indices.

    Separators are spaces, commas or semicolons; a range is written `a:b` or `a-b` and is
    inclusive at both ends. Row numbers are 1-based, the way the worksheet's row headers read.
    """
    if spec is None:
        return []
    text = str(spec).strip()
    if not text:
        return []
    picked: set[int] = set()
    for token in re.split(r"[\s,;]+", text):
        if not token:
            continue
        match = _ROW_TOKEN.match(token)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                start, end = end, start
        elif token.isdigit():
            start = end = int(token)
        else:
            raise ProcedureError(
                f"'{token}' is not a row number or range. {what} are written like '1:5 12 20:25' — "
                f"single row numbers and a:b ranges, separated by spaces."
            )
        if start < 1:
            raise ProcedureError(f"Row numbers start at 1; got '{token}'.")
        for row in range(start, end + 1):
            if row <= n_rows:
                picked.add(row - 1)
    if not picked:
        raise ProcedureError(f"{what} '{text}' does not name any row in this worksheet (it has {n_rows} rows).")
    return sorted(picked)


def require_columns(df: pd.DataFrame, columns: list[str], *, what: str = "This operation") -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        available = ", ".join(str(c) for c in df.columns) or "(none)"
        raise ProcedureError(f"{what} names column(s) that are not in this worksheet: {', '.join(missing)}. Available: {available}")


def unique_name(taken: list[str] | set[str], base: str) -> str:
    """A column/worksheet name that is not already in use — 'Sorted', then 'Sorted_2', ..."""
    existing = set(taken)
    cleaned = (base or "C").strip() or "C"
    if cleaned not in existing:
        return cleaned
    n = 2
    while f"{cleaned}_{n}" in existing:
        n += 1
    return f"{cleaned}_{n}"


def _blank_column(n_rows: int) -> pd.Series:
    return pd.Series(pd.array([None] * n_rows, dtype=object), dtype=object)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Reset the index and hand back a copy — every operation returns a fresh, 0..n-1 frame."""
    out = df.reset_index(drop=True)
    return out


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _to_datetime(series: pd.Series, fmt: str | None = None) -> pd.Series:
    if fmt:
        return pd.to_datetime(series, format=fmt, errors="coerce")
    return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)


# ---------------------------------------------------------------------------
# the condition builder (Subset Worksheet, Copy ▸ Columns to Columns)
# ---------------------------------------------------------------------------

CONDITION_OPERATORS = (
    "=",
    "≠",
    ">",
    "<",
    "≥",
    "≤",
    "contains",
    "starts with",
    "ends with",
    "between",
    "is missing",
    "is not missing",
)

_OP_ALIASES = {"!=": "≠", "<>": "≠", ">=": "≥", "<=": "≤", "==": "="}


def _numeric_pair(series: pd.Series, value: Any) -> tuple[pd.Series, float] | None:
    """A numeric comparison when both sides really are numbers — otherwise fall back to text, so
    '=' on a text column still works and '>' on a numeric one is not a string comparison."""
    try:
        target = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    numbers = _numeric(series)
    if numbers.notna().sum() == 0:
        return None
    return numbers, target


def _text(series: pd.Series) -> pd.Series:
    return series.astype(object).where(series.notna(), None).map(lambda v: "" if v is None else str(v))


def condition_mask(df: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    column = str(condition.get("column") or "").strip()
    if not column:
        raise ProcedureError("Every condition needs a column.")
    require_columns(df, [column], what="The condition")
    operator = _OP_ALIASES.get(str(condition.get("operator") or "=").strip(), str(condition.get("operator") or "=").strip())
    if operator not in CONDITION_OPERATORS:
        raise ProcedureError(f"'{operator}' is not a condition operator. Use one of: {', '.join(CONDITION_OPERATORS)}.")

    series = df[column]
    blank = series.map(_is_blank)

    if operator == "is missing":
        return blank
    if operator == "is not missing":
        return ~blank

    value = condition.get("value")
    if operator == "between":
        low, high = _numeric_pair(series, value), _numeric_pair(series, condition.get("value2"))
        if low is None or high is None:
            raise ProcedureError(f"'between' on '{column}' needs two numbers; got '{value}' and '{condition.get('value2')}'.")
        numbers = low[0]
        lo, hi = low[1], high[1]
        if lo > hi:
            lo, hi = hi, lo
        return numbers.between(lo, hi) & numbers.notna()

    if value is None or str(value).strip() == "":
        raise ProcedureError(f"The condition on '{column}' needs a value to compare against.")

    if operator in ("contains", "starts with", "ends with"):
        text = _text(series).str.lower()
        needle = str(value).strip().lower()
        if operator == "contains":
            return text.str.contains(re.escape(needle), regex=True, na=False) & ~blank
        if operator == "starts with":
            return text.str.startswith(needle) & ~blank
        return text.str.endswith(needle) & ~blank

    pair = _numeric_pair(series, value)
    if pair is not None:
        numbers, target = pair
        ok = numbers.notna()
        if operator == "=":
            return ok & (numbers == target)
        if operator == "≠":
            return ~(ok & (numbers == target))
        if operator == ">":
            return ok & (numbers > target)
        if operator == "<":
            return ok & (numbers < target)
        if operator == "≥":
            return ok & (numbers >= target)
        return ok & (numbers <= target)

    text = _text(series)
    needle = str(value).strip()
    if operator == "=":
        return (text == needle) & ~blank
    if operator == "≠":
        return ~((text == needle) & ~blank)
    # An ordering comparison on text is a lexical one, which is what a spreadsheet does too.
    if operator == ">":
        return (text > needle) & ~blank
    if operator == "<":
        return (text < needle) & ~blank
    if operator == "≥":
        return (text >= needle) & ~blank
    return (text <= needle) & ~blank


def conditions_mask(df: pd.DataFrame, conditions: list[dict], joiner: str = "and") -> pd.Series:
    live = [c for c in (conditions or []) if c and str(c.get("column") or "").strip()]
    if not live:
        raise ProcedureError("Add at least one condition (choose a column, an operator and a value).")
    masks = [condition_mask(df, c) for c in live]
    combined = masks[0]
    for mask in masks[1:]:
        combined = (combined & mask) if str(joiner).lower() == "and" else (combined | mask)
    return combined.fillna(False)


def describe_conditions(conditions: list[dict], joiner: str) -> str:
    live = [c for c in (conditions or []) if c and str(c.get("column") or "").strip()]
    parts = []
    for c in live:
        op = _OP_ALIASES.get(str(c.get("operator") or "="), str(c.get("operator") or "="))
        if op in ("is missing", "is not missing"):
            parts.append(f"{c['column']} {op}")
        elif op == "between":
            parts.append(f"{c['column']} between {c.get('value')} and {c.get('value2')}")
        else:
            parts.append(f"{c['column']} {op} {c.get('value')}")
    return f" {joiner.upper()} ".join(parts)


# ---------------------------------------------------------------------------
# Step 1 — rows, order, basic column operations
# ---------------------------------------------------------------------------


def _sort_specs(options: dict) -> list[tuple[str, bool]]:
    raw = options.get("by") or []
    specs: list[tuple[str, bool]] = []
    for entry in raw:
        if not entry:
            continue
        column = str(entry.get("column") or "").strip()
        if not column:
            continue
        descending = str(entry.get("direction") or "ascending").lower().startswith("desc")
        specs.append((column, descending))
    return specs[:4]


def op_sort(df: pd.DataFrame, options: dict) -> DataOpResult:
    specs = _sort_specs(options)
    if not specs:
        raise ProcedureError("Choose at least one column to sort by.")
    require_columns(df, [c for c, _ in specs], what="Sort")

    # Sort on a numeric view of each by-column where the column really is numeric, so 10 comes
    # after 9 rather than after 1. mergesort is stable, which is what makes a second by-column
    # (and a repeated sort) behave the way a spreadsheet's multi-level sort does.
    work = df.copy()
    keys = []
    for i, (column, _) in enumerate(specs):
        numbers = _numeric(work[column])
        key = f"__sortkey_{i}"
        work[key] = numbers if numbers.notna().sum() == len(work[column].dropna()) and numbers.notna().any() else _text(work[column])
        keys.append(key)

    sorted_df = work.sort_values(by=keys, ascending=[not desc for _, desc in specs], kind="mergesort").drop(columns=keys)
    sorted_df = _clean(sorted_df)

    order = ", ".join(f"{c} {'descending' if d else 'ascending'}" for c, d in specs)
    summary = f"Sorted {len(sorted_df)} rows by {order}."
    if str(option(options, "destination", "in_place")) == "new":
        return DataOpResult("new", [(str(option(options, "new_name", "Sorted")), sorted_df)], _report(summary + " Stored in a new worksheet."))
    return DataOpResult("in_place", [("", sorted_df)], _report(summary))


def op_rank(df: pd.DataFrame, options: dict) -> DataOpResult:
    column = str(option(options, "column", "") or "")
    require_columns(df, [column], what="Rank")
    numbers = _numeric(df[column])
    if numbers.notna().sum() == 0:
        raise ProcedureError(f"Rank needs numeric values in '{column}', but none could be read.")

    ranks = numbers.rank(method="average", ascending=not str(option(options, "direction", "ascending")).lower().startswith("desc"))
    out = df.copy()
    target = unique_name([c for c in out.columns if c != option(options, "store_in")], str(option(options, "store_in", f"Rank of {column}")))
    if str(option(options, "store_in", "")) in out.columns:
        target = str(options["store_in"])  # overwrite an existing destination column on purpose
    out[target] = ranks
    ties = int(len(numbers.dropna()) - numbers.dropna().nunique())
    summary = f"Ranked {int(numbers.notna().sum())} values of '{column}' into '{target}'" + (f" — {ties} tied value(s) share an average rank." if ties else ".")
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


def op_delete_rows(df: pd.DataFrame, options: dict) -> DataOpResult:
    rows = parse_row_spec(option(options, "rows", ""), len(df))
    columns = list_option(options, "columns")
    all_columns = not columns or len(set(columns)) == len(df.columns)

    if all_columns:
        if len(rows) >= len(df):
            raise ProcedureError("That would delete every row. Use File > New > New Worksheet for an empty grid instead.")
        out = _clean(df.drop(index=df.index[rows]))
        summary = f"Deleted {len(rows)} row(s) from every column."
        return DataOpResult("in_place", [("", out)], _report(summary))

    # Minitab's "from columns" form: the cells go, and what is below them shifts up, so the other
    # columns keep their rows. The column is padded back to full length with blanks.
    require_columns(df, columns, what="Delete Rows")
    out = df.copy()
    drop = set(rows)
    for column in columns:
        kept = [v for i, v in enumerate(out[column].tolist()) if i not in drop]
        kept += [None] * (len(out) - len(kept))
        out[column] = pd.array(kept, dtype=object)
    summary = f"Deleted {len(rows)} row(s) from {len(columns)} column(s) ({', '.join(columns)}); the values below shifted up."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


def op_erase_variables(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if not columns:
        raise ProcedureError("Choose the columns to erase.")
    require_columns(df, columns, what="Erase Variables")
    out = df.copy()
    for column in columns:
        out[column] = _blank_column(len(out))
    summary = f"Erased the contents of {len(columns)} column(s): {', '.join(columns)}. The columns themselves remain."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


def op_transpose(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if not columns:
        raise ProcedureError("Choose the columns to transpose.")
    require_columns(df, columns, what="Transpose Columns")
    name_column = str(option(options, "name_column", "") or "")
    if name_column:
        require_columns(df, [name_column], what="Transpose Columns")
        labels = [("" if _is_blank(v) else str(v)) for v in df[name_column].tolist()]
    else:
        labels = [f"Row_{i + 1}" for i in range(len(df))]

    taken = {"Variable"}
    headers = []
    for i, label in enumerate(labels):
        headers.append(unique_name(taken, label or f"Row_{i + 1}"))
        taken.add(headers[-1])

    data = {"Variable": columns}
    for j, header in enumerate(headers):
        data[header] = [df[column].iloc[j] for column in columns]
    out = pd.DataFrame(data)

    summary = (
        f"Transposed {len(columns)} column(s) into {len(columns)} row(s) of a new worksheet"
        + (f", named from '{name_column}'." if name_column else ".")
    )
    return DataOpResult("new", [(str(option(options, "new_name", "Transposed")), out)], _report(summary))


def op_display_data(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns") or [str(c) for c in df.columns]
    require_columns(df, columns, what="Display Data")
    rows = parse_row_spec(option(options, "rows", ""), len(df)) if str(option(options, "rows", "") or "").strip() else list(range(len(df)))
    limit = int_option(options, "max_rows", 500, what="Maximum rows") or 500
    shown = rows[:limit]

    widths = {c: max(len(str(c)), 8) for c in columns}
    cells: dict[str, list[str]] = {}
    for column in columns:
        values = []
        for i in shown:
            v = df[column].iloc[i]
            values.append("" if _is_blank(v) else (g(v, 8) if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) else str(v)))
        cells[column] = values
        widths[column] = max(widths[column], *(len(v) for v in values)) if values else widths[column]

    header = "Row  " + "  ".join(str(c).rjust(widths[c]) for c in columns)
    lines = [header, "-" * len(header)]
    for n, i in enumerate(shown):
        lines.append(f"{i + 1:<5}" + "  ".join(cells[c][n].rjust(widths[c]) for c in columns))
    if len(rows) > len(shown):
        lines.append(f"... {len(rows) - len(shown)} more row(s) not shown (raise 'Maximum rows' to see them).")

    summary = f"Displayed {len(shown)} row(s) of {len(columns)} column(s) in the Session Window."
    return DataOpResult("none", [], _report(summary, text="\n".join(lines), title=f"Data Display: {', '.join(columns)}"))


def op_worksheet_info(df: pd.DataFrame, options: dict) -> DataOpResult:
    rows = []
    for column in df.columns:
        series = df[column]
        missing = int(series.map(_is_blank).sum())
        numbers = _numeric(series)
        kind = "numeric" if numbers.notna().sum() == (len(series) - missing) and (len(series) - missing) > 0 else ("empty" if missing == len(series) else "text")
        if pd.api.types.is_datetime64_any_dtype(series):
            kind = "date/time"
        rows.append(
            {
                "Column": str(column),
                "Type": kind,
                "Count": len(series) - missing,
                "Missing": missing,
                "Distinct": int(series.dropna().astype(str).nunique()),
            }
        )
    filled = sum(r["Count"] for r in rows)
    highlights = [
        {"label": "Columns", "value": len(df.columns), "decimals": 0},
        {"label": "Rows", "value": len(df), "decimals": 0},
        {"label": "Cells with data", "value": filled, "decimals": 0},
        {"label": "Missing cells", "value": len(df) * len(df.columns) - filled, "decimals": 0},
    ]
    summary = f"{len(df)} rows × {len(df.columns)} columns; {filled} cell(s) hold data."
    return DataOpResult("none", [], _report(summary, tables=[{"title": "Columns", "rows": rows}], highlights=highlights))


# ---------------------------------------------------------------------------
# Step 2 — reshape: stack / unstack
# ---------------------------------------------------------------------------


def _maybe_new(options: dict, name: str, out: pd.DataFrame, summary: str, *, base: pd.DataFrame | None = None) -> DataOpResult:
    """Stack/unstack output goes either to a new worksheet or is appended to the current one."""
    if str(option(options, "destination", "new")) == "new":
        return DataOpResult("new", [(str(option(options, "new_name", name)), out)], _report(f"{summary} Stored in a new worksheet."))
    if base is None:
        raise ProcedureError("This operation can only write to a new worksheet.")
    merged = base.copy()
    n = max(len(merged), len(out))
    if n > len(merged):
        pad = pd.DataFrame({c: pd.array([None] * (n - len(merged)), dtype=object) for c in merged.columns})
        merged = pd.concat([merged, pad], ignore_index=True)
    for column in out.columns:
        target = unique_name(list(merged.columns), str(column))
        values = out[column].tolist() + [None] * (n - len(out))
        merged[target] = values
    return DataOpResult("in_place", [("", _clean(merged))], _report(f"{summary} Appended to the current worksheet."))


def op_stack_columns(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if len(columns) < 2:
        raise ProcedureError("Stacking needs at least two columns.")
    require_columns(df, columns, what="Stack Columns")

    values: list[Any] = []
    subscripts: list[Any] = []
    omit_blank = bool(option(options, "omit_missing", False))
    use_indices = bool(option(options, "index_subscripts", False))
    for i, column in enumerate(columns):
        for v in df[column].tolist():
            if omit_blank and _is_blank(v):
                continue
            values.append(None if _is_blank(v) else v)
            subscripts.append(i + 1 if use_indices else column)

    value_name = str(option(options, "value_name", "Stacked") or "Stacked")
    data = {value_name: values}
    if bool(option(options, "include_subscripts", True)):
        data[str(option(options, "subscript_name", "Subscripts") or "Subscripts")] = subscripts
    out = pd.DataFrame(data)
    summary = f"Stacked {len(columns)} column(s) into {len(values)} value(s) in '{value_name}'."
    return _maybe_new(options, "Stacked", out, summary, base=df)


def op_stack_blocks(df: pd.DataFrame, options: dict) -> DataOpResult:
    blocks_raw = options.get("blocks") or []
    blocks = [[str(c) for c in (b or []) if c] for b in blocks_raw]
    blocks = [b for b in blocks if b]
    if len(blocks) < 2:
        raise ProcedureError("Stacking blocks needs at least two blocks of columns.")
    width = len(blocks[0])
    if any(len(b) != width for b in blocks):
        raise ProcedureError(f"Every block must hold the same number of columns; the first has {width}, and the others have {', '.join(str(len(b)) for b in blocks[1:])}.")
    for block in blocks:
        require_columns(df, block, what="Stack Blocks of Columns")

    headers = [unique_name([], str(c)) for c in blocks[0]]
    seen: list[str] = []
    headers = []
    for c in blocks[0]:
        headers.append(unique_name(seen, str(c)))
        seen.append(headers[-1])

    pieces = []
    for i, block in enumerate(blocks):
        part = df[block].copy()
        part.columns = headers
        if bool(option(options, "include_subscripts", True)):
            part[str(option(options, "subscript_name", "Subscripts") or "Subscripts")] = (i + 1) if bool(option(options, "index_subscripts", False)) else ", ".join(block)
        pieces.append(part)
    out = _clean(pd.concat(pieces, ignore_index=True))
    summary = f"Stacked {len(blocks)} block(s) of {width} column(s) into {len(out)} rows."
    return _maybe_new(options, "Stacked blocks", out, summary, base=df)


def op_stack_rows(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if len(columns) < 1:
        raise ProcedureError("Choose the columns whose rows should be stacked.")
    require_columns(df, columns, what="Stack Rows")
    rows = parse_row_spec(option(options, "rows", ""), len(df)) if str(option(options, "rows", "") or "").strip() else list(range(len(df)))

    values: list[Any] = []
    row_subs: list[Any] = []
    col_subs: list[Any] = []
    omit_blank = bool(option(options, "omit_missing", False))
    for r in rows:
        for column in columns:
            v = df[column].iloc[r]
            if omit_blank and _is_blank(v):
                continue
            values.append(None if _is_blank(v) else v)
            row_subs.append(r + 1)
            col_subs.append(column)

    value_name = str(option(options, "value_name", "Stacked") or "Stacked")
    data: dict[str, list[Any]] = {value_name: values}
    if bool(option(options, "include_subscripts", True)):
        data[str(option(options, "subscript_name", "Row") or "Row")] = row_subs
        data["Column"] = col_subs
    out = pd.DataFrame(data)
    summary = f"Stacked {len(rows)} row(s) across {len(columns)} column(s) into {len(values)} value(s)."
    return _maybe_new(options, "Stacked rows", out, summary, base=df)


def op_unstack_columns(df: pd.DataFrame, options: dict) -> DataOpResult:
    value_columns = list_option(options, "columns")
    if not value_columns:
        raise ProcedureError("Choose the column (or columns) to unstack.")
    subscript = str(option(options, "subscript_column", "") or "")
    if not subscript:
        raise ProcedureError("Choose the subscripts column that says which group each value belongs to.")
    require_columns(df, [*value_columns, subscript], what="Unstack Columns")

    labels = ["(missing)" if _is_blank(v) else str(v) for v in df[subscript].tolist()]
    groups: list[str] = []
    for label in labels:
        if label not in groups:
            groups.append(label)
    if bool(option(options, "sort_groups", True)):
        groups = sorted(groups)
    if not bool(option(options, "include_missing", False)):
        groups = [gp for gp in groups if gp != "(missing)"]
    if not groups:
        raise ProcedureError(f"'{subscript}' holds no group values to unstack by.")

    series: dict[str, list[Any]] = {}
    taken: list[str] = []
    for value_column in value_columns:
        for group in groups:
            picked = [df[value_column].iloc[i] for i, label in enumerate(labels) if label == group]
            base = f"{value_column}_{group}" if len(value_columns) > 1 else str(group)
            name = unique_name(taken, base)
            taken.append(name)
            series[name] = [None if _is_blank(v) else v for v in picked]

    height = max((len(v) for v in series.values()), default=0)
    out = pd.DataFrame({k: v + [None] * (height - len(v)) for k, v in series.items()})
    summary = f"Unstacked {len(value_columns)} column(s) by '{subscript}' into {len(out.columns)} column(s) across {len(groups)} group(s)."
    return _maybe_new(options, f"Unstacked {value_columns[0]}", out, summary, base=df)


# ---------------------------------------------------------------------------
# Step 3 — worksheet-level operations
# ---------------------------------------------------------------------------


def _subset_mask(df: pd.DataFrame, options: dict) -> tuple[pd.Series, str]:
    mode = str(option(options, "by", "condition"))
    if mode == "rows":
        rows = parse_row_spec(option(options, "rows", ""), len(df))
        mask = pd.Series(False, index=df.index)
        mask.iloc[rows] = True
        return mask, f"rows {option(options, 'rows', '')}"
    joiner = str(option(options, "joiner", "and"))
    conditions = options.get("conditions") or []
    return conditions_mask(df, conditions, joiner), describe_conditions(conditions, joiner)


def op_subset(df: pd.DataFrame, options: dict) -> DataOpResult:
    mask, described = _subset_mask(df, options)
    exclude = str(option(options, "action", "include")) == "exclude"
    keep = ~mask if exclude else mask
    out = _clean(df[keep])
    if out.empty:
        raise ProcedureError(f"No rows {'are left after excluding' if exclude else 'match'} {described}. The worksheet was not changed.")
    verb = "Excluded" if exclude else "Kept"
    summary = f"{verb} rows where {described}: {len(out)} of {len(df)} row(s) in the new worksheet."
    return DataOpResult("new", [(str(option(options, "new_name", "Subset")), out)], _report(summary))


def op_split(df: pd.DataFrame, options: dict) -> DataOpResult:
    by = str(option(options, "by_column", "") or "")
    if not by:
        raise ProcedureError("Choose the By column to split on.")
    require_columns(df, [by], what="Split Worksheet")
    labels = ["(missing)" if _is_blank(v) else str(v) for v in df[by].tolist()]
    groups: list[str] = []
    for label in labels:
        if label not in groups:
            groups.append(label)
    groups = sorted(groups)
    if not bool(option(options, "include_missing", False)):
        groups = [gp for gp in groups if gp != "(missing)"]
    if not groups:
        raise ProcedureError(f"'{by}' holds no values to split on.")
    limit = int_option(options, "max_worksheets", 30, what="Maximum worksheets") or 30
    if len(groups) > limit:
        raise ProcedureError(f"'{by}' has {len(groups)} distinct values, which would create {len(groups)} worksheets. Raise 'Maximum worksheets' past {limit} if that is really what you want.")

    base = str(option(options, "base_name", "Split"))
    drop_by = bool(option(options, "drop_by_column", False))
    frames = []
    for group in groups:
        part = _clean(df[[label == group for label in labels]])
        if drop_by:
            part = part.drop(columns=[by])
        frames.append((f"{base} {group}", part))
    summary = f"Split into {len(frames)} worksheet(s) by '{by}': {', '.join(groups)}."
    return DataOpResult("many", frames, _report(summary))


def op_stack_worksheets(df: pd.DataFrame, options: dict, others: dict[str, pd.DataFrame], names: dict[str, str]) -> DataOpResult:
    ids = list_option(options, "worksheets")
    if len(ids) < 2:
        raise ProcedureError("Choose at least two worksheets to stack.")
    missing = [i for i in ids if i not in others]
    if missing:
        raise ProcedureError("One of the chosen worksheets is no longer open. Close this dialog and try again.")

    source_name = str(option(options, "source_name", "Source") or "Source")
    include_source = bool(option(options, "include_source", True))
    pieces = []
    for dataset_id in ids:
        part = others[dataset_id].copy()
        part.columns = [str(c) for c in part.columns]
        if include_source:
            part[source_name] = names.get(dataset_id, dataset_id)
        pieces.append(part)
    out = _clean(pd.concat(pieces, ignore_index=True, sort=False))
    summary = f"Stacked {len(ids)} worksheet(s) ({', '.join(names.get(i, i) for i in ids)}) into {len(out)} rows × {len(out.columns)} columns, aligning columns by name."
    return DataOpResult("new", [(str(option(options, "new_name", "Stacked worksheets")), out)], _report(summary))


def _key_pairs(options: dict) -> list[tuple[str, str]]:
    pairs = []
    for entry in options.get("keys") or []:
        if not entry:
            continue
        left = str(entry.get("left") or "").strip()
        right = str(entry.get("right") or left).strip()
        if left and right:
            pairs.append((left, right))
    return pairs


def op_merge_match(df: pd.DataFrame, options: dict, others: dict[str, pd.DataFrame], names: dict[str, str]) -> DataOpResult:
    other_id = str(option(options, "worksheet", "") or "")
    if other_id not in others:
        raise ProcedureError("Choose the worksheet to merge with.")
    right = others[other_id].copy()
    right.columns = [str(c) for c in right.columns]

    pairs = _key_pairs(options)
    if not pairs:
        raise ProcedureError("Choose at least one pair of key columns to match on.")
    require_columns(df, [l for l, _ in pairs], what="Merge Worksheets")
    require_columns(right, [r for _, r in pairs], what="Merge Worksheets")

    how = str(option(options, "how", "inner"))
    if how not in ("inner", "left", "outer"):
        raise ProcedureError("Join type must be inner, left or outer.")

    # Match on a text view of each key so 3 and '3' meet — a worksheet column widens to text the
    # moment anyone types into it, and two sheets can easily disagree on which is which.
    left_df = df.copy()
    left_keys, right_keys = [], []
    for i, (l, r) in enumerate(pairs):
        lk, rk = f"__k_l_{i}", f"__k_r_{i}"
        left_df[lk] = _text(left_df[l]).str.strip()
        right[rk] = _text(right[r]).str.strip()
        left_keys.append(lk)
        right_keys.append(rk)

    right_drop = [r for _, r in pairs] if bool(option(options, "drop_duplicate_keys", True)) else []
    merged = left_df.merge(
        right.drop(columns=[c for c in right_drop if c in right.columns]),
        how=how,
        left_on=left_keys,
        right_on=right_keys,
        suffixes=("", f"_{names.get(other_id, 'right')}"),
    )
    merged = merged.drop(columns=[c for c in [*left_keys, *right_keys] if c in merged.columns])
    out = _clean(merged)

    matched = len(out) if how == "inner" else int(out.notna().any(axis=1).sum())
    summary = (
        f"{how.capitalize()} join of this worksheet with '{names.get(other_id, other_id)}' on "
        f"{', '.join(f'{l}={r}' for l, r in pairs)}: {len(df)} + {len(right)} rows in, {len(out)} row(s) out."
    )
    return DataOpResult("new", [(str(option(options, "new_name", "Merged")), out)], _report(summary))


def op_merge_side_by_side(df: pd.DataFrame, options: dict, others: dict[str, pd.DataFrame], names: dict[str, str]) -> DataOpResult:
    ids = list_option(options, "worksheets")
    if not ids:
        raise ProcedureError("Choose at least one other worksheet to place beside this one.")
    frames = [("this worksheet", df)] + [(names.get(i, i), others[i]) for i in ids if i in others]
    height = max(len(f) for _, f in frames)

    data: dict[str, list[Any]] = {}
    for label, frame in frames:
        for column in frame.columns:
            name = unique_name(list(data.keys()), str(column))
            values = frame[column].tolist()
            data[name] = values + [None] * (height - len(values))
    out = pd.DataFrame(data)
    summary = f"Placed {len(frames)} worksheet(s) side by side by row position: {len(out.columns)} column(s) × {height} row(s)."
    return DataOpResult("new", [(str(option(options, "new_name", "Side by side")), out)], _report(summary))


# ---------------------------------------------------------------------------
# Step 4 — copy
# ---------------------------------------------------------------------------


def op_copy_columns(df: pd.DataFrame, options: dict, others: dict[str, pd.DataFrame], names: dict[str, str]) -> DataOpResult:
    columns = list_option(options, "columns")
    if not columns:
        raise ProcedureError("Choose the columns to copy.")
    require_columns(df, columns, what="Copy Columns")

    described = "all rows"
    picked = df
    if bool(option(options, "use_condition", False)):
        mask, described = _subset_mask(df, options)
        if str(option(options, "action", "include")) == "exclude":
            mask = ~mask
            described = f"NOT ({described})"
        picked = df[mask]
    copied = _clean(picked[columns])

    requested = [str(n).strip() for n in (options.get("new_names") or []) if str(n).strip()]
    destination = str(option(options, "destination", "same"))

    if destination == "new":
        out = copied.copy()
        out.columns = [requested[i] if i < len(requested) else str(c) for i, c in enumerate(out.columns)]
        summary = f"Copied {len(out.columns)} column(s) ({described}, {len(out)} row(s)) into a new worksheet."
        return DataOpResult("new", [(str(option(options, "new_name", "Copied columns")), out)], _report(summary))

    if destination == "other":
        other_id = str(option(options, "worksheet", "") or "")
        if other_id not in others:
            raise ProcedureError("Choose the worksheet to copy into.")
        target = others[other_id].copy()
        target.columns = [str(c) for c in target.columns]
        height = max(len(target), len(copied))
        if height > len(target):
            pad = pd.DataFrame({c: pd.array([None] * (height - len(target)), dtype=object) for c in target.columns})
            target = pd.concat([target, pad], ignore_index=True)
        applied = []
        for i, column in enumerate(copied.columns):
            name = unique_name(list(target.columns), requested[i] if i < len(requested) else str(column))
            values = copied[column].tolist()
            target[name] = values + [None] * (height - len(values))
            applied.append(name)
        summary = f"Copied {len(applied)} column(s) ({described}) into '{names.get(other_id, other_id)}' as {', '.join(applied)}."
        return DataOpResult("other_in_place", [("", _clean(target))], _report(summary), target_id=other_id)

    out = df.copy()
    height = max(len(out), len(copied))
    if height > len(out):
        pad = pd.DataFrame({c: pd.array([None] * (height - len(out)), dtype=object) for c in out.columns})
        out = pd.concat([out, pad], ignore_index=True)
    applied = []
    for i, column in enumerate(copied.columns):
        name = unique_name(list(out.columns), requested[i] if i < len(requested) else f"{column}_copy")
        values = copied[column].tolist()
        out[name] = values + [None] * (height - len(values))
        applied.append(name)
    summary = f"Copied {len(applied)} column(s) ({described}) into this worksheet as {', '.join(applied)}."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


def op_copy_worksheet(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns") or [str(c) for c in df.columns]
    require_columns(df, columns, what="Copy Worksheet")
    described = "all rows"
    picked = df
    if bool(option(options, "use_condition", False)):
        mask, described = _subset_mask(df, options)
        if str(option(options, "action", "include")) == "exclude":
            mask = ~mask
            described = f"NOT ({described})"
        picked = df[mask]
    out = _clean(picked[columns])
    summary = f"Duplicated {len(columns)} column(s) × {len(out)} row(s) ({described}) into a new worksheet."
    return DataOpResult("new", [(str(option(options, "new_name", "Copy of worksheet")), out)], _report(summary))


def op_set_columns(df: pd.DataFrame, options: dict) -> DataOpResult:
    """Write literal value lists into named columns — how Copy ▸ Constants to Column lands values
    from the constants store in the worksheet."""
    specs = options.get("columns") or []
    if not specs:
        raise ProcedureError("Nothing to write.")
    out = df.copy()
    height = max([len(out), *[len(s.get("values") or []) for s in specs]])
    if height > len(out):
        pad = pd.DataFrame({c: pd.array([None] * (height - len(out)), dtype=object) for c in out.columns})
        out = pd.concat([out, pad], ignore_index=True)
    applied = []
    for spec in specs:
        values = list(spec.get("values") or [])
        requested = str(spec.get("name") or "C").strip() or "C"
        name = requested if (requested in out.columns and bool(spec.get("overwrite", True))) else unique_name(list(out.columns), requested)
        out[name] = [None if _is_blank(v) else v for v in values] + [None] * (height - len(values))
        applied.append(name)
    summary = f"Wrote {len(applied)} column(s) into the worksheet: {', '.join(applied)}."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary, stored_columns=", ".join(applied)))


# ---------------------------------------------------------------------------
# Step 5 — values & types
# ---------------------------------------------------------------------------

DATE_UNITS = ("year", "quarter", "month", "week", "day", "hour", "minute", "second")
DATE_COMPONENTS = (
    "year",
    "quarter",
    "month",
    "month name",
    "week of year",
    "day of year",
    "day of month",
    "weekday",
    "weekday name",
    "hour",
    "minute",
    "second",
)


def _coerce_to(value: Any, to: str) -> Any:
    if _is_blank(value):
        return None
    if to == "numeric":
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None
    if to == "datetime":
        parsed = pd.to_datetime(str(value).strip(), errors="coerce")
        return None if pd.isna(parsed) else parsed
    return str(value)


def _recode_series(series: pd.Series, options: dict, to: str) -> tuple[pd.Series, int]:
    mappings = [m for m in (options.get("mappings") or []) if m and str(m.get("from", "")).strip() != ""]
    ranges = [r for r in (options.get("ranges") or []) if r]
    others = str(option(options, "others", "keep"))  # keep | missing
    other_value = option(options, "other_value", None)

    lookup = {str(m["from"]).strip(): m.get("to") for m in mappings}
    lookup_lower = {k.lower(): v for k, v in lookup.items()}
    numbers = _numeric(series)

    out: list[Any] = []
    changed = 0
    for i, raw in enumerate(series.tolist()):
        key = "" if _is_blank(raw) else str(raw).strip()
        replacement: Any = None
        hit = False

        if key in lookup:
            replacement, hit = lookup[key], True
        elif key.lower() in lookup_lower:
            replacement, hit = lookup_lower[key.lower()], True
        else:
            n = numbers.iloc[i]
            if not pd.isna(n):
                for r in ranges:
                    low = r.get("low")
                    high = r.get("high")
                    try:
                        lo = float(low) if str(low).strip() != "" and low is not None else -np.inf
                        hi = float(high) if str(high).strip() != "" and high is not None else np.inf
                    except (TypeError, ValueError):
                        raise ProcedureError(f"Recode range bounds must be numbers; got '{low}' and '{high}'.") from None
                    low_ok = n >= lo if r.get("low_inclusive", True) else n > lo
                    high_ok = n <= hi if r.get("high_inclusive", True) else n < hi
                    if low_ok and high_ok:
                        replacement, hit = r.get("to"), True
                        break

        if hit:
            changed += 1
            out.append(_coerce_to(replacement, to))
        elif _is_blank(raw):
            out.append(None)
        elif others == "missing":
            out.append(None)
        elif others == "value":
            out.append(_coerce_to(other_value, to))
        else:
            out.append(_coerce_to(raw, to))

    if to == "numeric":
        return pd.to_numeric(pd.Series(out), errors="coerce"), changed
    if to == "datetime":
        return pd.to_datetime(pd.Series(out), errors="coerce"), changed
    return pd.Series(out, dtype=object), changed


def op_recode(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if not columns:
        raise ProcedureError("Choose the columns to recode.")
    require_columns(df, columns, what="Recode")
    to = str(option(options, "to", "text"))
    if to not in ("numeric", "text", "datetime"):
        raise ProcedureError("Recode target type must be numeric, text or date/time.")
    if not (options.get("mappings") or options.get("ranges")):
        raise ProcedureError("Add at least one old value → new value row (or a range) to recode.")

    out = df.copy()
    same = str(option(options, "destination", "same")) == "same"
    suffix = str(option(options, "suffix", "_recoded") or "_recoded")
    rows = []
    for column in columns:
        recoded, changed = _recode_series(out[column], options, to)
        target = column if same else unique_name(list(out.columns), f"{column}{suffix}")
        out[target] = recoded.values
        rows.append({"Column": column, "Written to": target, "Values recoded": changed, "New type": to})
    total = sum(r["Values recoded"] for r in rows)
    summary = f"Recoded {total} value(s) across {len(columns)} column(s) to {to}."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary, tables=[{"title": "Recode", "rows": rows}]))


def op_recode_conversion_table(df: pd.DataFrame, options: dict, others: dict[str, pd.DataFrame], names: dict[str, str]) -> DataOpResult:
    columns = list_option(options, "columns")
    if not columns:
        raise ProcedureError("Choose the columns to recode.")
    require_columns(df, columns, what="Recode")

    table_id = str(option(options, "table_worksheet", "") or "")
    table_df = others.get(table_id, df) if table_id else df
    old_column = str(option(options, "old_column", "") or "")
    new_column = str(option(options, "new_column", "") or "")
    if not old_column or not new_column:
        raise ProcedureError("Choose the old-value column and the new-value column of the conversion table.")
    require_columns(table_df, [old_column, new_column], what="The conversion table")

    mappings = []
    for old, new in zip(table_df[old_column].tolist(), table_df[new_column].tolist()):
        if _is_blank(old):
            continue
        mappings.append({"from": str(old).strip(), "to": None if _is_blank(new) else new})
    if not mappings:
        raise ProcedureError(f"'{old_column}' in the conversion table holds no values to match on.")

    merged = {**options, "mappings": mappings, "ranges": []}
    result = op_recode(df, merged)
    where = names.get(table_id, "this worksheet")
    result.report["summary"] = f"{result.report['summary']} Conversion table: {old_column} → {new_column} on {where} ({len(mappings)} entries)."
    result.report["conclusion"] = result.report["summary"]
    return result


def op_change_type(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if not columns:
        raise ProcedureError("Choose the columns to convert.")
    require_columns(df, columns, what="Change Data Type")
    to = str(option(options, "to", "numeric"))
    if to not in ("numeric", "text", "datetime"):
        raise ProcedureError("Target type must be numeric, text or date/time.")
    fmt = str(option(options, "date_format", "") or "") or None

    rows = []
    converted: dict[str, pd.Series] = {}
    total_fail = 0
    for column in columns:
        series = df[column]
        filled = int((~series.map(_is_blank)).sum())
        if to == "numeric":
            new = _numeric(series)
        elif to == "datetime":
            new = _to_datetime(series, fmt)
        else:
            new = series.map(lambda v: None if _is_blank(v) else str(v)).astype(object)
        ok = int(new.notna().sum())
        fail = filled - ok
        total_fail += max(0, fail)
        converted[column] = new
        sample = [str(v) for v, keep in zip(series.tolist(), new.isna().tolist()) if keep and not _is_blank(v)][:3]
        rows.append(
            {
                "Column": column,
                "Values": filled,
                "Would parse": ok,
                "Would become missing": max(0, fail),
                "Examples that fail": ", ".join(sample),
            }
        )

    preview = bool(option(options, "preview", False))
    verb = "would convert" if preview else "converted"
    summary = (
        f"Change {', '.join(columns)} to {to}: {verb} {sum(r['Would parse'] for r in rows)} value(s); "
        f"{total_fail} value(s) {'would become' if preview else 'became'} missing."
    )
    report = _report(summary, tables=[{"title": "Conversion preview" if preview else "Conversion", "rows": rows}], preview=preview, failures=total_fail)
    if preview:
        return DataOpResult("none", [], report)

    out = df.copy()
    for column, new in converted.items():
        out[column] = new.values
    return DataOpResult("in_place", [("", _clean(out))], report)


def _component(values: pd.Series, component: str, as_text: bool) -> pd.Series:
    dt = values.dt
    table = {
        "year": dt.year,
        "quarter": dt.quarter,
        "month": dt.month,
        "month name": dt.month_name(),
        "week of year": dt.isocalendar().week.astype("Int64"),
        "day of year": dt.dayofyear,
        "day of month": dt.day,
        "weekday": dt.weekday + 1,
        "weekday name": dt.day_name(),
        "hour": dt.hour,
        "minute": dt.minute,
        "second": dt.second,
    }
    if component not in table:
        raise ProcedureError(f"'{component}' is not a date/time component. Choose from: {', '.join(DATE_COMPONENTS)}.")
    out = table[component]
    if as_text:
        return out.map(lambda v: None if pd.isna(v) else str(v)).astype(object)
    numbers = pd.to_numeric(out, errors="coerce")
    if numbers.notna().sum() == 0 and not as_text:
        # 'month name' has no numeric reading — keep the text rather than a column of blanks.
        return out.map(lambda v: None if pd.isna(v) else str(v)).astype(object)
    return numbers


def op_date_extract(df: pd.DataFrame, options: dict) -> DataOpResult:
    column = str(option(options, "column", "") or "")
    require_columns(df, [column], what="Extract Date/Time")
    components = list_option(options, "components")
    if not components:
        raise ProcedureError("Choose at least one component to extract.")
    parsed = _to_datetime(df[column], str(option(options, "date_format", "") or "") or None)
    if parsed.notna().sum() == 0:
        raise ProcedureError(f"'{column}' holds no values that read as a date or time. Convert it with Data > Change Data Type first, or set an explicit format.")

    as_text = str(option(options, "as", "numeric")) == "text"
    out = df.copy()
    applied = []
    for component in components:
        name = unique_name(list(out.columns), f"{column} {component}")
        out[name] = _component(parsed, component, as_text).values
        applied.append(name)
    summary = f"Extracted {len(applied)} component(s) of '{column}' ({int(parsed.notna().sum())} date(s) read) into {', '.join(applied)}."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


_ROUND_FREQ = {"year": "YS", "quarter": "QS", "month": "MS", "week": "W-MON", "day": "D", "hour": "h", "minute": "min", "second": "s"}


def op_date_round(df: pd.DataFrame, options: dict) -> DataOpResult:
    column = str(option(options, "column", "") or "")
    require_columns(df, [column], what="Round Date/Time")
    unit = str(option(options, "unit", "day"))
    if unit not in DATE_UNITS:
        raise ProcedureError(f"Rounding unit must be one of: {', '.join(DATE_UNITS)}.")
    how = str(option(options, "how", "floor"))
    if how not in ("round", "floor", "ceiling"):
        raise ProcedureError("Choose round, floor (down) or ceiling (up).")

    parsed = _to_datetime(df[column], str(option(options, "date_format", "") or "") or None)
    if parsed.notna().sum() == 0:
        raise ProcedureError(f"'{column}' holds no values that read as a date or time.")

    freq = _ROUND_FREQ[unit]
    if unit in ("day", "hour", "minute", "second"):
        rounded = {"round": parsed.dt.round, "floor": parsed.dt.floor, "ceiling": parsed.dt.ceil}[how](freq)
    else:
        # Calendar units are not fixed-length, so pandas cannot round to them directly — the period
        # start is the floor, and the next period's start is the ceiling.
        periods = parsed.dt.to_period({"year": "Y", "quarter": "Q", "month": "M", "week": "W"}[unit])
        starts = periods.dt.start_time
        if how == "floor":
            rounded = starts
        elif how == "ceiling":
            ends = periods.dt.end_time.dt.normalize() + pd.Timedelta(days=1)
            rounded = starts.where(parsed == starts, ends)
        else:
            ends = periods.dt.end_time
            midpoint = starts + (ends - starts) / 2
            rounded = starts.where(parsed <= midpoint, ends.dt.normalize() + pd.Timedelta(days=1))

    out = df.copy()
    same = str(option(options, "destination", "new")) == "same"
    target = column if same else unique_name(list(out.columns), f"{column} {how} {unit}")
    out[target] = rounded.values
    summary = f"{how.capitalize()}ed {int(parsed.notna().sum())} value(s) of '{column}' to the nearest {unit}, into '{target}'."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


def op_concatenate(df: pd.DataFrame, options: dict) -> DataOpResult:
    columns = list_option(options, "columns")
    if len(columns) < 2:
        raise ProcedureError("Concatenate needs at least two columns.")
    require_columns(df, columns, what="Concatenate")
    separator = option(options, "separator", " ")
    separator = "" if separator is None else str(separator)
    skip_blank = bool(option(options, "skip_missing", True))

    joined = []
    for i in range(len(df)):
        parts = []
        for column in columns:
            v = df[column].iloc[i]
            if _is_blank(v):
                if skip_blank:
                    continue
                parts.append("")
            else:
                parts.append(g(v, 12) if isinstance(v, (float, np.floating)) else str(v))
        joined.append(separator.join(parts) if parts else None)

    out = df.copy()
    target = unique_name(list(out.columns), str(option(options, "new_column", "Concatenated") or "Concatenated"))
    out[target] = pd.array(joined, dtype=object)
    summary = f"Combined {len(columns)} column(s) into '{target}' with separator '{separator}'."
    return DataOpResult("in_place", [("", _clean(out))], _report(summary))


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_SIMPLE: dict[str, Callable[[pd.DataFrame, dict], DataOpResult]] = {
    "sort": op_sort,
    "rank": op_rank,
    "delete_rows": op_delete_rows,
    "erase_variables": op_erase_variables,
    "transpose": op_transpose,
    "display_data": op_display_data,
    "worksheet_info": op_worksheet_info,
    "stack_columns": op_stack_columns,
    "stack_blocks": op_stack_blocks,
    "stack_rows": op_stack_rows,
    "unstack_columns": op_unstack_columns,
    "subset": op_subset,
    "split": op_split,
    "copy_worksheet": op_copy_worksheet,
    "set_columns": op_set_columns,
    "recode": op_recode,
    "change_type": op_change_type,
    "date_extract": op_date_extract,
    "date_round": op_date_round,
    "concatenate": op_concatenate,
}

_CROSS_SHEET: dict[str, Callable[[pd.DataFrame, dict, dict, dict], DataOpResult]] = {
    "stack_worksheets": op_stack_worksheets,
    "merge_match": op_merge_match,
    "merge_side_by_side": op_merge_side_by_side,
    "copy_columns": op_copy_columns,
    "recode_conversion_table": op_recode_conversion_table,
}

OPERATIONS = tuple(sorted([*_SIMPLE.keys(), *_CROSS_SHEET.keys()]))


def compute(
    df: pd.DataFrame,
    operation: str,
    options: dict[str, Any],
    *,
    others: dict[str, pd.DataFrame] | None = None,
    names: dict[str, str] | None = None,
) -> DataOpResult:
    """One entry point for every Data-menu operation.

    `others` maps dataset_id -> DataFrame for the *other* open worksheets, and `names` maps the
    same ids to their display names; only the cross-worksheet operations look at them.
    """
    if operation in _SIMPLE:
        return _SIMPLE[operation](df, options or {})
    if operation in _CROSS_SHEET:
        return _CROSS_SHEET[operation](df, options or {}, others or {}, names or {})
    raise ProcedureError(f"'{operation}' is not a Data operation. Known operations: {', '.join(OPERATIONS)}.")
