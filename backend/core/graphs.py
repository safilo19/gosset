"""Graph data computation: everything a plot needs, computed server-side so the frontend only
renders. One entry point (`compute`) dispatches on graph_type.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import interpolate, stats

from . import procedures

# Every graph type the /graph-data endpoint (and the MCP tool) understands.
GRAPH_TYPES = (
    "scatter",
    "bubble",
    "line",
    "area",
    "bar",
    "pie",
    "time_series",
    "histogram",
    "boxplot",
    "heatmap",
    "correlogram",
    "binned_scatter",
    "dotplot",
    "individual_value",
    "interval",
    "main_effects",
    "interaction",
    "ecdf",
    "probability",
    "distribution",
    "stem_leaf",
    "matrix_plot",
    "marginal",
    "parallel_coords",
    "contour",
    "surface",
    "scatter3d",
)

PARALLEL_ROW_CAP = 500
MATRIX_PLOT_COLUMN_CAP = 5


class GraphError(ValueError):
    """Raised with a message meant for the user (bad column choice, too few rows, ...)."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe(value: Any) -> Any:
    """JSON has no NaN/Infinity; every number leaving this module goes through here."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _require(columns: list[str], count: int, graph_type: str, what: str) -> None:
    if len(columns) < count:
        raise GraphError(f"{graph_type} needs at least {count} column(s) ({what}); got {len(columns)}.")


def _numeric_series(df: pd.DataFrame, column: str, graph_type: str) -> pd.Series:
    if column not in df.columns:
        raise GraphError(f"Column '{column}' is not in this dataset.")
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        raise GraphError(
            f"{graph_type} needs numeric values in '{column}', but none could be read. "
            f"Numeric columns available: {', '.join(numeric) or '(none)'}"
        )
    return series


def _xy(df: pd.DataFrame, x_col: str, y_col: str, graph_type: str) -> pd.DataFrame:
    for col in (x_col, y_col):
        if col not in df.columns:
            raise GraphError(f"Column '{col}' is not in this dataset.")
    frame = pd.DataFrame({"x": pd.to_numeric(df[x_col], errors="coerce"), "y": pd.to_numeric(df[y_col], errors="coerce")}).dropna()
    if frame.empty:
        raise GraphError(f"{graph_type} found no rows where both '{x_col}' and '{y_col}' are numeric.")
    return frame


def _bin_edges(values: np.ndarray, bin_width: float | None, n_bins: int | None) -> np.ndarray:
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi <= lo:
        hi = lo + 1.0
    if bin_width and bin_width > 0:
        start = math.floor(lo / bin_width) * bin_width
        edges = np.arange(start, hi + bin_width, bin_width)
        return edges if len(edges) > 1 else np.array([lo, hi])
    if n_bins and n_bins > 0:
        return np.linspace(lo, hi, int(n_bins) + 1)
    # Freedman–Diaconis, falling back to Sturges when the IQR is zero
    q75, q25 = np.percentile(values, [75, 25])
    iqr = q75 - q25
    width = 2 * iqr / (len(values) ** (1 / 3)) if iqr > 0 else 0
    count = int(np.ceil((hi - lo) / width)) if width > 0 else int(np.ceil(np.log2(len(values)) + 1))
    count = max(3, min(count, 60))
    return np.linspace(lo, hi, count + 1)


def _histogram(values: np.ndarray, bin_width: float | None = None, n_bins: int | None = None) -> dict:
    edges = _bin_edges(values, bin_width, n_bins)
    counts, edges = np.histogram(values, bins=edges)
    bins = [
        {
            "x0": _safe(edges[i]),
            "x1": _safe(edges[i + 1]),
            "center": _safe((edges[i] + edges[i + 1]) / 2),
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]
    return {"bins": bins, "bin_width": _safe(edges[1] - edges[0]), "n": int(len(values))}


def _group_note(df: pd.DataFrame, value_col: str, group_col: str | None, what: str) -> str | None:
    """Refuse a grouping column that is really a measurement; return a warning for a crowded one.

    The rule itself is in procedures.check_group_column so the MCP tools, the REST API and these
    graphs cannot disagree about it. `swap` names the two dialog fields every grouped Graph-menu item
    uses, which is what lets the form offer a one-click swap instead of an error to puzzle over.
    """
    return procedures.check_group_column(
        df,
        group_col,
        what="This plot",
        value_column=value_col,
        swap=("column", "group_column"),
    )


def _group_values(df: pd.DataFrame, value_col: str, group_col: str | None, graph_type: str) -> list[tuple[str, np.ndarray]]:
    """[(label, values)] — one entry per group, or a single entry when no group column is given."""
    values = pd.to_numeric(df[value_col], errors="coerce") if value_col in df.columns else None
    if values is None:
        raise GraphError(f"Column '{value_col}' is not in this dataset.")
    _group_note(df, value_col, group_col, graph_type)
    if not group_col:
        clean = values.dropna()
        if clean.empty:
            raise GraphError(f"{graph_type} found no numeric values in '{value_col}'.")
        return [(value_col, clean.to_numpy(dtype=float))]

    if group_col not in df.columns:
        raise GraphError(f"Group column '{group_col}' is not in this dataset.")
    out: list[tuple[str, np.ndarray]] = []
    for label, chunk in df.assign(_v=values).groupby(df[group_col].astype(str), sort=True):
        clean = chunk["_v"].dropna()
        if not clean.empty:
            out.append((str(label), clean.to_numpy(dtype=float)))
    if not out:
        raise GraphError(f"{graph_type} found no numeric values in '{value_col}' for any group of '{group_col}'.")
    return out


# ---------------------------------------------------------------------------
# native chart types
# ---------------------------------------------------------------------------


def _scatter(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "scatter", "x, y")
    x_col, y_col = columns[0], columns[1]
    group_col = options.get("group_column") or None
    frame = pd.DataFrame({"x": pd.to_numeric(df[x_col], errors="coerce"), "y": pd.to_numeric(df[y_col], errors="coerce")})
    if group_col:
        if group_col not in df.columns:
            raise GraphError(f"Group column '{group_col}' is not in this dataset.")
        frame["g"] = df[group_col].astype(str)
    frame = frame.dropna(subset=["x", "y"])
    if frame.empty:
        raise GraphError(f"scatter found no rows where both '{x_col}' and '{y_col}' are numeric.")

    if group_col:
        series = [
            {"label": str(label), "points": [{"x": _safe(r.x), "y": _safe(r.y)} for r in chunk.itertuples()]}
            for label, chunk in frame.groupby("g", sort=True)
        ]
    else:
        series = [{"label": f"{y_col} vs {x_col}", "points": [{"x": _safe(r.x), "y": _safe(r.y)} for r in frame.itertuples()]}]
    return {"series": series, "x_label": x_col, "y_label": y_col, "group_column": group_col, "n": int(len(frame))}


def _bubble(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 3, "bubble", "x, y, size")
    x_col, y_col, size_col = columns[0], columns[1], columns[2]
    frame = pd.DataFrame(
        {
            "x": pd.to_numeric(df[x_col], errors="coerce"),
            "y": pd.to_numeric(df[y_col], errors="coerce"),
            "s": pd.to_numeric(df[size_col], errors="coerce"),
        }
    ).dropna()
    if frame.empty:
        raise GraphError(f"bubble found no rows where '{x_col}', '{y_col}' and '{size_col}' are all numeric.")
    s_min, s_max = float(frame["s"].min()), float(frame["s"].max())
    r_min, r_max = 4.0, 22.0
    span = s_max - s_min
    points = [
        {
            "x": _safe(row.x),
            "y": _safe(row.y),
            "r": _safe(r_min if span == 0 else r_min + (row.s - s_min) / span * (r_max - r_min)),
            "size": _safe(row.s),
        }
        for row in frame.itertuples()
    ]
    return {"points": points, "x_label": x_col, "y_label": y_col, "size_label": size_col, "size_min": _safe(s_min), "size_max": _safe(s_max)}


def _line(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "line", "x, y")
    x_col, y_col = columns[0], columns[1]
    frame = _xy(df, x_col, y_col, "line").sort_values("x")
    return {
        "points": [{"x": _safe(r.x), "y": _safe(r.y)} for r in frame.itertuples()],
        "x_label": x_col,
        "y_label": y_col,
    }


def _bar(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Category column plus an optional value column: with a value column the bars are its mean
    (or sum) per category, without one they are row counts."""
    _require(columns, 1, "bar", "category")
    cat_col = columns[0]
    value_col = columns[1] if len(columns) > 1 else (options.get("value_column") or None)
    group_col = options.get("group_column") or None
    agg = (options.get("aggregate") or "mean").lower()
    if cat_col not in df.columns:
        raise GraphError(f"Column '{cat_col}' is not in this dataset.")

    labels = [str(v) for v in pd.Index(df[cat_col].astype(str).dropna().unique()).sort_values()]
    if not labels:
        raise GraphError(f"Column '{cat_col}' has no values to chart.")

    def aggregate(frame: pd.DataFrame) -> list[Any]:
        if not value_col:
            counts = frame[cat_col].astype(str).value_counts()
            return [int(counts.get(lab, 0)) for lab in labels]
        values = pd.to_numeric(frame[value_col], errors="coerce")
        grouped = values.groupby(frame[cat_col].astype(str))
        series = grouped.sum() if agg == "sum" else grouped.mean()
        return [_safe(series.get(lab)) for lab in labels]

    if group_col:
        if group_col not in df.columns:
            raise GraphError(f"Group column '{group_col}' is not in this dataset.")
        series = [{"label": str(label), "values": aggregate(chunk)} for label, chunk in df.groupby(df[group_col].astype(str), sort=True)]
    else:
        series = [{"label": (f"{agg} of {value_col}" if value_col else "count"), "values": aggregate(df)}]

    return {
        "labels": labels,
        "series": series,
        "x_label": cat_col,
        "y_label": (f"{agg} of {value_col}" if value_col else "count"),
        "stacked": bool(options.get("stacked")),
    }


def _pie(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 1, "pie", "category")
    cat_col = columns[0]
    value_col = columns[1] if len(columns) > 1 else (options.get("value_column") or None)
    if cat_col not in df.columns:
        raise GraphError(f"Column '{cat_col}' is not in this dataset.")
    if value_col:
        values = pd.to_numeric(df[value_col], errors="coerce")
        series = values.groupby(df[cat_col].astype(str)).sum().sort_values(ascending=False)
        label = f"sum of {value_col}"
    else:
        series = df[cat_col].astype(str).value_counts()
        label = "count"
    if series.empty:
        raise GraphError(f"pie found nothing to total for '{cat_col}'.")
    total = float(series.sum()) or 1.0
    return {
        "labels": [str(i) for i in series.index],
        "values": [_safe(v) for v in series.to_numpy()],
        "shares": [_safe(float(v) / total) for v in series.to_numpy()],
        "value_label": label,
        "category_label": cat_col,
    }


def _time_series(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "time_series", "date, value")
    date_col, value_col = columns[0], columns[1]
    for col in (date_col, value_col):
        if col not in df.columns:
            raise GraphError(f"Column '{col}' is not in this dataset.")
    dates = pd.to_datetime(df[date_col], errors="coerce")
    values = pd.to_numeric(df[value_col], errors="coerce")
    frame = pd.DataFrame({"t": dates, "y": values}).dropna().sort_values("t")
    if frame.empty:
        raise GraphError(f"time_series could not read '{date_col}' as dates paired with numeric '{value_col}'.")
    return {
        "points": [{"t": r.t.isoformat(), "y": _safe(r.y)} for r in frame.itertuples()],
        "x_label": date_col,
        "y_label": value_col,
        "n": int(len(frame)),
    }


def _histogram_graph(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 1, "histogram", "numeric column")
    column = columns[0]
    values = _numeric_series(df, column, "histogram").to_numpy(dtype=float)
    out = _histogram(values, options.get("bin_width"), options.get("n_bins"))
    out.update({"column": column, "x_label": column, "y_label": "frequency"})
    return out


# ---------------------------------------------------------------------------
# plugin-based types
# ---------------------------------------------------------------------------


def _boxplot(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 1, "boxplot", "numeric column(s)")
    group_col = options.get("group_column") or None
    entries: list[tuple[str, np.ndarray]] = []
    if group_col:
        entries = _group_values(df, columns[0], group_col, "boxplot")
    else:
        for column in columns:
            entries.append((column, _numeric_series(df, column, "boxplot").to_numpy(dtype=float)))

    groups = []
    for label, values in entries:
        q1, median, q3 = (float(v) for v in np.percentile(values, [25, 50, 75]))
        iqr = q3 - q1
        lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        inliers = values[(values >= lo_fence) & (values <= hi_fence)]
        outliers = values[(values < lo_fence) | (values > hi_fence)]
        groups.append(
            {
                "label": label,
                "min": _safe(float(np.min(inliers)) if inliers.size else float(np.min(values))),
                "q1": _safe(q1),
                "median": _safe(median),
                "q3": _safe(q3),
                "max": _safe(float(np.max(inliers)) if inliers.size else float(np.max(values))),
                "mean": _safe(float(np.mean(values))),
                "outliers": [_safe(v) for v in outliers.tolist()],
                "n": int(values.size),
            }
        )
    return {"groups": groups, "value_label": columns[0] if group_col else "value", "group_label": group_col or ""}


def _heatmap(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Row category × column category, colored by an aggregate of a value column (count when no
    value column is given) — a pivot table drawn as a matrix."""
    _require(columns, 2, "heatmap", "row category, column category")
    row_col, col_col = columns[0], columns[1]
    value_col = columns[2] if len(columns) > 2 else (options.get("value_column") or None)
    agg = (options.get("aggregate") or "mean").lower()
    for col in (row_col, col_col):
        if col not in df.columns:
            raise GraphError(f"Column '{col}' is not in this dataset.")

    if value_col:
        frame = df.assign(_v=pd.to_numeric(df[value_col], errors="coerce"))
        pivot = frame.pivot_table(index=frame[row_col].astype(str), columns=frame[col_col].astype(str), values="_v", aggfunc="sum" if agg == "sum" else "mean")
        value_label = f"{agg} of {value_col}"
    else:
        pivot = pd.crosstab(df[row_col].astype(str), df[col_col].astype(str))
        value_label = "count"
    if pivot.empty:
        raise GraphError("heatmap produced an empty table for those columns.")

    y_labels = [str(i) for i in pivot.index]
    x_labels = [str(c) for c in pivot.columns]
    cells = []
    for yi, y in enumerate(y_labels):
        for xi, x in enumerate(x_labels):
            cells.append({"x": x, "y": y, "xi": xi, "yi": yi, "value": _safe(pivot.iloc[yi, xi])})
    finite = [c["value"] for c in cells if c["value"] is not None]
    return {
        "x_labels": x_labels,
        "y_labels": y_labels,
        "cells": cells,
        "value_label": value_label,
        "min": _safe(min(finite) if finite else 0),
        "max": _safe(max(finite) if finite else 0),
        "x_label": col_col,
        "y_label": row_col,
    }


def _correlogram(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "correlogram", "2+ numeric columns")
    method = (options.get("method") or "pearson").lower()
    if method not in ("pearson", "spearman"):
        raise GraphError("Correlation method must be 'pearson' or 'spearman'.")
    frame = df[[c for c in columns if c in df.columns]].apply(pd.to_numeric, errors="coerce")
    if frame.shape[1] < 2:
        raise GraphError("correlogram needs at least 2 numeric columns.")
    matrix = frame.corr(method=method)
    labels = [str(c) for c in matrix.columns]
    cells = []
    for yi, y in enumerate(labels):
        for xi, x in enumerate(labels):
            cells.append({"x": x, "y": y, "xi": xi, "yi": yi, "value": _safe(matrix.iloc[yi, xi])})
    return {"x_labels": labels, "y_labels": labels, "cells": cells, "method": method, "value_label": f"{method} r", "min": -1, "max": 1}


def _binned_scatter(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "binned_scatter", "x, y")
    x_col, y_col = columns[0], columns[1]
    frame = _xy(df, x_col, y_col, "binned_scatter")
    x_bins = int(options.get("x_bins") or 12)
    y_bins = int(options.get("y_bins") or 10)
    counts, x_edges, y_edges = np.histogram2d(frame["x"].to_numpy(dtype=float), frame["y"].to_numpy(dtype=float), bins=[max(2, x_bins), max(2, y_bins)])
    cells = []
    for xi in range(counts.shape[0]):
        for yi in range(counts.shape[1]):
            count = int(counts[xi, yi])
            if count == 0:
                continue
            cells.append(
                {
                    "xi": xi,
                    "yi": yi,
                    "x0": _safe(x_edges[xi]),
                    "x1": _safe(x_edges[xi + 1]),
                    "y0": _safe(y_edges[yi]),
                    "y1": _safe(y_edges[yi + 1]),
                    "x": _safe((x_edges[xi] + x_edges[xi + 1]) / 2),
                    "y": _safe((y_edges[yi] + y_edges[yi + 1]) / 2),
                    "count": count,
                }
            )
    return {
        "cells": cells,
        "x_edges": [_safe(v) for v in x_edges.tolist()],
        "y_edges": [_safe(v) for v in y_edges.tolist()],
        "max_count": int(counts.max()) if counts.size else 0,
        "x_label": x_col,
        "y_label": y_col,
        "n": int(len(frame)),
    }


# ---------------------------------------------------------------------------
# computed statistical plots
# ---------------------------------------------------------------------------


def _dotplot(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Values binned, then stacked: each point carries the height it sits at in its bin, which is
    the whole trick to a dotplot and is much easier to do here than in the browser."""
    _require(columns, 1, "dotplot", "numeric column")
    column = columns[0]
    values = _numeric_series(df, column, "dotplot").to_numpy(dtype=float)
    edges = _bin_edges(values, options.get("bin_width"), options.get("n_bins") or 30)
    index = np.clip(np.digitize(values, edges) - 1, 0, len(edges) - 2)
    stacks: dict[int, int] = {}
    points = []
    for value, bin_index in sorted(zip(values.tolist(), index.tolist()), key=lambda pair: pair[0]):
        height = stacks.get(bin_index, 0) + 1
        stacks[bin_index] = height
        centre = (edges[bin_index] + edges[bin_index + 1]) / 2
        points.append({"x": _safe(centre), "y": height, "value": _safe(value)})
    return {
        "points": points,
        "max_stack": max(stacks.values()) if stacks else 0,
        "bin_width": _safe(edges[1] - edges[0]),
        "x_label": column,
        "y_label": "count",
        "n": int(values.size),
    }


def _individual_value(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Jittered by group. The jitter is generated here (seeded) so the picture is stable across
    re-renders and matches whatever ends up in an exported report."""
    _require(columns, 1, "individual_value", "numeric column")
    value_col = columns[0]
    group_col = options.get("group_column") or (columns[1] if len(columns) > 1 else None)
    entries = _group_values(df, value_col, group_col, "individual_value")
    rng = np.random.default_rng(12345)
    spread = float(options.get("jitter") or 0.16)
    groups = []
    for index, (label, values) in enumerate(entries):
        offsets = rng.uniform(-spread, spread, size=values.size)
        groups.append(
            {
                "label": label,
                "index": index,
                "mean": _safe(float(np.mean(values))),
                "points": [{"x": _safe(index + float(o)), "y": _safe(float(v))} for v, o in zip(values.tolist(), offsets.tolist())],
                "n": int(values.size),
            }
        )
    return {"groups": groups, "value_label": value_col, "group_label": group_col or "", "labels": [g["label"] for g in groups]}


def _interval(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 1, "interval", "numeric column")
    value_col = columns[0]
    group_col = options.get("group_column") or (columns[1] if len(columns) > 1 else None)
    level = float(options.get("confidence") or 0.95)
    if not 0 < level < 1:
        raise GraphError("Confidence level must be between 0 and 1.")
    entries = _group_values(df, value_col, group_col, "interval")
    groups = []
    for index, (label, values) in enumerate(entries):
        n = values.size
        mean = float(np.mean(values))
        if n > 1:
            se = float(stats.sem(values, ddof=1))
            half = float(stats.t.ppf(0.5 + level / 2, n - 1)) * se if se > 0 else 0.0
        else:
            se, half = 0.0, 0.0
        groups.append(
            {
                "label": label,
                "index": index,
                "mean": _safe(mean),
                "se": _safe(se),
                "ci_low": _safe(mean - half),
                "ci_high": _safe(mean + half),
                "n": int(n),
            }
        )
    return {
        "groups": groups,
        "labels": [g["label"] for g in groups],
        "confidence": level,
        "value_label": value_col,
        "group_label": group_col or "",
    }


def _factor_cells(df: pd.DataFrame, value_col: str, factors: list[str], graph_type: str) -> pd.DataFrame:
    """Complete-case frame of the response plus its factors, factors read as text labels."""
    if value_col not in df.columns:
        raise GraphError(f"Column '{value_col}' is not in this dataset.")
    missing = [f for f in factors if f not in df.columns]
    if missing:
        raise GraphError(f"Factor column(s) not in this dataset: {', '.join(missing)}.")
    data = {"__y": pd.to_numeric(df[value_col], errors="coerce")}
    for factor in factors:
        labels = df[factor].astype("object")
        data[factor] = labels.where(labels.notna() & (labels.astype(str).str.strip() != ""), np.nan)
    frame = pd.DataFrame(data).dropna()
    if frame.empty:
        raise GraphError(f"{graph_type} found no rows where '{value_col}' is numeric and every factor has a value.")
    for factor in factors:
        frame[factor] = frame[factor].astype(str)
    return frame


def _main_effects(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """One panel per factor: the response mean at each of its levels, against the grand mean.

    Shared by Graph > Main Effects Plot and Stat > ANOVA > Main Effects Plot — and, with the means
    supplied by a fitted model instead of the raw data, by the GLM's Factorial Plots.
    """
    _require(columns, 2, "main effects plot", "a response and at least one factor")
    value_col, factors = columns[0], [c for c in columns[1:] if c]
    frame = _factor_cells(df, value_col, factors, "Main effects plot")
    grand = float(frame["__y"].mean())

    panels = []
    for factor in factors:
        grouped = frame.groupby(factor, sort=True)["__y"]
        levels = [str(k) for k in grouped.groups.keys()]
        panels.append(
            {
                "factor": factor,
                "labels": levels,
                "points": [
                    {"x": i, "label": level, "y": _safe(float(grouped.get_group(level).mean())), "n": int(grouped.get_group(level).size)}
                    for i, level in enumerate(levels)
                ],
            }
        )
    return {
        "panels": panels,
        "grand_mean": _safe(grand),
        "value_label": value_col,
        "n": int(len(frame)),
        "fitted": False,
    }


def _interaction(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """One panel per pair of factors: the response mean at each combination, one line per level of
    the second factor. Parallel lines mean no interaction — that is the whole point of the plot."""
    _require(columns, 3, "interaction plot", "a response and at least two factors")
    value_col, factors = columns[0], [c for c in columns[1:] if c]
    if len(factors) < 2:
        raise GraphError("An interaction plot needs at least two factors.")
    frame = _factor_cells(df, value_col, factors, "Interaction plot")

    panels = []
    for i, x_factor in enumerate(factors):
        for trace_factor in factors[i + 1 :]:
            x_levels = sorted(frame[x_factor].unique().tolist())
            series = []
            for trace_level in sorted(frame[trace_factor].unique().tolist()):
                subset = frame[frame[trace_factor] == trace_level]
                points = []
                for index, x_level in enumerate(x_levels):
                    cell = subset[subset[x_factor] == x_level]["__y"]
                    # An empty cell breaks the line rather than being drawn at zero.
                    points.append({"x": index, "label": x_level, "y": None if cell.empty else _safe(float(cell.mean())), "n": int(cell.size)})
                series.append({"label": f"{trace_factor} = {trace_level}", "points": points})
            panels.append({"x_factor": x_factor, "trace_factor": trace_factor, "labels": x_levels, "series": series})

    return {"panels": panels, "value_label": value_col, "n": int(len(frame)), "fitted": False}


def _ecdf(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 1, "ecdf", "numeric column")
    value_col = columns[0]
    group_col = options.get("group_column") or None
    entries = _group_values(df, value_col, group_col, "ecdf")
    series = []
    for label, values in entries:
        ordered = np.sort(values)
        n = ordered.size
        points = [{"x": _safe(float(v)), "y": _safe((i + 1) / n)} for i, v in enumerate(ordered.tolist())]
        series.append({"label": label, "points": points, "n": int(n)})
    return {"series": series, "x_label": value_col, "y_label": "cumulative proportion", "group_label": group_col or ""}


def _probability(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Normal Q-Q plot: ordered sample values against the normal quantiles they would sit at,
    plus the fitted reference line — the standard normality check."""
    _require(columns, 1, "probability", "numeric column")
    column = columns[0]
    values = _numeric_series(df, column, "probability").to_numpy(dtype=float)
    if values.size < 3:
        raise GraphError("probability plot needs at least 3 values.")
    (theoretical, ordered), (slope, intercept, r) = stats.probplot(values, dist="norm", fit=True)
    line_x = [float(np.min(theoretical)), float(np.max(theoretical))]
    normality = stats.shapiro(values) if 3 <= values.size <= 5000 else None
    return {
        "points": [{"x": _safe(t), "y": _safe(v)} for t, v in zip(theoretical.tolist(), ordered.tolist())],
        "line": [{"x": _safe(x), "y": _safe(slope * x + intercept)} for x in line_x],
        "slope": _safe(slope),
        "intercept": _safe(intercept),
        "r_squared": _safe(r**2),
        "shapiro_p": _safe(normality.pvalue) if normality is not None else None,
        "mean": _safe(float(np.mean(values))),
        "std": _safe(float(np.std(values, ddof=1))) if values.size > 1 else None,
        "n": int(values.size),
        "x_label": "theoretical quantile",
        "y_label": column,
        "column": column,
    }


_DISTRIBUTIONS = {
    "normal": ("mean", "sd"),
    "t": ("df",),
    "chi_square": ("df",),
    "f": ("df1", "df2"),
    "binomial": ("n", "p"),
    "poisson": ("mean",),
}


def _distribution(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """No data columns: a textbook distribution curve from parameters, optionally with the area
    between two x-values shaded and its probability computed (Minitab's version of this plot)."""
    name = (options.get("distribution") or "normal").lower()
    if name not in _DISTRIBUTIONS:
        raise GraphError(f"Unknown distribution '{name}'. Expected one of: {', '.join(_DISTRIBUTIONS)}.")
    params = options.get("parameters") or {}
    kind = (options.get("curve") or "pdf").lower()
    if kind not in ("pdf", "cdf"):
        raise GraphError("curve must be 'pdf' or 'cdf'.")

    def param(key: str, default: float) -> float:
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            raise GraphError(f"Parameter '{key}' must be a number.") from None

    discrete = name in ("binomial", "poisson")
    if name == "normal":
        mean, sd = param("mean", 0.0), param("sd", 1.0)
        if sd <= 0:
            raise GraphError("Standard deviation must be greater than 0.")
        dist = stats.norm(loc=mean, scale=sd)
        label = f"Normal(mean={mean:g}, sd={sd:g})"
    elif name == "t":
        dof = param("df", 10.0)
        if dof <= 0:
            raise GraphError("Degrees of freedom must be greater than 0.")
        dist, label = stats.t(df=dof), f"t(df={dof:g})"
    elif name == "chi_square":
        dof = param("df", 5.0)
        if dof <= 0:
            raise GraphError("Degrees of freedom must be greater than 0.")
        dist, label = stats.chi2(df=dof), f"Chi-square(df={dof:g})"
    elif name == "f":
        df1, df2 = param("df1", 5.0), param("df2", 10.0)
        if df1 <= 0 or df2 <= 0:
            raise GraphError("Both degrees of freedom must be greater than 0.")
        dist, label = stats.f(dfn=df1, dfd=df2), f"F(df1={df1:g}, df2={df2:g})"
    elif name == "binomial":
        trials, prob = int(param("n", 20)), param("p", 0.5)
        if trials < 1 or not 0 <= prob <= 1:
            raise GraphError("Binomial needs n >= 1 and p between 0 and 1.")
        dist, label = stats.binom(n=trials, p=prob), f"Binomial(n={trials}, p={prob:g})"
    else:
        lam = param("mean", 4.0)
        if lam <= 0:
            raise GraphError("Poisson mean must be greater than 0.")
        dist, label = stats.poisson(mu=lam), f"Poisson(mean={lam:g})"

    if discrete:
        hi = int(dist.ppf(0.9995))
        xs = np.arange(0, max(hi, 1) + 1)
        ys = dist.cdf(xs) if kind == "cdf" else dist.pmf(xs)
    else:
        lo, hi = float(dist.ppf(0.0005)), float(dist.ppf(0.9995))
        xs = np.linspace(lo, hi, 400)
        ys = dist.cdf(xs) if kind == "cdf" else dist.pdf(xs)

    result = {
        "label": label,
        "distribution": name,
        "curve": kind,
        "discrete": discrete,
        "points": [{"x": _safe(x), "y": _safe(y)} for x, y in zip(np.asarray(xs).tolist(), np.asarray(ys).tolist())],
        "x_label": "x",
        "y_label": "cumulative probability" if kind == "cdf" else ("probability" if discrete else "density"),
        "mean": _safe(float(dist.mean())),
        "sd": _safe(float(dist.std())),
    }

    shade_from = options.get("shade_from")
    shade_to = options.get("shade_to")
    if shade_from is not None or shade_to is not None:
        lo_x = float(shade_from) if shade_from is not None else float(np.min(xs))
        hi_x = float(shade_to) if shade_to is not None else float(np.max(xs))
        if hi_x < lo_x:
            lo_x, hi_x = hi_x, lo_x
        probability = float(dist.cdf(hi_x) - (dist.cdf(lo_x - 1) if discrete else dist.cdf(lo_x)))
        shaded = [p for p in result["points"] if p["x"] is not None and lo_x <= p["x"] <= hi_x]
        result["shaded"] = {"from": _safe(lo_x), "to": _safe(hi_x), "probability": _safe(probability), "points": shaded}
    return result


def _stem_leaf(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """Text output, the way Minitab renders it: leaf unit, cumulative counts, stem, leaves."""
    _require(columns, 1, "stem_leaf", "numeric column")
    column = columns[0]
    values = np.sort(_numeric_series(df, column, "stem_leaf").to_numpy(dtype=float))
    n = values.size
    spread = float(values[-1] - values[0])
    # pick a leaf unit that yields roughly 5-20 stems
    exponent = math.floor(math.log10(spread / 12)) if spread > 0 else 0
    leaf_unit = 10.0**exponent
    stem_unit = leaf_unit * 10

    buckets: dict[int, list[int]] = {}
    for value in values.tolist():
        stem = int(math.floor(value / stem_unit))
        leaf = int(abs(round(value / leaf_unit)) % 10)
        buckets.setdefault(stem, []).append(leaf)

    stems = sorted(buckets)
    counts = [len(buckets[s]) for s in stems]
    median_position = (n + 1) / 2
    lines = []
    cumulative = 0
    running_from_top = list(np.cumsum(counts))
    running_from_bottom = list(np.cumsum(counts[::-1]))[::-1]
    for i, stem in enumerate(stems):
        cumulative += counts[i]
        if running_from_top[i] >= median_position and (i == 0 or running_from_top[i - 1] < median_position):
            depth = f"({counts[i]})"
        elif running_from_top[i] < median_position:
            depth = str(running_from_top[i])
        else:
            depth = str(running_from_bottom[i])
        leaves = "".join(str(leaf) for leaf in sorted(buckets[stem]))
        lines.append(f"{depth:>5}  {stem:>4}  {leaves}")

    header = [
        f"Stem-and-Leaf Display: {column}",
        "",
        f"Leaf Unit = {leaf_unit:g}    N = {n}",
        "",
    ]
    return {
        "text": "\n".join(header + lines),
        "leaf_unit": _safe(leaf_unit),
        "n": int(n),
        "column": column,
        "stems": len(stems),
    }


# ---------------------------------------------------------------------------
# composite / multi-panel
# ---------------------------------------------------------------------------


def _matrix_plot(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "matrix_plot", "2+ numeric columns")
    picked = [c for c in columns if c in df.columns][:MATRIX_PLOT_COLUMN_CAP]
    frame = df[picked].apply(pd.to_numeric, errors="coerce").dropna()
    if frame.empty or frame.shape[1] < 2:
        raise GraphError("matrix_plot needs at least 2 numeric columns with overlapping values.")
    panels = []
    for y_col in picked:
        for x_col in picked:
            if x_col == y_col:
                panels.append({"x_col": x_col, "y_col": y_col, "diagonal": True, "points": []})
                continue
            panels.append(
                {
                    "x_col": x_col,
                    "y_col": y_col,
                    "diagonal": False,
                    "points": [{"x": _safe(a), "y": _safe(b)} for a, b in zip(frame[x_col].tolist(), frame[y_col].tolist())],
                }
            )
    return {
        "columns": picked,
        "panels": panels,
        "n": int(len(frame)),
        "truncated_columns": max(0, len([c for c in columns if c in df.columns]) - len(picked)),
    }


def _marginal(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "marginal", "x, y")
    x_col, y_col = columns[0], columns[1]
    frame = _xy(df, x_col, y_col, "marginal")
    return {
        "points": [{"x": _safe(r.x), "y": _safe(r.y)} for r in frame.itertuples()],
        "x_hist": _histogram(frame["x"].to_numpy(dtype=float), options.get("bin_width")),
        "y_hist": _histogram(frame["y"].to_numpy(dtype=float), options.get("bin_width")),
        "x_label": x_col,
        "y_label": y_col,
        "n": int(len(frame)),
    }


def _parallel_coords(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    _require(columns, 2, "parallel_coords", "2+ numeric columns")
    picked = [c for c in columns if c in df.columns]
    frame = df[picked].apply(pd.to_numeric, errors="coerce").dropna()
    if frame.empty or frame.shape[1] < 2:
        raise GraphError("parallel_coords needs at least 2 numeric columns with overlapping values.")

    group_col = options.get("group_column") or None
    groups = df.loc[frame.index, group_col].astype(str) if group_col and group_col in df.columns else None

    total = int(len(frame))
    cap = int(options.get("row_cap") or PARALLEL_ROW_CAP)
    truncated = total > cap
    if truncated:
        frame = frame.iloc[:cap]
        if groups is not None:
            groups = groups.iloc[:cap]

    axes = []
    normalized = pd.DataFrame(index=frame.index)
    for column in picked:
        lo, hi = float(frame[column].min()), float(frame[column].max())
        span = hi - lo
        axes.append({"name": column, "min": _safe(lo), "max": _safe(hi)})
        normalized[column] = 0.5 if span == 0 else (frame[column] - lo) / span

    rows = []
    for position, (_index, row) in enumerate(normalized.iterrows()):
        rows.append(
            {
                "values": [_safe(v) for v in row.tolist()],
                "raw": [_safe(v) for v in frame.iloc[position].tolist()],
                "group": str(groups.iloc[position]) if groups is not None else None,
            }
        )
    return {
        "axes": axes,
        "rows": rows,
        "n_total": total,
        "n_drawn": len(rows),
        "truncated": truncated,
        "row_cap": cap,
        "group_label": group_col or "",
    }


# ---------------------------------------------------------------------------
# 3D / contour
# ---------------------------------------------------------------------------


def _grid_from_xyz(frame: pd.DataFrame, resolution: int) -> tuple[list[float], list[float], list[list[Any]]]:
    """Scattered (x, y, z) readings interpolated onto a regular grid — contour and surface both
    need a grid, and real data almost never arrives on one."""
    x = frame["x"].to_numpy(dtype=float)
    y = frame["y"].to_numpy(dtype=float)
    z = frame["z"].to_numpy(dtype=float)
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        raise GraphError("The x and y columns must each vary — with one of them constant there is no surface to draw.")

    resolution = max(8, min(int(resolution or 40), 80))
    xi = np.linspace(x.min(), x.max(), resolution)
    yi = np.linspace(y.min(), y.max(), resolution)
    mesh_x, mesh_y = np.meshgrid(xi, yi)

    # Linear interpolation triangulates, which Qhull refuses to do when the x/y points are
    # collinear (two columns that are exact multiples of each other, say). Nearest-neighbour uses
    # a KD-tree instead, so it still produces a readable surface for that degenerate case.
    grid = None
    try:
        grid = interpolate.griddata((x, y), z, (mesh_x, mesh_y), method="linear")
    except Exception:  # noqa: BLE001 - scipy raises QhullError for degenerate input
        grid = None
    if grid is None or np.all(np.isnan(grid)):
        try:
            grid = interpolate.griddata((x, y), z, (mesh_x, mesh_y), method="nearest")
        except Exception as exc:  # noqa: BLE001
            raise GraphError(
                "Could not interpolate a grid from these columns — the x/y points are degenerate "
                "(often because the two columns are exact multiples of one another). Pick x and y "
                "columns that vary independently."
            ) from exc
    rows = [[_safe(v) for v in row] for row in grid.tolist()]
    return [_safe(v) for v in xi.tolist()], [_safe(v) for v in yi.tolist()], rows


def _xyz_frame(df: pd.DataFrame, columns: list[str], graph_type: str) -> pd.DataFrame:
    _require(columns, 3, graph_type, "x, y, z")
    for col in columns[:3]:
        if col not in df.columns:
            raise GraphError(f"Column '{col}' is not in this dataset.")
    frame = pd.DataFrame(
        {
            "x": pd.to_numeric(df[columns[0]], errors="coerce"),
            "y": pd.to_numeric(df[columns[1]], errors="coerce"),
            "z": pd.to_numeric(df[columns[2]], errors="coerce"),
        }
    ).dropna()
    if len(frame) < 4:
        raise GraphError(f"{graph_type} needs at least 4 rows where x, y and z are all numeric.")
    return frame


def _contour(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    frame = _xyz_frame(df, columns, "contour")
    xi, yi, grid = _grid_from_xyz(frame, options.get("resolution"))
    return {"x": xi, "y": yi, "z": grid, "x_label": columns[0], "y_label": columns[1], "z_label": columns[2], "n": int(len(frame))}


def _surface(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    out = _contour(df, columns, options)
    out["kind"] = "surface"
    return out


def _scatter3d(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    frame = _xyz_frame(df, columns, "scatter3d")
    group_col = options.get("group_column") or (columns[3] if len(columns) > 3 else None)
    if group_col and group_col in df.columns:
        labels = df.loc[frame.index, group_col].astype(str)
        series = []
        for label, chunk in frame.assign(g=labels).groupby("g", sort=True):
            series.append(
                {
                    "label": str(label),
                    "x": [_safe(v) for v in chunk["x"].tolist()],
                    "y": [_safe(v) for v in chunk["y"].tolist()],
                    "z": [_safe(v) for v in chunk["z"].tolist()],
                }
            )
    else:
        series = [
            {
                "label": columns[2],
                "x": [_safe(v) for v in frame["x"].tolist()],
                "y": [_safe(v) for v in frame["y"].tolist()],
                "z": [_safe(v) for v in frame["z"].tolist()],
            }
        ]
    return {"series": series, "x_label": columns[0], "y_label": columns[1], "z_label": columns[2], "group_label": group_col or "", "n": int(len(frame))}


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_COMPUTERS = {
    "scatter": _scatter,
    "bubble": _bubble,
    "line": _line,
    "area": _line,
    "bar": _bar,
    "pie": _pie,
    "time_series": _time_series,
    "histogram": _histogram_graph,
    "boxplot": _boxplot,
    "heatmap": _heatmap,
    "correlogram": _correlogram,
    "binned_scatter": _binned_scatter,
    "dotplot": _dotplot,
    "individual_value": _individual_value,
    "interval": _interval,
    "main_effects": _main_effects,
    "interaction": _interaction,
    "ecdf": _ecdf,
    "probability": _probability,
    "distribution": _distribution,
    "stem_leaf": _stem_leaf,
    "matrix_plot": _matrix_plot,
    "marginal": _marginal,
    "parallel_coords": _parallel_coords,
    "contour": _contour,
    "surface": _surface,
    "scatter3d": _scatter3d,
}


def compute(df: pd.DataFrame, graph_type: str, columns: list[str], options: dict | None = None) -> dict:
    """Return the series a single graph needs. `graph_type` is one of GRAPH_TYPES."""
    computer = _COMPUTERS.get(graph_type)
    if computer is None:
        raise GraphError(f"Unknown graph_type '{graph_type}'. Expected one of: {', '.join(GRAPH_TYPES)}.")
    opts = dict(options or {})
    cols = list(columns or [])
    result = computer(df, cols, opts)
    result.setdefault("graph_type", graph_type)
    result.setdefault("columns", cols)

    # The grouping check runs once, HERE, for every graph type that takes one — rather than in each of
    # the nine computers that reach for `group_column`. A degenerate column has already raised out of
    # the computer (via _group_values); what this adds is the soft warning, carried in the payload so
    # the result window and the report can both show it.
    group_col = opts.get("group_column") or None
    if group_col and not result.get("warnings"):
        warning = _group_note(df, cols[0] if cols else "", group_col, graph_type)
        if warning:
            result["warnings"] = [warning]
    return result
