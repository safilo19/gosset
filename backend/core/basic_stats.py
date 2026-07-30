"""Stat > Basic Statistics — the 18 procedures Minitab groups under that one menu.

One entry point (`compute`) dispatches on `procedure`, exactly like backend/core/graphs.py does for
plots: every number a result window shows is calculated here, so the frontend only lays it out.

Every procedure returns the same shape, which the result renderer and the report exporter both
read generically:

    procedure, title, method            what was run
    tables: [{title, rows}]             Minitab's output blocks, in order
    highlights: [{label, value, ...}]   the stat tiles above the tables
    graphs: [{renderer, title, data}]   optional plots, drawn by charts/renderers.js
    null_hypothesis, alternative_hypothesis, statistic, p_value, significant, ...
    conclusion, summary                 plain language, for the Session Window and reports

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as st
from statsmodels.stats.diagnostic import lilliefors
from statsmodels.stats.proportion import proportion_confint
from statsmodels.stats.rates import confint_poisson, confint_poisson_2indep, test_poisson, test_poisson_2indep

from backend.core import graphs as graphs_core
from backend.core import procedures

PROCEDURES = (
    "display_descriptives",
    "store_descriptives",
    "graphical_summary",
    "z1",
    "t1",
    "t2",
    "paired_t",
    "prop1",
    "prop2",
    "poisson1",
    "poisson2",
    "var1",
    "var2",
    "correlation",
    "covariance",
    "normality",
    "outlier",
    "poisson_gof",
)

# Everything generic (option parsing, JSON sanitising, interval arithmetic) lives in
# procedures.py, shared with regression_models.py. Aliased to the private names this module has
# always used, so the call sites below read unchanged.
ALTERNATIVES = procedures.ALTERNATIVES
_ALT_SYMBOL = procedures.ALT_SYMBOL

BasicStatsError = procedures.ProcedureError

_json_safe = procedures.json_safe
_g = procedures.g
_p_text = procedures.p_text
_option = procedures.option
_float_option = procedures.float_option
_int_option = procedures.int_option
_alternative = procedures.alternative_option
_confidence = procedures.confidence
_numeric = procedures.numeric
_require_n = procedures.require_n
_crit = procedures.crit
_interval = procedures.interval
_ci_label = procedures.ci_label
_ci_text = procedures.ci_text
_verdict = procedures.verdict


def _p_value(statistic: float, alternative: str, *, df: float | None = None) -> float:
    """Upper-tail-symmetric p-value for a z or t statistic."""
    dist = st.norm if df is None else st.t(df)
    if alternative == "two-sided":
        return float(2 * dist.sf(abs(statistic)))
    if alternative == "greater":
        return float(dist.sf(statistic))
    return float(dist.cdf(statistic))


def _hypotheses(param: str, value: float, alternative: str) -> tuple[str, str]:
    return f"{param} = {_g(value)}", f"{param} {_ALT_SYMBOL[alternative]} {_g(value)}"


def _two_groups(df: pd.DataFrame, value_col: str, group_col: str, what: str) -> tuple[str, np.ndarray, str, np.ndarray]:
    """Split one numeric column by a grouping column that must have exactly two levels."""
    if group_col not in df.columns:
        raise BasicStatsError(f"Group column '{group_col}' is not in this worksheet.")
    frame = pd.DataFrame({"v": pd.to_numeric(df[value_col], errors="coerce"), "g": df[group_col]}).dropna()
    if frame.empty:
        raise BasicStatsError(f"{what} found no rows where '{value_col}' is numeric and '{group_col}' is filled in.")
    frame["g"] = frame["g"].astype(str)
    labels = sorted(frame["g"].unique())
    if len(labels) != 2:
        raise BasicStatsError(
            f"{what} needs exactly 2 groups in '{group_col}', found {len(labels)} "
            f"({', '.join(labels[:8])}{'…' if len(labels) > 8 else ''})."
        )
    a = frame.loc[frame["g"] == labels[0], "v"].to_numpy(dtype=float)
    b = frame.loc[frame["g"] == labels[1], "v"].to_numpy(dtype=float)
    return labels[0], a, labels[1], b


def _sample_row(label: str, values: np.ndarray) -> dict[str, Any]:
    n = len(values)
    sd = float(np.std(values, ddof=1)) if n > 1 else float("nan")
    return {
        "Sample": label,
        "N": n,
        "Mean": float(np.mean(values)),
        "StDev": sd,
        "SE Mean": sd / math.sqrt(n) if n > 1 else float("nan"),
    }


# ---------------------------------------------------------------------------
# optional plots shared by the tests of means
# ---------------------------------------------------------------------------

_TEST_GRAPH_OPTIONS = ("histogram", "boxplot", "individual_value")
_TEST_GRAPH_RENDERER = {"histogram": "histogram", "boxplot": "boxplot", "individual_value": "individualValue"}


def _test_graphs(
    df: pd.DataFrame,
    options: dict,
    specs: list[tuple[str, str | None]],
    *,
    reference: float | None = None,
    reference_label: str = "hypothesized value",
) -> list[dict]:
    """The optional histogram / boxplot / individual value plot of the data under test. `specs` is
    [(value_column, group_column|None)] — one entry per sample, or one entry with a group column
    when the samples live in a single column."""
    wanted = [name for name in _TEST_GRAPH_OPTIONS if _option(options, f"graph_{name}", False)]
    if not wanted:
        return []

    out: list[dict] = []
    for name in wanted:
        for value_col, group_col in specs:
            graph_options: dict[str, Any] = {}
            if name == "boxplot":
                columns = [value_col]
                if group_col:
                    graph_options["group_column"] = group_col
            elif name == "individual_value":
                columns = [value_col]
                if group_col:
                    graph_options["group_column"] = group_col
            else:
                columns = [value_col]
            try:
                data = graphs_core.compute(df, name, columns, graph_options)
            except graphs_core.GraphError:
                continue  # a plot that can't be drawn must not lose the test result
            if reference is not None:
                data["reference"] = reference
                data["reference_label"] = reference_label
            title = f"{name.replace('_', ' ').title()} of {value_col}" + (f" by {group_col}" if group_col else "")
            out.append({"renderer": _TEST_GRAPH_RENDERER[name], "title": title, "data": data})
    return out


# ---------------------------------------------------------------------------
# descriptive statistics
# ---------------------------------------------------------------------------

# (key, label) in Minitab's own display order — the picker may choose any subset, and the output
# always follows this order rather than the order they were ticked.
DESCRIPTIVE_STATS: tuple[tuple[str, str], ...] = (
    ("n", "N"),
    ("n_missing", "N missing"),
    ("mean", "Mean"),
    ("se_mean", "SE Mean"),
    ("stdev", "StDev"),
    ("variance", "Variance"),
    ("coef_var", "CoefVar"),
    ("minimum", "Minimum"),
    ("q1", "Q1"),
    ("median", "Median"),
    ("q3", "Q3"),
    ("maximum", "Maximum"),
    ("iqr", "IQR"),
    ("range", "Range"),
    ("sum", "Sum"),
    ("skewness", "Skewness"),
    ("kurtosis", "Kurtosis"),
)

DESCRIPTIVE_LABELS = dict(DESCRIPTIVE_STATS)
DESCRIPTIVE_KEYS = tuple(k for k, _ in DESCRIPTIVE_STATS)
DEFAULT_DESCRIPTIVE_STATS = ("n", "n_missing", "mean", "se_mean", "stdev", "minimum", "q1", "median", "q3", "maximum")

# Short forms for stored worksheet column names, so a stored column reads "Mean(yield_kg)" rather
# than "SE Mean(yield_kg)" with a space in it.
_STORE_PREFIX = {
    "n": "N",
    "n_missing": "NMissing",
    "mean": "Mean",
    "se_mean": "SEMean",
    "stdev": "StDev",
    "variance": "Variance",
    "coef_var": "CoefVar",
    "minimum": "Minimum",
    "q1": "Q1",
    "median": "Median",
    "q3": "Q3",
    "maximum": "Maximum",
    "iqr": "IQR",
    "range": "Range",
    "sum": "Sum",
    "skewness": "Skewness",
    "kurtosis": "Kurtosis",
}


def _requested_stats(options: dict) -> list[str]:
    raw = _option(options, "statistics", None)
    if not raw:
        return list(DEFAULT_DESCRIPTIVE_STATS)
    chosen = {str(s) for s in raw}
    unknown = chosen - set(DESCRIPTIVE_KEYS)
    if unknown:
        raise BasicStatsError(f"Unknown statistic(s): {', '.join(sorted(unknown))}.")
    picked = [k for k in DESCRIPTIVE_KEYS if k in chosen]
    if not picked:
        raise BasicStatsError("Choose at least one statistic to display.")
    return picked


def _describe_values(values: np.ndarray, n_missing: int) -> dict[str, float | int | None]:
    n = int(len(values))
    if n == 0:
        return {k: None for k in DESCRIPTIVE_KEYS} | {"n": 0, "n_missing": n_missing}
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1)) if n > 1 else None
    q1, median, q3 = (float(v) for v in np.percentile(values, [25, 50, 75]))
    return {
        "n": n,
        "n_missing": int(n_missing),
        "mean": mean,
        "se_mean": (sd / math.sqrt(n)) if sd is not None else None,
        "stdev": sd,
        "variance": (sd * sd) if sd is not None else None,
        "coef_var": (100.0 * sd / mean) if (sd is not None and mean != 0) else None,
        "minimum": float(np.min(values)),
        "q1": q1,
        "median": median,
        "q3": q3,
        "maximum": float(np.max(values)),
        "iqr": q3 - q1,
        "range": float(np.max(values) - np.min(values)),
        "sum": float(np.sum(values)),
        # adjusted Fisher-Pearson, matching what Minitab reports
        "skewness": float(st.skew(values, bias=False)) if n > 2 else None,
        "kurtosis": float(st.kurtosis(values, fisher=True, bias=False)) if n > 3 else None,
    }


def _descriptive_rows(df: pd.DataFrame, columns: list[str], group_col: str | None) -> list[dict[str, Any]]:
    """One row per variable, or per variable × group level."""
    if not columns:
        raise BasicStatsError("Choose at least one variable.")
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise BasicStatsError(f"Column(s) not in this worksheet: {', '.join(missing)}.")
    if group_col and group_col not in df.columns:
        raise BasicStatsError(f"Group column '{group_col}' is not in this worksheet.")

    rows: list[dict[str, Any]] = []
    for column in columns:
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().sum() == 0:
            raise BasicStatsError(f"Column '{column}' has no numeric values to describe.")
        if not group_col:
            values = numeric.dropna().to_numpy(dtype=float)
            rows.append({"variable": column, "group": None, **_describe_values(values, int(numeric.isna().sum()))})
            continue
        groups = df[group_col].astype(str).where(df[group_col].notna(), None)
        for label in sorted({g for g in groups if g is not None}):
            mask = groups == label
            chunk = numeric[mask]
            values = chunk.dropna().to_numpy(dtype=float)
            if len(values) == 0:
                continue
            rows.append({"variable": column, "group": label, **_describe_values(values, int(chunk.isna().sum()))})
    if not rows:
        raise BasicStatsError("No group had any numeric values to describe.")
    return rows


def _descriptive_table(rows: list[dict[str, Any]], keys: list[str], group_col: str | None) -> list[dict[str, Any]]:
    table = []
    for row in rows:
        out: dict[str, Any] = {"Variable": row["variable"]}
        if group_col:
            out[group_col] = row["group"]
        for key in keys:
            out[DESCRIPTIVE_LABELS[key]] = row.get(key)
        table.append(out)
    return table


def _display_descriptives(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    group_col = _option(options, "group_column", None)
    keys = _requested_stats(options)
    rows = _descriptive_rows(df, columns, group_col)
    table = _descriptive_table(rows, keys, group_col)

    graphs: list[dict] = []
    for name in _TEST_GRAPH_OPTIONS:
        if not _option(options, f"graph_{name}", False):
            continue
        for column in columns:
            graph_options = {"group_column": group_col} if group_col else {}
            try:
                data = graphs_core.compute(df, name, [column], graph_options)
            except graphs_core.GraphError:
                continue
            title = f"{name.replace('_', ' ').title()} of {column}" + (f" by {group_col}" if group_col else "")
            graphs.append({"renderer": _TEST_GRAPH_RENDERER[name], "title": title, "data": data})

    total_n = sum(int(r["n"] or 0) for r in rows)
    what = f"{len(columns)} variable(s)" + (f" by {group_col} ({len({r['group'] for r in rows})} group(s))" if group_col else "")
    summary = f"Descriptive statistics for {what}: {len(keys)} statistic(s) over {total_n} observation(s)."
    return {
        "procedure": "display_descriptives",
        "title": f"Descriptive Statistics: {', '.join(columns)}",
        "method": f"{len(keys)} statistic(s)" + (f", grouped by {group_col}" if group_col else ""),
        "variables": list(columns),
        "group_column": group_col,
        "statistics": keys,
        "tables": [{"title": "Statistics", "rows": table}],
        "highlights": _descriptive_highlights(rows, keys),
        "graphs": graphs,
        "conclusion": summary,
        "summary": summary,
    }


def _descriptive_highlights(rows: list[dict[str, Any]], keys: list[str]) -> list[dict]:
    first = rows[0]
    tiles = [{"label": "Rows described", "value": sum(int(r["n"] or 0) for r in rows), "decimals": 0}]
    for key in ("mean", "stdev", "median"):
        if key in keys and first.get(key) is not None:
            label = f"{DESCRIPTIVE_LABELS[key]} ({first['variable']})"
            tiles.append({"label": label, "value": first[key]})
    if len(tiles) == 1:
        tiles.append({"label": "Statistics shown", "value": len(keys), "decimals": 0})
    return tiles[:4]


def _store_descriptives(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Computes the same statistics as the display procedure, but shaped as worksheet columns —
    one row per group, one column per statistic per variable. The frontend writes them into the
    grid with the ordinary cell/paste endpoints."""
    group_col = _option(options, "group_column", None)
    keys = _requested_stats(options)
    rows = _descriptive_rows(df, columns, group_col)

    groups = list(dict.fromkeys(r["group"] for r in rows)) if group_col else [None]
    by_key = {(r["variable"], r["group"]): r for r in rows}

    new_columns: list[dict[str, Any]] = []
    if group_col:
        new_columns.append({"name": group_col, "values": [g for g in groups]})
    for column in columns:
        for key in keys:
            new_columns.append(
                {
                    "name": f"{_STORE_PREFIX[key]}({column})",
                    "values": [(by_key.get((column, g)) or {}).get(key) for g in groups],
                }
            )

    preview = _descriptive_table(rows, keys, group_col)
    summary = (
        f"Stored {len(new_columns)} column(s) of descriptive statistics for {', '.join(columns)}"
        + (f", one row per level of {group_col} ({len(groups)} rows)." if group_col else " (1 row).")
    )
    return {
        "procedure": "store_descriptives",
        "title": f"Store Descriptive Statistics: {', '.join(columns)}",
        "method": f"{len(keys)} statistic(s) × {len(columns)} variable(s)",
        "variables": list(columns),
        "group_column": group_col,
        "statistics": keys,
        "store_columns": new_columns,
        "row_count": len(groups),
        "tables": [{"title": "Stored statistics", "rows": preview}],
        "highlights": [
            {"label": "Columns to store", "value": len(new_columns), "decimals": 0},
            {"label": "Rows per column", "value": len(groups), "decimals": 0},
            {"label": "Statistics", "value": len(keys), "decimals": 0},
        ],
        "graphs": [],
        "conclusion": summary,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# normality machinery, shared by Graphical Summary and the Normality Test
# ---------------------------------------------------------------------------


def _anderson_darling(values: np.ndarray) -> tuple[float, float]:
    """A² and its p-value for the composite normal hypothesis (mean and sd estimated from the
    data). The p-value uses D'Agostino & Stephens' fitted formulas — the same ones behind R's
    nortest::ad.test — because scipy.stats.anderson only reports critical values."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    if n < 8:
        raise BasicStatsError(f"The Anderson-Darling test needs at least 8 values; got {n}.")
    sd = float(np.std(x, ddof=1))
    if sd == 0:
        raise BasicStatsError("Every value is identical, so normality cannot be assessed.")
    p = st.norm.cdf((x - float(np.mean(x))) / sd)
    p = np.clip(p, 1e-12, 1 - 1e-12)
    i = np.arange(1, n + 1)
    a2 = -n - float(np.sum((2 * i - 1) * (np.log(p) + np.log1p(-p[::-1])))) / n
    z = a2 * (1 + 0.75 / n + 2.25 / n**2)
    if z >= 0.6:
        p_value = math.exp(1.2937 - 5.709 * z + 0.0186 * z**2)
    elif z > 0.34:
        p_value = math.exp(0.9177 - 4.279 * z - 1.38 * z**2)
    elif z > 0.2:
        p_value = 1 - math.exp(-8.318 + 42.796 * z - 59.938 * z**2)
    else:
        p_value = 1 - math.exp(-13.436 + 101.14 * z - 223.73 * z**2)
    return a2, float(min(max(p_value, 0.0), 1.0))


def _probability_plot(values: np.ndarray, conf: float = 0.95) -> dict:
    """Points, the fitted normal reference line, and pointwise confidence bands. Plotting positions
    are Benard's (i - 0.3)/(n + 0.4), which is what Minitab uses."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    mean = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    if sd == 0:
        raise BasicStatsError("Every value is identical, so a probability plot cannot be drawn.")
    i = np.arange(1, n + 1)
    p = (i - 0.3) / (n + 0.4)
    z = st.norm.ppf(p)

    alpha = 1 - conf
    p_low = np.clip(st.beta.ppf(alpha / 2, i, n - i + 1), 1e-6, 1 - 1e-6)
    p_high = np.clip(st.beta.ppf(1 - alpha / 2, i, n - i + 1), 1e-6, 1 - 1e-6)

    r = float(np.corrcoef(x, z)[0, 1])
    return {
        "points": [{"x": float(xi), "y": float(zi)} for xi, zi in zip(x, z)],
        "line": [
            {"x": mean + sd * float(z[0]), "y": float(z[0])},
            {"x": mean + sd * float(z[-1]), "y": float(z[-1])},
        ],
        "band_lower": [{"x": mean + sd * float(st.norm.ppf(pl)), "y": float(zi)} for pl, zi in zip(p_low, z)],
        "band_upper": [{"x": mean + sd * float(st.norm.ppf(ph)), "y": float(zi)} for ph, zi in zip(p_high, z)],
        "x_label": "value",
        "y_label": "normal score (z)",
        "n": n,
        "mean": mean,
        "stdev": sd,
        "r_squared": r * r,
        "confidence": conf,
    }


def _ci_mean(values: np.ndarray, conf: float) -> tuple[float, float]:
    n = len(values)
    se = float(np.std(values, ddof=1)) / math.sqrt(n)
    crit = float(st.t.ppf(1 - (1 - conf) / 2, n - 1))
    mean = float(np.mean(values))
    return mean - crit * se, mean + crit * se


def _ci_stdev(values: np.ndarray, conf: float) -> tuple[float, float]:
    n = len(values)
    var = float(np.var(values, ddof=1))
    alpha = 1 - conf
    lower = (n - 1) * var / float(st.chi2.ppf(1 - alpha / 2, n - 1))
    upper = (n - 1) * var / float(st.chi2.ppf(alpha / 2, n - 1))
    return math.sqrt(lower), math.sqrt(upper)


def _ci_median(values: np.ndarray, conf: float) -> tuple[float | None, float | None]:
    """Distribution-free interval from the order statistics: the largest k whose two-sided
    binomial tail is still within α. Returns (None, None) when n is too small to bracket it."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    alpha = 1 - conf
    k = 0
    for candidate in range(1, n // 2 + 1):
        if 2 * st.binom.cdf(candidate - 1, n, 0.5) <= alpha:
            k = candidate
        else:
            break
    if k == 0:
        return None, None
    return float(x[k - 1]), float(x[n - k])


# ---------------------------------------------------------------------------
# 1. Display / 2. Store / 3. Graphical Summary
# ---------------------------------------------------------------------------


def _graphical_summary(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    conf = _confidence(options)
    if not columns:
        raise BasicStatsError("Choose at least one variable.")

    panels = []
    tables = []
    for column in columns:
        values = _numeric(df, column, what="Graphical Summary")
        _require_n(values, 8, "Graphical Summary", column)
        stats = _describe_values(values, int(pd.to_numeric(df[column], errors="coerce").isna().sum()))
        a2, ad_p = _anderson_darling(values)

        histogram = graphs_core.compute(df, "histogram", [column], {})
        # normal curve scaled to the histogram's counts: n × bin width × pdf
        lo, hi = float(np.min(values)), float(np.max(values))
        pad = (hi - lo) * 0.12 or 1.0
        xs = np.linspace(lo - pad, hi + pad, 120)
        scale = len(values) * float(histogram["bin_width"])
        histogram["curve"] = [
            {"x": float(x), "y": float(scale * st.norm.pdf(x, stats["mean"], stats["stdev"]))} for x in xs
        ]
        histogram["curve_label"] = f"Normal(μ={_g(stats['mean'], 4)}, σ={_g(stats['stdev'], 4)})"

        boxplot = graphs_core.compute(df, "boxplot", [column], {})
        mean_ci = _ci_mean(values, conf)
        median_ci = _ci_median(values, conf)
        stdev_ci = _ci_stdev(values, conf)

        stat_rows = [
            {"Statistic": DESCRIPTIVE_LABELS[key], "Value": stats[key]}
            for key in ("n", "n_missing", "mean", "se_mean", "stdev", "variance", "skewness", "kurtosis", "minimum", "q1", "median", "q3", "maximum")
            if stats.get(key) is not None
        ]
        stat_rows.append({"Statistic": "Anderson-Darling A²", "Value": a2})
        stat_rows.append({"Statistic": "A² p-value", "Value": ad_p})

        interval_rows = [
            {"Parameter": "Mean", "Estimate": stats["mean"], "Lower": mean_ci[0], "Upper": mean_ci[1]},
            {"Parameter": "Median", "Estimate": stats["median"], "Lower": median_ci[0], "Upper": median_ci[1]},
            {"Parameter": "StDev", "Estimate": stats["stdev"], "Lower": stdev_ci[0], "Upper": stdev_ci[1]},
        ]

        panels.append(
            {
                "variable": column,
                "histogram": histogram,
                "boxplot": boxplot,
                "stat_rows": stat_rows,
                "intervals": [r for r in interval_rows if r["Parameter"] in ("Mean", "Median")],
                "all_intervals": interval_rows,
                "confidence": conf,
                "anderson_darling": a2,
                "anderson_darling_p": ad_p,
                "normal": bool(ad_p >= 0.05),
            }
        )
        tables.append({"title": f"Statistics — {column}", "rows": stat_rows})
        tables.append({"title": f"{conf * 100:g}% confidence intervals — {column}", "rows": interval_rows})

    verdicts = [
        f"{p['variable']}: A² = {_g(p['anderson_darling'], 4)}, p = {_p_text(p['anderson_darling_p'])} "
        f"({'consistent with a normal distribution' if p['normal'] else 'not consistent with a normal distribution'})"
        for p in panels
    ]
    summary = f"Graphical summary of {', '.join(columns)} at {conf * 100:g}% confidence. " + "; ".join(verdicts) + "."
    first = panels[0]
    return {
        "procedure": "graphical_summary",
        "title": f"Graphical Summary: {', '.join(columns)}",
        "method": f"Histogram with fitted normal curve, boxplot, {conf * 100:g}% intervals, Anderson-Darling normality test",
        "variables": list(columns),
        "confidence_level": conf,
        "panels": panels,
        "tables": tables,
        "highlights": [
            {"label": f"Mean ({first['variable']})", "value": first["stat_rows"][2]["Value"] if len(first["stat_rows"]) > 2 else None},
            {"label": "Anderson-Darling A²", "value": first["anderson_darling"]},
            {"label": "A² p-value", "value": first["anderson_darling_p"], "tone": "positive" if first["normal"] else "negative"},
        ],
        "graphs": [],
        "conclusion": summary,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 4-7. tests of means
# ---------------------------------------------------------------------------


def _one_sample_mean(df: pd.DataFrame, columns: list[str], options: dict, *, known_sigma: bool) -> dict:
    column = columns[0] if columns else _option(options, "column")
    values = _numeric(df, column, what="This test")
    _require_n(values, 2, "This test", column)
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    mu0 = _float_option(options, "hypothesized_mean", 0.0, what="Hypothesized mean")

    n = len(values)
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))

    if known_sigma:
        sigma = _float_option(options, "sigma", None, what="Known standard deviation (sigma)")
        if sigma is None or sigma <= 0:
            raise BasicStatsError("1-Sample Z needs a known standard deviation (sigma) greater than 0.")
        se = sigma / math.sqrt(n)
        statistic = (mean - mu0) / se
        p_value = _p_value(statistic, alternative)
        low, high = _interval(mean, se, alternative, conf)
        stat_label, df_value = "Z-Value", None
        title = f"1-Sample Z: {column}"
        method = f"Known standard deviation σ = {_g(sigma)}"
        procedure = "z1"
        descriptive = {"Variable": column, "N": n, "Mean": mean, "StDev": sd, "SE Mean": se}
    else:
        se = sd / math.sqrt(n)
        if se == 0:
            raise BasicStatsError(f"Every value in '{column}' is identical, so a t-test has no variability to work with.")
        statistic = (mean - mu0) / se
        df_value = n - 1
        p_value = _p_value(statistic, alternative, df=df_value)
        low, high = _interval(mean, se, alternative, conf, df=df_value)
        stat_label = "T-Value"
        title = f"1-Sample T: {column}"
        method = "Standard deviation estimated from the sample"
        procedure = "t1"
        descriptive = {"Variable": column, "N": n, "Mean": mean, "StDev": sd, "SE Mean": se}

    null_text, alt_text = _hypotheses("μ", mu0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the mean")
    descriptive[ci_label] = _ci_text(low, high)

    test_row = {stat_label: statistic}
    if df_value is not None:
        test_row["DF"] = df_value
    test_row["P-Value"] = p_value

    conclusion = f"Mean {column} = {_g(mean)} (n = {n}) against {alt_text}. {verdict}"
    return {
        "procedure": procedure,
        "title": title,
        "method": method,
        "variables": [column],
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_mean": mu0,
        "statistic": statistic,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {"title": "Descriptive Statistics", "rows": [descriptive]},
            {"title": "Test", "rows": [test_row]},
        ],
        "highlights": [
            {"label": "Mean", "value": mean},
            {"label": stat_label, "value": statistic},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": _test_graphs(df, options, [(column, None)], reference=mu0, reference_label=f"H₀: μ = {_g(mu0)}"),
        "conclusion": conclusion,
        "summary": f"{title} — {conclusion}",
    }


def _two_sample_t(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    layout = str(_option(options, "layout", "one_column"))
    equal_var = bool(_option(options, "equal_variances", False))
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    d0 = _float_option(options, "hypothesized_difference", 0.0, what="Hypothesized difference")

    if layout == "two_columns":
        if len(columns) < 2:
            raise BasicStatsError("With samples in two columns, choose both a first and a second column.")
        label_a, label_b = columns[0], columns[1]
        a = _numeric(df, label_a, what="2-Sample t")
        b = _numeric(df, label_b, what="2-Sample t")
        graph_specs = [(label_a, None), (label_b, None)]
    elif layout == "one_column":
        if len(columns) < 2:
            raise BasicStatsError("With samples in one column, choose both the sample column and the group column.")
        value_col, group_col = columns[0], columns[1]
        label_a, a, label_b, b = _two_groups(df, value_col, group_col, "2-Sample t")
        graph_specs = [(value_col, group_col)]
    else:
        raise BasicStatsError(f"Unknown data layout '{layout}'. Expected 'one_column' or 'two_columns'.")

    for label, sample in ((label_a, a), (label_b, b)):
        if len(sample) < 2:
            raise BasicStatsError(f"2-Sample t needs at least 2 values per sample; '{label}' has {len(sample)}.")

    n1, n2 = len(a), len(b)
    m1, m2 = float(np.mean(a)), float(np.mean(b))
    s1, s2 = float(np.std(a, ddof=1)), float(np.std(b, ddof=1))
    difference = m1 - m2

    if equal_var:
        pooled_var = ((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2)
        se = math.sqrt(pooled_var * (1 / n1 + 1 / n2))
        df_value = float(n1 + n2 - 2)
        method = "Pooled standard deviation (equal variances assumed)"
        pooled_sd = math.sqrt(pooled_var)
    else:
        se = math.sqrt(s1**2 / n1 + s2**2 / n2)
        denominator = (s1**2 / n1) ** 2 / (n1 - 1) + (s2**2 / n2) ** 2 / (n2 - 1)
        df_value = float((s1**2 / n1 + s2**2 / n2) ** 2 / denominator) if denominator > 0 else float(n1 + n2 - 2)
        method = "Welch approximation (equal variances not assumed)"
        pooled_sd = None

    if se == 0:
        raise BasicStatsError("Both samples are constant, so a 2-sample t-test has no variability to work with.")
    statistic = (difference - d0) / se
    p_value = _p_value(statistic, alternative, df=df_value)
    low, high = _interval(difference, se, alternative, conf, df=df_value)

    null_text, alt_text = _hypotheses("μ₁ - μ₂", d0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the difference")

    estimation = {"Estimated difference": difference, ci_label: _ci_text(low, high)}
    if pooled_sd is not None:
        estimation["Pooled StDev"] = pooled_sd

    conclusion = (
        f"{label_a} mean {_g(m1)} (n = {n1}) vs {label_b} mean {_g(m2)} (n = {n2}); "
        f"difference {_g(difference)}. {verdict}"
    )
    return {
        "procedure": "t2",
        "title": f"2-Sample T: {label_a} vs {label_b}",
        "method": method,
        "layout": layout,
        "variables": [label_a, label_b],
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_difference": d0,
        "difference": difference,
        "statistic": statistic,
        "degrees_of_freedom": df_value,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {"title": "Descriptive Statistics", "rows": [_sample_row(label_a, a), _sample_row(label_b, b)]},
            {"title": "Estimation for Difference", "rows": [estimation]},
            {"title": "Test", "rows": [{"T-Value": statistic, "DF": df_value, "P-Value": p_value}]},
        ],
        "highlights": [
            {"label": "Difference", "value": difference},
            {"label": "T-Value", "value": statistic},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": _test_graphs(df, options, graph_specs, reference=d0 if d0 else None, reference_label=f"H₀: difference = {_g(d0)}"),
        "conclusion": conclusion,
        "summary": f"2-Sample T ({method}) — {conclusion}",
    }


def _paired_t(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise BasicStatsError("Paired t needs two columns: the first and the second measurement.")
    col_a, col_b = columns[0], columns[1]
    for column in (col_a, col_b):
        if column not in df.columns:
            raise BasicStatsError(f"Column '{column}' is not in this worksheet.")
    frame = pd.DataFrame(
        {"a": pd.to_numeric(df[col_a], errors="coerce"), "b": pd.to_numeric(df[col_b], errors="coerce")}
    ).dropna()
    if len(frame) < 2:
        raise BasicStatsError(f"Paired t needs at least 2 rows where both '{col_a}' and '{col_b}' are numeric; found {len(frame)}.")

    a = frame["a"].to_numpy(dtype=float)
    b = frame["b"].to_numpy(dtype=float)
    differences = a - b
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    mu0 = _float_option(options, "hypothesized_mean", 0.0, what="Hypothesized mean difference")

    n = len(differences)
    mean = float(np.mean(differences))
    sd = float(np.std(differences, ddof=1))
    se = sd / math.sqrt(n)
    if se == 0:
        raise BasicStatsError("Every pair has the same difference, so a paired t-test has no variability to work with.")
    statistic = (mean - mu0) / se
    df_value = n - 1
    p_value = _p_value(statistic, alternative, df=df_value)
    low, high = _interval(mean, se, alternative, conf, df=df_value)

    null_text, alt_text = _hypotheses("μ_difference", mu0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the mean difference")

    difference_column = f"{col_a} - {col_b}"
    working = df.copy()
    working[difference_column] = pd.Series(differences, index=frame.index)

    conclusion = (
        f"Mean difference {difference_column} = {_g(mean)} over {n} pair(s) "
        f"({col_a} mean {_g(float(np.mean(a)))}, {col_b} mean {_g(float(np.mean(b)))}). {verdict}"
    )
    return {
        "procedure": "paired_t",
        "title": f"Paired T: {col_a} - {col_b}",
        "method": "Test of the mean of the paired differences",
        "variables": [col_a, col_b],
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_mean": mu0,
        "statistic": statistic,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [_sample_row(col_a, a), _sample_row(col_b, b), _sample_row(difference_column, differences)],
            },
            {"title": "Estimation for Paired Difference", "rows": [{"Mean difference": mean, "StDev": sd, "SE Mean": se, ci_label: _ci_text(low, high)}]},
            {"title": "Test", "rows": [{"T-Value": statistic, "DF": df_value, "P-Value": p_value}]},
        ],
        "highlights": [
            {"label": "Mean difference", "value": mean},
            {"label": "T-Value", "value": statistic},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": _test_graphs(working, options, [(difference_column, None)], reference=mu0, reference_label=f"H₀: difference = {_g(mu0)}"),
        "conclusion": conclusion,
        "summary": f"Paired T — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 8-9. proportions
# ---------------------------------------------------------------------------


def _events_from_column(df: pd.DataFrame, column: str, options: dict, key: str) -> tuple[int, int, str, list[str]]:
    """(events, trials, event label, all labels) from a column of two categories."""
    if column not in df.columns:
        raise BasicStatsError(f"Column '{column}' is not in this worksheet.")
    series = df[column].dropna()
    series = series[series.astype(str).str.strip() != ""]
    if series.empty:
        raise BasicStatsError(f"Column '{column}' has no values to count.")
    labels = sorted(series.astype(str).unique())
    if len(labels) != 2:
        raise BasicStatsError(
            f"A proportion needs a column with exactly 2 categories; '{column}' has {len(labels)} "
            f"({', '.join(labels[:8])}{'…' if len(labels) > 8 else ''})."
        )
    chosen = _option(options, key, None)
    event = str(chosen) if chosen is not None and str(chosen) in labels else labels[-1]
    events = int((series.astype(str) == event).sum())
    return events, int(len(series)), event, labels


def _proportion_ci(events: int, trials: int, alternative: str, conf: float, method: str) -> tuple[float | None, float | None]:
    alpha = 1 - conf
    sm_method = "beta" if method == "exact" else "normal"
    if alternative == "two-sided":
        low, high = proportion_confint(events, trials, alpha=alpha, method=sm_method)
        return float(low), float(high)
    low, high = proportion_confint(events, trials, alpha=2 * alpha, method=sm_method)
    return (float(low), None) if alternative == "greater" else (None, float(high))


def _one_proportion(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    source = str(_option(options, "input", "raw"))
    method = str(_option(options, "method", "exact"))
    if method not in ("exact", "normal"):
        raise BasicStatsError(f"method must be 'exact' or 'normal'; got '{method}'.")
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    p0 = _float_option(options, "hypothesized_p", 0.5, what="Hypothesized proportion")
    if not 0 < p0 < 1:
        raise BasicStatsError(f"The hypothesized proportion must be between 0 and 1; got {_g(p0)}.")

    if source == "summarized":
        events = _int_option(options, "events", None, what="Number of events")
        trials = _int_option(options, "trials", None, what="Number of trials")
        if events is None or trials is None:
            raise BasicStatsError("Summarized input needs both the number of events and the number of trials.")
        label, event_label = "Summarized data", "event"
        subject = "the summarized counts"
    else:
        column = columns[0] if columns else _option(options, "column")
        events, trials, event_label, _labels = _events_from_column(df, column, options, "event_value")
        label = column
        subject = f"'{event_label}' in {column}"

    if trials <= 0:
        raise BasicStatsError("The number of trials must be greater than 0.")
    if not 0 <= events <= trials:
        raise BasicStatsError(f"The number of events ({events}) must be between 0 and the number of trials ({trials}).")

    p_hat = events / trials
    low, high = _proportion_ci(events, trials, alternative, conf, method)

    if method == "exact":
        result = st.binomtest(events, trials, p0, alternative={"two-sided": "two-sided", "less": "less", "greater": "greater"}[alternative])
        p_value = float(result.pvalue)
        statistic = None
        stat_label = "Events"
        stat_value: float | int = events
        method_text = "Exact (binomial) test and Clopper-Pearson interval"
    else:
        se0 = math.sqrt(p0 * (1 - p0) / trials)
        statistic = (p_hat - p0) / se0
        p_value = _p_value(statistic, alternative)
        stat_label = "Z-Value"
        stat_value = statistic
        method_text = "Normal approximation (test uses the null standard error; interval is the Wald interval)"

    null_text, alt_text = _hypotheses("p", p0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the proportion")

    test_row: dict[str, Any] = {}
    if statistic is not None:
        test_row["Z-Value"] = statistic
    test_row["P-Value"] = p_value

    conclusion = f"{events} of {trials} ({p_hat * 100:.4g}%) for {subject}, tested against {alt_text}. {verdict}"
    return {
        "procedure": "prop1",
        "title": f"1 Proportion: {label}",
        "method": method_text,
        "input": source,
        "event": event_label,
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_p": p0,
        "statistic": statistic,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [{"Sample": label, "N": trials, "Event": events, "Sample p": p_hat, ci_label: _ci_text(low, high, 5)}],
            },
            {"title": "Test", "rows": [test_row]},
        ],
        "highlights": [
            {"label": "Sample p", "value": p_hat},
            {"label": stat_label, "value": stat_value, "decimals": 0 if stat_label == "Events" else None},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"1 Proportion ({method} method) — {conclusion}",
    }


def _two_proportions(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    source = str(_option(options, "input", "raw"))
    layout = str(_option(options, "layout", "two_columns"))
    pooled = bool(_option(options, "pooled", False))
    fisher = bool(_option(options, "fisher", False))
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    d0 = _float_option(options, "hypothesized_difference", 0.0, what="Hypothesized difference")

    event_label = "event"
    if source == "summarized":
        e1 = _int_option(options, "events1", None, what="Sample 1 events")
        n1 = _int_option(options, "trials1", None, what="Sample 1 trials")
        e2 = _int_option(options, "events2", None, what="Sample 2 events")
        n2 = _int_option(options, "trials2", None, what="Sample 2 trials")
        if None in (e1, n1, e2, n2):
            raise BasicStatsError("Summarized input needs events and trials for both samples.")
        label1, label2 = "Sample 1", "Sample 2"
    elif layout == "one_column":
        if len(columns) < 2:
            raise BasicStatsError("With samples in one column, choose both the sample column and the group column.")
        value_col, group_col = columns[0], columns[1]
        if value_col not in df.columns or group_col not in df.columns:
            raise BasicStatsError(f"Columns '{value_col}' and '{group_col}' must both be in this worksheet.")
        frame = df[[value_col, group_col]].dropna()
        if frame.empty:
            raise BasicStatsError(f"No rows have both '{value_col}' and '{group_col}' filled in.")
        groups = sorted(frame[group_col].astype(str).unique())
        if len(groups) != 2:
            raise BasicStatsError(f"2 Proportions needs exactly 2 groups in '{group_col}', found {len(groups)}.")
        events_labels = sorted(frame[value_col].astype(str).unique())
        if len(events_labels) != 2:
            raise BasicStatsError(f"2 Proportions needs exactly 2 categories in '{value_col}', found {len(events_labels)}.")
        chosen = _option(options, "event_value", None)
        event_label = str(chosen) if chosen is not None and str(chosen) in events_labels else events_labels[-1]
        label1, label2 = groups
        first = frame[frame[group_col].astype(str) == label1][value_col].astype(str)
        second = frame[frame[group_col].astype(str) == label2][value_col].astype(str)
        e1, n1 = int((first == event_label).sum()), int(len(first))
        e2, n2 = int((second == event_label).sum()), int(len(second))
    else:
        if len(columns) < 2:
            raise BasicStatsError("With samples in two columns, choose both the first and the second column.")
        label1, label2 = columns[0], columns[1]
        shared = _option(options, "event_value", None)
        e1, n1, ev1, labels1 = _events_from_column(df, label1, options, "event_value")
        e2, n2, ev2, labels2 = _events_from_column(df, label2, options, "event_value")
        if ev1 != ev2:
            # both columns must count the same category as the event, or the difference is meaningless
            common = sorted(set(labels1) & set(labels2))
            if not common:
                raise BasicStatsError(f"'{label1}' and '{label2}' share no category, so there is no common event to count.")
            event_label = str(shared) if shared is not None and str(shared) in common else common[-1]
            e1 = int((df[label1].dropna().astype(str) == event_label).sum())
            e2 = int((df[label2].dropna().astype(str) == event_label).sum())
        else:
            event_label = ev1

    for label, events, trials in ((label1, e1, n1), (label2, e2, n2)):
        if trials <= 0:
            raise BasicStatsError(f"{label} has no trials to work with.")
        if not 0 <= events <= trials:
            raise BasicStatsError(f"{label}: events ({events}) must be between 0 and trials ({trials}).")

    p1, p2 = e1 / n1, e2 / n2
    difference = p1 - p2
    se_unpooled = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    p_bar = (e1 + e2) / (n1 + n2)
    se_pooled = math.sqrt(p_bar * (1 - p_bar) * (1 / n1 + 1 / n2))

    use_pooled = pooled and d0 == 0
    se_test = se_pooled if use_pooled else se_unpooled
    if se_test == 0:
        raise BasicStatsError("Both samples have the same constant outcome, so the difference has no standard error.")
    statistic = (difference - d0) / se_test
    p_value = _p_value(statistic, alternative)
    low, high = _interval(difference, se_unpooled, alternative, conf)

    method_bits = ["pooled estimate of p" if use_pooled else "separate estimates of p (unpooled)"]
    if pooled and d0 != 0:
        method_bits.append("pooling ignored because the hypothesized difference is not 0")
    tests = [{"Method": f"Normal approximation ({method_bits[0]})", "Z-Value": statistic, "P-Value": p_value}]

    fisher_p = None
    if fisher:
        table = [[e1, n1 - e1], [e2, n2 - e2]]
        odds_ratio, fisher_p = st.fisher_exact(table, alternative=alternative)
        tests.append({"Method": "Fisher's exact test", "Z-Value": None, "P-Value": float(fisher_p), "Odds ratio": float(odds_ratio)})
        method_bits.append("Fisher's exact test reported alongside")

    null_text, alt_text = _hypotheses("p₁ - p₂", d0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the difference")

    conclusion = (
        f"{label1}: {e1}/{n1} = {p1 * 100:.4g}% vs {label2}: {e2}/{n2} = {p2 * 100:.4g}% "
        f"(difference {_g(difference, 4)}). {verdict}"
    )
    if fisher_p is not None:
        conclusion += f" Fisher's exact p = {_p_text(float(fisher_p))}."

    return {
        "procedure": "prop2",
        "title": f"2 Proportions: {label1} vs {label2}",
        "method": "; ".join(method_bits),
        "input": source,
        "layout": layout if source != "summarized" else "summarized",
        "event": event_label,
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_difference": d0,
        "difference": difference,
        "statistic": statistic,
        "p_value": p_value,
        "fisher_p_value": None if fisher_p is None else float(fisher_p),
        "significant": significant,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [
                    {"Sample": label1, "N": n1, "Event": e1, "Sample p": p1},
                    {"Sample": label2, "N": n2, "Event": e2, "Sample p": p2},
                ],
            },
            {"title": "Estimation for Difference", "rows": [{"Estimated difference": difference, ci_label: _ci_text(low, high, 5)}]},
            {"title": "Test", "rows": tests},
        ],
        "highlights": [
            {"label": "Difference", "value": difference},
            {"label": "Z-Value", "value": statistic},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"2 Proportions — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 10-11. Poisson rates
# ---------------------------------------------------------------------------


def _poisson_inputs(df: pd.DataFrame, column: str | None, options: dict, suffix: str = "") -> tuple[int, float, str, int]:
    """(total occurrences, exposure, label, number of observations)."""
    length = _float_option(options, f"length{suffix}", 1.0, what="Length of observation")
    if length is None or length <= 0:
        raise BasicStatsError("The length of observation must be greater than 0.")
    if str(_option(options, "input", "raw")) == "summarized":
        total = _int_option(options, f"occurrences{suffix}", None, what="Total occurrences")
        n_obs = _int_option(options, f"observations{suffix}", None, what="Sample size")
        if total is None or n_obs is None:
            raise BasicStatsError("Summarized input needs the total occurrences and the sample size.")
        if total < 0:
            raise BasicStatsError("Total occurrences cannot be negative.")
        if n_obs <= 0:
            raise BasicStatsError("The sample size must be greater than 0.")
        return total, n_obs * length, f"Summarized{suffix or ' data'}", n_obs

    values = _numeric(df, column or "", what="A Poisson rate")
    if np.any(values < 0) or np.any(values != np.floor(values)):
        raise BasicStatsError(f"'{column}' must contain whole, non-negative counts to be treated as Poisson data.")
    return int(values.sum()), len(values) * length, str(column), len(values)


def _one_poisson_rate(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    method = str(_option(options, "method", "exact"))
    if method not in ("exact", "normal"):
        raise BasicStatsError(f"method must be 'exact' or 'normal'; got '{method}'.")
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    r0 = _float_option(options, "hypothesized_rate", 1.0, what="Hypothesized rate")
    if r0 is None or r0 <= 0:
        raise BasicStatsError("The hypothesized rate must be greater than 0.")

    column = columns[0] if columns else _option(options, "column")
    total, exposure, label, n_obs = _poisson_inputs(df, column, options)
    length = _float_option(options, "length", 1.0, what="Length of observation")
    rate = total / exposure

    sm_method = "exact-c" if method == "exact" else "score"
    result = test_poisson(total, exposure, value=r0, method=sm_method, alternative=alternative)
    p_value = float(result.pvalue)
    statistic = None if (result.statistic is None or not np.isfinite(result.statistic)) else float(result.statistic)

    ci_method = "exact-c" if method == "exact" else "wald"
    if alternative == "two-sided":
        low, high = confint_poisson(total, exposure, method=ci_method, alpha=alpha)
        low, high = float(low), float(high)
    else:
        bounds = confint_poisson(total, exposure, method=ci_method, alpha=2 * alpha)
        low, high = (float(bounds[0]), None) if alternative == "greater" else (None, float(bounds[1]))

    null_text, alt_text = _hypotheses("rate", r0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the rate")
    method_text = (
        "Exact (conditional Poisson) test and exact interval"
        if method == "exact"
        else "Normal approximation (score test and Wald interval)"
    )

    test_row: dict[str, Any] = {}
    if statistic is not None:
        test_row["Z-Value"] = statistic
    test_row["P-Value"] = p_value

    conclusion = (
        f"{total} occurrence(s) over {_g(exposure)} unit(s) of exposure gives a rate of {_g(rate)}, "
        f"tested against {alt_text}. {verdict}"
    )
    return {
        "procedure": "poisson1",
        "title": f"1-Sample Poisson Rate: {label}",
        "method": method_text,
        "input": str(_option(options, "input", "raw")),
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_rate": r0,
        "length_of_observation": length,
        "total_occurrences": total,
        "rate": rate,
        "statistic": statistic,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [
                    {
                        "Sample": label,
                        "N": n_obs,
                        "Total occurrences": total,
                        "Sample rate": rate,
                        ci_label: _ci_text(low, high, 5),
                    }
                ],
            },
            {"title": "Test", "rows": [test_row]},
        ],
        "highlights": [
            {"label": "Sample rate", "value": rate},
            {"label": "Total occurrences", "value": total, "decimals": 0},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"1-Sample Poisson Rate ({method} method) — {conclusion}",
    }


def _two_poisson_rates(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    method = str(_option(options, "method", "exact"))
    if method not in ("exact", "normal"):
        raise BasicStatsError(f"method must be 'exact' or 'normal'; got '{method}'.")
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    d0 = _float_option(options, "hypothesized_difference", 0.0, what="Hypothesized difference")

    source = str(_option(options, "input", "raw"))
    if source == "summarized":
        total1, exposure1, label1, n1 = _poisson_inputs(df, None, options, "1")
        total2, exposure2, label2, n2 = _poisson_inputs(df, None, options, "2")
        label1, label2 = "Sample 1", "Sample 2"
    else:
        if len(columns) < 2:
            raise BasicStatsError("2-Sample Poisson Rate needs two count columns.")
        total1, exposure1, label1, n1 = _poisson_inputs(df, columns[0], options, "")
        total2, exposure2, label2, n2 = _poisson_inputs(df, columns[1], options, "")
        label1, label2 = columns[0], columns[1]

    rate1, rate2 = total1 / exposure1, total2 / exposure2
    difference = rate1 - rate2

    sm_method = "etest-score" if method == "exact" else "score"
    result = test_poisson_2indep(
        total1, exposure1, total2, exposure2, value=d0, method=sm_method, compare="diff", alternative=alternative
    )
    p_value = float(result.pvalue)
    statistic = None if (result.statistic is None or not np.isfinite(result.statistic)) else float(result.statistic)

    if alternative == "two-sided":
        low, high = confint_poisson_2indep(total1, exposure1, total2, exposure2, method="score", compare="diff", alpha=alpha)
        low, high = float(low), float(high)
    else:
        bounds = confint_poisson_2indep(total1, exposure1, total2, exposure2, method="score", compare="diff", alpha=2 * alpha)
        low, high = (float(bounds[0]), None) if alternative == "greater" else (None, float(bounds[1]))

    null_text, alt_text = _hypotheses("rate₁ - rate₂", d0, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)
    ci_label = _ci_label(alternative, conf, "the difference")
    method_text = (
        "Exact (E-test) for the difference in rates, score interval"
        if method == "exact"
        else "Normal approximation (score test and score interval)"
    )

    conclusion = (
        f"{label1}: {total1} occurrence(s), rate {_g(rate1)}; {label2}: {total2} occurrence(s), rate {_g(rate2)}; "
        f"difference {_g(difference)}. {verdict}"
    )
    return {
        "procedure": "poisson2",
        "title": f"2-Sample Poisson Rate: {label1} vs {label2}",
        "method": method_text,
        "input": source,
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_difference": d0,
        "difference": difference,
        "statistic": statistic,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [
                    {"Sample": label1, "N": n1, "Total occurrences": total1, "Exposure": exposure1, "Sample rate": rate1},
                    {"Sample": label2, "N": n2, "Total occurrences": total2, "Exposure": exposure2, "Sample rate": rate2},
                ],
            },
            {"title": "Estimation for Difference", "rows": [{"Estimated difference": difference, ci_label: _ci_text(low, high, 5)}]},
            {"title": "Test", "rows": [{"Z-Value": statistic, "P-Value": p_value}]},
        ],
        "highlights": [
            {"label": "Difference in rates", "value": difference},
            {"label": f"Rate {label1}", "value": rate1},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"2-Sample Poisson Rate ({method} method) — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 12-13. variances
# ---------------------------------------------------------------------------


def _bonett_interval(values: np.ndarray, conf: float, alternative: str) -> tuple[float | None, float | None, float]:
    """Bonett's kurtosis-adjusted interval for a variance, and its standard error term. Robust to
    non-normal data, which is why Minitab reports it next to the chi-square interval."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 5:
        raise BasicStatsError("Bonett's method needs at least 5 values.")
    variance = float(np.var(x, ddof=1))
    if variance == 0:
        raise BasicStatsError("Every value is identical, so there is no variance to estimate.")
    trim = 1 / (2 * math.sqrt(n - 4)) if n > 4 else 0.0
    trim = min(max(trim, 0.0), 0.49)
    m = float(st.trim_mean(x, trim))
    kurtosis = n * float(np.sum((x - m) ** 4)) / (float(np.sum((x - float(np.mean(x))) ** 2)) ** 2)
    se = math.sqrt(max(kurtosis - (n - 3) / n, 1e-12) / (n - 1))

    z = _crit(alternative, conf)
    if n <= z:
        raise BasicStatsError("The sample is too small for Bonett's method at this confidence level.")
    c = n / (n - z)
    center = math.log(c * variance)
    if alternative == "two-sided":
        return math.exp(center - z * se), math.exp(center + z * se), se
    if alternative == "greater":
        return math.exp(center - z * se), None, se
    return None, math.exp(center + z * se), se


def _bonett_p_value(values: np.ndarray, sigma2_null: float, alternative: str) -> float | None:
    """Bonett's interval inverted: the confidence level at which the hypothesized variance sits
    exactly on the interval's boundary. Bisection, because the interval has no closed-form test."""

    def outside(alpha: float) -> bool:
        try:
            low, high, _se = _bonett_interval(values, 1 - alpha, alternative)
        except BasicStatsError:
            return False
        if low is not None and sigma2_null < low:
            return True
        return high is not None and sigma2_null > high

    if not outside(0.999):
        return None if outside(1e-9) else 1.0
    if outside(1e-9):
        return 0.0
    lo, hi = 1e-9, 0.999
    for _ in range(60):
        mid = (lo + hi) / 2
        if outside(mid):
            hi = mid
        else:
            lo = mid
    return float((lo + hi) / 2)


def _one_variance(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf
    target = str(_option(options, "hypothesized_kind", "variance"))
    if target not in ("variance", "stdev"):
        raise BasicStatsError("Choose whether the hypothesized value is a variance or a standard deviation.")
    entered = _float_option(options, "hypothesized_value", 1.0, what="Hypothesized value")
    if entered is None or entered <= 0:
        raise BasicStatsError("The hypothesized variance / standard deviation must be greater than 0.")
    variance_null = entered if target == "variance" else entered**2

    source = str(_option(options, "input", "raw"))
    values: np.ndarray | None = None
    if source == "summarized":
        n = _int_option(options, "sample_size", None, what="Sample size")
        observed = _float_option(options, "sample_value", None, what="Sample variance / standard deviation")
        kind = str(_option(options, "sample_kind", target))
        if n is None or observed is None:
            raise BasicStatsError("Summarized input needs the sample size and the sample variance (or standard deviation).")
        if n < 2:
            raise BasicStatsError("The sample size must be at least 2.")
        if observed <= 0:
            raise BasicStatsError("The sample variance / standard deviation must be greater than 0.")
        variance = observed if kind == "variance" else observed**2
        label = "Summarized data"
    else:
        column = columns[0] if columns else _option(options, "column")
        values = _numeric(df, column, what="1 Variance")
        _require_n(values, 2, "1 Variance", column)
        n = len(values)
        variance = float(np.var(values, ddof=1))
        if variance == 0:
            raise BasicStatsError(f"Every value in '{column}' is identical, so there is no variance to test.")
        label = str(column)

    df_value = n - 1
    chi2 = df_value * variance / variance_null
    if alternative == "two-sided":
        p_value = float(2 * min(st.chi2.cdf(chi2, df_value), st.chi2.sf(chi2, df_value)))
        p_value = min(p_value, 1.0)
        ci_low = df_value * variance / float(st.chi2.ppf(1 - alpha / 2, df_value))
        ci_high = df_value * variance / float(st.chi2.ppf(alpha / 2, df_value))
    elif alternative == "greater":
        p_value = float(st.chi2.sf(chi2, df_value))
        ci_low = df_value * variance / float(st.chi2.ppf(conf, df_value))
        ci_high = None
    else:
        p_value = float(st.chi2.cdf(chi2, df_value))
        ci_low = None
        ci_high = df_value * variance / float(st.chi2.ppf(alpha, df_value))

    methods = [
        {
            "Method": "Chi-square (assumes a normal distribution)",
            "Test statistic": chi2,
            "DF": df_value,
            "P-Value": p_value,
            "CI for variance": _ci_text(ci_low, ci_high, 5),
            "CI for StDev": _ci_text(None if ci_low is None else math.sqrt(ci_low), None if ci_high is None else math.sqrt(ci_high), 5),
        }
    ]
    notes = []
    if values is None:
        notes.append("Bonett's method needs the raw data, so only the chi-square method is available for summarized input.")
    else:
        try:
            b_low, b_high, _se = _bonett_interval(values, conf, alternative)
            b_p = _bonett_p_value(values, variance_null, alternative)
            methods.append(
                {
                    "Method": "Bonett (adjusts for kurtosis)",
                    "Test statistic": None,
                    "DF": None,
                    "P-Value": b_p,
                    "CI for variance": _ci_text(b_low, b_high, 5),
                    "CI for StDev": _ci_text(None if b_low is None else math.sqrt(b_low), None if b_high is None else math.sqrt(b_high), 5),
                }
            )
            notes.append("Bonett's p-value is obtained by inverting its confidence interval; it has no closed form.")
        except BasicStatsError as err:
            notes.append(f"Bonett's method was not computed: {err}")

    param = "σ²" if target == "variance" else "σ"
    null_text, alt_text = _hypotheses(param, entered, alternative)
    significant, verdict = _verdict(p_value, alpha, null_text)

    conclusion = (
        f"Sample variance {_g(variance)} (StDev {_g(math.sqrt(variance))}, n = {n}) against {alt_text}. {verdict}"
    )
    return {
        "procedure": "var1",
        "title": f"1 Variance: {label}",
        "method": "Chi-square" + (" and Bonett" if len(methods) > 1 else " only"),
        "input": source,
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "hypothesized_variance": variance_null,
        "hypothesized_stdev": math.sqrt(variance_null),
        "variance": variance,
        "stdev": math.sqrt(variance),
        "statistic": chi2,
        "degrees_of_freedom": df_value,
        "p_value": p_value,
        "significant": significant,
        "note": " ".join(notes) or None,
        "tables": [
            {"title": "Descriptive Statistics", "rows": [{"Sample": label, "N": n, "StDev": math.sqrt(variance), "Variance": variance}]},
            {"title": "Tests and intervals", "rows": methods},
        ],
        "highlights": [
            {"label": "Variance", "value": variance},
            {"label": "Chi-square", "value": chi2},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
        ],
        "graphs": _test_graphs(df, options, [(label, None)]) if values is not None else [],
        "conclusion": conclusion,
        "summary": f"1 Variance — {conclusion}",
    }


def _two_variances(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    layout = str(_option(options, "layout", "one_column"))
    alternative = _alternative(options)
    conf = _confidence(options)
    alpha = 1 - conf

    if layout == "two_columns":
        if len(columns) < 2:
            raise BasicStatsError("With samples in two columns, choose both the first and the second column.")
        label1, label2 = columns[0], columns[1]
        a = _numeric(df, label1, what="2 Variances")
        b = _numeric(df, label2, what="2 Variances")
        graph_specs = [(label1, None), (label2, None)]
    elif layout == "one_column":
        if len(columns) < 2:
            raise BasicStatsError("With samples in one column, choose both the sample column and the group column.")
        value_col, group_col = columns[0], columns[1]
        label1, a, label2, b = _two_groups(df, value_col, group_col, "2 Variances")
        graph_specs = [(value_col, group_col)]
    else:
        raise BasicStatsError(f"Unknown data layout '{layout}'. Expected 'one_column' or 'two_columns'.")

    for label, sample in ((label1, a), (label2, b)):
        if len(sample) < 2:
            raise BasicStatsError(f"2 Variances needs at least 2 values per sample; '{label}' has {len(sample)}.")

    n1, n2 = len(a), len(b)
    v1, v2 = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    if v2 == 0 or v1 == 0:
        raise BasicStatsError("One of the samples is constant, so the ratio of variances is undefined.")
    ratio = v1 / v2
    df1, df2 = n1 - 1, n2 - 1

    if alternative == "two-sided":
        f_p = float(2 * min(st.f.cdf(ratio, df1, df2), st.f.sf(ratio, df1, df2)))
        f_p = min(f_p, 1.0)
        f_low = ratio / float(st.f.ppf(1 - alpha / 2, df1, df2))
        f_high = ratio / float(st.f.ppf(alpha / 2, df1, df2))
    elif alternative == "greater":
        f_p = float(st.f.sf(ratio, df1, df2))
        f_low = ratio / float(st.f.ppf(conf, df1, df2))
        f_high = None
    else:
        f_p = float(st.f.cdf(ratio, df1, df2))
        f_low = None
        f_high = ratio / float(st.f.ppf(alpha, df1, df2))

    # Levene centred on the median (Brown-Forsythe) — the version that holds up on skewed data,
    # and the one Minitab reports for "Levene's test".
    levene = st.levene(a, b, center="median")
    levene_p = float(levene.pvalue)
    if alternative != "two-sided":
        # Levene is inherently two-sided; halve or complement it to match the requested direction.
        half = levene_p / 2
        larger_first = v1 >= v2
        if alternative == "greater":
            levene_p = half if larger_first else 1 - half
        else:
            levene_p = half if not larger_first else 1 - half

    methods = [
        {
            "Method": "F-test (assumes normal distributions)",
            "Test statistic": ratio,
            "DF1": df1,
            "DF2": df2,
            "P-Value": f_p,
            "CI for ratio": _ci_text(f_low, f_high, 5),
        },
        {
            "Method": "Levene's test (median-centred; any continuous distribution)",
            "Test statistic": float(levene.statistic),
            "DF1": 1,
            "DF2": n1 + n2 - 2,
            "P-Value": levene_p,
            "CI for ratio": "",
        },
    ]

    null_text, alt_text = _hypotheses("σ₁² / σ₂²", 1, alternative)
    significant, verdict = _verdict(f_p, alpha, null_text)
    conclusion = (
        f"{label1}: StDev {_g(math.sqrt(v1))} (n = {n1}); {label2}: StDev {_g(math.sqrt(v2))} (n = {n2}); "
        f"ratio of variances {_g(ratio)}. F-test: {verdict} Levene's test p = {_p_text(levene_p)}."
    )
    return {
        "procedure": "var2",
        "title": f"2 Variances: {label1} vs {label2}",
        "method": "F-test and Levene's test reported side by side",
        "layout": layout,
        "null_hypothesis": null_text,
        "alternative_hypothesis": alt_text,
        "alternative": alternative,
        "confidence_level": conf,
        "ratio": ratio,
        "statistic": ratio,
        "p_value": f_p,
        "levene_p_value": levene_p,
        "significant": significant,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [
                    {"Sample": label1, "N": n1, "StDev": math.sqrt(v1), "Variance": v1},
                    {"Sample": label2, "N": n2, "StDev": math.sqrt(v2), "Variance": v2},
                ],
            },
            {"title": "Ratio of variances", "rows": [{"Estimated ratio": ratio, "F-test CI": _ci_text(f_low, f_high, 5)}]},
            {"title": "Tests", "rows": methods},
        ],
        "highlights": [
            {"label": "Ratio of variances", "value": ratio},
            {"label": "F P-Value", "value": f_p, "tone": "positive" if significant else None},
            {"label": "Levene P-Value", "value": levene_p, "tone": "positive" if levene_p < alpha else None},
        ],
        "graphs": _test_graphs(df, options, graph_specs),
        "conclusion": conclusion,
        "summary": f"2 Variances — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 14-15. association
# ---------------------------------------------------------------------------


def _correlation(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    method = str(_option(options, "method", "pearson"))
    if method not in ("pearson", "spearman"):
        raise BasicStatsError(f"method must be 'pearson' or 'spearman'; got '{method}'.")
    if len(columns) < 2:
        raise BasicStatsError("Correlation needs at least 2 columns.")

    frame = pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce") for c in _existing(df, columns)})
    matrix: dict[str, dict[str, float | None]] = {a: {} for a in columns}
    p_matrix: dict[str, dict[str, float | None]] = {a: {} for a in columns}
    pairs = []
    for a, b in combinations(columns, 2):
        sub = frame[[a, b]].dropna()
        if len(sub) < 3:
            matrix[a][b] = matrix[b][a] = None
            p_matrix[a][b] = p_matrix[b][a] = None
            continue
        if method == "pearson":
            r, p = st.pearsonr(sub[a], sub[b])
        else:
            r, p = st.spearmanr(sub[a], sub[b])
        r, p = float(r), float(p)
        matrix[a][b] = matrix[b][a] = r
        p_matrix[a][b] = p_matrix[b][a] = p
        pairs.append(
            {
                "Pair": f"{a} × {b}",
                "N": int(len(sub)),
                "Correlation": r,
                "P-Value": p,
                "Strength": _strength(r),
            }
        )
    for a in columns:
        matrix[a][a] = 1.0
        p_matrix[a][a] = None
    if not pairs:
        raise BasicStatsError("No pair of the chosen columns has at least 3 rows with both values present.")

    # Minitab prints the coefficient and the p-value in the same cell, one under the other.
    combined_rows = []
    for a in columns:
        row: dict[str, Any] = {"": a}
        for b in columns:
            if a == b:
                row[b] = ""
            else:
                r = matrix[a][b]
                p = p_matrix[a][b]
                row[b] = "" if r is None else f"{r:.3f}\np = {_p_text(p)}"
        combined_rows.append(row)

    pairs.sort(key=lambda item: abs(item["Correlation"]), reverse=True)
    alpha = 1 - _confidence(options)
    significant_pairs = [p for p in pairs if p["P-Value"] is not None and p["P-Value"] < alpha]
    top = pairs[0]

    graphs = []
    if _option(options, "graph_matrix_plot", False):
        try:
            graphs.append(
                {
                    "renderer": "matrixPlot",
                    "title": "Matrix plot",
                    "data": graphs_core.compute(df, "matrix_plot", columns[:5], {}),
                }
            )
        except graphs_core.GraphError:
            pass

    interpretation = (
        f"The strongest relationship is {top['Pair']} (r = {_g(top['Correlation'], 4)}, p = {_p_text(top['P-Value'])}, "
        f"a {top['Strength']} correlation). {len(significant_pairs)} of {len(pairs)} pair(s) are significant at α = {_g(alpha)}."
    )
    return {
        "procedure": "correlation",
        "title": f"Correlation: {', '.join(columns)}",
        "method": f"{method.title()} correlation, {len(columns)} column(s), p-value for every pair",
        "variables": list(columns),
        "correlation_method": method,
        "confidence_level": 1 - alpha,
        "matrix": {a: {b: matrix[a][b] for b in columns} for a in columns},
        "p_matrix": {a: {b: p_matrix[a][b] for b in columns} for a in columns},
        "tables": [
            {"title": f"{method.title()} correlation matrix (coefficient and p-value)", "rows": combined_rows},
            {"title": "Pairs, strongest first", "rows": pairs},
        ],
        "highlights": [
            {"label": top["Pair"], "value": top["Correlation"], "tone": "positive" if top["Correlation"] >= 0 else "negative"},
            {"label": "Pairs compared", "value": len(pairs), "decimals": 0},
            {"label": f"Significant at α={_g(alpha)}", "value": len(significant_pairs), "decimals": 0},
        ],
        "graphs": graphs,
        "conclusion": interpretation,
        "interpretation": interpretation,
        "summary": f"{method.title()} correlation across {len(columns)} column(s). {interpretation}",
    }


def _strength(correlation: float) -> str:
    magnitude = abs(correlation)
    if magnitude >= 0.7:
        strength = "strong"
    elif magnitude >= 0.4:
        strength = "moderate"
    elif magnitude >= 0.2:
        strength = "weak"
    else:
        return "negligible"
    return f"{strength} {'positive' if correlation >= 0 else 'negative'}"


def _existing(df: pd.DataFrame, columns: list[str]) -> list[str]:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise BasicStatsError(f"Column(s) not in this worksheet: {', '.join(missing)}.")
    return list(columns)


def _covariance(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise BasicStatsError("Covariance needs at least 2 columns.")
    frame = pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce") for c in _existing(df, columns)})
    usable = frame.dropna()
    if len(usable) < 2:
        raise BasicStatsError("Covariance needs at least 2 rows where every chosen column has a value.")

    cov = usable.cov()
    rows = [{"": a, **{b: float(cov.loc[a, b]) for b in columns}} for a in columns]
    variances = [{"Variable": a, "Variance": float(cov.loc[a, a]), "StDev": math.sqrt(float(cov.loc[a, a]))} for a in columns]

    off_diagonal = [(a, b, float(cov.loc[a, b])) for a, b in combinations(columns, 2)]
    strongest = max(off_diagonal, key=lambda item: abs(item[2]))
    summary = (
        f"Covariance matrix for {len(columns)} column(s) over {len(usable)} complete row(s). "
        f"The largest covariance in magnitude is {strongest[0]} × {strongest[1]} = {_g(strongest[2], 4)}."
    )
    return {
        "procedure": "covariance",
        "title": f"Covariance: {', '.join(columns)}",
        "method": f"Pairwise covariance over {len(usable)} complete row(s)",
        "variables": list(columns),
        "n": int(len(usable)),
        "matrix": {a: {b: float(cov.loc[a, b]) for b in columns} for a in columns},
        "tables": [
            {"title": "Covariance matrix", "rows": rows},
            {"title": "Variances", "rows": variances},
        ],
        "highlights": [
            {"label": f"{strongest[0]} × {strongest[1]}", "value": strongest[2]},
            {"label": "Complete rows", "value": int(len(usable)), "decimals": 0},
            {"label": "Columns", "value": len(columns), "decimals": 0},
        ],
        "graphs": [],
        "conclusion": summary,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 16-18. distribution checks
# ---------------------------------------------------------------------------

NORMALITY_METHODS = {
    "anderson_darling": "Anderson-Darling",
    "kolmogorov_smirnov": "Kolmogorov-Smirnov",
    "shapiro_wilk": "Shapiro-Wilk",
}


def _normality(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    method = str(_option(options, "method", "anderson_darling"))
    if method not in NORMALITY_METHODS:
        raise BasicStatsError(f"method must be one of {', '.join(NORMALITY_METHODS)}; got '{method}'.")
    conf = _confidence(options)
    alpha = 1 - conf
    column = columns[0] if columns else _option(options, "column")
    values = _numeric(df, column, what="The normality test")
    _require_n(values, 8 if method == "anderson_darling" else 3, "The normality test", column)

    if method == "anderson_darling":
        statistic, p_value = _anderson_darling(values)
        stat_label = "A-Squared"
        method_note = "The p-value comes from the fitted formulas of D'Agostino & Stephens, since scipy reports only critical values."
    elif method == "kolmogorov_smirnov":
        statistic, p_value = lilliefors(values, dist="norm", pvalmethod="table")
        statistic, p_value = float(statistic), float(p_value)
        stat_label = "KS"
        method_note = "The p-value is Lilliefors', which accounts for the mean and standard deviation being estimated from the data."
    else:
        result = st.shapiro(values)
        statistic, p_value = float(result.statistic), float(result.pvalue)
        stat_label = "W"
        method_note = (
            "Stands in for Minitab's Ryan-Joiner test: Ryan-Joiner is proprietary, and Shapiro-Wilk is "
            "the equivalent regression-of-order-statistics test."
        )

    stats = _describe_values(values, int(pd.to_numeric(df[column], errors="coerce").isna().sum()))
    plot = _probability_plot(values, conf)
    plot["reference"] = None
    normal = bool(p_value >= alpha)

    conclusion = (
        f"{NORMALITY_METHODS[method]} on {column}: {stat_label} = {_g(statistic, 5)}, p = {_p_text(p_value)}. "
        + (
            f"There is not enough evidence to reject normality at α = {_g(alpha)}."
            if normal
            else f"Reject normality at α = {_g(alpha)} — the data are not consistent with a normal distribution."
        )
    )
    return {
        "procedure": "normality",
        "title": f"Normality Test: {column}",
        "method": f"{NORMALITY_METHODS[method]}. {method_note}",
        "variables": [column],
        "normality_method": method,
        "null_hypothesis": "The data follow a normal distribution",
        "alternative_hypothesis": "The data do not follow a normal distribution",
        "confidence_level": conf,
        "statistic": statistic,
        "p_value": p_value,
        "significant": not normal,
        "normal": normal,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [
                    {
                        "Variable": column,
                        "N": stats["n"],
                        "Mean": stats["mean"],
                        "StDev": stats["stdev"],
                        "Skewness": stats["skewness"],
                        "Kurtosis": stats["kurtosis"],
                    }
                ],
            },
            {"title": "Test", "rows": [{"Method": NORMALITY_METHODS[method], stat_label: statistic, "P-Value": p_value}]},
        ],
        "highlights": [
            {"label": stat_label, "value": statistic},
            {"label": "P-Value", "value": p_value, "tone": "positive" if normal else "negative"},
            {"label": "N", "value": stats["n"], "decimals": 0},
        ],
        "graphs": [{"renderer": "probability", "title": f"Probability plot of {column} with {conf * 100:g}% CI bands", "data": plot}],
        "conclusion": conclusion,
        "summary": f"Normality Test ({NORMALITY_METHODS[method]}) — {conclusion}",
    }


# Dixon's r10 critical values (Rorabacher 1991); Dixon's test has no closed-form p-value, so the
# statistic is compared against these instead.
_DIXON_CRITICAL = {
    3: (0.941, 0.988),
    4: (0.765, 0.889),
    5: (0.642, 0.780),
    6: (0.560, 0.698),
    7: (0.507, 0.637),
    8: (0.468, 0.590),
    9: (0.437, 0.555),
    10: (0.412, 0.527),
    11: (0.392, 0.502),
    12: (0.376, 0.482),
    13: (0.361, 0.465),
    14: (0.349, 0.450),
    15: (0.338, 0.438),
    16: (0.329, 0.426),
    17: (0.320, 0.416),
    18: (0.313, 0.407),
    19: (0.306, 0.398),
    20: (0.300, 0.391),
    21: (0.295, 0.384),
    22: (0.290, 0.378),
    23: (0.285, 0.372),
    24: (0.281, 0.367),
    25: (0.277, 0.362),
    26: (0.273, 0.357),
    27: (0.269, 0.353),
    28: (0.266, 0.349),
    29: (0.263, 0.345),
    30: (0.260, 0.341),
}

DIXON_MAX_N = max(_DIXON_CRITICAL)


def _outlier(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    method = str(_option(options, "method", "grubbs"))
    if method not in ("grubbs", "dixon"):
        raise BasicStatsError("method must be 'grubbs' or 'dixon'.")
    conf = _confidence(options)
    alpha = 1 - conf
    column = columns[0] if columns else _option(options, "column")

    if not column or column not in df.columns:
        raise BasicStatsError(f"Column '{column}' is not in this worksheet.")
    numeric = pd.to_numeric(df[column], errors="coerce")
    usable = numeric.dropna()
    if usable.empty:
        raise BasicStatsError(f"The outlier test needs numeric values in '{column}', but none could be read.")
    values = usable.to_numpy(dtype=float)
    row_numbers = [int(i) + 1 for i in usable.index]  # worksheet rows are 1-based
    n = len(values)
    _require_n(values, 3, "The outlier test", column)

    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    if sd == 0:
        raise BasicStatsError(f"Every value in '{column}' is identical, so there is no outlier to find.")

    deviations = np.abs(values - mean)
    index = int(np.argmax(deviations))
    suspect_value = float(values[index])
    suspect_row = row_numbers[index]
    side = "largest" if suspect_value > mean else "smallest"

    critical: float | None = None
    if method == "grubbs":
        statistic = float(deviations[index] / sd)
        stat_label = "G"
        denominator = (n - 1) ** 2 - n * statistic**2
        if denominator <= 0:
            p_value = 0.0
        else:
            t_equivalent = statistic * math.sqrt(n * (n - 2) / denominator)
            p_value = float(min(1.0, 2 * n * st.t.sf(t_equivalent, n - 2)))
        t_crit = float(st.t.ppf(1 - alpha / (2 * n), n - 2))
        critical = float((n - 1) / math.sqrt(n) * math.sqrt(t_crit**2 / (n - 2 + t_crit**2)))
        method_text = "Grubbs' test for one outlier (two-sided, Bonferroni-adjusted)"
        note = None
    else:
        if n > DIXON_MAX_N:
            raise BasicStatsError(
                f"Dixon's Q test only applies to samples of at most {DIXON_MAX_N} values; '{column}' has {n}. Use Grubbs' test instead."
            )
        ordered = np.sort(values)
        spread = float(ordered[-1] - ordered[0])
        gap = float(ordered[-1] - ordered[-2]) if side == "largest" else float(ordered[1] - ordered[0])
        statistic = gap / spread if spread > 0 else 0.0
        stat_label = "Q"
        critical_05, critical_01 = _DIXON_CRITICAL[n]
        critical = critical_05 if alpha >= 0.05 else critical_01
        p_value = None
        method_text = f"Dixon's Q test (r10) against the tabulated critical value at α = {_g(alpha if alpha in (0.05, 0.01) else 0.05)}"
        note = (
            "Dixon's test has no closed-form p-value; the statistic is compared with tabulated critical "
            f"values (α = 0.05: {critical_05}, α = 0.01: {critical_01} for n = {n})."
        )

    if p_value is not None:
        significant = bool(p_value < alpha)
    else:
        significant = bool(critical is not None and statistic > critical)

    verdict = (
        f"Row {suspect_row} ({column} = {_g(suspect_value)}) is flagged as an outlier."
        if significant
        else f"No outlier was detected; row {suspect_row} ({column} = {_g(suspect_value)}) is the most extreme value but is within the expected range."
    )

    # Individual value plot with the suspect drawn as its own, red series.
    rest = [{"x": _jitter(i, n), "y": float(v)} for i, v in enumerate(values) if i != index]
    plot = {
        "value_label": column,
        "group_label": "",
        "labels": [column],
        "groups": [
            {"label": column, "index": 0, "n": n - 1, "mean": mean, "points": rest},
            {"label": "flagged value", "index": 0, "n": 1, "mean": None, "points": [{"x": 0, "y": suspect_value}]},
        ],
        "highlight_dataset": 1,
    }

    return {
        "procedure": "outlier",
        "title": f"Outlier Test: {column}",
        "method": method_text,
        "variables": [column],
        "outlier_method": method,
        "null_hypothesis": "All values come from the same population (no outlier)",
        "alternative_hypothesis": f"The {side} value is an outlier",
        "confidence_level": conf,
        "statistic": statistic,
        "critical_value": critical,
        "p_value": p_value,
        "significant": significant,
        "outlier_row": suspect_row if significant else None,
        "outlier_value": suspect_value if significant else None,
        "note": note,
        "tables": [
            {
                "title": "Descriptive Statistics",
                "rows": [{"Variable": column, "N": n, "Mean": mean, "StDev": sd, "Min": float(np.min(values)), "Max": float(np.max(values))}],
            },
            {
                "title": "Test",
                "rows": [
                    {
                        "Method": method_text,
                        "Row": suspect_row,
                        "Value": suspect_value,
                        stat_label: statistic,
                        "Critical value": critical,
                        "P-Value": p_value,
                        "Outlier": "yes" if significant else "no",
                    }
                ],
            },
        ],
        "highlights": [
            {"label": stat_label, "value": statistic},
            {"label": "P-Value" if p_value is not None else "Critical value", "value": p_value if p_value is not None else critical, "tone": "negative" if significant else "positive"},
            {"label": f"Most extreme (row {suspect_row})", "value": suspect_value},
        ],
        "graphs": [{"renderer": "outlierPlot", "title": f"Individual value plot of {column}", "data": plot}],
        "conclusion": f"{method_text}: {stat_label} = {_g(statistic, 4)}" + (f", p = {_p_text(p_value)}" if p_value is not None else f" vs critical {_g(critical, 4)}") + f". {verdict}",
        "summary": f"Outlier Test ({method}) on {column} — {verdict}",
    }


def _jitter(index: int, n: int) -> float:
    """Deterministic spread around x=0 so overlapping values stay visible without randomness
    (a re-render must not move the points)."""
    if n <= 1:
        return 0.0
    golden = (index * 0.6180339887498949) % 1.0
    return (golden - 0.5) * 0.6


def _poisson_gof(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    conf = _confidence(options)
    alpha = 1 - conf
    column = columns[0] if columns else _option(options, "column")
    values = _numeric(df, column, what="The Poisson goodness-of-fit test")
    if np.any(values < 0) or np.any(values != np.floor(values)):
        raise BasicStatsError(f"'{column}' must contain whole, non-negative counts for a Poisson goodness-of-fit test.")
    _require_n(values, 5, "The Poisson goodness-of-fit test", column)

    counts = values.astype(int)
    n = len(counts)
    lam = float(np.mean(counts))
    if lam <= 0:
        raise BasicStatsError(f"Every count in '{column}' is 0, so no Poisson mean can be estimated.")

    top = int(counts.max())
    categories = [
        {"lower": k, "upper": k, "observed": int(np.sum(counts == k)), "expected": n * float(st.poisson.pmf(k, lam))}
        for k in range(top + 1)
    ]
    # the open-ended top category carries the whole upper tail, the way Minitab's table does
    categories.append({"lower": top + 1, "upper": None, "observed": 0, "expected": n * float(st.poisson.sf(top, lam))})
    categories = _merge_small_categories(categories, minimum=5.0)

    if len(categories) < 3:
        raise BasicStatsError(
            "After combining categories with an expected count below 5 there are too few left to test "
            "(the chi-square test needs at least 3). More rows, or a larger mean, would give a usable table."
        )

    observed = np.array([c["observed"] for c in categories], dtype=float)
    expected = np.array([c["expected"] for c in categories], dtype=float)
    contributions = (observed - expected) ** 2 / expected
    chi2 = float(contributions.sum())
    df_value = len(categories) - 2  # one for the total, one for the estimated mean
    p_value = float(st.chi2.sf(chi2, df_value))
    significant = bool(p_value < alpha)

    rows = [
        {
            "Count": _category_label(c),
            "Observed": int(c["observed"]),
            "Poisson probability": float(c["expected"] / n),
            "Expected": float(c["expected"]),
            "Contribution to Chi-Square": float(contribution),
        }
        for c, contribution in zip(categories, contributions)
    ]

    chart = {
        "labels": [_category_label(c) for c in categories],
        "series": [
            {"label": "Observed", "values": [int(c["observed"]) for c in categories]},
            {"label": "Expected", "values": [float(c["expected"]) for c in categories]},
        ],
        "x_label": column,
        "y_label": "rows",
    }

    verdict = (
        f"Reject the Poisson model at α = {_g(alpha)}: p = {_p_text(p_value)}."
        if significant
        else f"The counts are consistent with a Poisson distribution at α = {_g(alpha)}: p = {_p_text(p_value)}."
    )
    conclusion = f"{n} row(s) of '{column}' with an estimated mean of {_g(lam)} over {len(categories)} category/categories. {verdict}"
    return {
        "procedure": "poisson_gof",
        "title": f"Goodness-of-Fit Test for Poisson: {column}",
        "method": "Chi-square goodness of fit, mean estimated from the data, categories with an expected count below 5 combined",
        "variables": [column],
        "null_hypothesis": "The counts follow a Poisson distribution",
        "alternative_hypothesis": "The counts do not follow a Poisson distribution",
        "confidence_level": conf,
        "n": n,
        "estimated_mean": lam,
        "statistic": chi2,
        "degrees_of_freedom": df_value,
        "p_value": p_value,
        "significant": significant,
        "tables": [
            {"title": "Observed and expected counts", "rows": rows},
            {"title": "Chi-Square Test", "rows": [{"N": n, "DF": df_value, "Chi-Square": chi2, "P-Value": p_value}]},
        ],
        "highlights": [
            {"label": "Estimated mean (λ)", "value": lam},
            {"label": "Chi-Square", "value": chi2},
            {"label": "P-Value", "value": p_value, "tone": "positive" if not significant else "negative"},
        ],
        "graphs": [{"renderer": "observedExpected", "title": f"Observed and expected counts of {column}", "data": chart}],
        "conclusion": conclusion,
        "summary": f"Goodness-of-Fit Test for Poisson — {conclusion}",
    }


def _category_label(category: dict) -> str:
    if category["upper"] is None:
        return f"≥ {category['lower']}"
    if category["lower"] == category["upper"]:
        return str(category["lower"])
    return f"{category['lower']}–{category['upper']}"


def _merge_small_categories(categories: list[dict], minimum: float) -> list[dict]:
    """Fold categories whose expected count is below `minimum` into their neighbour, working in
    from both tails — the standard fix for a chi-square table with thin cells."""
    working = [dict(c) for c in categories]

    def merge(into: int, other: int) -> None:
        low = working[min(into, other)]
        high = working[max(into, other)]
        low["observed"] += high["observed"]
        low["expected"] += high["expected"]
        low["upper"] = high["upper"]
        working.pop(max(into, other))

    while len(working) > 2 and working[-1]["expected"] < minimum:
        merge(len(working) - 2, len(working) - 1)
    while len(working) > 2 and working[0]["expected"] < minimum:
        merge(0, 1)
    # anything still thin in the middle joins the category above it
    index = 0
    while index < len(working) - 1 and len(working) > 2:
        if working[index]["expected"] < minimum:
            merge(index, index + 1)
        else:
            index += 1
    return working


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_HANDLERS = {
    "display_descriptives": _display_descriptives,
    "store_descriptives": _store_descriptives,
    "graphical_summary": _graphical_summary,
    "z1": lambda df, columns, options: _one_sample_mean(df, columns, options, known_sigma=True),
    "t1": lambda df, columns, options: _one_sample_mean(df, columns, options, known_sigma=False),
    "t2": _two_sample_t,
    "paired_t": _paired_t,
    "prop1": _one_proportion,
    "prop2": _two_proportions,
    "poisson1": _one_poisson_rate,
    "poisson2": _two_poisson_rates,
    "var1": _one_variance,
    "var2": _two_variances,
    "correlation": _correlation,
    "covariance": _covariance,
    "normality": _normality,
    "outlier": _outlier,
    "poisson_gof": _poisson_gof,
}


def compute(df: pd.DataFrame, procedure: str, columns: list[str] | None, options: dict | None) -> dict:
    """Run one Basic Statistics procedure. `columns` is ordered the way the procedure expects
    (e.g. [value, group] for a 2-sample test in one column); `options` holds everything else."""
    handler = _HANDLERS.get(procedure)
    if handler is None:
        raise BasicStatsError(f"Unknown procedure '{procedure}'. Expected one of: {', '.join(PROCEDURES)}.")
    result = handler(df, list(columns or []), dict(options or {}))
    return _json_safe(result)
