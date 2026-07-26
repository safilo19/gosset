"""describe_dataset and compute_correlation logic. Plain Python — no MCP or web-framework code."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import pandas as pd


@dataclass
class ColumnStatsResult:
    column: str
    dtype: str
    count: int
    missing: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | str | None = None
    max: float | str | None = None


def describe_columns(df: pd.DataFrame, columns: list[str]) -> list[ColumnStatsResult]:
    stats: list[ColumnStatsResult] = []
    for col in columns:
        series = df[col]
        missing = int(series.isna().sum())
        count = int(series.notna().sum())

        if pd.api.types.is_numeric_dtype(series):
            mean = series.mean()
            median = series.median()
            std = series.std()
            col_min = series.min()
            col_max = series.max()
            stats.append(
                ColumnStatsResult(
                    column=col,
                    dtype=str(series.dtype),
                    count=count,
                    missing=missing,
                    mean=None if pd.isna(mean) else float(mean),
                    median=None if pd.isna(median) else float(median),
                    std=None if pd.isna(std) else float(std),
                    min=None if pd.isna(col_min) else float(col_min),
                    max=None if pd.isna(col_max) else float(col_max),
                )
            )
        else:
            non_null = series.dropna()
            stats.append(
                ColumnStatsResult(
                    column=col,
                    dtype=str(series.dtype),
                    count=count,
                    missing=missing,
                    min=str(non_null.min()) if not non_null.empty else None,
                    max=str(non_null.max()) if not non_null.empty else None,
                )
            )
    return stats


def describe_summary(dataset_id: str, stats: list[ColumnStatsResult]) -> str:
    lines = [f"Described {len(stats)} column(s) of dataset '{dataset_id}':"]
    for s in stats:
        if s.mean is not None:
            lines.append(
                f"- {s.column} ({s.dtype}): mean={s.mean:.3g}, median={s.median:.3g}, std={s.std:.3g}, "
                f"range=[{s.min:.3g}, {s.max:.3g}], missing={s.missing}"
            )
        else:
            lines.append(f"- {s.column} ({s.dtype}): range=[{s.min}, {s.max}], missing={s.missing}")
    return "\n".join(lines)


@dataclass
class CorrelationPairResult:
    column_a: str
    column_b: str
    correlation: float
    strength: str


@dataclass
class CorrelationResult:
    matrix: dict[str, dict[str, float | None]]
    strongest_pairs: list[CorrelationPairResult]
    interpretation: str
    summary: str


def strength_label(correlation: float) -> str:
    magnitude = abs(correlation)
    if magnitude >= 0.7:
        strength = "strong"
    elif magnitude >= 0.4:
        strength = "moderate"
    elif magnitude >= 0.2:
        strength = "weak"
    else:
        return "negligible"
    direction = "positive" if correlation >= 0 else "negative"
    return f"{strength} {direction}"


def compute_correlation(dataset_id: str, df: pd.DataFrame, columns: list[str], method: str) -> CorrelationResult:
    non_numeric = [c for c in columns if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        raise ValueError(
            f"Column(s) {', '.join(non_numeric)} are not numeric and cannot be correlated. "
            f"Numeric columns available in '{dataset_id}': {', '.join(numeric_cols) or '(none)'}"
        )

    corr_df = df[columns].corr(method=method)
    matrix: dict[str, dict[str, float | None]] = {
        col: {other: (None if pd.isna(v) else round(float(v), 4)) for other, v in row.items()}
        for col, row in corr_df.to_dict().items()
    }

    pairs = []
    for col_a, col_b in combinations(columns, 2):
        value = corr_df.loc[col_a, col_b]
        if pd.isna(value):
            continue
        pairs.append(
            CorrelationPairResult(
                column_a=col_a,
                column_b=col_b,
                correlation=round(float(value), 4),
                strength=strength_label(float(value)),
            )
        )
    pairs.sort(key=lambda p: abs(p.correlation), reverse=True)
    strongest = pairs[:3]

    if strongest:
        top = strongest[0]
        interpretation = (
            f"The strongest relationship is between '{top.column_a}' and '{top.column_b}' "
            f"(r = {top.correlation}, {method}) — a {top.strength} correlation."
        )
        if len(strongest) > 1:
            others = "; ".join(f"'{p.column_a}' vs '{p.column_b}' (r = {p.correlation}, {p.strength})" for p in strongest[1:])
            interpretation += f" Other notable pairs: {others}."
    else:
        interpretation = "No valid correlation could be computed for the given columns (insufficient non-missing data)."

    summary = (
        f"Computed {method} correlation across {len(columns)} columns in dataset '{dataset_id}'.\n{interpretation}"
    )

    return CorrelationResult(matrix=matrix, strongest_pairs=strongest, interpretation=interpretation, summary=summary)
