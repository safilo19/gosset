"""The one way this suite calls into the core.

Every test goes through `run_basic_stats` / `run_regression` / `run_anova` / `run_calc` /
`run_graph` / `run_data_op` rather than importing `compute` directly, and each of those runs
`properties.check_result_invariants` on the way out. That is what makes the universal property
checks apply to ALL result schemas instead of the ones a test author remembered — adding a
procedure to the suite gets them for free, and there is no way to opt out by accident.

It also gives the suite one place to record which procedures were exercised, which is where
VALIDATION.md's coverage table comes from.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from backend.core import anova, basic_stats, calc, data_ops, graphs, regression_models
from backend.tests.properties import check_result_invariants


def run_basic_stats(
    df: pd.DataFrame,
    procedure: str,
    columns: Sequence[str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict:
    result = basic_stats.compute(df, procedure, list(columns or []), dict(options or {}))
    return check_result_invariants(result, context=f"basic_stats.{procedure}")


def run_regression(
    df: pd.DataFrame,
    procedure: str,
    columns: Sequence[str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict:
    result = regression_models.compute(df, procedure, list(columns or []), dict(options or {}))
    return check_result_invariants(result, context=f"regression_models.{procedure}")


def run_anova(
    df: pd.DataFrame,
    procedure: str,
    columns: Sequence[str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict:
    result = anova.compute(df, procedure, list(columns or []), dict(options or {}))
    return check_result_invariants(result, context=f"anova.{procedure}")


def run_calc(
    df: pd.DataFrame,
    procedure: str,
    columns: Sequence[str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict:
    result = calc.compute(df, procedure, list(columns or []), dict(options or {}))
    return check_result_invariants(result, context=f"calc.{procedure}")


def run_graph(
    df: pd.DataFrame,
    graph_type: str,
    columns: Sequence[str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict:
    result = graphs.compute(df, graph_type, list(columns or []), dict(options or {}))
    return check_result_invariants(result, context=f"graphs.{graph_type}")


def run_data_op(
    df: pd.DataFrame,
    operation: str,
    options: Mapping[str, Any] | None = None,
    *,
    others: Mapping[str, pd.DataFrame] | None = None,
    names: Mapping[str, str] | None = None,
) -> data_ops.DataOpResult:
    """Data operations return a `DataOpResult` dataclass, not the tables/highlights envelope, so the
    invariant walker is pointed at its `report` payload rather than at the frames it carries."""
    result = data_ops.compute(df, operation, dict(options or {}), others=dict(others or {}), names=dict(names or {}))
    check_result_invariants(result.report, context=f"data_ops.{operation}.report")
    return result
