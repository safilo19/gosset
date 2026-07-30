"""Calc menu — the Calculator, data generation, random data, probability, resampling and matrices.

Same contract as basic_stats.py / regression_models.py / anova.py: one
`compute(df, procedure, columns, options)` dispatching on `procedure`, results shaped as
tables / highlights / graphs / narrative.

Three things travel back to the frontend rather than being written here, because the store they
belong to lives there (which is what lets them be saved in a .baproj):

  store_columns   [{name, values}]  -> written through the ordinary `set_columns` data operation,
                                       so a Calc result is undoable like any other worksheet edit
  store_constant  {name, value}     -> the K1/K2… store
  store_matrix    {name, rows}      -> the M1/M2… store

Randomness is seeded by `options.seed` when Calc > Set Base has been used, so the same seed gives
the same column twice — the whole purpose of that dialog.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy import stats as st

from backend.core import distributions as dists
from backend.core import expressions as expr
from backend.core import graphs as graphs_core
from backend.core.procedures import (
    ProcedureError,
    ci_text,
    confidence,
    float_option,
    g,
    int_option,
    json_safe,
    list_option,
    option,
    p_text,
    require_columns,
)

PROCEDURES = (
    "calculator",
    "validate_expression",
    "catalogue",
    "column_statistics",
    "row_statistics",
    "standardize",
    "patterned_numbers",
    "patterned_arbitrary",
    "patterned_text",
    "patterned_datetime",
    "mesh_data",
    "indicator_variables",
    "sample_columns",
    "random_data",
    "probability",
    "bootstrap_1sample",
    "bootstrap_2sample",
    "randomization_1mean",
    "randomization_1proportion",
    "randomization_2means",
    "matrix_from_columns",
    "matrix_to_columns",
    "matrix_transpose",
    "matrix_invert",
    "matrix_diagonal",
    "matrix_define",
    "matrix_eigen",
    "matrix_arithmetic",
)

MAX_GENERATED_ROWS = 100_000
MAX_RESAMPLES = 100_000
MAX_MATRIX_CELLS = 250_000


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _rng(options: dict) -> np.random.Generator:
    """Seeded from Calc > Set Base when it has been used, so a run is reproducible."""
    seed = option(options, "seed", None)
    if seed in (None, ""):
        return np.random.default_rng()
    try:
        return np.random.default_rng(int(seed))
    except (TypeError, ValueError):
        raise ProcedureError(f"The base (seed) must be a whole number; got '{seed}'.") from None


def _build_context(df: pd.DataFrame, options: dict) -> expr.Context:
    numeric: dict[str, np.ndarray] = {}
    text: dict[str, np.ndarray] = {}
    for column in df.columns:
        series = df[column]
        numbers = pd.to_numeric(series, errors="coerce")
        filled = series.notna() & (series.astype(str).str.strip() != "")
        if filled.sum() > 0 and numbers.notna().sum() == filled.sum():
            numeric[str(column)] = numbers.to_numpy(dtype=float)
        else:
            text[str(column)] = series.astype(object).where(series.notna(), None).to_numpy()
    constants = {}
    for key, value in (option(options, "constants", None) or {}).items():
        constants[str(key).upper()] = value
    return expr.Context(columns=numeric, text_columns=text, constants=constants, n_rows=len(df))


def _clean_values(values: Any) -> tuple[list[Any], int]:
    """Turn a computed column into worksheet values, counting how many came out missing.

    Division by zero, the log of a negative number and a text value where a number was expected all
    land here as NaN/inf; the worksheet shows them as empty and the caller reports the count, which
    is Minitab's `*` behaviour.
    """
    out: list[Any] = []
    missing = 0
    for value in np.atleast_1d(values):
        if value is None:
            out.append(None)
            missing += 1
            continue
        if isinstance(value, (bool, np.bool_)):
            out.append(int(value))
            continue
        if isinstance(value, (int, float, np.integer, np.floating)):
            number = float(value)
            if not math.isfinite(number):
                out.append(None)
                missing += 1
            else:
                out.append(number)
            continue
        text = str(value)
        if text.strip() == "" or text.lower() == "nan":
            out.append(None)
            missing += 1
        else:
            out.append(text)
    return out, missing


def _scalar(value: Any) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return None if not math.isfinite(number) else number
    return str(value)


def _repeat(values: list[Any], each: int, whole: int) -> list[Any]:
    """Minitab's two repeat controls: repeat each value in turn, then repeat the whole sequence."""
    if each < 1 or whole < 1:
        raise ProcedureError("Both repeat counts must be at least 1.")
    expanded = [v for v in values for _ in range(each)]
    out = expanded * whole
    if len(out) > MAX_GENERATED_ROWS:
        raise ProcedureError(f"That would generate {len(out):,} rows; the limit is {MAX_GENERATED_ROWS:,}.")
    return out


def _names_option(options: dict, key: str = "store_in") -> list[str]:
    """A destination that may name several columns.

    Some of these fields are a real list (the per-column name boxes); others are one text box whose
    hint says "separated by spaces", and a plain list_option would take `inv1 inv2` as a single
    column called "inv1 inv2". Splitting here means every caller gets the same behaviour.
    """
    raw = option(options, key, None)
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for value in values:
        for part in str(value).replace(",", " ").split():
            if part.strip():
                out.append(part.strip())
    return out


def _store_names(options: dict, count: int, what: str) -> list[str]:
    names = _names_option(options)
    if not names:
        raise ProcedureError(f"{what} needs at least one column to store the result in.")
    if len(names) < count:
        # One name and several columns: number them, the way a paste would.
        base = names[0]
        names = [base if i == 0 else f"{base}_{i + 1}" for i in range(count)]
    return names[:count]


def _numeric_column(df: pd.DataFrame, column: str, what: str) -> np.ndarray:
    require_columns(df, [column])
    values = pd.to_numeric(df[column], errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        raise ProcedureError(f"{what} needs numeric values in '{column}', but none could be read.")
    return values


def _histogram_graph(values: np.ndarray, title: str, label: str, marks: list[dict] | None = None) -> dict:
    data = graphs_core.compute(pd.DataFrame({label: values}), "histogram", [label], {})
    data["value_label"] = label
    if marks:
        data["marks"] = marks
    return {"renderer": "resampleHistogram", "title": title, "data": data}


# ---------------------------------------------------------------------------
# 1. The Calculator
# ---------------------------------------------------------------------------


def _catalogue(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Static reference data the dialogs build themselves from — the function browser's contents
    and every distribution with its Minitab-named parameters."""
    return {
        "procedure": "catalogue",
        "functions": expr.function_catalogue(),
        "distributions": dists.catalogue_payload(),
        "tables": [],
        "graphs": [],
        "summary": "Calculator function library and distribution catalogue.",
    }


def _validate_expression(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    outcome = expr.check(str(option(options, "expression", "") or ""), _build_context(df, options))
    return {"procedure": "validate_expression", **outcome, "tables": [], "graphs": [], "summary": outcome.get("error") or "Formula is valid."}


def _calculator(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    source = str(option(options, "expression", "") or "")
    destination = str(option(options, "store_in", "") or "").strip()
    if not destination:
        raise ProcedureError("Choose a column or a constant to store the result in.")
    as_constant = bool(option(options, "as_constant", False)) or destination.upper().startswith("K") and destination[1:].isdigit()

    context = _build_context(df, options)
    result = expr.evaluate(source, context)

    if result.is_scalar:
        value = _scalar(result.value)
        if not as_constant:
            # A single number assigned to a column fills every row with it, which is what a
            # spreadsheet does and what MEAN('x') into a column is asking for.
            values, missing = _clean_values(np.array([result.value] * max(len(df), 1)))
            return _calculator_column_result(source, destination, values, missing, result, len(df), constant_hint=value)
        return {
            "procedure": "calculator",
            "title": f"Calculator: {destination} = {source}",
            "method": "Expression evaluated against the worksheet",
            "expression": source,
            "store_constant": {"name": destination, "value": value},
            "tables": [{"title": "Result", "rows": [{"Stored in": destination, "Value": value, "Expression": source}]}],
            "highlights": [{"label": destination, "value": value if isinstance(value, (int, float)) else None}],
            "graphs": [],
            "conclusion": f"{destination} = {g(value, 8) if isinstance(value, (int, float)) else value}  (from {source})",
            "summary": f"Calculator stored {destination} = {g(value, 8) if isinstance(value, (int, float)) else value}.",
        }

    if as_constant:
        raise ProcedureError(
            f"'{source}' produces one value per row, so it cannot go into the constant {destination}. "
            "Wrap it in a statistic — MEAN(...), SUM(...), MAX(...) — or store it in a column."
        )

    values, missing = _clean_values(result.value)
    if len(values) != len(df):
        # A formula built from an aggregate and a literal can be shorter than the worksheet.
        if len(values) == 1:
            values = values * len(df)
        else:
            raise ProcedureError(f"The formula produced {len(values)} value(s) but the worksheet has {len(df)} row(s).")
    return _calculator_column_result(source, destination, values, missing, result, len(df))


def _calculator_column_result(source: str, destination: str, values: list, missing: int, result, n_rows: int, constant_hint: Any = None) -> dict:
    preview = [{"Row": i + 1, destination: values[i]} for i in range(min(5, len(values)))]
    notes = []
    if missing:
        notes.append(
            f"{missing} of {len(values)} value(s) came out missing — a division by zero, the log of a "
            "negative number or a value that is not a number leaves the cell empty rather than failing the run."
        )
    if constant_hint is not None:
        notes.append(f"The formula gives one value ({g(constant_hint, 8) if isinstance(constant_hint, (int, float)) else constant_hint}); every row was filled with it.")
    return {
        "procedure": "calculator",
        "title": f"Calculator: {destination} = {source}",
        "method": "Expression evaluated against the worksheet",
        "expression": source,
        "store_columns": [{"name": destination, "values": values}],
        "missing": missing,
        "note": " ".join(notes) or None,
        "tables": [
            {"title": "Result", "rows": [{"Stored in": destination, "Rows": len(values), "Missing": missing, "Type": result.kind, "Expression": source}]},
            {"title": "First rows", "rows": preview},
        ],
        "highlights": [
            {"label": "Rows written", "value": len(values), "decimals": 0},
            {"label": "Missing", "value": missing, "decimals": 0, "tone": "negative" if missing else None},
            {"label": "Result type", "value": result.kind, "decimals": 0},
            {"label": "Columns used", "value": len(result.used_columns), "decimals": 0},
        ],
        "graphs": [],
        "conclusion": f"Stored {len(values)} value(s) in '{destination}' from {source}." + (f" {missing} missing." if missing else ""),
        "summary": f"Calculator: {destination} = {source} ({len(values)} rows, {missing} missing).",
    }


# ---------------------------------------------------------------------------
# 2. Column / Row statistics, Standardize
# ---------------------------------------------------------------------------

_STATISTICS: dict[str, tuple[str, Callable[[np.ndarray], float]]] = {
    "sum": ("Sum", lambda v: float(np.sum(v))),
    "mean": ("Mean", lambda v: float(np.mean(v))),
    "stdev": ("Standard deviation", lambda v: float(np.std(v, ddof=1)) if v.size > 1 else float("nan")),
    "variance": ("Variance", lambda v: float(np.var(v, ddof=1)) if v.size > 1 else float("nan")),
    "median": ("Median", lambda v: float(np.median(v))),
    "minimum": ("Minimum", lambda v: float(np.min(v))),
    "maximum": ("Maximum", lambda v: float(np.max(v))),
    "range": ("Range", lambda v: float(np.max(v) - np.min(v))),
    "n": ("N (non-missing)", lambda v: float(v.size)),
    "sum_of_squares": ("Sum of squares", lambda v: float(np.sum(v**2))),
}


def _column_statistics(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the column to summarise.")
    column = columns[0]
    key = str(option(options, "statistic", "mean"))
    if key not in _STATISTICS and key != "n_missing":
        raise ProcedureError(f"Unknown statistic '{key}'. Choose one of: {', '.join([*_STATISTICS, 'n_missing'])}.")

    require_columns(df, [column])
    series = df[column]
    numbers = pd.to_numeric(series, errors="coerce")
    values = numbers.dropna().to_numpy(dtype=float)
    filled = int(series.notna().sum())

    if key == "n_missing":
        label, value = "N missing", float(len(df) - filled)
    else:
        label, fn = _STATISTICS[key]
        if values.size == 0:
            raise ProcedureError(f"'{column}' has no numeric values to summarise.")
        value = fn(values)

    text = f"{label} of {column} = {g(value, 8)}   (N = {values.size}, N missing = {len(df) - values.size})"
    result = {
        "procedure": "column_statistics",
        "title": f"Column Statistics: {label} of {column}",
        "method": "Statistic computed down the column, ignoring missing values",
        "column": column,
        "statistic": key,
        "value": value,
        "text": text,
        "tables": [{"title": "Column statistics", "rows": [{"Column": column, "Statistic": label, "Value": value, "N": int(values.size), "N missing": int(len(df) - values.size)}]}],
        "highlights": [{"label": label, "value": value}, {"label": "N", "value": int(values.size), "decimals": 0}],
        "graphs": [],
        "conclusion": text,
        "summary": f"Column Statistics — {text}",
    }
    destination = str(option(options, "store_in", "") or "").strip()
    if destination:
        result["store_constant"] = {"name": destination, "value": value}
        result["conclusion"] += f"  Stored in {destination}."
    return result


def _row_statistics(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 1:
        raise ProcedureError("Choose the columns to summarise across each row.")
    key = str(option(options, "statistic", "mean"))
    if key not in _STATISTICS and key != "n_missing":
        raise ProcedureError(f"Unknown statistic '{key}'. Choose one of: {', '.join([*_STATISTICS, 'n_missing'])}.")
    require_columns(df, columns)
    destination = str(option(options, "store_in", "") or "").strip()
    if not destination:
        raise ProcedureError("Choose a column to store the row statistic in.")

    block = df[columns].apply(pd.to_numeric, errors="coerce")
    if key == "n_missing":
        label = "N missing"
        computed = block.isna().sum(axis=1).astype(float).to_numpy()
    else:
        label, fn = _STATISTICS[key]
        computed = np.array([fn(row[np.isfinite(row)]) if np.isfinite(row).any() else float("nan") for row in block.to_numpy(dtype=float)])

    values, missing = _clean_values(computed)
    return {
        "procedure": "row_statistics",
        "title": f"Row Statistics: {label} across {', '.join(columns)}",
        "method": "Statistic computed across each row, ignoring missing values in that row",
        "statistic": key,
        "store_columns": [{"name": destination, "values": values}],
        "note": f"{missing} row(s) had no usable value and came out missing." if missing else None,
        "tables": [{"title": "Row statistics", "rows": [{"Statistic": label, "Across": ", ".join(columns), "Stored in": destination, "Rows": len(values), "Missing": missing}]}],
        "highlights": [{"label": "Rows written", "value": len(values), "decimals": 0}, {"label": "Missing", "value": missing, "decimals": 0}],
        "graphs": [],
        "conclusion": f"{label} across {len(columns)} column(s) stored in '{destination}' for {len(values)} row(s).",
        "summary": f"Row Statistics — {label} across {', '.join(columns)} into '{destination}'.",
    }


def _standardize(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the columns to standardize.")
    require_columns(df, columns)
    method = str(option(options, "method", "z"))
    known = ("z", "subtract_mean", "divide_sd", "subtract_divide", "range")
    if method not in known:
        raise ProcedureError(f"Unknown standardize method '{method}'. Expected one of: {', '.join(known)}.")
    suffix = str(option(options, "suffix", "_std") or "_std")
    names = _names_option(options)

    stored = []
    rows = []
    for i, column in enumerate(columns):
        numbers = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        usable = numbers[np.isfinite(numbers)]
        if usable.size == 0:
            raise ProcedureError(f"'{column}' has no numeric values to standardize.")
        mean, sd = float(np.mean(usable)), float(np.std(usable, ddof=1)) if usable.size > 1 else 0.0

        with np.errstate(all="ignore"):
            if method == "z":
                if sd == 0:
                    raise ProcedureError(f"'{column}' is constant, so it has no standard deviation to divide by.")
                out, detail = (numbers - mean) / sd, f"(x − {g(mean, 6)}) / {g(sd, 6)}"
            elif method == "subtract_mean":
                out, detail = numbers - mean, f"x − {g(mean, 6)}"
            elif method == "divide_sd":
                if sd == 0:
                    raise ProcedureError(f"'{column}' is constant, so it has no standard deviation to divide by.")
                out, detail = numbers / sd, f"x / {g(sd, 6)}"
            elif method == "subtract_divide":
                subtract = float_option(options, "subtract", 0.0, what="Value to subtract") or 0.0
                divide = float_option(options, "divide", 1.0, what="Value to divide by")
                if not divide:
                    raise ProcedureError("The value to divide by cannot be zero.")
                out, detail = (numbers - subtract) / divide, f"(x − {g(subtract, 6)}) / {g(divide, 6)}"
            else:
                low = float_option(options, "range_low", 0.0, what="Range minimum") or 0.0
                high = float_option(options, "range_high", 1.0, what="Range maximum")
                if high is None or high <= low:
                    raise ProcedureError(f"The range maximum must be above the minimum; got {g(low)} and {g(high)}.")
                span = float(np.max(usable) - np.min(usable))
                if span == 0:
                    raise ProcedureError(f"'{column}' is constant, so it cannot be scaled to a range.")
                out = low + (numbers - float(np.min(usable))) * (high - low) / span
                detail = f"scaled to [{g(low)}, {g(high)}]"

        target = names[i] if i < len(names) else f"{column}{suffix}"
        values, missing = _clean_values(out)
        stored.append({"name": target, "values": values})
        rows.append({"Column": column, "Stored in": target, "Mean": mean, "StDev": sd, "Transform": detail, "Missing": missing})

    labels = {
        "z": "Subtract mean and divide by standard deviation (z-scores)",
        "subtract_mean": "Subtract the mean",
        "divide_sd": "Divide by the standard deviation",
        "subtract_divide": "Subtract a value and divide by a value",
        "range": "Scale to a range",
    }
    return {
        "procedure": "standardize",
        "title": f"Standardize: {', '.join(columns)}",
        "method": labels[method],
        "store_columns": stored,
        "tables": [{"title": "Standardize", "rows": rows}],
        "highlights": [{"label": "Columns", "value": len(stored), "decimals": 0}, {"label": "Method", "value": labels[method], "decimals": 0}],
        "graphs": [],
        "conclusion": f"{labels[method]} applied to {len(stored)} column(s): {', '.join(r['Stored in'] for r in rows)}.",
        "summary": f"Standardize — {labels[method]} into {', '.join(r['Stored in'] for r in rows)}.",
    }


# ---------------------------------------------------------------------------
# 3. Patterned data, mesh, indicators
# ---------------------------------------------------------------------------


def _pattern_result(procedure: str, title: str, method: str, name: str, values: list[Any], extra_note: str | None = None) -> dict:
    return {
        "procedure": procedure,
        "title": title,
        "method": method,
        "store_columns": [{"name": name, "values": values}],
        "note": extra_note,
        "tables": [{"title": "Generated", "rows": [{"Stored in": name, "Values": len(values), "First": values[0] if values else None, "Last": values[-1] if values else None}]}],
        "highlights": [{"label": "Values generated", "value": len(values), "decimals": 0}],
        "graphs": [],
        "conclusion": f"Generated {len(values)} value(s) into '{name}'." + (f" {extra_note}" if extra_note else ""),
        "summary": f"{title} — {len(values)} value(s) into '{name}'.",
    }


def _repeat_options(options: dict) -> tuple[int, int]:
    each = int_option(options, "repeat_each", 1, what="Repeat each value") or 1
    whole = int_option(options, "repeat_whole", 1, what="Repeat the whole sequence") or 1
    return each, whole


def _patterned_numbers(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    name = str(option(options, "store_in", "") or "").strip()
    if not name:
        raise ProcedureError("Choose a column to store the numbers in.")
    start = float_option(options, "from", 1.0, what="From") or 0.0
    stop = float_option(options, "to", 10.0, what="To")
    step = float_option(options, "step", 1.0, what="In steps of")
    if stop is None:
        raise ProcedureError("Enter the value to count up to.")
    if not step:
        raise ProcedureError("The step cannot be zero.")
    if (stop - start) / step < 0:
        raise ProcedureError(f"A step of {g(step)} never gets from {g(start)} to {g(stop)}. Change the sign of the step.")

    count = int(math.floor((stop - start) / step + 1e-9)) + 1
    if count > MAX_GENERATED_ROWS:
        raise ProcedureError(f"That sequence has {count:,} values; the limit is {MAX_GENERATED_ROWS:,}.")
    base = [start + i * step for i in range(count)]
    each, whole = _repeat_options(options)
    values = _repeat(base, each, whole)
    return _pattern_result(
        "patterned_numbers",
        f"Simple Set of Numbers: {g(start)} to {g(stop)} step {g(step)}",
        "Arithmetic sequence with Minitab's two repeat controls",
        name,
        values,
        f"{count} distinct value(s), each repeated {each}×, whole sequence repeated {whole}×." if (each > 1 or whole > 1) else None,
    )


def _split_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip() != ""]
    text = str(raw or "")
    parts = [p.strip() for p in text.replace("\n", " ").replace("\t", " ").replace(",", " ").split(" ")]
    return [p for p in parts if p]


def _patterned_arbitrary(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    name = str(option(options, "store_in", "") or "").strip()
    if not name:
        raise ProcedureError("Choose a column to store the numbers in.")
    tokens = _split_list(option(options, "values", ""))
    if not tokens:
        raise ProcedureError("Type the list of numbers, separated by spaces or commas.")
    base: list[Any] = []
    for token in tokens:
        try:
            base.append(float(token))
        except ValueError:
            raise ProcedureError(f"'{token}' is not a number. For text labels use Make Patterned Data > Text Values.") from None
    each, whole = _repeat_options(options)
    values = _repeat(base, each, whole)
    return _pattern_result("patterned_arbitrary", f"Arbitrary Set of Numbers ({len(base)} values)", "Typed list with Minitab's two repeat controls", name, values)


def _patterned_text(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    name = str(option(options, "store_in", "") or "").strip()
    if not name:
        raise ProcedureError("Choose a column to store the labels in.")
    raw = option(options, "values", "")
    # Text labels can contain spaces, so only commas and newlines separate them.
    base = [p.strip() for p in str(raw).replace("\n", ",").split(",") if p.strip()] if not isinstance(raw, list) else [str(v) for v in raw]
    if not base:
        raise ProcedureError("Type the list of labels, one per line or separated by commas.")
    each, whole = _repeat_options(options)
    values = _repeat(base, each, whole)
    return _pattern_result("patterned_text", f"Text Values ({len(base)} labels)", "Typed labels with Minitab's two repeat controls", name, values)


_DATE_STEPS = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS", "hour": "h", "minute": "min", "second": "s"}


def _patterned_datetime(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    name = str(option(options, "store_in", "") or "").strip()
    if not name:
        raise ProcedureError("Choose a column to store the dates in.")
    mode = str(option(options, "mode", "simple"))
    each, whole = _repeat_options(options)

    if mode == "arbitrary":
        raw = option(options, "values", "")
        tokens = [p.strip() for p in str(raw).replace("\n", ",").split(",") if p.strip()] if not isinstance(raw, list) else [str(v) for v in raw]
        if not tokens:
            raise ProcedureError("Type the list of dates, one per line or separated by commas.")
        parsed = pd.to_datetime(pd.Series(tokens), errors="coerce")
        bad = [t for t, ok in zip(tokens, parsed.notna()) if not ok]
        if bad:
            raise ProcedureError(f"These do not read as dates: {', '.join(bad[:5])}.")
        base = [d.strftime("%Y-%m-%d %H:%M:%S") if (d.hour or d.minute or d.second) else d.strftime("%Y-%m-%d") for d in parsed]
        label = f"Arbitrary Set of Date/Time Values ({len(base)} dates)"
    else:
        start_raw, stop_raw = option(options, "from", None), option(options, "to", None)
        if not start_raw or not stop_raw:
            raise ProcedureError("Enter both the first and the last date.")
        start, stop = pd.to_datetime(start_raw, errors="coerce"), pd.to_datetime(stop_raw, errors="coerce")
        if pd.isna(start) or pd.isna(stop):
            raise ProcedureError(f"'{start_raw}' and '{stop_raw}' must both read as dates (for example 2024-01-31).")
        unit = str(option(options, "unit", "day"))
        if unit not in _DATE_STEPS:
            raise ProcedureError(f"Unknown step unit '{unit}'. Expected one of: {', '.join(_DATE_STEPS)}.")
        count = int_option(options, "step_count", 1, what="Step size") or 1
        if count < 1:
            raise ProcedureError("The step size must be at least 1.")
        if stop < start:
            raise ProcedureError("The last date must not be before the first.")
        freq = f"{count}{_DATE_STEPS[unit]}"
        try:
            stamps = pd.date_range(start=start, end=stop, freq=freq)
        except Exception as err:  # noqa: BLE001
            raise ProcedureError(f"That date sequence could not be generated: {err}") from err
        if len(stamps) == 0:
            raise ProcedureError("That range and step produce no dates.")
        if len(stamps) > MAX_GENERATED_ROWS:
            raise ProcedureError(f"That would generate {len(stamps):,} dates; the limit is {MAX_GENERATED_ROWS:,}.")
        timed = unit in ("hour", "minute", "second")
        base = [d.strftime("%Y-%m-%d %H:%M:%S") if timed else d.strftime("%Y-%m-%d") for d in stamps]
        label = f"Simple Set of Date/Time Values ({len(base)} × {count} {unit})"

    values = _repeat(base, each, whole)
    return _pattern_result("patterned_datetime", label, "Date sequence with Minitab's two repeat controls", name, values)


def _mesh_data(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    names = _names_option(options) or ["X", "Y"]
    if len(names) < 2:
        names = [names[0], f"{names[0]}_Y"]

    def axis(prefix: str, default_to: float) -> np.ndarray:
        start = float_option(options, f"{prefix}_from", 0.0, what=f"{prefix.upper()} from") or 0.0
        stop = float_option(options, f"{prefix}_to", default_to, what=f"{prefix.upper()} to")
        step = float_option(options, f"{prefix}_step", 1.0, what=f"{prefix.upper()} step")
        if stop is None or not step:
            raise ProcedureError(f"The {prefix.upper()} axis needs a 'to' value and a non-zero step.")
        if (stop - start) / step < 0:
            raise ProcedureError(f"A {prefix.upper()} step of {g(step)} never gets from {g(start)} to {g(stop)}.")
        count = int(math.floor((stop - start) / step + 1e-9)) + 1
        return np.array([start + i * step for i in range(count)], dtype=float)

    xs, ys = axis("x", 10.0), axis("y", 10.0)
    total = xs.size * ys.size
    if total > MAX_GENERATED_ROWS:
        raise ProcedureError(f"That mesh has {total:,} points ({xs.size} × {ys.size}); the limit is {MAX_GENERATED_ROWS:,}.")
    grid_x, grid_y = np.meshgrid(xs, ys)
    x_values, _ = _clean_values(grid_x.ravel())
    y_values, _ = _clean_values(grid_y.ravel())

    return {
        "procedure": "mesh_data",
        "title": f"Mesh Data: {xs.size} × {ys.size}",
        "method": "Every combination of the two axes, ready for a contour or surface plot",
        "store_columns": [{"name": names[0], "values": x_values}, {"name": names[1], "values": y_values}],
        "tables": [{"title": "Mesh", "rows": [{"X column": names[0], "X points": int(xs.size), "Y column": names[1], "Y points": int(ys.size), "Rows": int(total)}]}],
        "highlights": [{"label": "Grid points", "value": int(total), "decimals": 0}, {"label": "X points", "value": int(xs.size), "decimals": 0}, {"label": "Y points", "value": int(ys.size), "decimals": 0}],
        "graphs": [],
        "conclusion": f"Generated a {xs.size} × {ys.size} mesh ({total} rows) into '{names[0]}' and '{names[1]}'.",
        "summary": f"Mesh Data — {xs.size} × {ys.size} grid into '{names[0]}' and '{names[1]}'.",
    }


def _indicator_variables(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the categorical column to dummy-code.")
    column = columns[0]
    require_columns(df, [column])
    labels = df[column].astype("object")
    labels = labels.where(labels.notna() & (labels.astype(str).str.strip() != ""), None)
    levels = sorted({str(v) for v in labels if v is not None})
    if len(levels) < 2:
        raise ProcedureError(f"'{column}' has {len(levels)} level in the worksheet — there is nothing to dummy-code.")
    if len(levels) > 60:
        raise ProcedureError(f"'{column}' has {len(levels)} levels; that is too many indicator columns to create.")
    drop_first = bool(option(options, "drop_first", False))
    emit = levels[1:] if drop_first else levels

    stored = []
    for level in emit:
        values = [None if v is None else (1 if str(v) == level else 0) for v in labels]
        stored.append({"name": f"{column}_{level}", "values": values})
    return {
        "procedure": "indicator_variables",
        "title": f"Indicator Variables for {column}",
        "method": "One 0/1 column per level" + (f"; '{levels[0]}' left out as the reference level" if drop_first else ""),
        "store_columns": stored,
        "tables": [{"title": "Indicator variables", "rows": [{"Level": level, "Column": f"{column}_{level}", "Rows with 1": int(sum(1 for v in labels if v is not None and str(v) == level))} for level in emit]}],
        "highlights": [{"label": "Levels", "value": len(levels), "decimals": 0}, {"label": "Columns created", "value": len(stored), "decimals": 0}],
        "graphs": [],
        "conclusion": f"Created {len(stored)} indicator column(s) for {column}: {', '.join(s['name'] for s in stored)}.",
        "summary": f"Indicator Variables — {len(stored)} column(s) for {column}.",
    }


# ---------------------------------------------------------------------------
# 4. Random data
# ---------------------------------------------------------------------------


def _sample_columns(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the columns to sample from.")
    require_columns(df, columns)
    count = int_option(options, "rows", 10, what="Number of rows to sample")
    if count is None or count < 1:
        raise ProcedureError("Sample at least one row.")
    replace = bool(option(options, "replace", False))
    if not replace and count > len(df):
        raise ProcedureError(f"Sampling {count} rows without replacement needs at least {count} rows; the worksheet has {len(df)}.")

    rng = _rng(options)
    picks = rng.choice(len(df), size=count, replace=replace)
    names = _names_option(options)
    stored = []
    for i, column in enumerate(columns):
        target = names[i] if i < len(names) else f"{column}_sample"
        values, _ = _clean_values(df[column].to_numpy()[picks])
        stored.append({"name": target, "values": values})
    return {
        "procedure": "sample_columns",
        "title": f"Sample From Columns: {count} row(s)",
        "method": f"Rows drawn {'with' if replace else 'without'} replacement" + (f", seeded with base {option(options, 'seed', None)}" if option(options, "seed", None) not in (None, "") else ""),
        "store_columns": stored,
        "tables": [{"title": "Sample", "rows": [{"Source": c, "Stored in": s["name"], "Rows": count} for c, s in zip(columns, stored)]}],
        "highlights": [{"label": "Rows sampled", "value": count, "decimals": 0}, {"label": "Replacement", "value": "yes" if replace else "no", "decimals": 0}],
        "graphs": [],
        "conclusion": f"Sampled {count} row(s) {'with' if replace else 'without'} replacement from {', '.join(columns)}.",
        "summary": f"Sample From Columns — {count} row(s) into {', '.join(s['name'] for s in stored)}.",
    }


def _random_data(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    name = str(option(options, "distribution", "normal"))
    rows = int_option(options, "rows", 100, what="Number of rows")
    if rows is None or rows < 1:
        raise ProcedureError("Generate at least one row.")
    if rows > MAX_GENERATED_ROWS:
        raise ProcedureError(f"That would generate {rows:,} rows; the limit is {MAX_GENERATED_ROWS:,}.")
    params = option(options, "parameters", None) or {}
    rng = _rng(options)
    seed = option(options, "seed", None)

    if name == "multivariate_normal":
        return _random_multivariate(df, options, rng, rows, seed)
    if name == "discrete":
        return _random_discrete(df, options, rng, rows, seed)

    dist = dists.get(name)
    frozen = dists.frozen(name, params)
    targets = _store_names(options, max(1, len(_names_option(options)) or 1), "Random Data")
    stored = []
    for target in targets:
        draws = frozen.rvs(size=rows, random_state=rng)
        values, _ = _clean_values(np.asarray(draws, dtype=float))
        stored.append({"name": target, "values": values})

    label = dist.describe(params)
    return {
        "procedure": "random_data",
        "title": f"Random Data: {rows} row(s) from {label}",
        "method": f"numpy/scipy draw from {label}" + (f", seeded with base {seed}" if seed not in (None, "") else " (no base set — a different sample every run)"),
        "store_columns": stored,
        "distribution": name,
        "tables": [{"title": "Random data", "rows": [{"Distribution": label, "Rows": rows, "Columns": ", ".join(s["name"] for s in stored), "Base (seed)": seed if seed not in (None, "") else "not set"}]}],
        "highlights": [{"label": "Rows", "value": rows, "decimals": 0}, {"label": "Columns", "value": len(stored), "decimals": 0}, {"label": "Base", "value": (seed if seed not in (None, "") else "not set"), "decimals": 0}],
        "graphs": [],
        "conclusion": f"Generated {rows} row(s) from {label} into {', '.join(s['name'] for s in stored)}." + ("" if seed not in (None, "") else " No base is set, so this sample will differ next time — use Calc > Set Base to make it repeatable."),
        "summary": f"Random Data — {rows} row(s) from {label}.",
    }


def _random_multivariate(df: pd.DataFrame, options: dict, rng, rows: int, seed) -> dict:
    means = [float(v) for v in _split_list(option(options, "mean_vector", ""))] if option(options, "mean_vector", "") else []
    matrix = option(options, "covariance", None)
    if not means:
        raise ProcedureError("Enter the mean vector, for example: 0 0")
    if not matrix:
        raise ProcedureError("Choose or type the covariance matrix.")
    cov = np.asarray(matrix, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ProcedureError(f"The covariance matrix must be square; it is {cov.shape[0]}×{cov.shape[1] if cov.ndim > 1 else 1}.")
    if cov.shape[0] != len(means):
        raise ProcedureError(f"The mean vector has {len(means)} value(s) but the covariance matrix is {cov.shape[0]}×{cov.shape[0]}.")
    eigenvalues = np.linalg.eigvalsh((cov + cov.T) / 2)
    if float(np.min(eigenvalues)) < -1e-8:
        raise ProcedureError("The covariance matrix is not positive semi-definite, so it cannot describe a distribution.")

    draws = rng.multivariate_normal(np.asarray(means, dtype=float), cov, size=rows)
    targets = _store_names(options, cov.shape[0], "Multivariate Normal")
    stored = []
    for i, target in enumerate(targets):
        values, _ = _clean_values(draws[:, i])
        stored.append({"name": target, "values": values})
    return {
        "procedure": "random_data",
        "title": f"Random Data: {rows} row(s) from a {cov.shape[0]}-variate normal",
        "method": f"numpy multivariate_normal" + (f", seeded with base {seed}" if seed not in (None, "") else ""),
        "store_columns": stored,
        "tables": [
            {"title": "Random data", "rows": [{"Distribution": f"Multivariate Normal ({cov.shape[0]} variables)", "Rows": rows, "Columns": ", ".join(t for t in targets), "Base (seed)": seed if seed not in (None, "") else "not set"}]},
            {"title": "Sample means", "rows": [{"Column": t, "Requested mean": means[i], "Sample mean": float(np.mean(draws[:, i]))} for i, t in enumerate(targets)]},
        ],
        "highlights": [{"label": "Rows", "value": rows, "decimals": 0}, {"label": "Variables", "value": cov.shape[0], "decimals": 0}],
        "graphs": [],
        "conclusion": f"Generated {rows} row(s) from a {cov.shape[0]}-variate normal into {', '.join(targets)}.",
        "summary": f"Random Data — multivariate normal, {rows} row(s).",
    }


def _random_discrete(df: pd.DataFrame, options: dict, rng, rows: int, seed) -> dict:
    value_column = str(option(options, "value_column", "") or "")
    prob_column = str(option(options, "probability_column", "") or "")
    if not value_column or not prob_column:
        raise ProcedureError("A discrete distribution needs a column of values and a column of probabilities.")
    require_columns(df, [value_column, prob_column])
    frame = pd.DataFrame({"v": df[value_column], "p": pd.to_numeric(df[prob_column], errors="coerce")}).dropna()
    if frame.empty:
        raise ProcedureError("No usable value/probability pairs were found in those columns.")
    probabilities = frame["p"].to_numpy(dtype=float)
    if np.any(probabilities < 0):
        raise ProcedureError("Probabilities cannot be negative.")
    total = float(probabilities.sum())
    if total <= 0:
        raise ProcedureError("The probabilities add up to zero.")
    if abs(total - 1.0) > 1e-6:
        probabilities = probabilities / total

    picks = rng.choice(len(frame), size=rows, p=probabilities)
    targets = _store_names(options, max(1, len(_names_option(options)) or 1), "Discrete")
    source = frame["v"].to_numpy()
    stored = []
    for target in targets:
        values, _ = _clean_values(source[rng.choice(len(frame), size=rows, p=probabilities)] if target != targets[0] else source[picks])
        stored.append({"name": target, "values": values})
    return {
        "procedure": "random_data",
        "title": f"Random Data: {rows} row(s) from a discrete distribution",
        "method": f"Values from '{value_column}' with probabilities from '{prob_column}'" + (f", renormalised (they summed to {g(total, 6)})" if abs(total - 1.0) > 1e-6 else "") + (f", seeded with base {seed}" if seed not in (None, "") else ""),
        "store_columns": stored,
        "tables": [{"title": "Discrete distribution", "rows": [{"Value": v, "Probability": float(p)} for v, p in zip(frame["v"], probabilities)]}],
        "highlights": [{"label": "Rows", "value": rows, "decimals": 0}, {"label": "Distinct values", "value": len(frame), "decimals": 0}],
        "graphs": [],
        "conclusion": f"Generated {rows} row(s) from {len(frame)} discrete value(s) into {', '.join(s['name'] for s in stored)}.",
        "summary": f"Random Data — discrete, {rows} row(s).",
    }


# ---------------------------------------------------------------------------
# 5. Probability distributions
# ---------------------------------------------------------------------------


def _probability(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    name = str(option(options, "distribution", "normal"))
    mode = str(option(options, "mode", "pdf"))
    if mode not in ("pdf", "cdf", "icdf"):
        raise ProcedureError("Choose probability density, cumulative probability or inverse cumulative probability.")
    params = option(options, "parameters", None) or {}
    dist = dists.get(name)
    frozen = dists.frozen(name, params)
    label = dist.describe(params)

    input_column = str(option(options, "input_column", "") or "")
    single = option(options, "input_value", None)
    if input_column:
        require_columns(df, [input_column])
        inputs = pd.to_numeric(df[input_column], errors="coerce").to_numpy(dtype=float)
        source = f"column '{input_column}'"
    elif single not in (None, ""):
        inputs = np.array([float_option(options, "input_value", None, what="Input value")], dtype=float)
        source = "a single value"
    else:
        raise ProcedureError("Enter a value, or choose a column of values.")

    if mode == "icdf" and np.any((inputs < 0) | (inputs > 1)) and np.isfinite(inputs).any():
        raise ProcedureError("An inverse cumulative probability takes probabilities between 0 and 1.")

    with np.errstate(all="ignore"):
        if mode == "pdf":
            out = frozen.pmf(inputs) if dist.discrete else frozen.pdf(inputs)
            heading = "Probability" if dist.discrete else "Density"
        elif mode == "cdf":
            out = frozen.cdf(inputs)
            heading = "Cumulative probability"
        else:
            out = frozen.ppf(inputs)
            heading = "Inverse cumulative"

    mode_label = {"pdf": "Probability density" if not dist.discrete else "Probability mass", "cdf": "Cumulative probability", "icdf": "Inverse cumulative probability"}[mode]
    graphs = []
    if bool(option(options, "plot", False)):
        plot_options = {"distribution": name, "parameters": params, "curve": "cdf" if mode == "cdf" else "pdf"}
        marker = float(inputs[0]) if inputs.size and np.isfinite(inputs[0]) else None
        if mode == "icdf" and np.isfinite(out).any():
            marker = float(np.atleast_1d(out)[0])
        if marker is not None:
            plot_options["shade_to"] = marker
        try:
            graphs.append({"renderer": "distribution", "title": f"{label} — {mode_label}", "data": graphs_core.compute(df, "distribution", [], plot_options)})
        except Exception:  # noqa: BLE001 - the plot is a bonus; never let it fail the calculation
            graphs = []

    result: dict[str, Any] = {
        "procedure": "probability",
        "title": f"{mode_label}: {label}",
        "method": f"{mode_label} of {label}, evaluated at {source}",
        "distribution": name,
        "mode": mode,
        "graphs": graphs,
    }

    if input_column:
        destination = str(option(options, "store_in", "") or "").strip()
        values, missing = _clean_values(out)
        if destination:
            result["store_columns"] = [{"name": destination, "values": values}]
        preview_rows = [{"x": _scalar(inputs[i]), heading: values[i]} for i in range(min(10, len(values)))]
        result.update(
            {
                "tables": [{"title": f"{mode_label} (first {len(preview_rows)} of {len(values)})", "rows": preview_rows}],
                "highlights": [{"label": "Values", "value": len(values), "decimals": 0}, {"label": "Missing", "value": missing, "decimals": 0}],
                "note": f"Stored in '{destination}'." if destination else "No destination column was given, so the values are shown here only.",
                "conclusion": f"{mode_label} of {label} for {len(values)} value(s) from '{input_column}'." + (f" Stored in '{destination}'." if destination else ""),
                "summary": f"{mode_label} — {label}, {len(values)} value(s).",
            }
        )
        return result

    x = _scalar(inputs[0])
    y = _scalar(np.atleast_1d(out)[0])
    text = f"{label}\n{'x':>16}  {heading}\n{g(x, 8):>16}  {g(y, 8)}"
    result.update(
        {
            "text": text,
            "value": y,
            "tables": [{"title": mode_label, "rows": [{"Distribution": label, "x": x, heading: y}]}],
            "highlights": [{"label": heading, "value": y}, {"label": "x", "value": x}],
            "conclusion": f"{mode_label} of {label} at {g(x, 8)} is {g(y, 8)}.",
            "summary": f"{mode_label} — {label} at {g(x, 8)} = {g(y, 8)}.",
        }
    )
    destination = str(option(options, "store_in", "") or "").strip()
    if destination:
        result["store_constant"] = {"name": destination, "value": y}
        result["conclusion"] += f" Stored in {destination}."
    return result


# ---------------------------------------------------------------------------
# 6. Resampling
# ---------------------------------------------------------------------------

_RESAMPLE_STATS: dict[str, tuple[str, Callable[[np.ndarray], float]]] = {
    "mean": ("mean", lambda v: float(np.mean(v))),
    "median": ("median", lambda v: float(np.median(v))),
    "stdev": ("standard deviation", lambda v: float(np.std(v, ddof=1)) if v.size > 1 else float("nan")),
    "sum": ("sum", lambda v: float(np.sum(v))),
    "variance": ("variance", lambda v: float(np.var(v, ddof=1)) if v.size > 1 else float("nan")),
    "minimum": ("minimum", lambda v: float(np.min(v))),
    "maximum": ("maximum", lambda v: float(np.max(v))),
    "range": ("range", lambda v: float(np.max(v) - np.min(v))),
}


def _resample_count(options: dict) -> int:
    count = int_option(options, "resamples", 1000, what="Number of resamples") or 1000
    if count < 50:
        raise ProcedureError("Use at least 50 resamples — fewer than that gives a distribution too coarse to read.")
    if count > MAX_RESAMPLES:
        raise ProcedureError(f"{count:,} resamples is more than the limit of {MAX_RESAMPLES:,}.")
    return count


def _percentile_ci(draws: np.ndarray, conf: float) -> tuple[float, float]:
    alpha = 1 - conf
    return float(np.percentile(draws, 100 * alpha / 2)), float(np.percentile(draws, 100 * (1 - alpha / 2)))


def _resample_result(procedure: str, title: str, method: str, observed: float, observed_label: str, draws: np.ndarray, options: dict, extra_rows: list[dict], conclusion_extra: str, marks: list[dict]) -> dict:
    conf = confidence(options)
    seed = option(options, "seed", None)
    se = float(np.std(draws, ddof=1))
    low, high = _percentile_ci(draws, conf)
    rows = [
        {"Statistic": observed_label, "Observed": observed, "Bootstrap mean": float(np.mean(draws)), "Bootstrap SE": se, f"{conf * 100:g}% percentile CI": ci_text(low, high, 6), "Resamples": int(draws.size)},
    ]
    return {
        "procedure": procedure,
        "title": title,
        "method": method + (f"; base (seed) {seed}" if seed not in (None, "") else "; no base set, so this run will not repeat exactly"),
        "observed": observed,
        "bootstrap_se": se,
        "ci": [low, high],
        "confidence_level": conf,
        "resamples": int(draws.size),
        "tables": [{"title": "Resampling summary", "rows": rows}, *extra_rows],
        "highlights": [
            {"label": f"Observed {observed_label}", "value": observed},
            {"label": "Bootstrap SE", "value": se},
            {"label": f"{conf * 100:g}% CI low", "value": low},
            {"label": f"{conf * 100:g}% CI high", "value": high},
        ],
        "graphs": [_histogram_graph(draws, title, "resampled statistic", marks)],
        "conclusion": conclusion_extra,
        "summary": f"{title} — {conclusion_extra}",
    }


def _bootstrap_1sample(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the column to bootstrap.")
    column = columns[0]
    key = str(option(options, "statistic", "mean"))
    if key == "proportion":
        return _bootstrap_proportion(df, column, options)
    if key not in _RESAMPLE_STATS:
        raise ProcedureError(f"Unknown statistic '{key}'. Choose one of: {', '.join([*_RESAMPLE_STATS, 'proportion'])}.")
    label, fn = _RESAMPLE_STATS[key]

    sample = _numeric_column(df, column, "Bootstrapping")
    if sample.size < 2:
        raise ProcedureError(f"'{column}' has only {sample.size} usable value; bootstrapping needs at least 2.")
    count = _resample_count(options)
    rng = _rng(options)
    conf = confidence(options)

    picks = rng.integers(0, sample.size, size=(count, sample.size))
    draws = np.array([fn(sample[row]) for row in picks], dtype=float)
    observed = fn(sample)
    low, high = _percentile_ci(draws, conf)
    return _resample_result(
        "bootstrap_1sample",
        f"Bootstrapping for the {label} of {column}",
        f"{count:,} resamples of {sample.size} value(s) drawn with replacement",
        observed,
        label,
        draws,
        options,
        [{"title": "Sample", "rows": [{"Column": column, "N": int(sample.size), f"Observed {label}": observed}]}],
        f"Observed {label} of {column} = {g(observed, 6)}; bootstrap SE {g(float(np.std(draws, ddof=1)), 5)}, "
        f"{conf * 100:g}% percentile CI {ci_text(low, high, 6)} from {count:,} resamples.",
        [{"value": observed, "label": f"observed {label}", "color": "danger"}],
    )


def _bootstrap_proportion(df: pd.DataFrame, column: str, options: dict) -> dict:
    require_columns(df, [column])
    event = option(options, "event", None)
    series = df[column].astype(object)
    series = series[series.notna() & (series.astype(str).str.strip() != "")]
    if series.empty:
        raise ProcedureError(f"'{column}' has no values to bootstrap.")
    labels = series.astype(str).to_numpy()
    if event in (None, ""):
        distinct = sorted(set(labels))
        if len(distinct) != 2:
            raise ProcedureError(f"'{column}' has {len(distinct)} distinct value(s). Choose which one counts as the event.")
        event = distinct[-1]
    indicator = (labels == str(event)).astype(float)

    count = _resample_count(options)
    rng = _rng(options)
    conf = confidence(options)
    picks = rng.integers(0, indicator.size, size=(count, indicator.size))
    draws = indicator[picks].mean(axis=1)
    observed = float(indicator.mean())
    low, high = _percentile_ci(draws, conf)
    return _resample_result(
        "bootstrap_1sample",
        f"Bootstrapping for the proportion of {event} in {column}",
        f"{count:,} resamples of {indicator.size} value(s) drawn with replacement",
        observed,
        f"proportion of '{event}'",
        draws,
        options,
        [{"title": "Sample", "rows": [{"Column": column, "Event": str(event), "N": int(indicator.size), "Events": int(indicator.sum()), "Observed proportion": observed}]}],
        f"Observed proportion of '{event}' = {g(observed, 6)} ({int(indicator.sum())} of {indicator.size}); "
        f"{conf * 100:g}% percentile CI {ci_text(low, high, 6)} from {count:,} resamples.",
        [{"value": observed, "label": "observed proportion", "color": "danger"}],
    )


def _two_samples(df: pd.DataFrame, columns: list[str], options: dict, what: str) -> tuple[str, np.ndarray, str, np.ndarray]:
    layout = str(option(options, "layout", "one_column"))
    if layout == "two_columns":
        if len(columns) < 2:
            raise ProcedureError(f"{what} with samples in two columns needs both columns.")
        return columns[0], _numeric_column(df, columns[0], what), columns[1], _numeric_column(df, columns[1], what)
    if len(columns) < 2:
        raise ProcedureError(f"{what} with samples in one column needs both the value column and the group column.")
    value_column, group_column = columns[0], columns[1]
    require_columns(df, [value_column, group_column])
    frame = pd.DataFrame({"v": pd.to_numeric(df[value_column], errors="coerce"), "g": df[group_column].astype(object)}).dropna()
    frame = frame[frame["g"].astype(str).str.strip() != ""]
    groups = sorted(frame["g"].astype(str).unique().tolist())
    if len(groups) != 2:
        raise ProcedureError(f"'{group_column}' has {len(groups)} group(s); {what} needs exactly 2.")
    a = frame.loc[frame["g"].astype(str) == groups[0], "v"].to_numpy(dtype=float)
    b = frame.loc[frame["g"].astype(str) == groups[1], "v"].to_numpy(dtype=float)
    return groups[0], a, groups[1], b


def _bootstrap_2sample(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    label_a, a, label_b, b = _two_samples(df, columns, options, "Bootstrapping for 2-sample means")
    if a.size < 2 or b.size < 2:
        raise ProcedureError("Each sample needs at least 2 values.")
    count = _resample_count(options)
    rng = _rng(options)
    conf = confidence(options)

    draws = np.array(
        [float(np.mean(a[rng.integers(0, a.size, a.size)]) - np.mean(b[rng.integers(0, b.size, b.size)])) for _ in range(count)],
        dtype=float,
    )
    observed = float(np.mean(a) - np.mean(b))
    low, high = _percentile_ci(draws, conf)
    excludes_zero = not (low <= 0 <= high)
    return _resample_result(
        "bootstrap_2sample",
        f"Bootstrapping for the difference in means: {label_a} − {label_b}",
        f"{count:,} resamples, each sample drawn with replacement at its own size",
        observed,
        "difference in means",
        draws,
        options,
        [{"title": "Samples", "rows": [{"Sample": label_a, "N": int(a.size), "Mean": float(np.mean(a))}, {"Sample": label_b, "N": int(b.size), "Mean": float(np.mean(b))}]}],
        f"Observed difference {label_a} − {label_b} = {g(observed, 6)}; {conf * 100:g}% percentile CI {ci_text(low, high, 6)} "
        f"from {count:,} resamples — the interval {'excludes' if excludes_zero else 'includes'} zero.",
        [{"value": observed, "label": "observed difference", "color": "danger"}, {"value": 0.0, "label": "no difference", "color": "muted"}],
    )


def _randomization_result(procedure: str, title: str, method: str, observed: float, observed_label: str, draws: np.ndarray, null_value: float, options: dict, extra_rows: list[dict], alternative: str) -> dict:
    count = draws.size
    centred = draws - float(np.mean(draws)) + null_value if procedure == "randomization_2means" else draws
    if alternative == "greater":
        tail = int(np.sum(draws >= observed))
    elif alternative == "less":
        tail = int(np.sum(draws <= observed))
    else:
        tail = int(np.sum(np.abs(draws - null_value) >= abs(observed - null_value)))
    # +1 in both parts: the observed arrangement is itself one of the possible ones, so a p-value
    # of exactly 0 is never reported from a finite number of resamples.
    p_value = (tail + 1) / (count + 1)
    alpha = 1 - confidence(options)
    significant = p_value < alpha
    seed = option(options, "seed", None)
    return {
        "procedure": procedure,
        "title": title,
        "method": method + (f"; base (seed) {seed}" if seed not in (None, "") else "; no base set, so this run will not repeat exactly"),
        "observed": observed,
        "p_value": p_value,
        "resamples": int(count),
        "tables": [
            {"title": "Randomization test", "rows": [{"Statistic": observed_label, "Observed": observed, "Null value": null_value, "Alternative": alternative, "Resamples": int(count), "As extreme or more": tail, "P-Value": p_value}]},
            *extra_rows,
        ],
        "highlights": [
            {"label": f"Observed {observed_label}", "value": observed},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
            {"label": "Resamples", "value": int(count), "decimals": 0},
            {"label": "As extreme", "value": tail, "decimals": 0},
        ],
        "graphs": [_histogram_graph(draws, title, "statistic under H₀", [{"value": observed, "label": f"observed {observed_label}", "color": "danger"}, {"value": null_value, "label": "null value", "color": "muted"}])],
        "conclusion": (
            f"Observed {observed_label} = {g(observed, 6)}; under the null hypothesis {tail} of {count:,} resamples were "
            f"as extreme or more, giving p = {p_text(p_value)}. "
            + (f"Reject the null at α = {g(alpha)}." if significant else f"Cannot reject the null at α = {g(alpha)}.")
        ),
        "summary": f"{title} — p = {p_text(p_value)} from {count:,} resamples.",
    }


def _alternative(options: dict) -> str:
    alt = str(option(options, "alternative", "two-sided"))
    if alt not in ("two-sided", "less", "greater"):
        raise ProcedureError("The alternative must be two-sided, less or greater.")
    return alt


def _randomization_1mean(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the column to test.")
    column = columns[0]
    sample = _numeric_column(df, column, "Randomization test")
    if sample.size < 2:
        raise ProcedureError(f"'{column}' has only {sample.size} usable value.")
    null_value = float_option(options, "null_value", 0.0, what="Hypothesized mean") or 0.0
    count = _resample_count(options)
    rng = _rng(options)

    # Minitab's shift-and-resample: move the sample so its mean IS the null value, then bootstrap
    # from the shifted data. That builds the distribution of the mean under H₀ from this very sample.
    shifted = sample - float(np.mean(sample)) + null_value
    picks = rng.integers(0, shifted.size, size=(count, shifted.size))
    draws = shifted[picks].mean(axis=1)
    observed = float(np.mean(sample))
    return _randomization_result(
        "randomization_1mean",
        f"Randomization Test for the mean of {column}",
        f"{count:,} resamples of the sample shifted to a mean of {g(null_value)} (Minitab's shift-and-resample)",
        observed,
        "mean",
        draws,
        null_value,
        options,
        [{"title": "Sample", "rows": [{"Column": column, "N": int(sample.size), "Observed mean": observed, "Hypothesized mean": null_value}]}],
        _alternative(options),
    )


def _randomization_1proportion(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the column to test.")
    column = columns[0]
    require_columns(df, [column])
    series = df[column].astype(object)
    series = series[series.notna() & (series.astype(str).str.strip() != "")]
    if series.empty:
        raise ProcedureError(f"'{column}' has no values to test.")
    labels = series.astype(str).to_numpy()
    event = option(options, "event", None)
    if event in (None, ""):
        distinct = sorted(set(labels))
        if len(distinct) != 2:
            raise ProcedureError(f"'{column}' has {len(distinct)} distinct value(s). Choose which one counts as the event.")
        event = distinct[-1]
    indicator = (labels == str(event)).astype(float)
    null_value = float_option(options, "null_value", 0.5, what="Hypothesized proportion")
    if null_value is None or not 0 < null_value < 1:
        raise ProcedureError("The hypothesized proportion must be between 0 and 1.")

    count = _resample_count(options)
    rng = _rng(options)
    # Under H₀ each observation is an independent event with probability p₀ — so the null
    # distribution is simulated directly rather than resampled from the data.
    draws = rng.binomial(indicator.size, null_value, size=count) / indicator.size
    observed = float(indicator.mean())
    return _randomization_result(
        "randomization_1proportion",
        f"Randomization Test for the proportion of {event} in {column}",
        f"{count:,} simulated samples of {indicator.size} observation(s) with event probability {g(null_value)}",
        observed,
        f"proportion of '{event}'",
        draws,
        null_value,
        options,
        [{"title": "Sample", "rows": [{"Column": column, "Event": str(event), "N": int(indicator.size), "Events": int(indicator.sum()), "Observed proportion": observed, "Hypothesized": null_value}]}],
        _alternative(options),
    )


def _randomization_2means(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    label_a, a, label_b, b = _two_samples(df, columns, options, "Randomization test for 2-sample means")
    if a.size < 2 or b.size < 2:
        raise ProcedureError("Each sample needs at least 2 values.")
    count = _resample_count(options)
    rng = _rng(options)

    # Permutation: under H₀ the group labels carry no information, so reshuffling them and
    # recomputing the difference builds the null distribution exactly.
    pooled = np.concatenate([a, b])
    n_a = a.size
    draws = np.empty(count, dtype=float)
    for i in range(count):
        shuffled = rng.permutation(pooled)
        draws[i] = float(np.mean(shuffled[:n_a]) - np.mean(shuffled[n_a:]))
    observed = float(np.mean(a) - np.mean(b))
    return _randomization_result(
        "randomization_2means",
        f"Randomization Test: {label_a} − {label_b}",
        f"{count:,} permutations of the group labels across the pooled {pooled.size} observation(s)",
        observed,
        "difference in means",
        draws,
        0.0,
        options,
        [{"title": "Samples", "rows": [{"Sample": label_a, "N": int(a.size), "Mean": float(np.mean(a))}, {"Sample": label_b, "N": int(b.size), "Mean": float(np.mean(b))}]}],
        _alternative(options),
    )


# ---------------------------------------------------------------------------
# 7. Matrices
# ---------------------------------------------------------------------------


def _matrix_in(options: dict, key: str, what: str) -> np.ndarray:
    raw = option(options, key, None)
    if raw is None:
        raise ProcedureError(f"{what} was not given.")
    try:
        matrix = np.asarray(raw, dtype=float)
    except (TypeError, ValueError):
        raise ProcedureError(f"{what} must be a rectangular block of numbers.") from None
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.size == 0:
        raise ProcedureError(f"{what} must be a two-dimensional matrix with at least one value.")
    if matrix.size > MAX_MATRIX_CELLS:
        raise ProcedureError(f"{what} has {matrix.size:,} cells; the limit is {MAX_MATRIX_CELLS:,}.")
    if not np.isfinite(matrix).all():
        raise ProcedureError(f"{what} contains a missing or infinite value, so it cannot be used in matrix arithmetic.")
    return matrix


def _matrix_out(name: str, matrix: np.ndarray, procedure: str, title: str, method: str, conclusion: str, extra_tables: list[dict] | None = None) -> dict:
    rows, cols = matrix.shape
    preview = [{"": f"row {i + 1}", **{f"c{j + 1}": float(matrix[i, j]) for j in range(min(cols, 8))}} for i in range(min(rows, 8))]
    return {
        "procedure": procedure,
        "title": title,
        "method": method,
        "store_matrix": {"name": name, "rows": [[float(v) for v in row] for row in matrix]},
        "tables": [
            {"title": "Result", "rows": [{"Stored in": name, "Rows": int(rows), "Columns": int(cols)}]},
            *(extra_tables or []),
            {"title": f"{name} (first {min(rows, 8)}×{min(cols, 8)})", "rows": preview},
        ],
        "highlights": [{"label": "Rows", "value": int(rows), "decimals": 0}, {"label": "Columns", "value": int(cols), "decimals": 0}],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"{title} — {name} is {rows}×{cols}.",
    }


def _matrix_name(options: dict, default: str = "M") -> str:
    name = str(option(options, "store_in", "") or "").strip()
    if not name:
        raise ProcedureError("Choose a matrix to store the result in.")
    return name


def _matrix_from_columns(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if not columns:
        raise ProcedureError("Choose the columns to build the matrix from.")
    require_columns(df, columns)
    block = df[columns].apply(pd.to_numeric, errors="coerce")
    usable = block.dropna()
    if usable.empty:
        raise ProcedureError("None of those columns has a row where every value is numeric.")
    matrix = usable.to_numpy(dtype=float)
    name = _matrix_name(options)
    dropped = len(block) - len(usable)
    return _matrix_out(
        name,
        matrix,
        "matrix_from_columns",
        f"Matrix from columns: {', '.join(columns)}",
        "Each chosen column becomes a column of the matrix; rows with a missing value are left out",
        f"Built {name} as {matrix.shape[0]}×{matrix.shape[1]} from {', '.join(columns)}." + (f" {dropped} row(s) with missing values were left out." if dropped else ""),
    )


def _matrix_to_columns(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    matrix = _matrix_in(options, "matrix", "The matrix")
    names = _names_option(options)
    base = str(option(options, "source_name", "M") or "M")
    stored = []
    for j in range(matrix.shape[1]):
        target = names[j] if j < len(names) else f"{base}_c{j + 1}"
        values, _ = _clean_values(matrix[:, j])
        stored.append({"name": target, "values": values})
    return {
        "procedure": "matrix_to_columns",
        "title": f"Matrix to columns: {matrix.shape[0]}×{matrix.shape[1]}",
        "method": "Each column of the matrix becomes a worksheet column",
        "store_columns": stored,
        "tables": [{"title": "Columns written", "rows": [{"Matrix column": i + 1, "Worksheet column": s["name"], "Rows": len(s["values"])} for i, s in enumerate(stored)]}],
        "highlights": [{"label": "Columns written", "value": len(stored), "decimals": 0}, {"label": "Rows", "value": int(matrix.shape[0]), "decimals": 0}],
        "graphs": [],
        "conclusion": f"Wrote {matrix.shape[1]} matrix column(s) into the worksheet as {', '.join(s['name'] for s in stored)}.",
        "summary": f"Matrix to columns — {', '.join(s['name'] for s in stored)}.",
    }


def _matrix_transpose(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    matrix = _matrix_in(options, "matrix", "The matrix")
    name = _matrix_name(options)
    out = matrix.T
    return _matrix_out(name, out, "matrix_transpose", f"Transpose: {matrix.shape[0]}×{matrix.shape[1]} → {out.shape[0]}×{out.shape[1]}", "Rows become columns", f"Transposed a {matrix.shape[0]}×{matrix.shape[1]} matrix into {name} ({out.shape[0]}×{out.shape[1]}).")


def _matrix_invert(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    matrix = _matrix_in(options, "matrix", "The matrix")
    if matrix.shape[0] != matrix.shape[1]:
        raise ProcedureError(f"Only a square matrix can be inverted; this one is {matrix.shape[0]}×{matrix.shape[1]}.")
    determinant = float(np.linalg.det(matrix))
    condition = float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition > 1e12 or determinant == 0:
        raise ProcedureError(
            f"This matrix is singular (determinant {g(determinant, 4)}, condition number {g(condition, 4)}), so it has no inverse. "
            "Two of its rows or columns are exact — or very nearly — multiples of each other."
        )
    inverse = np.linalg.inv(matrix)
    name = _matrix_name(options)
    identity_error = float(np.max(np.abs(matrix @ inverse - np.eye(matrix.shape[0]))))
    return _matrix_out(
        name,
        inverse,
        "matrix_invert",
        f"Invert: {matrix.shape[0]}×{matrix.shape[0]}",
        "numpy.linalg.inv, with a singularity check first",
        f"Inverted a {matrix.shape[0]}×{matrix.shape[0]} matrix into {name}. Determinant {g(determinant, 6)}; "
        f"the largest deviation of M·M⁻¹ from the identity is {g(identity_error, 3)}.",
        [{"title": "Checks", "rows": [{"Determinant": determinant, "Condition number": condition, "Max |M·M⁻¹ − I|": identity_error}]}],
    )


def _matrix_diagonal(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    direction = str(option(options, "direction", "extract"))
    if direction == "extract":
        matrix = _matrix_in(options, "matrix", "The matrix")
        diagonal = np.diag(matrix)
        target = str(option(options, "store_in", "") or "").strip()
        if not target:
            raise ProcedureError("Choose a worksheet column to store the diagonal in.")
        values, _ = _clean_values(diagonal)
        return {
            "procedure": "matrix_diagonal",
            "title": f"Diagonal of a {matrix.shape[0]}×{matrix.shape[1]} matrix",
            "method": "The elements where the row and column index match",
            "store_columns": [{"name": target, "values": values}],
            "tables": [{"title": "Diagonal", "rows": [{"Stored in": target, "Values": len(values), "Trace (sum)": float(np.sum(diagonal))}]}],
            "highlights": [{"label": "Values", "value": len(values), "decimals": 0}, {"label": "Trace", "value": float(np.sum(diagonal))}],
            "graphs": [],
            "conclusion": f"Extracted {len(values)} diagonal element(s) into '{target}'; their sum (the trace) is {g(float(np.sum(diagonal)), 6)}.",
            "summary": f"Diagonal — {len(values)} value(s) into '{target}'.",
        }

    if not columns:
        raise ProcedureError("Choose the column whose values become the diagonal.")
    values = _numeric_column(df, columns[0], "Diagonal")
    name = _matrix_name(options)
    matrix = np.diag(values)
    return _matrix_out(name, matrix, "matrix_diagonal", f"Diagonal matrix from {columns[0]}", "A square matrix with the column's values on the diagonal and zeros elsewhere", f"Built {name} as a {matrix.shape[0]}×{matrix.shape[0]} diagonal matrix from '{columns[0]}'.")


def _matrix_define(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    kind = str(option(options, "kind", "identity"))
    rows = int_option(options, "rows", 3, what="Rows") or 3
    cols = int_option(options, "columns", rows, what="Columns") or rows
    if rows < 1 or cols < 1:
        raise ProcedureError("A matrix needs at least one row and one column.")
    if rows * cols > MAX_MATRIX_CELLS:
        raise ProcedureError(f"A {rows}×{cols} matrix has {rows * cols:,} cells; the limit is {MAX_MATRIX_CELLS:,}.")
    name = _matrix_name(options)
    if kind == "identity":
        matrix = np.eye(rows)
        cols = rows
        described = f"the {rows}×{rows} identity"
    elif kind == "constant":
        value = float_option(options, "value", 0.0, what="Value") or 0.0
        matrix = np.full((rows, cols), value, dtype=float)
        described = f"a {rows}×{cols} matrix of {g(value)}"
    else:
        raise ProcedureError("Choose identity or constant.")
    return _matrix_out(name, matrix, "matrix_define", f"Define {described}", "Constructed from the given dimensions", f"Defined {name} as {described}.")


def _matrix_eigen(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    matrix = _matrix_in(options, "matrix", "The matrix")
    if matrix.shape[0] != matrix.shape[1]:
        raise ProcedureError(f"Eigen analysis needs a square matrix; this one is {matrix.shape[0]}×{matrix.shape[1]}.")
    symmetric = bool(np.allclose(matrix, matrix.T, atol=1e-10))
    note = None
    if symmetric:
        # eigh is the right routine for a symmetric matrix: real results, orthonormal vectors, and
        # it never returns the tiny imaginary parts that eig produces from rounding.
        eigenvalues, vectors = np.linalg.eigh(matrix)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues, vectors = eigenvalues[order], vectors[:, order]
        method = "numpy.linalg.eigh (the matrix is symmetric, so the eigenvalues are real)"
    else:
        raw_values, raw_vectors = np.linalg.eig(matrix)
        imaginary = float(np.max(np.abs(np.imag(raw_values))))
        if imaginary > 1e-9:
            note = (
                f"This matrix is not symmetric and has complex eigenvalues (largest imaginary part {g(imaginary, 4)}). "
                "Only the real parts are stored — read them with that in mind."
            )
        eigenvalues, vectors = np.real(raw_values), np.real(raw_vectors)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues, vectors = eigenvalues[order], vectors[:, order]
        method = "numpy.linalg.eig (the matrix is not symmetric)"

    values_column = str(option(options, "store_values_in", "") or "").strip()
    vectors_matrix = str(option(options, "store_vectors_in", "") or "").strip()
    if not values_column and not vectors_matrix:
        raise ProcedureError("Choose where to put the eigenvalues, the eigenvectors, or both.")

    total = float(np.sum(np.abs(eigenvalues)))
    rows = [{"#": i + 1, "Eigenvalue": float(v), "% of total |λ|": (abs(float(v)) / total * 100) if total > 0 else None} for i, v in enumerate(eigenvalues)]
    result: dict[str, Any] = {
        "procedure": "matrix_eigen",
        "title": f"Eigen Analysis of a {matrix.shape[0]}×{matrix.shape[0]} matrix",
        "method": method,
        "note": note,
        "tables": [{"title": "Eigenvalues (largest first)", "rows": rows}],
        "highlights": [
            {"label": "Largest eigenvalue", "value": float(eigenvalues[0])},
            {"label": "Smallest eigenvalue", "value": float(eigenvalues[-1])},
            {"label": "Symmetric", "value": "yes" if symmetric else "no", "decimals": 0},
            {"label": "Trace", "value": float(np.trace(matrix))},
        ],
        "graphs": [],
        "conclusion": f"Eigenvalues (largest first): {', '.join(g(float(v), 6) for v in eigenvalues[:6])}{'…' if eigenvalues.size > 6 else ''}." + (f" {note}" if note else ""),
        "summary": f"Eigen Analysis — {matrix.shape[0]} eigenvalue(s), largest {g(float(eigenvalues[0]), 6)}.",
    }
    if values_column:
        values, _ = _clean_values(eigenvalues)
        result["store_columns"] = [{"name": values_column, "values": values}]
    if vectors_matrix:
        result["store_matrix"] = {"name": vectors_matrix, "rows": [[float(v) for v in row] for row in vectors]}
        result["tables"].append({"title": f"Eigenvectors → {vectors_matrix} (one per column, matching the order above)", "rows": [{"": f"row {i + 1}", **{f"v{j + 1}": float(vectors[i, j]) for j in range(min(vectors.shape[1], 8))}} for i in range(min(vectors.shape[0], 8))]})
    return result


def _matrix_arithmetic(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    operation = str(option(options, "operation", "add"))
    known = ("add", "subtract", "multiply", "elementwise", "scalar")
    if operation not in known:
        raise ProcedureError(f"Unknown matrix operation '{operation}'. Expected one of: {', '.join(known)}.")
    left = _matrix_in(options, "left", "The first matrix")
    name = _matrix_name(options)

    if operation == "scalar":
        factor = float_option(options, "scalar", 1.0, what="Scalar")
        if factor is None:
            raise ProcedureError("Enter the number to multiply by.")
        out = left * factor
        described = f"{g(factor)} × M ({left.shape[0]}×{left.shape[1]})"
    else:
        right = _matrix_in(options, "right", "The second matrix")
        if operation == "multiply":
            if left.shape[1] != right.shape[0]:
                raise ProcedureError(
                    f"These matrices cannot be multiplied: the first is {left.shape[0]}×{left.shape[1]} and the second is "
                    f"{right.shape[0]}×{right.shape[1]}. The first matrix's column count ({left.shape[1]}) must equal the "
                    f"second's row count ({right.shape[0]})."
                )
            out = left @ right
            described = f"{left.shape[0]}×{left.shape[1]} · {right.shape[0]}×{right.shape[1]}"
        else:
            if left.shape != right.shape:
                symbol = {"add": "added", "subtract": "subtracted", "elementwise": "multiplied element by element"}[operation]
                raise ProcedureError(f"Matrices can only be {symbol} when they are the same size; these are {left.shape[0]}×{left.shape[1]} and {right.shape[0]}×{right.shape[1]}.")
            out = {"add": left + right, "subtract": left - right, "elementwise": left * right}[operation]
            described = f"{left.shape[0]}×{left.shape[1]} {'+' if operation == 'add' else '−' if operation == 'subtract' else '∘'} {right.shape[0]}×{right.shape[1]}"

    return _matrix_out(name, out, "matrix_arithmetic", f"Matrix arithmetic: {described}", {"add": "Element-by-element addition", "subtract": "Element-by-element subtraction", "multiply": "Matrix product", "elementwise": "Element-by-element product", "scalar": "Every element multiplied by a number"}[operation], f"{described} → {name} ({out.shape[0]}×{out.shape[1]}).")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[pd.DataFrame, list[str], dict], dict]] = {
    "calculator": _calculator,
    "validate_expression": _validate_expression,
    "catalogue": _catalogue,
    "column_statistics": _column_statistics,
    "row_statistics": _row_statistics,
    "standardize": _standardize,
    "patterned_numbers": _patterned_numbers,
    "patterned_arbitrary": _patterned_arbitrary,
    "patterned_text": _patterned_text,
    "patterned_datetime": _patterned_datetime,
    "mesh_data": _mesh_data,
    "indicator_variables": _indicator_variables,
    "sample_columns": _sample_columns,
    "random_data": _random_data,
    "probability": _probability,
    "bootstrap_1sample": _bootstrap_1sample,
    "bootstrap_2sample": _bootstrap_2sample,
    "randomization_1mean": _randomization_1mean,
    "randomization_1proportion": _randomization_1proportion,
    "randomization_2means": _randomization_2means,
    "matrix_from_columns": _matrix_from_columns,
    "matrix_to_columns": _matrix_to_columns,
    "matrix_transpose": _matrix_transpose,
    "matrix_invert": _matrix_invert,
    "matrix_diagonal": _matrix_diagonal,
    "matrix_define": _matrix_define,
    "matrix_eigen": _matrix_eigen,
    "matrix_arithmetic": _matrix_arithmetic,
}


def compute(df: pd.DataFrame, procedure: str, columns: list[str] | None, options: dict | None) -> dict:
    handler = _HANDLERS.get(procedure)
    if handler is None:
        raise ProcedureError(f"'{procedure}' is not a Calc procedure. Known procedures: {', '.join(PROCEDURES)}.")
    return json_safe(handler(df if df is not None else pd.DataFrame(), [str(c) for c in (columns or [])], dict(options or {})))
