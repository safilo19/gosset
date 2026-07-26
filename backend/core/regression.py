"""run_regression logic (linear/logistic + VIF). Plain Python — no MCP or web-framework code."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor


@dataclass
class RegressionResult:
    n_obs: int
    r_squared: float
    r_squared_label: str
    intercept: float
    params: pd.Series
    p_values: pd.Series
    std_errors: pd.Series
    vif: dict[str, float]
    target_encoding: dict | None = None


def fit_regression(df: pd.DataFrame, target: str, features: list[str], model_type: str) -> RegressionResult:
    non_numeric_features = [f for f in features if not pd.api.types.is_numeric_dtype(df[f])]
    if non_numeric_features:
        raise ValueError(
            f"Feature(s) {', '.join(non_numeric_features)} are not numeric (run_regression requires numeric "
            f"features). Encode categorical columns to numeric first, e.g. with one-hot/label encoding."
        )

    data = df[[target] + features].dropna()
    min_rows = len(features) + 2
    if len(data) < min_rows:
        raise ValueError(
            f"Not enough complete rows to fit a regression: {len(data)} row(s) with no missing values across "
            f"{target} and {features}, but at least {min_rows} are needed for {len(features)} feature(s)."
        )

    target_encoding = None
    if model_type == "logistic":
        y_raw = data[target]
        uniques = sorted(y_raw.unique().tolist(), key=str)
        if len(uniques) != 2:
            raise ValueError(
                f"logistic regression needs a binary target; '{target}' has {len(uniques)} distinct value(s): "
                f"{uniques}. Did you mean model_type='linear'?"
            )
        if set(uniques) == {0, 1}:
            y = y_raw.astype(int)
        else:
            target_encoding = {str(uniques[0]): 0, str(uniques[1]): 1}
            y = y_raw.map({uniques[0]: 0, uniques[1]: 1}).astype(int)
    else:
        if not pd.api.types.is_numeric_dtype(data[target]):
            raise ValueError(f"linear regression needs a numeric target; '{target}' has dtype {data[target].dtype}.")
        y = data[target]

    X = sm.add_constant(data[features])

    if model_type == "linear":
        fitted = sm.OLS(y, X).fit()
        r_squared = float(fitted.rsquared)
        r_squared_label = "R²"
    else:
        fitted = sm.Logit(y, X).fit(disp=0)
        r_squared = float(fitted.prsquared)
        r_squared_label = "Pseudo R² (McFadden)"

    vif: dict[str, float] = {}
    if len(features) >= 2:
        for i, feat in enumerate(features, start=1):  # index 0 is the constant column
            raw_vif = float(variance_inflation_factor(X.values, i))
            # Near-perfect collinearity can drive VIF to inf/nan; JSON has no such literal, so clamp it.
            vif[feat] = 9999.0 if math.isinf(raw_vif) or math.isnan(raw_vif) else raw_vif

    return RegressionResult(
        n_obs=len(data),
        r_squared=r_squared,
        r_squared_label=r_squared_label,
        intercept=float(fitted.params["const"]),
        params=fitted.params.drop("const"),
        p_values=fitted.pvalues.drop("const"),
        std_errors=fitted.bse.drop("const"),
        vif=vif,
        target_encoding=target_encoding,
    )


@dataclass
class RegressionCoefficient:
    feature: str
    coefficient: float
    std_err: float
    p_value: float
    significant: bool
    vif: float | None
    multicollinearity_flag: str | None


@dataclass
class RegressionOutcome:
    n_obs: int
    r_squared: float
    r_squared_label: str
    intercept: float
    target_encoding: dict | None
    coefficients: list[RegressionCoefficient]
    multicollinearity_warnings: list[str] = field(default_factory=list)
    summary: str = ""
    content_lines: list[str] = field(default_factory=list)


def run_regression(df: pd.DataFrame, target: str, features: list[str], model_type: str) -> RegressionOutcome:
    result = fit_regression(df, target, features, model_type)

    coefficients = []
    warnings: list[str] = []
    for feat in features:
        vif = result.vif.get(feat)
        flag = None
        if vif is not None:
            if vif > 10:
                flag = "high concern"
            elif vif > 5:
                flag = "moderate concern"
        if flag:
            warnings.append(
                f"'{feat}' has VIF={vif:.1f} ({flag}) — it's highly correlated with the other features, "
                f"so its coefficient estimate may be unstable."
            )
        coefficients.append(
            RegressionCoefficient(
                feature=feat,
                coefficient=float(result.params[feat]),
                std_err=float(result.std_errors[feat]),
                p_value=float(result.p_values[feat]),
                significant=bool(result.p_values[feat] < 0.05),
                vif=vif,
                multicollinearity_flag=flag,
            )
        )

    significant_feats = [c for c in coefficients if c.significant]
    insignificant_feats = [c for c in coefficients if not c.significant]

    lines = [
        f"{model_type.title()} regression of '{target}' on {features} (n={result.n_obs}).",
        f"{result.r_squared_label} = {result.r_squared:.3g}.",
    ]
    if result.target_encoding:
        lines.append(f"Target encoded as: {result.target_encoding}.")
    if significant_feats:
        lines.append(
            "Significant predictors (p<0.05): "
            + "; ".join(f"{c.feature} (coef={c.coefficient:.3g}, p={c.p_value:.3g})" for c in significant_feats)
        )
    if insignificant_feats:
        lines.append("Not significant: " + ", ".join(f"{c.feature} (p={c.p_value:.3g})" for c in insignificant_feats))
    if warnings:
        lines.extend(warnings)
    elif len(features) >= 2:
        lines.append("No multicollinearity concerns detected (all VIF ≤ 5).")

    return RegressionOutcome(
        n_obs=result.n_obs,
        r_squared=result.r_squared,
        r_squared_label=result.r_squared_label,
        intercept=result.intercept,
        target_encoding=result.target_encoding,
        coefficients=coefficients,
        multicollinearity_warnings=warnings,
        summary=" ".join(lines),
        content_lines=lines,
    )
