"""Chart generation for generate_chart, using matplotlib's non-interactive Agg backend.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import base64
import io
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

_CHART_DIR = Path(tempfile.gettempdir()) / "personal_analytics_mcp_charts"

# House style, matching the frontend's design tokens (--ink, --muted, --border, --accent) so a
# server-rendered PNG sits in a result window without looking like it came from somewhere else.
# IBM Plex Sans is used when installed; matplotlib falls back down the list otherwise.
_INK = "#161616"
_MUTED = "#6f6f6f"
_BORDER = "#d5dae1"
_GRID = "#e5e8ec"
_ACCENT = "#0f62fe"
_DANGER = "#da1e28"

_HOUSE_STYLE = {
    "font.family": "sans-serif",
    "font.sans-serif": ["IBM Plex Sans", "Segoe UI", "DejaVu Sans"],
    "font.size": 9.5,
    "figure.facecolor": "#ffffff",
    "savefig.facecolor": "#ffffff",
    "axes.facecolor": "#ffffff",
    "axes.edgecolor": _BORDER,
    "axes.linewidth": 0.8,
    "axes.labelcolor": _MUTED,
    "axes.labelsize": 9.5,
    "axes.titlesize": 11,
    # "medium" logs a findfont warning on every render for fonts without that weight
    "axes.titleweight": "normal",
    "axes.titlecolor": _INK,
    "axes.titlelocation": "left",
    "axes.titlepad": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "axes.prop_cycle": plt.cycler(color=[_ACCENT, "#007d79", "#d02670", "#198038", "#ff832b"]),
    "grid.color": _GRID,
    "grid.linewidth": 0.8,
    "text.color": _INK,
    "xtick.color": _MUTED,
    "ytick.color": _MUTED,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "legend.frameon": False,
}

# Diverging map for the correlation heatmap: --danger through a neutral to --accent.
_CORR_CMAP = LinearSegmentedColormap.from_list("pa_corr", [_DANGER, "#f4f4f4", _ACCENT])


@dataclass
class ChartResult:
    title: str
    chart_path: str
    image_base64: str
    summary: str


def _finish(fig, ax, title: str, out_path: Path) -> Path:
    ax.set_title(title)
    ax.tick_params(length=3, width=0.8, color=_BORDER)
    ax.set_axisbelow(True)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format="png", dpi=120)
    plt.close(fig)
    return out_path


def _short(labels: list[str], limit: int = 18) -> list[str]:
    return [lab if len(lab) <= limit else f"{lab[: limit - 1]}…" for lab in labels]


def render_analysis_chart(data: dict, title: str, out_path: Path) -> Path | None:
    """Render a chart straight from an analysis result, for analyses that don't produce their own
    PNG (only generate_chart does). Exported reports need a figure under every section's table,
    and until this existed a regression or segmentation section had nothing to embed.

    Returns None when the result has no shape worth plotting (e.g. describe, whose per-column
    means are in different units and would make a misleading single bar chart)."""
    with plt.rc_context(_HOUSE_STYLE):
        rows = data.get("coefficients")
        if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
            fig, ax = plt.subplots(figsize=(7.2, 3.6))
            labels = _short([str(r.get("feature", "")) for r in rows])
            values = [float(r.get("coefficient") or 0) for r in rows]
            # washed out where the model doesn't support the effect
            alphas = [0.4 if r.get("significant") is False else 1.0 for r in rows]
            colors_ = [(0.14, 0.63, 0.28, a) if v >= 0 else (0.85, 0.12, 0.16, a) for v, a in zip(values, alphas)]
            ax.bar(labels, values, color=colors_, width=0.6)
            ax.axhline(0, color=_BORDER, linewidth=0.8)
            ax.set_ylabel("coefficient")
            return _finish(fig, ax, f"{title} — coefficients", out_path)

        pairs = data.get("strongest_pairs")
        if isinstance(pairs, list) and pairs and all(isinstance(r, dict) for r in pairs):
            fig, ax = plt.subplots(figsize=(7.2, 3.6))
            labels = _short([f"{r.get('column_a')} × {r.get('column_b')}" for r in pairs], 24)
            values = [float(r.get("correlation") or 0) for r in pairs]
            ax.bar(labels, values, color=[_ACCENT if v >= 0 else _DANGER for v in values], width=0.6)
            ax.set_ylim(-1, 1)
            ax.axhline(0, color=_BORDER, linewidth=0.8)
            ax.set_ylabel("correlation")
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
            return _finish(fig, ax, f"{title} — correlations", out_path)

        points = data.get("forecast")
        if isinstance(points, list) and points and all(isinstance(r, dict) for r in points):
            fig, ax = plt.subplots(figsize=(7.2, 3.6))
            periods = [str(r.get("period", i)) for i, r in enumerate(points)]
            values = [float(r.get("forecast") or 0) for r in points]
            lower = [r.get("lower_ci") for r in points]
            upper = [r.get("upper_ci") for r in points]
            if all(v is not None for v in lower + upper):
                ax.fill_between(periods, [float(v) for v in lower], [float(v) for v in upper], color=_ACCENT, alpha=0.14, label="confidence interval")
            ax.plot(periods, values, marker="o", markersize=3.5, linewidth=1.6, color=_ACCENT, label="forecast")
            ax.set_ylabel("forecast")
            ax.legend(loc="best")
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
            return _finish(fig, ax, f"{title} — forecast", out_path)

        segments = data.get("segments")
        if isinstance(segments, list) and segments and all(isinstance(r, dict) for r in segments):
            fig, ax = plt.subplots(figsize=(7.2, 3.6))
            labels = _short([str(r.get("segment", "")) for r in segments], 22)
            sizes = [float(r.get("size") or 0) for r in segments]
            ax.bar(labels, sizes, color=_ACCENT, width=0.6)
            ax.set_ylabel("rows in segment")
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
            return _finish(fig, ax, f"{title} — segment sizes", out_path)

        importances = data.get("feature_importances")
        if isinstance(importances, list) and importances and all(isinstance(r, dict) for r in importances):
            ordered = sorted(importances, key=lambda r: float(r.get("importance") or 0), reverse=True)
            fig, ax = plt.subplots(figsize=(7.2, 3.6))
            ax.bar(_short([str(r.get("feature", "")) for r in ordered]), [float(r.get("importance") or 0) for r in ordered], color=_ACCENT, width=0.6)
            ax.set_ylabel("importance")
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
            return _finish(fig, ax, f"{title} — feature importance", out_path)

        models = data.get("results")
        if isinstance(models, list) and models and all(isinstance(r, dict) and "model" in r for r in models):
            ordered = sorted(models, key=lambda r: float(r.get("score") or 0), reverse=True)
            best = data.get("best_model")
            fig, ax = plt.subplots(figsize=(7.2, 3.6))
            ax.bar(
                _short([str(r.get("model", "")) for r in ordered], 22),
                [float(r.get("score") or 0) for r in ordered],
                color=["#198038" if r.get("model") == best else _ACCENT for r in ordered],
                width=0.6,
            )
            ax.set_ylabel("score")
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
            return _finish(fig, ax, f"{title} — model comparison", out_path)

        groups = data.get("groups")
        if isinstance(groups, list) and groups and all(isinstance(r, dict) for r in groups):
            usable = [r for r in groups if r.get("mean") is not None]
            if usable:
                fig, ax = plt.subplots(figsize=(7.2, 3.6))
                ax.bar(_short([str(r.get("group", "")) for r in usable], 22), [float(r["mean"]) for r in usable], color=_ACCENT, width=0.6)
                ax.set_ylabel("group mean")
                plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
                return _finish(fig, ax, f"{title} — group means", out_path)

    return None


def validate_columns(chart_type: str, columns: list[str], df: pd.DataFrame) -> None:
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    if chart_type == "histogram":
        if len(columns) != 1:
            raise ValueError(f"histogram needs exactly 1 numeric column, got {len(columns)}: {columns}.")
        if not pd.api.types.is_numeric_dtype(df[columns[0]]):
            raise ValueError(
                f"histogram needs a numeric column; '{columns[0]}' has dtype {df[columns[0]].dtype}. "
                f"Numeric columns available: {', '.join(numeric_cols) or '(none)'}"
            )
    elif chart_type in ("bar", "line", "scatter"):
        if len(columns) != 2:
            raise ValueError(f"{chart_type} needs exactly 2 columns [x, y], got {len(columns)}: {columns}.")
        y_col = columns[1]
        if not pd.api.types.is_numeric_dtype(df[y_col]):
            raise ValueError(
                f"{chart_type} needs a numeric y column; '{y_col}' has dtype {df[y_col].dtype}. "
                f"Numeric columns available: {', '.join(numeric_cols) or '(none)'}"
            )
        if chart_type == "scatter" and not pd.api.types.is_numeric_dtype(df[columns[0]]):
            raise ValueError(
                f"scatter needs a numeric x column; '{columns[0]}' has dtype {df[columns[0]].dtype}. "
                f"Numeric columns available: {', '.join(numeric_cols) or '(none)'}"
            )
    elif chart_type == "heatmap":
        if len(columns) < 2:
            raise ValueError(
                f"heatmap needs at least 2 numeric columns to compute a correlation matrix, got {len(columns)}: "
                f"{columns}. Numeric columns available: {', '.join(numeric_cols) or '(none)'}"
            )
        non_numeric = [c for c in columns if not pd.api.types.is_numeric_dtype(df[c])]
        if non_numeric:
            raise ValueError(
                f"heatmap needs numeric columns; {', '.join(non_numeric)} are not numeric. "
                f"Numeric columns available: {', '.join(numeric_cols) or '(none)'}"
            )
    else:
        raise ValueError(f"Unknown chart_type '{chart_type}'.")


def generate_chart(dataset_id: str, chart_type: str, columns: list[str], df: pd.DataFrame) -> ChartResult:
    validate_columns(chart_type, columns, df)
    with plt.rc_context(_HOUSE_STYLE):
        fig, ax = plt.subplots(figsize=(8, 4.6))

        if chart_type == "bar":
            cat_col, value_col = columns
            grouped = df.groupby(cat_col)[value_col].mean()
            ax.bar(grouped.index.astype(str), grouped.to_numpy(), color=_ACCENT, width=0.62)
            ax.set_xlabel(cat_col)
            ax.set_ylabel(f"mean {value_col}")
            title = f"Mean {value_col} by {cat_col}"

        elif chart_type == "line":
            x_col, y_col = columns
            sub = df[[x_col, y_col]].dropna().sort_values(x_col)
            ax.plot(sub[x_col], sub[y_col], marker="o", markersize=3.5, linewidth=1.6, color=_ACCENT)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            title = f"{y_col} over {x_col}"
            fig.autofmt_xdate()

        elif chart_type == "scatter":
            x_col, y_col = columns
            sub = df[[x_col, y_col]].dropna()
            ax.scatter(sub[x_col], sub[y_col], s=26, alpha=0.85, color=_ACCENT, linewidths=0)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            title = f"{y_col} vs. {x_col}"

        elif chart_type == "histogram":
            col = columns[0]
            ax.hist(df[col].dropna(), bins=20, color=_ACCENT, edgecolor="#ffffff", linewidth=0.8)
            ax.set_xlabel(col)
            ax.set_ylabel("count")
            title = f"Distribution of {col}"

        else:  # heatmap
            corr = df[columns].corr()
            # A cell grid, not a continuous field: the gridlines and y-axis grid would draw
            # over the image, so they are turned off for this one chart type.
            ax.grid(False)
            im = ax.imshow(corr.to_numpy(), cmap=_CORR_CMAP, vmin=-1, vmax=1)
            ax.set_xticks(range(len(columns)))
            ax.set_yticks(range(len(columns)))
            ax.set_xticklabels(columns, rotation=45, ha="right")
            ax.set_yticklabels(columns)
            for i in range(len(columns)):
                for j in range(len(columns)):
                    value = corr.iloc[i, j]
                    ax.text(
                        j,
                        i,
                        f"{value:.2f}",
                        ha="center",
                        va="center",
                        color="#ffffff" if abs(value) > 0.62 else _INK,
                        fontsize=8.5,
                    )
            bar = fig.colorbar(im, ax=ax, label="correlation")
            bar.outline.set_edgecolor(_BORDER)
            title = f"Correlation heatmap ({', '.join(columns)})"

        ax.set_title(title)
        ax.tick_params(length=3, width=0.8, color=_BORDER)
        ax.set_axisbelow(True)
        fig.tight_layout()

        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=120)
    plt.close(fig)
    buffer.seek(0)
    png_bytes = buffer.getvalue()

    _CHART_DIR.mkdir(parents=True, exist_ok=True)
    chart_path = _CHART_DIR / f"{dataset_id}_{chart_type}_{uuid.uuid4().hex[:8]}.png"
    chart_path.write_bytes(png_bytes)

    summary = f"Generated a {chart_type} chart ('{title}') for dataset '{dataset_id}', saved to {chart_path}."

    return ChartResult(
        title=title,
        chart_path=str(chart_path),
        image_base64=base64.b64encode(png_bytes).decode("ascii"),
        summary=summary,
    )
