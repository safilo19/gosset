"""Helpers shared by the Stat-menu procedure modules (basic_stats.py, regression_models.py).

These modules all follow the same contract — one `compute(df, procedure, columns, options)` entry
point returning tables / highlights / graphs / narrative — so the option parsing, the JSON
sanitising and the interval arithmetic live here rather than once per module.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as st

ALTERNATIVES = ("two-sided", "less", "greater")
ALT_SYMBOL = {"two-sided": "≠", "less": "<", "greater": ">"}


class ProcedureError(ValueError):
    """Raised with a message meant for the user (wrong column type, too few rows, missing input).

    The API turns this into a 400 with the message intact, so every message here should read as
    something the person in front of the dialog can act on.
    """


class GroupColumnError(ProcedureError):
    """A grouping variable that is not one — a measurement column chosen where groups were wanted.

    Carries `swap`: the two option/field names to exchange, when the procedure has exactly two column
    inputs and swapping them is the likely fix. The API passes it through so the dialog can offer the
    swap as a button instead of making the person work out which box was wrong.
    """

    def __init__(self, message: str, *, swap: tuple[str, str] | None = None) -> None:
        super().__init__(message)
        self.swap = tuple(swap) if swap else None


# A grouping variable with more distinct values than this is a measurement, not a grouping variable.
# Between WARN and MAX it is allowed but called out: 20 boxes on one axis is legal and hard to read.
GROUP_MAX_LEVELS = 30
GROUP_WARN_LEVELS = 15


def check_group_column(
    df: pd.DataFrame,
    column: str | None,
    *,
    what: str = "This analysis",
    value_column: str | None = None,
    swap: tuple[str, str] | None = None,
) -> str | None:
    """Validate a grouping column and return a warning to show, or None.

    Raises GroupColumnError when the column cannot sensibly group anything:

    * more than GROUP_MAX_LEVELS distinct values — a continuous measurement chosen by mistake, which
      is how an interval plot ends up asked for 96 one-observation "groups";
    * every group holding a single row, whatever the level count, which is the same mistake arriving
      through a column that happens to have few distinct values.

    Lives here, not in a dialog, so the MCP tools and the REST API are protected identically — the
    friendly wording is the same wording the form window shows.
    """
    if not column:
        return None
    if column not in df.columns:
        raise ProcedureError(f"Group column '{column}' is not in this dataset.")

    series = df[column]
    present = series.dropna()
    if present.empty:
        raise GroupColumnError(f"Group column '{column}' has no values.", swap=swap)

    levels = int(present.nunique())
    numeric_like = bool(pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series))
    counts = present.astype(str).value_counts()
    singletons = int((counts == 1).sum())

    if levels > GROUP_MAX_LEVELS:
        kind = "it looks like a measurement, not a grouping variable" if numeric_like else "that is too many groups to plot or compare"
        message = f"'{column}' has {levels} distinct values — {kind}."
        if swap and value_column:
            message += f" Did you mean to swap the two columns, so '{column}' is measured and '{value_column}' does the grouping?"
        elif swap:
            message += " Did you mean to swap the two columns?"
        else:
            message += f" Choose a column with at most {GROUP_MAX_LEVELS} groups."
        raise GroupColumnError(message, swap=swap)

    # n = 1 everywhere: nothing to average, no spread to show, no test to run. Allowed at two levels
    # only if something has more than one row, which a paired-style layout can legitimately have.
    if levels > 1 and singletons == levels:
        message = (
            f"Every group of '{column}' has a single row, so there is nothing to summarise within a group. "
            f"{what} needs several observations per group."
        )
        if swap:
            message += " Swapping the two columns is usually what was meant."
        raise GroupColumnError(message, swap=swap)

    if levels > GROUP_WARN_LEVELS:
        return f"'{column}' has {levels} groups — the axis will be crowded, and pairwise comparisons between {levels} groups are hard to read."
    if singletons:
        thin = ", ".join(str(name) for name in counts[counts == 1].index[:4])
        more = "" if singletons <= 4 else f" (+{singletons - 4} more)"
        return f"{singletons} group(s) of '{column}' hold a single row ({thin}{more}), so they have no spread to show."
    return None


def json_safe(obj: Any) -> Any:
    """JSON has no NaN/Infinity and no numpy scalars; every result goes through here once."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if obj is None or isinstance(obj, (str, int)):
        return obj
    if isinstance(obj, np.ndarray):
        return [json_safe(v) for v in obj.tolist()]
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj


def g(value: float | None, digits: int = 6) -> str:
    """Compact rendering for narrative text ('μ = 52.4', not 'μ = 52.400000')."""
    if value is None:
        return "?"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    try:
        if float(value).is_integer():
            return str(int(value))
    except (OverflowError, ValueError):
        return str(value)
    return f"{float(value):.{digits}g}"


def p_text(p: float | None) -> str:
    if p is None:
        return "?"
    return f"{p:.3g}" if p >= 0.001 else f"{p:.2e}"


def option(options: dict, name: str, default: Any = None) -> Any:
    value = options.get(name, default)
    return default if value in ("", None) else value


def float_option(options: dict, name: str, default: float | None = None, *, what: str = "") -> float | None:
    value = option(options, name, None)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ProcedureError(f"{what or name} must be a number; got '{value}'.") from None


def int_option(options: dict, name: str, default: int | None = None, *, what: str = "") -> int | None:
    value = float_option(options, name, None, what=what)
    if value is None:
        return default
    if value != int(value):
        raise ProcedureError(f"{what or name} must be a whole number; got {g(value)}.")
    return int(value)


def list_option(options: dict, name: str) -> list[str]:
    value = option(options, name, None)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def alternative_option(options: dict) -> str:
    alt = str(option(options, "alternative", "two-sided"))
    if alt not in ALTERNATIVES:
        raise ProcedureError(f"alternative must be one of {', '.join(ALTERNATIVES)}; got '{alt}'.")
    return alt


def confidence(options: dict, name: str = "confidence") -> float:
    conf = float_option(options, name, 0.95, what="Confidence level")
    if conf > 1:  # someone typed 95 rather than 0.95
        conf = conf / 100.0
    if not 0.5 <= conf < 1:
        raise ProcedureError(f"Confidence level must be between 0.5 and 1 (or 50 and 100); got {g(conf)}.")
    return float(conf)


def numeric(df: pd.DataFrame, column: str, *, what: str = "This procedure") -> np.ndarray:
    if not column:
        raise ProcedureError(f"{what} needs a column to be chosen.")
    if column not in df.columns:
        raise ProcedureError(f"Column '{column}' is not in this worksheet.")
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        available = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        raise ProcedureError(
            f"{what} needs numeric values in '{column}', but none could be read. "
            f"Numeric columns available: {', '.join(available) or '(none)'}"
        )
    return series.to_numpy(dtype=float)


def require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ProcedureError(f"Column(s) not in this worksheet: {', '.join(missing)}.")


def require_n(values: np.ndarray, minimum: int, what: str, column: str) -> None:
    if len(values) < minimum:
        raise ProcedureError(f"{what} needs at least {minimum} values in '{column}'; only {len(values)} are usable.")


def crit(alternative: str, conf: float, *, df: float | None = None) -> float:
    """Two-sided procedures split α between the tails; a one-sided alternative puts it all in one."""
    alpha = 1 - conf
    q = 1 - alpha / 2 if alternative == "two-sided" else conf
    return float(st.t.ppf(q, df)) if df is not None else float(st.norm.ppf(q))


def interval(estimate: float, se: float, alternative: str, conf: float, *, df: float | None = None) -> tuple[float | None, float | None]:
    """(low, high) — one side is None for a one-sided alternative, the way Minitab reports a bound."""
    critical = crit(alternative, conf, df=df)
    if alternative == "two-sided":
        return estimate - critical * se, estimate + critical * se
    if alternative == "greater":
        return estimate - critical * se, None
    return None, estimate + critical * se


def ci_label(alternative: str, conf: float, what: str) -> str:
    """`what` should be spelled out ("the mean", not "μ"): these become table column headers, and
    the result tables render headers in uppercase — where μ turns into a capital Mu reading as M."""
    pct = f"{conf * 100:g}%"
    if alternative == "two-sided":
        return f"{pct} CI for {what}"
    return f"{pct} {'lower' if alternative == 'greater' else 'upper'} bound for {what}"


def ci_text(low: float | None, high: float | None, digits: int = 6) -> str:
    if low is not None and high is not None:
        return f"({g(low, digits)}, {g(high, digits)})"
    if low is not None:
        return f"{g(low, digits)} ≤"
    if high is not None:
        return f"≤ {g(high, digits)}"
    return ""


def verdict(p_value: float | None, alpha: float, null_text: str) -> tuple[bool, str]:
    if p_value is None:
        return False, "No p-value could be computed for this test."
    significant = bool(p_value < alpha)
    if significant:
        return True, f"Reject the null hypothesis ({null_text}) at α = {g(alpha)}: p = {p_text(p_value)}."
    return False, f"Cannot reject the null hypothesis ({null_text}) at α = {g(alpha)}: p = {p_text(p_value)}."
