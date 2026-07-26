"""run_hypothesis_test logic (t_test / anova / chi_square). Plain Python — no MCP or web-framework code."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


@dataclass
class HypothesisTestResult:
    statistic: float
    p_value: float
    degrees_of_freedom: float | None = None
    df_between: int | None = None
    df_within: int | None = None
    groups: list[dict] = field(default_factory=list)
    contingency_table: dict[str, dict[str, int]] | None = None


def run_t_test(df: pd.DataFrame, value_col: str, group_col: str) -> HypothesisTestResult:
    if not pd.api.types.is_numeric_dtype(df[value_col]):
        raise ValueError(f"t_test needs a numeric value column; '{value_col}' has dtype {df[value_col].dtype}.")

    sub = df[[value_col, group_col]].dropna()
    grouped = {name: g[value_col].to_numpy() for name, g in sub.groupby(group_col) if len(g) > 0}
    labels = list(grouped.keys())

    if len(labels) != 2:
        hint = " Did you mean anova?" if len(labels) > 2 else ""
        raise ValueError(
            f"t_test needs exactly 2 groups in '{group_col}', found {len(labels)} "
            f"({', '.join(str(x) for x in labels)}).{hint}"
        )

    a, b = grouped[labels[0]], grouped[labels[1]]
    res = scipy_stats.ttest_ind(a, b, equal_var=False)  # Welch's t-test: doesn't assume equal variances
    return HypothesisTestResult(
        statistic=float(res.statistic),
        p_value=float(res.pvalue),
        degrees_of_freedom=float(res.df),
        groups=[
            {"group": str(labels[0]), "count": len(a), "mean": float(np.mean(a))},
            {"group": str(labels[1]), "count": len(b), "mean": float(np.mean(b))},
        ],
    )


def run_anova(df: pd.DataFrame, value_col: str, group_col: str) -> HypothesisTestResult:
    if not pd.api.types.is_numeric_dtype(df[value_col]):
        raise ValueError(f"anova needs a numeric value column; '{value_col}' has dtype {df[value_col].dtype}.")

    sub = df[[value_col, group_col]].dropna()
    grouped = {name: g[value_col].to_numpy() for name, g in sub.groupby(group_col) if len(g) > 0}
    labels = list(grouped.keys())

    if len(labels) < 3:
        hint = " Did you mean t_test?" if len(labels) == 2 else ""
        raise ValueError(
            f"anova needs 3+ groups in '{group_col}', found {len(labels)} "
            f"({', '.join(str(x) for x in labels)}).{hint}"
        )

    samples = [grouped[label] for label in labels]
    res = scipy_stats.f_oneway(*samples)
    total_n = sum(len(s) for s in samples)
    df_between = len(labels) - 1
    df_within = total_n - len(labels)
    return HypothesisTestResult(
        statistic=float(res.statistic),
        p_value=float(res.pvalue),
        df_between=df_between,
        df_within=df_within,
        groups=[{"group": str(label), "count": len(s), "mean": float(np.mean(s))} for label, s in zip(labels, samples)],
    )


def run_chi_square(df: pd.DataFrame, col_a: str, col_b: str) -> tuple[HypothesisTestResult, bool]:
    sub = df[[col_a, col_b]].dropna()
    table = pd.crosstab(sub[col_a], sub[col_b])

    if table.shape[0] < 2 or table.shape[1] < 2:
        raise ValueError(
            f"chi_square needs at least 2 categories in each column; '{col_a}' has {table.shape[0]}, "
            f"'{col_b}' has {table.shape[1]}."
        )

    chi2, p_value, dof, expected = scipy_stats.chi2_contingency(table)
    contingency_table = {str(a): {str(b): int(table.loc[a, b]) for b in table.columns} for a in table.index}
    result = HypothesisTestResult(
        statistic=float(chi2),
        p_value=float(p_value),
        degrees_of_freedom=float(dof),
        contingency_table=contingency_table,
    )
    low_expected_counts = bool((expected < 5).any())
    return result, low_expected_counts


@dataclass
class HypothesisTestOutcome:
    statistic: float
    p_value: float
    degrees_of_freedom: float | None
    df_between: int | None
    df_within: int | None
    groups: list[dict]
    contingency_table: dict[str, dict[str, int]] | None
    significant: bool
    conclusion: str
    summary: str


def run_hypothesis_test(df: pd.DataFrame, test_type: str, columns: list[str], alpha: float) -> HypothesisTestOutcome:
    col_a, col_b = columns

    if test_type == "t_test":
        result = run_t_test(df, col_a, col_b)
        g1, g2 = result.groups
        detail = (
            f"Mean {col_a} for '{g1['group']}' = {g1['mean']:.4g} (n={g1['count']}) vs. "
            f"'{g2['group']}' = {g2['mean']:.4g} (n={g2['count']})."
        )
    elif test_type == "anova":
        result = run_anova(df, col_a, col_b)
        detail = "Group means: " + "; ".join(f"'{g['group']}' = {g['mean']:.4g} (n={g['count']})" for g in result.groups)
    elif test_type == "chi_square":
        result, low_expected = run_chi_square(df, col_a, col_b)
        low_expected_note = (
            " Note: some expected cell counts are below 5, so this approximation may be unreliable." if low_expected else ""
        )
        detail = f"Tested independence between '{col_a}' and '{col_b}'.{low_expected_note}"
    else:
        raise ValueError(f"Unknown test_type '{test_type}'. Expected one of: t_test, anova, chi_square.")

    significant = result.p_value < alpha
    conclusion = (
        f"{detail} "
        f"{'Statistically significant' if significant else 'Not statistically significant'} at "
        f"α={alpha} (p={result.p_value:.4g})."
    )
    summary = (
        f"Ran {test_type} on columns {columns}.\n"
        f"statistic={result.statistic:.4g}, p={result.p_value:.4g}.\n{conclusion}"
    )

    return HypothesisTestOutcome(
        statistic=result.statistic,
        p_value=result.p_value,
        degrees_of_freedom=result.degrees_of_freedom,
        df_between=result.df_between,
        df_within=result.df_within,
        groups=result.groups,
        contingency_table=result.contingency_table,
        significant=significant,
        conclusion=conclusion,
        summary=summary,
    )
