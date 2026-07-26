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

_CHART_DIR = Path(tempfile.gettempdir()) / "personal_analytics_mcp_charts"


@dataclass
class ChartResult:
    title: str
    chart_path: str
    image_base64: str
    summary: str


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
    fig, ax = plt.subplots(figsize=(8, 5))

    if chart_type == "bar":
        cat_col, value_col = columns
        grouped = df.groupby(cat_col)[value_col].mean()
        ax.bar(grouped.index.astype(str), grouped.to_numpy())
        ax.set_xlabel(cat_col)
        ax.set_ylabel(f"mean {value_col}")
        title = f"Mean {value_col} by {cat_col}"

    elif chart_type == "line":
        x_col, y_col = columns
        sub = df[[x_col, y_col]].dropna().sort_values(x_col)
        ax.plot(sub[x_col], sub[y_col], marker="o")
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        title = f"{y_col} over {x_col}"
        fig.autofmt_xdate()

    elif chart_type == "scatter":
        x_col, y_col = columns
        sub = df[[x_col, y_col]].dropna()
        ax.scatter(sub[x_col], sub[y_col], alpha=0.7)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        title = f"{y_col} vs. {x_col}"

    elif chart_type == "histogram":
        col = columns[0]
        ax.hist(df[col].dropna(), bins=20, edgecolor="white")
        ax.set_xlabel(col)
        ax.set_ylabel("count")
        title = f"Distribution of {col}"

    else:  # heatmap
        corr = df[columns].corr()
        im = ax.imshow(corr.to_numpy(), cmap="coolwarm", vmin=-1, vmax=1)
        ax.set_xticks(range(len(columns)))
        ax.set_yticks(range(len(columns)))
        ax.set_xticklabels(columns, rotation=45, ha="right")
        ax.set_yticklabels(columns)
        for i in range(len(columns)):
            for j in range(len(columns)):
                ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", color="black", fontsize=8)
        fig.colorbar(im, ax=ax, label="correlation")
        title = f"Correlation heatmap ({', '.join(columns)})"

    ax.set_title(title)
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
