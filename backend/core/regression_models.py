"""Stat > Regression — the 13 procedures Minitab groups under that menu, plus the Predict panel.

Same contract as basic_stats.py: one `compute(df, procedure, columns, options)` dispatching on
`procedure`, every result shaped as tables / highlights / graphs / narrative so the frontend only
lays it out.

Predictors reach patsy under generated safe identifiers (`x0`, `x1`, …) rather than their real
names: worksheet columns are routinely called `yield (kg)` or `C1`, which a formula cannot quote
reliably. `_pretty_term` maps the fitted labels back for display.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import ast
import math
import re
import warnings
from itertools import combinations
from typing import Any, Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import odr, optimize
from scipy import stats as st
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold
from statsmodels.miscmodels.ordinal_model import OrderedModel
from statsmodels.stats.anova import anova_lm
from statsmodels.stats.outliers_influence import OLSInfluence, variance_inflation_factor

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
    numeric,
    option,
    p_text,
    require_columns,
)

PROCEDURES = (
    "fitted_line",
    "fit_model",
    "predict",
    "best_subsets",
    "stepwise",
    "nonlinear",
    "orthogonal",
    "pls",
    "stability",
    "binary_fitted_line",
    "binary_logistic",
    "ordinal_logistic",
    "nominal_logistic",
    "poisson_regression",
)

# Best Subsets enumerates 2^k - 1 models; past this the wait stops being interactive.
MAX_SUBSET_PREDICTORS = 12
SUBSET_WARN_PREDICTORS = 10


# ---------------------------------------------------------------------------
# model frames: real column names in, patsy-safe identifiers out
# ---------------------------------------------------------------------------


class _Spec:
    """A fitted linear model plus everything needed to describe it in the user's own column names."""

    def __init__(self, frame: pd.DataFrame, response: str, continuous: list[str], categorical: list[str], interactions: bool):
        self.frame = frame
        self.response = response
        self.continuous = continuous
        self.categorical = categorical
        self.interactions = interactions
        self.safe: dict[str, str] = {}
        self.real: dict[str, str] = {}


def _model_frame(
    df: pd.DataFrame,
    response: str,
    continuous: list[str],
    categorical: list[str],
    *,
    what: str,
    numeric_response: bool = True,
    interactions: bool = False,
    extra: list[str] | None = None,
) -> _Spec:
    """Complete-case frame under safe identifiers. Rows with a missing value in any model column are
    dropped, the way every regression procedure has to."""
    if not response:
        raise ProcedureError(f"{what} needs a response column.")
    predictors = list(dict.fromkeys([*continuous, *categorical]))
    if not predictors:
        raise ProcedureError(f"{what} needs at least one predictor.")
    require_columns(df, [response, *predictors, *(extra or [])])
    overlap = [p for p in predictors if p == response]
    if overlap:
        raise ProcedureError(f"'{response}' cannot be both the response and a predictor.")

    columns: dict[str, pd.Series] = {}
    spec = _Spec(pd.DataFrame(), response, continuous, categorical, interactions)

    def register(name: str, prefix: str, index: int, as_numeric: bool) -> str:
        safe = f"{prefix}{index}"
        spec.safe[name] = safe
        spec.real[safe] = name
        columns[safe] = pd.to_numeric(df[name], errors="coerce") if as_numeric else df[name].astype("object")
        return safe

    register(response, "y", 0, numeric_response)
    for i, name in enumerate(continuous):
        series = pd.to_numeric(df[name], errors="coerce")
        if series.notna().sum() == 0:
            raise ProcedureError(f"Continuous predictor '{name}' has no numeric values.")
        register(name, "x", i, True)
    for i, name in enumerate(categorical):
        register(name, "f", i, False)
    for i, name in enumerate(extra or []):
        register(name, "e", i, True)

    frame = pd.DataFrame(columns)
    # blank strings in a categorical column are missing values, not a level
    for name in categorical:
        safe = spec.safe[name]
        frame[safe] = frame[safe].where(frame[safe].notna() & (frame[safe].astype(str).str.strip() != ""), np.nan)
    before = len(frame)
    frame = frame.dropna()
    if frame.empty:
        raise ProcedureError(f"{what} found no rows where every model column has a value.")

    minimum = len(predictors) + 2
    if len(frame) < minimum:
        raise ProcedureError(
            f"{what} needs at least {minimum} complete rows for {len(predictors)} predictor(s); "
            f"only {len(frame)} of {before} rows have a value in every model column."
        )
    for name in categorical:
        levels = frame[spec.safe[name]].astype(str).nunique()
        if levels < 2:
            raise ProcedureError(f"Categorical predictor '{name}' has only {levels} level in the usable rows — it cannot be fitted.")
        if levels > 30:
            raise ProcedureError(f"Categorical predictor '{name}' has {levels} levels; that is too many to dummy-code sensibly.")

    spec.frame = frame
    spec.rows_used = len(frame)
    spec.rows_dropped = before - len(frame)
    spec.row_labels = [int(i) + 1 for i in frame.index]  # worksheet rows are 1-based
    return spec


def _terms(spec: _Spec, continuous: list[str] | None = None, categorical: list[str] | None = None) -> list[str]:
    cont = spec.continuous if continuous is None else continuous
    cat = spec.categorical if categorical is None else categorical
    main = [spec.safe[c] for c in cont] + [f"C({spec.safe[c]})" for c in cat]
    if not spec.interactions or len(main) < 2:
        return main
    return main + [f"{a}:{b}" for a, b in combinations(main, 2)]


def _formula(spec: _Spec, continuous: list[str] | None = None, categorical: list[str] | None = None) -> str:
    terms = _terms(spec, continuous, categorical)
    if not terms:
        raise ProcedureError("The model has no terms left to fit.")
    return f"{spec.safe[spec.response]} ~ " + " + ".join(terms)


_TERM_TOKEN = re.compile(r"\b([xyfe]\d+)\b")


def _pretty_term(label: str, spec: _Spec) -> str:
    """`C(f0)[T.Treated]:x1` -> `treatment=Treated * temperature_c`."""
    out = label
    out = re.sub(r"C\((([xyfe]\d+))\)\[T\.([^\]]+)\]", lambda m: f"{spec.real.get(m.group(1), m.group(1))}={m.group(3)}", out)
    out = re.sub(r"C\((([xyfe]\d+))\)", lambda m: spec.real.get(m.group(1), m.group(1)), out)
    out = _TERM_TOKEN.sub(lambda m: spec.real.get(m.group(1), m.group(1)), out)
    return out.replace(":", " * ")


def _fit_ols(spec: _Spec, continuous: list[str] | None = None, categorical: list[str] | None = None):
    formula = _formula(spec, continuous, categorical)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = smf.ols(formula, data=spec.frame).fit()
    except Exception as err:  # noqa: BLE001 - patsy/linalg failures become a user-facing message
        raise ProcedureError(f"The model could not be fitted: {err}") from err
    if not np.isfinite(model.mse_resid) or model.df_resid <= 0:
        raise ProcedureError(
            "The model has no degrees of freedom left for error — there are as many terms as observations. "
            "Use fewer predictors, drop the interactions, or add rows."
        )
    return model


# ---------------------------------------------------------------------------
# the standard linear-model output blocks
# ---------------------------------------------------------------------------


def _r_squared_predicted(model) -> float | None:
    """1 - PRESS/SST, the leave-one-out R² Minitab prints as R-sq(pred)."""
    try:
        influence = OLSInfluence(model)
        leverage = np.asarray(influence.hat_matrix_diag, dtype=float)
        resid = np.asarray(model.resid, dtype=float)
        keep = leverage < 1 - 1e-10
        if not keep.any():
            return None
        press = float(np.sum((resid[keep] / (1 - leverage[keep])) ** 2))
        centered_tss = float(model.centered_tss)
        if centered_tss <= 0:
            return None
        return 1 - press / centered_tss
    except Exception:  # noqa: BLE001 - a nice-to-have statistic must not fail a model
        return None


def _model_summary_rows(model) -> list[dict[str, Any]]:
    return [
        {
            "S": math.sqrt(float(model.mse_resid)),
            "R-sq": float(model.rsquared),
            "R-sq(adj)": float(model.rsquared_adj),
            "R-sq(pred)": _r_squared_predicted(model),
        }
    ]


def _anova_rows(model, spec: _Spec) -> list[dict[str, Any]]:
    """Minitab's ANOVA block: a Regression row, one row per term (adjusted SS), Error and Total."""
    rows: list[dict[str, Any]] = [
        {
            "Source": "Regression",
            "DF": int(model.df_model),
            "Adj SS": float(model.ess),
            "Adj MS": float(model.ess / model.df_model) if model.df_model else None,
            "F-Value": float(model.fvalue) if np.isfinite(model.fvalue) else None,
            "P-Value": float(model.f_pvalue) if np.isfinite(model.f_pvalue) else None,
        }
    ]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            table = anova_lm(model, typ=2)
        for label, row in table.iterrows():
            if str(label) == "Residual":
                continue
            df_term = float(row["df"])
            rows.append(
                {
                    "Source": f"  {_pretty_term(str(label), spec)}",
                    "DF": int(df_term),
                    "Adj SS": float(row["sum_sq"]),
                    "Adj MS": float(row["sum_sq"] / df_term) if df_term else None,
                    "F-Value": None if pd.isna(row.get("F")) else float(row["F"]),
                    "P-Value": None if pd.isna(row.get("PR(>F)")) else float(row["PR(>F)"]),
                }
            )
    except Exception:  # noqa: BLE001 - a singular design can defeat the per-term decomposition
        rows.append({"Source": "  (per-term breakdown unavailable for this design)", "DF": None, "Adj SS": None, "Adj MS": None, "F-Value": None, "P-Value": None})

    rows.append({"Source": "Error", "DF": int(model.df_resid), "Adj SS": float(model.ssr), "Adj MS": float(model.mse_resid), "F-Value": None, "P-Value": None})
    rows.append({"Source": "Total", "DF": int(model.df_model + model.df_resid), "Adj SS": float(model.centered_tss), "Adj MS": None, "F-Value": None, "P-Value": None})
    return rows


def _vif_by_term(model) -> dict[str, float]:
    exog = np.asarray(model.model.exog, dtype=float)
    names = list(model.model.exog_names)
    out: dict[str, float] = {}
    if exog.shape[1] < 3:  # intercept + one term: nothing to be collinear with
        return out
    for i, name in enumerate(names):
        if name == "Intercept":
            continue
        try:
            value = float(variance_inflation_factor(exog, i))
        except Exception:  # noqa: BLE001
            continue
        out[name] = 9999.0 if not np.isfinite(value) else value
    return out


def _coefficient_rows(model, spec: _Spec, conf: float) -> list[dict[str, Any]]:
    vif = _vif_by_term(model)
    low, high = model.conf_int(alpha=1 - conf).T.values
    rows = []
    for i, name in enumerate(model.model.exog_names):
        label = "Constant" if name == "Intercept" else _pretty_term(name, spec)
        row: dict[str, Any] = {
            "Term": label,
            "Coef": float(model.params.iloc[i]),
            "SE Coef": float(model.bse.iloc[i]),
            f"{conf * 100:g}% CI": ci_text(float(low[i]), float(high[i]), 5),
            "T-Value": float(model.tvalues.iloc[i]),
            "P-Value": float(model.pvalues.iloc[i]),
        }
        if name in vif:
            row["VIF"] = vif[name]
        rows.append(row)
    return rows


def _equation(model, spec: _Spec, decimals: int = 4) -> str:
    parts = []
    for i, name in enumerate(model.model.exog_names):
        coef = float(model.params.iloc[i])
        if name == "Intercept":
            parts.append(f"{coef:.{decimals}g}")
            continue
        sign = " - " if coef < 0 else " + "
        parts.append(f"{sign}{abs(coef):.{decimals}g} {_pretty_term(name, spec)}")
    return f"{spec.response} = " + "".join(parts)


def _unusual_rows(model, spec: _Spec) -> tuple[list[dict[str, Any]], int, int]:
    """Minitab's unusual-observations table: R for a large standardised residual, X for high
    leverage (> 3p/n). Row numbers are worksheet rows, not positions in the fitted frame."""
    influence = OLSInfluence(model)
    std_resid = np.asarray(influence.resid_studentized_internal, dtype=float)
    leverage = np.asarray(influence.hat_matrix_diag, dtype=float)
    fitted = np.asarray(model.fittedvalues, dtype=float)
    observed = np.asarray(model.model.endog, dtype=float)
    n = len(std_resid)
    p = int(model.df_model) + 1
    leverage_cut = min(0.99, 3.0 * p / n) if n else 1.0

    rows = []
    large = 0
    high = 0
    for i in range(n):
        is_large = abs(std_resid[i]) > 2
        is_high = leverage[i] > leverage_cut
        if not (is_large or is_high):
            continue
        large += int(is_large)
        high += int(is_high)
        rows.append(
            {
                "Row": spec.row_labels[i],
                spec.response: float(observed[i]),
                "Fit": float(fitted[i]),
                "Residual": float(observed[i] - fitted[i]),
                "Std Resid": float(std_resid[i]),
                "Leverage": float(leverage[i]),
                "Flag": ("R" if is_large else "") + ("X" if is_high else ""),
            }
        )
    rows.sort(key=lambda r: abs(r["Std Resid"]), reverse=True)
    return rows[:40], large, high


def _histogram_of(values: np.ndarray, label: str) -> dict:
    frame = pd.DataFrame({label: values})
    return graphs_core.compute(frame, "histogram", [label], {})


def _probability_points(values: np.ndarray) -> dict:
    """Normal probability plot data (Benard plotting positions), for a residual panel."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    sd = float(np.std(x, ddof=1)) if n > 1 else 0.0
    mean = float(np.mean(x))
    i = np.arange(1, n + 1)
    z = st.norm.ppf((i - 0.3) / (n + 0.4))
    line_lo, line_hi = float(z[0]), float(z[-1])
    return {
        "points": [{"x": float(xi), "y": float(zi)} for xi, zi in zip(x, z)],
        "line": [{"x": mean + sd * line_lo, "y": line_lo}, {"x": mean + sd * line_hi, "y": line_hi}],
        "x_label": "residual",
        "y_label": "normal score (z)",
        "n": n,
        "r_squared": float(np.corrcoef(x, z)[0, 1] ** 2) if n > 2 and sd > 0 else None,
    }


def _four_in_one(model, spec: _Spec) -> dict:
    """The four residual plots Minitab draws in one window."""
    resid = np.asarray(model.resid, dtype=float)
    fitted = np.asarray(model.fittedvalues, dtype=float)
    return {
        "renderer": "fourInOne",
        "title": "Residual plots (four in one)",
        "data": {
            "normal": _probability_points(resid),
            "versus_fits": {
                "points": [{"x": float(f), "y": float(r)} for f, r in zip(fitted, resid)],
                "x_label": f"fitted {spec.response}",
                "y_label": "residual",
            },
            "histogram": _histogram_of(resid, "residual"),
            "versus_order": {
                "points": [{"x": int(row), "y": float(r)} for row, r in zip(spec.row_labels, resid)],
                "x_label": "observation order (worksheet row)",
                "y_label": "residual",
            },
        },
    }


def _residual_graphs(spec: _Spec, resid: np.ndarray, fitted: np.ndarray, *, label: str = "residual") -> list[dict]:
    """The lighter residual pair used by the models that have no four-in-one (nonlinear, GLM)."""
    return [
        {
            "renderer": "residualPair",
            "title": "Residual plots",
            "data": {
                "versus_fits": {
                    "points": [{"x": float(f), "y": float(r)} for f, r in zip(fitted, resid)],
                    "x_label": "fitted value",
                    "y_label": label,
                },
                "normal": _probability_points(resid),
            },
        }
    ]


# ---------------------------------------------------------------------------
# 1. Fitted Line Plot
# ---------------------------------------------------------------------------

_ORDER_NAME = {1: "Linear", 2: "Quadratic", 3: "Cubic"}


def _fitted_line(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Fitted Line Plot needs a response column and one predictor column.")
    response, predictor = columns[0], columns[1]
    order = int_option(options, "order", 1, what="Model order") or 1
    if order not in (1, 2, 3):
        raise ProcedureError("Model order must be 1 (linear), 2 (quadratic) or 3 (cubic).")
    conf = confidence(options)

    require_columns(df, [response, predictor])
    frame = pd.DataFrame(
        {"y": pd.to_numeric(df[response], errors="coerce"), "x": pd.to_numeric(df[predictor], errors="coerce")}
    ).dropna()
    if len(frame) < order + 2:
        raise ProcedureError(f"A {_ORDER_NAME[order].lower()} fit needs at least {order + 2} rows where both columns are numeric; found {len(frame)}.")
    if frame["x"].nunique() < order + 1:
        raise ProcedureError(
            f"'{predictor}' has only {frame['x'].nunique()} distinct value(s) — a {_ORDER_NAME[order].lower()} fit needs at least {order + 1}."
        )

    exog = pd.DataFrame({"x": frame["x"]})
    for power in range(2, order + 1):
        exog[f"x{power}"] = frame["x"] ** power
    model = sm.OLS(frame["y"], sm.add_constant(exog)).fit()

    grid = np.linspace(float(frame["x"].min()), float(frame["x"].max()), 120)
    grid_exog = pd.DataFrame({"x": grid})
    for power in range(2, order + 1):
        grid_exog[f"x{power}"] = grid**power
    prediction = model.get_prediction(sm.add_constant(grid_exog, has_constant="add")).summary_frame(alpha=1 - conf)

    labels = {"const": "constant", "x": predictor, "x2": f"{predictor}²", "x3": f"{predictor}³"}
    terms = []
    for name in model.model.exog_names:
        coef = float(model.params[name])
        if name == "const":
            terms.append(f"{coef:.5g}")
        else:
            terms.append(f"{' - ' if coef < 0 else ' + '}{abs(coef):.5g} {labels.get(name, name)}")
    equation = f"{response} = " + "".join(terms)

    s_value = math.sqrt(float(model.mse_resid))
    summary_rows = [
        {"S": s_value, "R-sq": float(model.rsquared), "R-sq(adj)": float(model.rsquared_adj), "R-sq(pred)": _r_squared_predicted(model)}
    ]
    coef_rows = []
    low, high = model.conf_int(alpha=1 - conf).T.values
    for i, name in enumerate(model.model.exog_names):
        coef_rows.append(
            {
                "Term": "Constant" if name == "const" else labels.get(name, name),
                "Coef": float(model.params.iloc[i]),
                "SE Coef": float(model.bse.iloc[i]),
                f"{conf * 100:g}% CI": ci_text(float(low[i]), float(high[i]), 5),
                "T-Value": float(model.tvalues.iloc[i]),
                "P-Value": float(model.pvalues.iloc[i]),
            }
        )

    curve = [
        {
            "x": float(x),
            "fit": float(prediction["mean"].iloc[i]),
            "ci_low": float(prediction["mean_ci_lower"].iloc[i]),
            "ci_high": float(prediction["mean_ci_upper"].iloc[i]),
            "pi_low": float(prediction["obs_ci_lower"].iloc[i]),
            "pi_high": float(prediction["obs_ci_upper"].iloc[i]),
        }
        for i, x in enumerate(grid)
    ]

    conclusion = (
        f"{_ORDER_NAME[order]} fit of {response} on {predictor} (n = {len(frame)}): R² = {model.rsquared * 100:.2f}%, "
        f"R²(adj) = {model.rsquared_adj * 100:.2f}%, S = {g(s_value, 4)}. "
        f"{'The highest-order term is significant' if model.pvalues.iloc[-1] < 0.05 else 'The highest-order term is not significant'} "
        f"(p = {p_text(float(model.pvalues.iloc[-1]))})."
    )
    return {
        "procedure": "fitted_line",
        "title": f"Fitted Line Plot: {response} vs {predictor}",
        "method": f"{_ORDER_NAME[order]} regression, {conf * 100:g}% confidence and prediction bands",
        "equation": equation,
        "order": order,
        "confidence_level": conf,
        "n": len(frame),
        "s": s_value,
        "r_squared": float(model.rsquared),
        "r_squared_adj": float(model.rsquared_adj),
        "p_value": float(model.f_pvalue),
        "tables": [
            {"title": "Model Summary", "rows": summary_rows},
            {"title": "Coefficients", "rows": coef_rows},
            {"title": "Analysis of Variance", "rows": [
                {"Source": "Regression", "DF": int(model.df_model), "SS": float(model.ess), "MS": float(model.ess / model.df_model), "F-Value": float(model.fvalue), "P-Value": float(model.f_pvalue)},
                {"Source": "Error", "DF": int(model.df_resid), "SS": float(model.ssr), "MS": float(model.mse_resid), "F-Value": None, "P-Value": None},
                {"Source": "Total", "DF": int(model.df_model + model.df_resid), "SS": float(model.centered_tss), "MS": None, "F-Value": None, "P-Value": None},
            ]},
        ],
        "highlights": [
            {"label": "R-sq", "value": float(model.rsquared) * 100, "suffix": "%"},
            {"label": "R-sq(adj)", "value": float(model.rsquared_adj) * 100, "suffix": "%"},
            {"label": "S", "value": s_value},
        ],
        "graphs": [
            {
                "renderer": "fittedLine",
                "title": f"Fitted line plot of {response} vs {predictor}",
                "data": {
                    "points": [{"x": float(r.x), "y": float(r.y)} for r in frame.itertuples()],
                    "curve": curve,
                    "x_label": predictor,
                    "y_label": response,
                    "equation": equation,
                    "annotations": [f"S = {g(s_value, 4)}", f"R-sq = {model.rsquared * 100:.1f}%", f"R-sq(adj) = {model.rsquared_adj * 100:.1f}%"],
                    "confidence": conf,
                },
            }
        ],
        "conclusion": conclusion,
        "summary": f"Fitted Line Plot ({_ORDER_NAME[order]}) — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 2. Fit Regression Model (+ the Predict panel)
# ---------------------------------------------------------------------------


def _model_options(columns: list[str], options: dict) -> tuple[str, list[str], list[str], bool]:
    """(response, continuous, categorical, interactions) from the ordered column list. The form sends
    the response first, then continuous predictors, then categorical ones, with the split in
    `n_continuous` so a name is never guessed at."""
    if not columns:
        raise ProcedureError("Choose a response column.")
    response = columns[0]
    rest = columns[1:]
    n_continuous = int_option(options, "n_continuous", len(rest), what="Continuous predictor count")
    n_continuous = max(0, min(int(n_continuous or 0), len(rest)))
    continuous = rest[:n_continuous]
    categorical = rest[n_continuous:]
    interactions = bool(option(options, "interactions", False))
    return response, continuous, categorical, interactions


def _fit_model(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, continuous, categorical, interactions = _model_options(columns, options)
    conf = confidence(options)
    spec = _model_frame(df, response, continuous, categorical, what="Fit Regression Model", interactions=interactions)
    model = _fit_ols(spec)

    coef_rows = _coefficient_rows(model, spec, conf)
    unusual, n_large, n_high = _unusual_rows(model, spec)
    summary_rows = _model_summary_rows(model)
    equation = _equation(model, spec)

    tables = [
        {"title": "Analysis of Variance", "rows": _anova_rows(model, spec)},
        {"title": "Model Summary", "rows": summary_rows},
        {"title": "Coefficients", "rows": coef_rows},
        {"title": "Regression Equation", "rows": [{"Equation": equation}]},
    ]
    if unusual:
        tables.append({"title": f"Fits and Diagnostics for Unusual Observations ({len(unusual)} shown)", "rows": unusual})

    graphs: list[dict] = []
    if option(options, "graph_residuals", True):
        graphs.append(_four_in_one(model, spec))

    high_vif = [r for r in coef_rows if isinstance(r.get("VIF"), (int, float)) and r["VIF"] > 10]
    notes = []
    if high_vif:
        notes.append("VIF above 10 for " + ", ".join(r["Term"] for r in high_vif) + " — those coefficients are unstable because the predictors overlap.")
    if spec.rows_dropped:
        notes.append(f"{spec.rows_dropped} row(s) were dropped for missing values.")
    if n_large or n_high:
        notes.append(f"{n_large} observation(s) have a standardised residual beyond ±2 (R) and {n_high} have high leverage (X).")

    significant = [r for r in coef_rows if r["Term"] != "Constant" and r["P-Value"] < 1 - conf]
    conclusion = (
        f"{response} on {len(continuous)} continuous and {len(categorical)} categorical predictor(s), n = {spec.rows_used}. "
        f"R² = {model.rsquared * 100:.2f}%, R²(adj) = {model.rsquared_adj * 100:.2f}%, S = {g(math.sqrt(model.mse_resid), 4)}. "
        f"Overall F = {g(float(model.fvalue), 4)}, p = {p_text(float(model.f_pvalue))}. "
        + (f"Significant terms: {', '.join(r['Term'] for r in significant)}." if significant else "No individual term is significant at this level.")
    )
    return {
        "procedure": "fit_model",
        "title": f"Regression: {response} versus {', '.join(continuous + categorical)}",
        "method": "Ordinary least squares"
        + (" with all two-way interactions" if interactions else "")
        + (f"; categorical predictors dummy-coded ({', '.join(categorical)})" if categorical else ""),
        "response": response,
        "continuous_predictors": continuous,
        "categorical_predictors": categorical,
        "interactions": interactions,
        "confidence_level": conf,
        "n": spec.rows_used,
        "equation": equation,
        "s": math.sqrt(float(model.mse_resid)),
        "r_squared": float(model.rsquared),
        "r_squared_adj": float(model.rsquared_adj),
        "p_value": float(model.f_pvalue),
        "note": " ".join(notes) or None,
        # everything the Predict panel needs to re-fit exactly this model
        "predict_spec": {
            "response": response,
            "continuous": continuous,
            "categorical": categorical,
            "interactions": interactions,
            "confidence": conf,
            "levels": {c: sorted(spec.frame[spec.safe[c]].astype(str).unique().tolist()) for c in categorical},
            "means": {c: float(spec.frame[spec.safe[c]].mean()) for c in continuous},
        },
        "tables": tables,
        "highlights": [
            {"label": "R-sq", "value": float(model.rsquared) * 100, "suffix": "%"},
            {"label": "R-sq(adj)", "value": float(model.rsquared_adj) * 100, "suffix": "%"},
            {"label": "S", "value": math.sqrt(float(model.mse_resid))},
            {"label": "P-Value (model)", "value": float(model.f_pvalue), "tone": "positive" if model.f_pvalue < 0.05 else None},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Fit Regression Model — {conclusion}",
    }


def _predict(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    """The Predict panel: refits the stored model spec and predicts one row of predictor values.
    Refitting costs milliseconds and keeps the API stateless, which matters because a result window
    can outlive any server-side model cache."""
    spec_in = option(options, "spec", None)
    if not isinstance(spec_in, dict):
        raise ProcedureError("Predict needs the model it should predict from.")
    values = option(options, "values", None) or {}
    if not isinstance(values, dict):
        raise ProcedureError("Predict needs a value for each predictor.")

    response = str(spec_in.get("response") or "")
    continuous = [str(c) for c in spec_in.get("continuous") or []]
    categorical = [str(c) for c in spec_in.get("categorical") or []]
    interactions = bool(spec_in.get("interactions"))
    conf = confidence({"confidence": spec_in.get("confidence", 0.95)})

    spec = _model_frame(df, response, continuous, categorical, what="Predict", interactions=interactions)
    model = _fit_ols(spec)

    row: dict[str, Any] = {}
    display: dict[str, Any] = {}
    for name in continuous:
        raw = values.get(name)
        if raw in (None, ""):
            raise ProcedureError(f"Enter a value for '{name}'.")
        try:
            row[spec.safe[name]] = float(raw)
        except (TypeError, ValueError):
            raise ProcedureError(f"'{name}' needs a numeric value; got '{raw}'.") from None
        display[name] = row[spec.safe[name]]
    for name in categorical:
        raw = values.get(name)
        levels = spec.frame[spec.safe[name]].astype(str).unique().tolist()
        if raw in (None, ""):
            raise ProcedureError(f"Choose a level for '{name}'.")
        if str(raw) not in levels:
            raise ProcedureError(f"'{raw}' is not a level of '{name}'. Fitted levels: {', '.join(sorted(levels))}.")
        row[spec.safe[name]] = str(raw)
        display[name] = str(raw)

    try:
        prediction = model.get_prediction(pd.DataFrame([row])).summary_frame(alpha=1 - conf)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The prediction could not be computed: {err}") from err

    fit = float(prediction["mean"].iloc[0])
    se_fit = float(prediction["mean_se"].iloc[0])
    ci = (float(prediction["mean_ci_lower"].iloc[0]), float(prediction["mean_ci_upper"].iloc[0]))
    pi = (float(prediction["obs_ci_lower"].iloc[0]), float(prediction["obs_ci_upper"].iloc[0]))
    pct = f"{conf * 100:g}%"

    return {
        "procedure": "predict",
        "title": f"Prediction for {response}",
        "settings": display,
        "fit": fit,
        "se_fit": se_fit,
        "ci": list(ci),
        "pi": list(pi),
        "tables": [
            {"title": "Settings", "rows": [display]} if display else {"title": "Settings", "rows": []},
            {
                "title": "Prediction",
                "rows": [{"Fit": fit, "SE Fit": se_fit, f"{pct} CI": ci_text(*ci, 5), f"{pct} PI": ci_text(*pi, 5)}],
            },
        ],
        "conclusion": (
            f"Predicted {response} = {g(fit, 5)} (SE {g(se_fit, 4)}); {pct} CI {ci_text(*ci, 5)}, {pct} PI {ci_text(*pi, 5)}."
        ),
        "summary": f"Predicted {response} = {g(fit, 5)} for {', '.join(f'{k}={v}' for k, v in display.items())}.",
    }


# ---------------------------------------------------------------------------
# 3. Best Subsets
# ---------------------------------------------------------------------------


def _best_subsets(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Best Subsets needs a response column and at least one candidate predictor.")
    response, candidates = columns[0], columns[1:]
    if len(candidates) > MAX_SUBSET_PREDICTORS:
        raise ProcedureError(
            f"Best Subsets evaluates every combination, which is 2^k − 1 models. {len(candidates)} predictors would be "
            f"{2 ** len(candidates) - 1:,} fits — the limit is {MAX_SUBSET_PREDICTORS} predictors "
            f"({2 ** MAX_SUBSET_PREDICTORS - 1:,} fits). Narrow the candidate list first, or use Stepwise."
        )
    keep_best = int_option(options, "models_per_size", 2, what="Models per size") or 2
    keep_best = max(1, min(keep_best, 5))

    spec = _model_frame(df, response, candidates, [], what="Best Subsets")
    full = _fit_ols(spec)
    mse_full = float(full.mse_resid)
    n = spec.rows_used
    centered_tss = float(full.centered_tss)

    by_size: dict[int, list[dict[str, Any]]] = {}
    for size in range(1, len(candidates) + 1):
        scored = []
        for subset in combinations(candidates, size):
            try:
                model = _fit_ols(spec, continuous=list(subset))
            except ProcedureError:
                continue
            p = size + 1
            cp = float(model.ssr / mse_full - (n - 2 * p)) if mse_full > 0 else None
            scored.append(
                {
                    "Vars": size,
                    "R-Sq": float(model.rsquared) * 100,
                    "R-Sq(adj)": float(model.rsquared_adj) * 100,
                    "R-Sq(pred)": (_r_squared_predicted(model) or 0) * 100,
                    "Mallows Cp": cp,
                    "S": math.sqrt(float(model.ssr / model.df_resid)),
                    **{name: ("X" if name in subset else "") for name in candidates},
                    "_subset": subset,
                    "_ssr": float(model.ssr),
                }
            )
        scored.sort(key=lambda r: r["R-Sq"], reverse=True)
        by_size[size] = scored[:keep_best]

    rows = []
    for size in sorted(by_size):
        rows.extend(by_size[size])
    if not rows:
        raise ProcedureError("No subset of these predictors could be fitted.")

    # Minitab's guidance: the model whose Cp is closest to p while still small
    def cp_distance(row: dict) -> float:
        cp = row["Mallows Cp"]
        return abs(cp - (row["Vars"] + 1)) if cp is not None else float("inf")

    best_cp = min(rows, key=cp_distance)
    best_adj = max(rows, key=lambda r: r["R-Sq(adj)"])
    display_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]

    conclusion = (
        f"Evaluated {2 ** len(candidates) - 1} subset(s) of {len(candidates)} candidate predictor(s) for {response} "
        f"(n = {n}), keeping the best {keep_best} per size. "
        f"Highest R²(adj): {', '.join(best_adj['_subset'])} at {best_adj['R-Sq(adj)']:.2f}%. "
        f"Mallows' Cp closest to p: {', '.join(best_cp['_subset'])} (Cp = {g(best_cp['Mallows Cp'], 4)}, p = {best_cp['Vars'] + 1})."
    )
    note = None
    if len(candidates) >= SUBSET_WARN_PREDICTORS:
        note = f"{len(candidates)} predictors means {2 ** len(candidates) - 1:,} models were fitted; anything larger will be slow."
    return {
        "procedure": "best_subsets",
        "title": f"Best Subsets Regression: {response} versus {', '.join(candidates)}",
        "method": f"All {2 ** len(candidates) - 1} subsets evaluated; best {keep_best} per subset size shown. Cp compares each model with the full {len(candidates)}-predictor model.",
        "response": response,
        "candidates": candidates,
        "n": n,
        "note": note,
        "tables": [{"title": "Best subsets (X marks the predictors in each model)", "rows": display_rows}],
        "highlights": [
            {"label": "Subsets evaluated", "value": 2 ** len(candidates) - 1, "decimals": 0},
            {"label": "Best R-Sq(adj)", "value": best_adj["R-Sq(adj)"], "suffix": "%"},
            {"label": "Predictors in it", "value": best_adj["Vars"], "decimals": 0},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"Best Subsets — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 4. Stepwise
# ---------------------------------------------------------------------------


def _stepwise(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Stepwise needs a response column and at least one candidate predictor.")
    response, candidates = columns[0], columns[1:]
    method = str(option(options, "method", "stepwise"))
    if method not in ("stepwise", "forward", "backward"):
        raise ProcedureError("method must be 'stepwise', 'forward' or 'backward'.")
    alpha_enter = float_option(options, "alpha_enter", 0.15, what="Alpha to enter") or 0.15
    alpha_remove = float_option(options, "alpha_remove", 0.15, what="Alpha to remove") or 0.15
    for name, value in (("Alpha to enter", alpha_enter), ("Alpha to remove", alpha_remove)):
        if not 0 < value < 1:
            raise ProcedureError(f"{name} must be between 0 and 1; got {g(value)}.")
    conf = confidence(options)

    spec = _model_frame(df, response, candidates, [], what="Stepwise")

    def p_values(subset: list[str]) -> dict[str, float]:
        model = _fit_ols(spec, continuous=subset)
        out = {}
        for i, name in enumerate(model.model.exog_names):
            if name == "Intercept":
                continue
            out[spec.real.get(name, name)] = float(model.pvalues.iloc[i])
        return out

    selected: list[str] = list(candidates) if method == "backward" else []
    steps: list[dict[str, Any]] = []
    step = 0

    while True:
        step += 1
        if step > 4 * len(candidates) + 6:
            steps.append({"Step": step, "Action": "stopped", "Term": "", "P-Value": None, "Model size": len(selected), "R-Sq": None, "Note": "step limit reached"})
            break
        changed = False

        # removal pass (stepwise and backward)
        if selected and method in ("stepwise", "backward"):
            current = p_values(selected)
            worst = max(current, key=lambda term: current[term])
            if current[worst] > alpha_remove and (method == "backward" or len(selected) > 0):
                selected = [t for t in selected if t != worst]
                model_after = _fit_ols(spec, continuous=selected) if selected else None
                steps.append(
                    {
                        "Step": step,
                        "Action": "removed",
                        "Term": worst,
                        "P-Value": current[worst],
                        "Model size": len(selected),
                        "R-Sq": (float(model_after.rsquared) * 100 if model_after is not None else 0.0),
                        "Note": f"p > alpha-to-remove ({g(alpha_remove)})",
                    }
                )
                changed = True

        # entry pass (stepwise and forward)
        if not changed and method in ("stepwise", "forward"):
            remaining = [c for c in candidates if c not in selected]
            best_term = None
            best_p = None
            for candidate in remaining:
                trial = [*selected, candidate]
                try:
                    p = p_values(trial)[candidate]
                except ProcedureError:
                    continue
                if best_p is None or p < best_p:
                    best_term, best_p = candidate, p
            if best_term is not None and best_p is not None and best_p < alpha_enter:
                selected = [*selected, best_term]
                model_after = _fit_ols(spec, continuous=selected)
                steps.append(
                    {
                        "Step": step,
                        "Action": "entered",
                        "Term": best_term,
                        "P-Value": best_p,
                        "Model size": len(selected),
                        "R-Sq": float(model_after.rsquared) * 100,
                        "Note": f"p < alpha-to-enter ({g(alpha_enter)})",
                    }
                )
                changed = True

        if not changed:
            break

    if not steps:
        steps.append({"Step": 1, "Action": "no term qualified", "Term": "", "P-Value": None, "Model size": 0, "R-Sq": 0.0, "Note": f"no candidate reached alpha-to-enter ({g(alpha_enter)})"})

    if not selected:
        conclusion = (
            f"Stepwise ({method}) selected no predictors for {response}: no candidate met alpha-to-enter = {g(alpha_enter)}."
        )
        return {
            "procedure": "stepwise",
            "title": f"Stepwise Regression: {response} versus {', '.join(candidates)}",
            "method": f"{method} selection, alpha-to-enter {g(alpha_enter)}, alpha-to-remove {g(alpha_remove)}",
            "response": response,
            "selected": [],
            "n": spec.rows_used,
            "tables": [{"title": "Step-by-step path", "rows": steps}],
            "highlights": [{"label": "Terms selected", "value": 0, "decimals": 0}],
            "graphs": [],
            "conclusion": conclusion,
            "summary": f"Stepwise — {conclusion}",
        }

    final_spec = _model_frame(df, response, selected, [], what="Stepwise")
    final = _fit_ols(final_spec)
    equation = _equation(final, final_spec)
    tables = [
        {"title": "Step-by-step path", "rows": steps},
        {"title": "Analysis of Variance (final model)", "rows": _anova_rows(final, final_spec)},
        {"title": "Model Summary (final model)", "rows": _model_summary_rows(final)},
        {"title": "Coefficients (final model)", "rows": _coefficient_rows(final, final_spec, conf)},
        {"title": "Regression Equation", "rows": [{"Equation": equation}]},
    ]
    unusual, _large, _high = _unusual_rows(final, final_spec)
    if unusual:
        tables.append({"title": f"Fits and Diagnostics for Unusual Observations ({len(unusual)} shown)", "rows": unusual})

    graphs = [_four_in_one(final, final_spec)] if option(options, "graph_residuals", True) else []
    dropped = [c for c in candidates if c not in selected]
    conclusion = (
        f"Stepwise ({method}) kept {len(selected)} of {len(candidates)} candidate(s) for {response}: {', '.join(selected)}"
        + (f"; left out {', '.join(dropped)}. " if dropped else ". ")
        + f"Final model R² = {final.rsquared * 100:.2f}%, R²(adj) = {final.rsquared_adj * 100:.2f}%, S = {g(math.sqrt(final.mse_resid), 4)} over {len(steps)} step(s)."
    )
    return {
        "procedure": "stepwise",
        "title": f"Stepwise Regression: {response} versus {', '.join(candidates)}",
        "method": f"{method} selection, alpha-to-enter {g(alpha_enter)}, alpha-to-remove {g(alpha_remove)}",
        "response": response,
        "selected": selected,
        "n": final_spec.rows_used,
        "equation": equation,
        "r_squared": float(final.rsquared),
        "r_squared_adj": float(final.rsquared_adj),
        "s": math.sqrt(float(final.mse_resid)),
        "predict_spec": {
            "response": response,
            "continuous": selected,
            "categorical": [],
            "interactions": False,
            "confidence": conf,
            "levels": {},
            "means": {c: float(final_spec.frame[final_spec.safe[c]].mean()) for c in selected},
        },
        "tables": tables,
        "highlights": [
            {"label": "Terms selected", "value": len(selected), "decimals": 0},
            {"label": "R-sq", "value": float(final.rsquared) * 100, "suffix": "%"},
            {"label": "R-sq(adj)", "value": float(final.rsquared_adj) * 100, "suffix": "%"},
            {"label": "Steps", "value": len(steps), "decimals": 0},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Stepwise ({method}) — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 5. Nonlinear Regression
# ---------------------------------------------------------------------------

# Only these names may appear in an expectation function. No attribute access, no subscripting, no
# calls to anything else — see _compile_expectation.
_ALLOWED_FUNCTIONS = {
    "exp", "log", "log10", "log2", "log1p", "sqrt", "cbrt", "abs", "power",
    "sin", "cos", "tan", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "maximum", "minimum", "sign", "floor", "ceil",
}
_ALLOWED_CONSTANTS = {"pi", "e"}

EXPECTATION_CATALOG: dict[str, dict[str, Any]] = {
    "exponential_growth": {"label": "Exponential growth", "formula": "theta1 * exp(theta2 * x)", "parameters": ["theta1", "theta2"]},
    "exponential_decay": {"label": "Exponential decay", "formula": "theta1 * exp(-theta2 * x)", "parameters": ["theta1", "theta2"]},
    "power": {"label": "Power", "formula": "theta1 * power(x, theta2)", "parameters": ["theta1", "theta2"]},
    "logistic": {"label": "Logistic (sigmoid)", "formula": "theta1 / (1 + exp(-theta2 * (x - theta3)))", "parameters": ["theta1", "theta2", "theta3"]},
    "michaelis_menten": {"label": "Michaelis-Menten", "formula": "theta1 * x / (theta2 + x)", "parameters": ["theta1", "theta2"]},
    "gompertz": {"label": "Gompertz", "formula": "theta1 * exp(-theta2 * exp(-theta3 * x))", "parameters": ["theta1", "theta2", "theta3"]},
}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
)


def _expression_names(formula: str) -> tuple[ast.Expression, set[str]]:
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as err:
        raise ProcedureError(f"The expectation function could not be parsed: {err.msg}.") from None

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, _ALLOWED_NODES):
            continue
        if isinstance(node, ast.Name):
            names.add(node.id)
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
                allowed = ", ".join(sorted(_ALLOWED_FUNCTIONS))
                raise ProcedureError(f"Only these functions may be used in an expectation function: {allowed}.")
            if node.keywords:
                raise ProcedureError("Keyword arguments are not allowed in an expectation function.")
            continue
        raise ProcedureError(
            f"'{type(node).__name__}' is not allowed in an expectation function — use only the predictor, "
            f"parameter names, numbers, + - * / ** and the permitted functions."
        )
    return tree, names


def _compile_expectation(formula: str, predictor_symbol: str, parameters: list[str]) -> Callable:
    """Compile a validated expectation function. The AST walk above has already rejected everything
    except arithmetic, the predictor, parameter names and whitelisted numpy functions, so nothing
    here can reach the interpreter's builtins or any object's attributes."""
    tree, names = _expression_names(formula)
    allowed = {predictor_symbol, *parameters, *_ALLOWED_FUNCTIONS, *_ALLOWED_CONSTANTS}
    unknown = sorted(names - allowed)
    if unknown:
        raise ProcedureError(
            f"Unknown name(s) in the expectation function: {', '.join(unknown)}. "
            f"Use '{predictor_symbol}' for the predictor plus the parameter names you listed."
        )
    code = compile(tree, "<expectation>", "eval")
    env: dict[str, Any] = {name: getattr(np, name) for name in _ALLOWED_FUNCTIONS if hasattr(np, name)}
    env["ceil"] = np.ceil
    env["pi"] = math.pi
    env["e"] = math.e

    def fitted(x, *values):
        scope = dict(env)
        scope[predictor_symbol] = x
        scope.update(dict(zip(parameters, values)))
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            return eval(code, {"__builtins__": {}}, scope)  # noqa: S307 - AST-validated above

    return fitted


def _parse_starting_values(text: Any, parameters: list[str]) -> dict[str, float]:
    """'theta1=10, theta2=0.5' -> {'theta1': 10.0, 'theta2': 0.5}. Bare numbers are taken in order."""
    if text in (None, ""):
        return {}
    raw = str(text).replace(";", ",").replace("\n", ",")
    out: dict[str, float] = {}
    positional: list[float] = []
    for chunk in [c.strip() for c in raw.split(",") if c.strip()]:
        if "=" in chunk:
            name, value = chunk.split("=", 1)
            name = name.strip()
            if name not in parameters:
                raise ProcedureError(f"'{name}' is not a parameter of this expectation function. Parameters: {', '.join(parameters)}.")
            try:
                out[name] = float(value.strip())
            except ValueError:
                raise ProcedureError(f"Starting value for '{name}' must be a number; got '{value.strip()}'.") from None
        else:
            try:
                positional.append(float(chunk))
            except ValueError:
                raise ProcedureError(f"Could not read '{chunk}' as a starting value. Use 'name=value' pairs separated by commas.") from None
    for name, value in zip(parameters, positional):
        out.setdefault(name, value)
    return out


def _auto_start(catalog_id: str | None, parameters: list[str], x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Sensible starting values. curve_fit from all-ones diverges on most of these forms."""
    y_max = float(np.max(y))
    y_min = float(np.min(y))
    x_span = float(np.max(x) - np.min(x)) or 1.0
    x_mid = float(np.median(x))
    guesses: dict[str, float] = {}

    def log_slope(sign: float) -> float:
        positive = y > 0
        if positive.sum() >= 2 and np.ptp(x[positive]) > 0:
            slope = float(np.polyfit(x[positive], np.log(y[positive]), 1)[0])
            return slope if slope != 0 else sign * 0.1
        return sign * 0.1

    if catalog_id == "exponential_growth":
        guesses = {"theta1": max(abs(y_min), 1e-3), "theta2": log_slope(1.0)}
    elif catalog_id == "exponential_decay":
        guesses = {"theta1": max(y_max, 1e-3), "theta2": abs(log_slope(-1.0))}
    elif catalog_id == "power":
        positive = (x > 0) & (y > 0)
        if positive.sum() >= 2 and np.ptp(np.log(x[positive])) > 0:
            slope, intercept = np.polyfit(np.log(x[positive]), np.log(y[positive]), 1)
            guesses = {"theta1": float(np.exp(intercept)), "theta2": float(slope)}
        else:
            guesses = {"theta1": max(y_max, 1e-3), "theta2": 1.0}
    elif catalog_id == "logistic":
        guesses = {"theta1": y_max * 1.05 or 1.0, "theta2": 4.0 / x_span, "theta3": x_mid}
    elif catalog_id == "michaelis_menten":
        guesses = {"theta1": y_max * 1.1 or 1.0, "theta2": max(x_mid, 1e-6)}
    elif catalog_id == "gompertz":
        guesses = {"theta1": y_max * 1.05 or 1.0, "theta2": 1.0, "theta3": 2.0 / x_span}
    return {name: guesses.get(name, 1.0) for name in parameters}


def _nonlinear(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Nonlinear Regression needs a response column and one predictor column.")
    response, predictor = columns[0], columns[1]
    require_columns(df, [response, predictor])
    frame = pd.DataFrame(
        {"y": pd.to_numeric(df[response], errors="coerce"), "x": pd.to_numeric(df[predictor], errors="coerce")}
    ).dropna()
    if len(frame) < 4:
        raise ProcedureError(f"Nonlinear Regression needs at least 4 rows where both columns are numeric; found {len(frame)}.")
    x = frame["x"].to_numpy(dtype=float)
    y = frame["y"].to_numpy(dtype=float)

    catalog_id = str(option(options, "expectation", "exponential_growth"))
    conf = confidence(options)
    if catalog_id == "custom":
        formula = option(options, "formula", None)
        if not formula:
            raise ProcedureError("Enter the expectation function, using 'x' for the predictor.")
        _tree, names = _expression_names(str(formula))
        parameters = sorted(names - {"x"} - _ALLOWED_FUNCTIONS - _ALLOWED_CONSTANTS)
        if not parameters:
            raise ProcedureError("The expectation function has no parameters to estimate — it must contain at least one name other than 'x'.")
        catalog_key = None
        label = "Custom"
    else:
        entry = EXPECTATION_CATALOG.get(catalog_id)
        if entry is None:
            raise ProcedureError(f"Unknown expectation function '{catalog_id}'. Choose one of: {', '.join(EXPECTATION_CATALOG)}, or 'custom'.")
        formula = entry["formula"]
        parameters = list(entry["parameters"])
        catalog_key = catalog_id
        label = entry["label"]

    if len(parameters) >= len(frame):
        raise ProcedureError(f"The model has {len(parameters)} parameter(s) but only {len(frame)} usable row(s).")

    fitted_fn = _compile_expectation(str(formula), "x", parameters)
    auto = _auto_start(catalog_key, parameters, x, y)
    provided = _parse_starting_values(option(options, "starting_values", None), parameters)
    start = {name: provided.get(name, auto[name]) for name in parameters}

    max_iterations = int_option(options, "max_iterations", 2000, what="Maximum iterations") or 2000
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            popt, pcov, infodict, mesg, ier = optimize.curve_fit(
                fitted_fn, x, y, p0=[start[name] for name in parameters], maxfev=max(200, max_iterations), full_output=True
            )
    except (RuntimeError, TypeError, ValueError) as err:
        raise ProcedureError(
            f"The fit did not converge: {err}. Try different starting values, or a different expectation function."
        ) from None

    predicted = np.asarray(fitted_fn(x, *popt), dtype=float)
    if not np.all(np.isfinite(predicted)):
        raise ProcedureError("The fitted function produced non-finite values — try different starting values.")
    resid = y - predicted
    dof = len(frame) - len(parameters)
    sse = float(np.sum(resid**2))
    s_value = math.sqrt(sse / dof) if dof > 0 else None
    sst = float(np.sum((y - np.mean(y)) ** 2))
    # For a nonlinear fit R² has no variance-decomposition meaning; Minitab reports it as a
    # descriptive "how much of the variation is accounted for" and so does this.
    r_squared = 1 - sse / sst if sst > 0 else None

    errors = np.sqrt(np.diag(pcov)) if pcov is not None and np.all(np.isfinite(pcov)) else np.full(len(parameters), np.nan)
    t_crit = float(st.t.ppf(1 - (1 - conf) / 2, dof)) if dof > 0 else float("nan")
    parameter_rows = []
    for i, name in enumerate(parameters):
        se = float(errors[i]) if np.isfinite(errors[i]) else None
        low = float(popt[i] - t_crit * se) if se is not None and np.isfinite(t_crit) else None
        high = float(popt[i] + t_crit * se) if se is not None and np.isfinite(t_crit) else None
        parameter_rows.append(
            {
                "Parameter": name,
                "Estimate": float(popt[i]),
                "SE Estimate": se,
                f"{conf * 100:g}% CI": ci_text(low, high, 5),
                "Starting value": start[name],
            }
        )

    grid = np.linspace(float(np.min(x)), float(np.max(x)), 160)
    grid_y = np.asarray(fitted_fn(grid, *popt), dtype=float)
    finite = np.isfinite(grid_y)

    converged = ier in (1, 2, 3, 4)
    conclusion = (
        f"{label} fit of {response} on {predictor} (n = {len(frame)}): {formula}. "
        + (f"S = {g(s_value, 4)}, " if s_value is not None else "")
        + (f"R² = {r_squared * 100:.2f}% (descriptive). " if r_squared is not None else "")
        + f"{'Converged' if converged else 'Did not converge cleanly'} after {int(infodict.get('nfev', 0))} function evaluation(s)."
    )
    return {
        "procedure": "nonlinear",
        "title": f"Nonlinear Regression: {response} versus {predictor}",
        "method": f"{label}: {formula} — least squares via Levenberg-Marquardt",
        "expectation": formula,
        "parameters": parameters,
        "n": len(frame),
        "s": s_value,
        "r_squared": r_squared,
        "iterations": int(infodict.get("nfev", 0)),
        "converged": converged,
        "convergence_message": str(mesg).strip() if mesg else None,
        "confidence_level": conf,
        "note": None if converged else "The optimiser stopped without a clean convergence flag — treat the estimates with caution.",
        "tables": [
            {"title": "Parameter Estimates", "rows": parameter_rows},
            {
                "title": "Model Summary",
                "rows": [{"Iterations (function evaluations)": int(infodict.get("nfev", 0)), "DF Error": dof, "SSE": sse, "S": s_value, "R-sq (descriptive)": None if r_squared is None else r_squared * 100}],
            },
        ],
        "highlights": [
            {"label": "S", "value": s_value},
            {"label": "R-sq (descriptive)", "value": None if r_squared is None else r_squared * 100, "suffix": "%"},
            {"label": "Function evaluations", "value": int(infodict.get("nfev", 0)), "decimals": 0},
        ],
        "graphs": [
            {
                "renderer": "fittedLine",
                "title": f"Fitted curve of {response} vs {predictor}",
                "data": {
                    "points": [{"x": float(a), "y": float(b)} for a, b in zip(x, y)],
                    "curve": [{"x": float(a), "fit": float(b)} for a, b in zip(grid[finite], grid_y[finite])],
                    "x_label": predictor,
                    "y_label": response,
                    "equation": f"{response} = {formula}",
                    "annotations": [f"{name} = {g(float(popt[i]), 4)}" for i, name in enumerate(parameters)],
                },
            },
            *_residual_graphs(None, resid, predicted),
        ],
        "conclusion": conclusion,
        "summary": f"Nonlinear Regression ({label}) — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 6. Orthogonal Regression
# ---------------------------------------------------------------------------


def _orthogonal(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Orthogonal Regression needs a response column and one predictor column.")
    response, predictor = columns[0], columns[1]
    require_columns(df, [response, predictor])
    ratio = float_option(options, "error_ratio", 1.0, what="Error variance ratio") or 1.0
    if ratio <= 0:
        raise ProcedureError("The error variance ratio must be greater than 0.")
    conf = confidence(options)

    frame = pd.DataFrame(
        {"y": pd.to_numeric(df[response], errors="coerce"), "x": pd.to_numeric(df[predictor], errors="coerce")}
    ).dropna()
    if len(frame) < 3:
        raise ProcedureError(f"Orthogonal Regression needs at least 3 rows where both columns are numeric; found {len(frame)}.")
    x = frame["x"].to_numpy(dtype=float)
    y = frame["y"].to_numpy(dtype=float)

    ols = sm.OLS(y, sm.add_constant(x)).fit()

    # scipy.odr weights each axis by 1/variance; the ratio is var(response)/var(predictor).
    data = odr.RealData(x, y, sx=np.sqrt(1.0), sy=np.sqrt(ratio))
    fit = odr.ODR(data, odr.Model(lambda beta, xx: beta[0] + beta[1] * xx), beta0=[float(ols.params[0]), float(ols.params[1])]).run()
    intercept, slope = float(fit.beta[0]), float(fit.beta[1])
    se_intercept, se_slope = (float(v) for v in np.sqrt(np.diag(fit.cov_beta))) if fit.cov_beta is not None else (float("nan"), float("nan"))
    dof = len(frame) - 2
    t_crit = float(st.t.ppf(1 - (1 - conf) / 2, dof)) if dof > 0 else float("nan")

    def row(term: str, coef: float, se: float, ols_coef: float) -> dict[str, Any]:
        low = coef - t_crit * se if np.isfinite(se) and np.isfinite(t_crit) else None
        high = coef + t_crit * se if np.isfinite(se) and np.isfinite(t_crit) else None
        p = float(2 * st.t.sf(abs(coef / se), dof)) if np.isfinite(se) and se > 0 and dof > 0 else None
        return {
            "Term": term,
            "Coef (orthogonal)": coef,
            "SE Coef": None if not np.isfinite(se) else se,
            f"{conf * 100:g}% CI": ci_text(low, high, 5),
            "P-Value": p,
            "Coef (OLS)": ols_coef,
        }

    coef_rows = [row("Constant", intercept, se_intercept, float(ols.params[0])), row(predictor, slope, se_slope, float(ols.params[1]))]
    grid = np.linspace(float(np.min(x)), float(np.max(x)), 60)
    conclusion = (
        f"Orthogonal fit of {response} on {predictor} (n = {len(frame)}, error variance ratio {g(ratio)}): "
        f"slope {g(slope, 5)} versus the OLS slope {g(float(ols.params[1]), 5)}. "
        f"Orthogonal regression allows for measurement error in {predictor}, which OLS assumes away — the two slopes "
        f"differ by {g(abs(slope - float(ols.params[1])), 3)}."
    )
    return {
        "procedure": "orthogonal",
        "title": f"Orthogonal Regression: {response} versus {predictor}",
        "method": f"Deming regression via scipy.odr, error variance ratio (response:predictor) {g(ratio)}",
        "error_ratio": ratio,
        "n": len(frame),
        "slope": slope,
        "intercept": intercept,
        "ols_slope": float(ols.params[1]),
        "confidence_level": conf,
        "equation": f"{response} = {g(intercept, 5)} {'-' if slope < 0 else '+'} {g(abs(slope), 5)} {predictor}",
        "tables": [
            {"title": "Coefficients (orthogonal fit, with OLS alongside)", "rows": coef_rows},
            {"title": "Model Summary", "rows": [{"N": len(frame), "Error variance ratio": ratio, "Residual sum of squares": float(fit.sum_square), "OLS R-sq": float(ols.rsquared) * 100}]},
        ],
        "highlights": [
            {"label": "Slope (orthogonal)", "value": slope},
            {"label": "Slope (OLS)", "value": float(ols.params[1])},
            {"label": "N", "value": len(frame), "decimals": 0},
        ],
        "graphs": [
            {
                "renderer": "compareFits",
                "title": "Orthogonal fit compared with ordinary least squares",
                "data": {
                    "points": [{"x": float(a), "y": float(b)} for a, b in zip(x, y)],
                    "series": [
                        {"label": "Orthogonal", "points": [{"x": float(v), "y": intercept + slope * float(v)} for v in grid]},
                        {"label": "OLS", "points": [{"x": float(v), "y": float(ols.params[0]) + float(ols.params[1]) * float(v)} for v in grid]},
                    ],
                    "x_label": predictor,
                    "y_label": response,
                },
            }
        ],
        "conclusion": conclusion,
        "summary": f"Orthogonal Regression — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 7. Partial Least Squares
# ---------------------------------------------------------------------------


def _pls(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 3:
        raise ProcedureError("Partial Least Squares needs a response column and at least 2 predictors.")
    response, predictors = columns[0], columns[1:]
    spec = _model_frame(df, response, predictors, [], what="Partial Least Squares")
    X = spec.frame[[spec.safe[p] for p in predictors]].to_numpy(dtype=float)
    y = spec.frame[spec.safe[response]].to_numpy(dtype=float)
    n = len(y)

    max_components = min(len(predictors), n - 1)
    if max_components < 1:
        raise ProcedureError("There are not enough rows to fit even one PLS component.")
    folds = max(2, min(int_option(options, "cv_folds", 5, what="Cross-validation folds") or 5, n))
    sst = float(np.sum((y - y.mean()) ** 2))

    def fit(components: int) -> PLSRegression:
        model = PLSRegression(n_components=components, scale=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(X, y)
        return model

    per_component = []
    for components in range(1, max_components + 1):
        model = fit(components)
        pred = model.predict(X).ravel()
        r_squared = 1 - float(np.sum((y - pred) ** 2)) / sst if sst > 0 else None
        press = 0.0
        splitter = KFold(n_splits=folds, shuffle=True, random_state=12345)
        try:
            for train, test in splitter.split(X):
                if len(train) <= components:
                    press = float("nan")
                    break
                cv_model = PLSRegression(n_components=components, scale=True)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    cv_model.fit(X[train], y[train])
                press += float(np.sum((y[test] - cv_model.predict(X[test]).ravel()) ** 2))
        except Exception:  # noqa: BLE001 - a CV failure must not lose the fit
            press = float("nan")
        predicted_r2 = 1 - press / sst if (sst > 0 and np.isfinite(press)) else None
        per_component.append(
            {
                "Components": components,
                "R-Sq": None if r_squared is None else r_squared * 100,
                "R-Sq(pred) from CV": None if predicted_r2 is None else predicted_r2 * 100,
                "PRESS": None if not np.isfinite(press) else press,
            }
        )

    requested = option(options, "components", "cv")
    if str(requested) == "cv":
        usable = [row for row in per_component if row["R-Sq(pred) from CV"] is not None]
        chosen = max(usable, key=lambda r: r["R-Sq(pred) from CV"])["Components"] if usable else 1
        chosen_reason = f"{folds}-fold cross-validation (highest predicted R²)"
    else:
        chosen = int_option(options, "components", 1, what="Number of components") or 1
        if not 1 <= chosen <= max_components:
            raise ProcedureError(f"Number of components must be between 1 and {max_components} for {len(predictors)} predictor(s) and {n} rows.")
        chosen_reason = "set in the dialog"

    model = fit(chosen)
    coefficients = np.asarray(model.coef_, dtype=float).reshape(-1)
    if coefficients.size != len(predictors):  # sklearn has moved this orientation before
        coefficients = np.asarray(model.coef_, dtype=float).T.reshape(-1)[: len(predictors)]
    intercept = float(np.asarray(model.intercept_, dtype=float).reshape(-1)[0])
    fitted_values = model.predict(X).ravel()
    resid = y - fitted_values
    chosen_row = next(row for row in per_component if row["Components"] == chosen)

    loadings = np.asarray(model.x_loadings_, dtype=float)
    loading_points = [
        {
            "label": predictors[i],
            "x": float(loadings[i, 0]),
            "y": float(loadings[i, 1]) if loadings.shape[1] > 1 else 0.0,
        }
        for i in range(len(predictors))
    ]

    conclusion = (
        f"PLS of {response} on {len(predictors)} predictor(s), n = {n}. Using {chosen} component(s) ({chosen_reason}): "
        f"R² = {chosen_row['R-Sq']:.2f}%"
        + (f", predicted R² = {chosen_row['R-Sq(pred) from CV']:.2f}% from {folds}-fold CV." if chosen_row["R-Sq(pred) from CV"] is not None else ".")
    )
    return {
        "procedure": "pls",
        "title": f"PLS Regression: {response} versus {', '.join(predictors)}",
        "method": f"sklearn PLSRegression, {chosen} component(s) {chosen_reason}, predictors standardised",
        "response": response,
        "predictors": predictors,
        "n": n,
        "components": chosen,
        "r_squared": chosen_row["R-Sq"],
        "r_squared_pred": chosen_row["R-Sq(pred) from CV"],
        "tables": [
            {"title": "Model selection by number of components", "rows": per_component},
            {
                "title": f"Coefficients ({chosen} component(s), original units)",
                "rows": [{"Term": "Constant", "Coef": intercept}] + [{"Term": predictors[i], "Coef": float(coefficients[i])} for i in range(len(predictors))],
            },
        ],
        "highlights": [
            {"label": "Components", "value": chosen, "decimals": 0},
            {"label": "R-sq", "value": chosen_row["R-Sq"], "suffix": "%"},
            {"label": "R-sq(pred)", "value": chosen_row["R-Sq(pred) from CV"], "suffix": "%"},
        ],
        "graphs": [
            {
                "renderer": "loadingPlot",
                "title": "Loading plot" + (" (components 1 and 2)" if loadings.shape[1] > 1 else " (component 1)"),
                "data": {"points": loading_points, "x_label": "Component 1 loading", "y_label": "Component 2 loading" if loadings.shape[1] > 1 else "(only one component)"},
            },
            *_residual_graphs(None, resid, fitted_values),
        ],
        "conclusion": conclusion,
        "summary": f"PLS Regression — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 8. Stability Study
# ---------------------------------------------------------------------------

# ICH Q1E pools batches only when the differences are clearly absent, which is why the poolability
# test uses a deliberately generous alpha rather than 0.05.
STABILITY_POOL_ALPHA = 0.25


def _stability(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Stability Study needs a response column and a time column.")
    response, time_col = columns[0], columns[1]
    batch_col = columns[2] if len(columns) > 2 else None
    spec_limit = float_option(options, "spec_limit", None, what="Specification limit")
    if spec_limit is None:
        raise ProcedureError("Enter the specification limit the shelf life is measured against.")
    spec_side = str(option(options, "spec_side", "lower"))
    if spec_side not in ("lower", "upper"):
        raise ProcedureError("The specification limit must be a 'lower' or an 'upper' limit.")
    conf = confidence(options)
    pool_alpha = float_option(options, "pool_alpha", STABILITY_POOL_ALPHA, what="Alpha for pooling") or STABILITY_POOL_ALPHA

    spec = _model_frame(df, response, [time_col], [batch_col] if batch_col else [], what="Stability Study")
    y_safe = spec.safe[response]
    t_safe = spec.safe[time_col]
    frame = spec.frame

    chosen_model_label: str
    pool_rows: list[dict[str, Any]] = []
    if batch_col:
        b_safe = spec.safe[batch_col]
        batches = sorted(frame[b_safe].astype(str).unique())
        if len(batches) < 2:
            batch_col = None
        else:
            full = smf.ols(f"{y_safe} ~ {t_safe} * C({b_safe})", data=frame).fit()
            equal_slopes = smf.ols(f"{y_safe} ~ {t_safe} + C({b_safe})", data=frame).fit()
            pooled = smf.ols(f"{y_safe} ~ {t_safe}", data=frame).fit()

            slope_test = full.compare_f_test(equal_slopes)
            slope_p = float(slope_test[0]) if False else float(slope_test[1])
            intercept_test = equal_slopes.compare_f_test(pooled)
            intercept_p = float(intercept_test[1])

            pool_rows = [
                {"Test": "Equal slopes (batch × time)", "F-Value": float(slope_test[0]), "DF": float(slope_test[2]), "P-Value": slope_p, "Pooled?": "no" if slope_p < pool_alpha else "yes"},
                {"Test": "Equal intercepts (batch)", "F-Value": float(intercept_test[0]), "DF": float(intercept_test[2]), "P-Value": intercept_p, "Pooled?": "no" if intercept_p < pool_alpha else "yes"},
            ]
            if slope_p < pool_alpha:
                model = full
                chosen_model_label = "Separate slopes and intercepts per batch"
            elif intercept_p < pool_alpha:
                model = equal_slopes
                chosen_model_label = "Common slope, separate intercepts per batch"
            else:
                model = pooled
                chosen_model_label = "Fully pooled (single line for all batches)"
    if not batch_col:
        batches = ["all data"]
        model = smf.ols(f"{y_safe} ~ {t_safe}", data=frame).fit()
        chosen_model_label = "Single line (no batch factor given)"

    # Shelf life: the time at which the one-sided bound on the mean crosses the spec limit.
    t_min = float(frame[t_safe].min())
    t_max = float(frame[t_safe].max())
    horizon = t_max + max(t_max - t_min, 1.0) * 3
    grid = np.linspace(min(t_min, 0.0), horizon, 400)
    alpha_one_sided = (1 - conf) * 2  # summary_frame's alpha is two-sided; double it for a one-sided bound

    curves = []
    shelf_lives: dict[str, float | None] = {}
    for batch in batches:
        exog = {t_safe: grid}
        if batch_col and batch != "all data":
            exog[spec.safe[batch_col]] = [batch] * len(grid)
        try:
            prediction = model.get_prediction(pd.DataFrame(exog)).summary_frame(alpha=alpha_one_sided)
        except Exception as err:  # noqa: BLE001
            raise ProcedureError(f"The stability model could not be projected forward: {err}") from err
        fit = prediction["mean"].to_numpy(dtype=float)
        bound = prediction["mean_ci_lower" if spec_side == "lower" else "mean_ci_upper"].to_numpy(dtype=float)
        crossing = None
        outside = bound < spec_limit if spec_side == "lower" else bound > spec_limit
        indices = np.nonzero(outside)[0]
        if indices.size:
            first = int(indices[0])
            if first == 0:
                crossing = float(grid[0])
            else:
                x0, x1 = float(grid[first - 1]), float(grid[first])
                b0, b1 = float(bound[first - 1]), float(bound[first])
                crossing = x0 + (spec_limit - b0) * (x1 - x0) / (b1 - b0) if b1 != b0 else x1
        shelf_lives[str(batch)] = crossing
        curves.append(
            {
                "label": str(batch),
                "fit": [{"x": float(a), "y": float(b)} for a, b in zip(grid, fit)],
                "bound": [{"x": float(a), "y": float(b)} for a, b in zip(grid, bound)],
                "points": [
                    {"x": float(r[t_safe]), "y": float(r[y_safe])}
                    for _i, r in frame.iterrows()
                    if (not batch_col) or str(r[spec.safe[batch_col]]) == str(batch)
                ],
                "shelf_life": crossing,
            }
        )

    valid = [v for v in shelf_lives.values() if v is not None]
    overall = min(valid) if valid else None

    # The search grid runs far past the data so a distant crossing is still found, but plotting all
    # of it squeezes the observed range into the left edge. Draw only as far as the answer needs.
    plot_max = max(t_max, max(valid) if valid else t_max) * 1.2 or horizon
    for curve in curves:
        curve["fit"] = [p for p in curve["fit"] if p["x"] <= plot_max]
        curve["bound"] = [p for p in curve["bound"] if p["x"] <= plot_max]
    shelf_rows = [
        {"Batch": name, "Shelf life": value, "Within the observed range?": "yes" if (value is not None and value <= t_max) else "no (extrapolated)" if value is not None else "not reached"}
        for name, value in shelf_lives.items()
    ]

    conclusion = (
        f"{chosen_model_label}. "
        + (f"Poolability at α = {g(pool_alpha)}: " + "; ".join(f"{r['Test']} p = {p_text(r['P-Value'])}" for r in pool_rows) + ". " if pool_rows else "")
        + (
            f"Estimated shelf life is {g(overall, 4)} {option(options, 'time_units', 'time unit(s)')} — where the "
            f"{conf * 100:g}% one-sided bound on the mean first crosses the {spec_side} spec limit of {g(spec_limit)}."
            if overall is not None
            else f"The {conf * 100:g}% bound never crosses the {spec_side} spec limit of {g(spec_limit)} within {g(horizon, 4)} time units, so no shelf life is estimated."
        )
    )
    return {
        "procedure": "stability",
        "title": f"Stability Study: {response} over {time_col}" + (f" by {batch_col}" if batch_col else ""),
        "method": f"{chosen_model_label}; poolability tested at α = {g(pool_alpha)} (ICH convention); shelf life where the {conf * 100:g}% one-sided bound crosses the {spec_side} spec limit",
        "response": response,
        "time_column": time_col,
        "batch_column": batch_col,
        "spec_limit": spec_limit,
        "spec_side": spec_side,
        "confidence_level": conf,
        "pool_alpha": pool_alpha,
        "model_used": chosen_model_label,
        "shelf_life": overall,
        "note": "Shelf lives beyond the last observed time point are extrapolations of the fitted model and should be treated as indicative." if (overall is not None and overall > t_max) else None,
        "tables": (
            ([{"title": f"Poolability of batches (α = {g(pool_alpha)})", "rows": pool_rows}] if pool_rows else [])
            + [
                {"title": "Model Summary", "rows": _model_summary_rows(model)},
                {"title": "Shelf life", "rows": shelf_rows},
            ]
        ),
        "highlights": [
            {"label": "Shelf life", "value": overall},
            {"label": "Batches", "value": len(batches), "decimals": 0},
            {"label": "R-sq", "value": float(model.rsquared) * 100, "suffix": "%"},
        ],
        "graphs": [
            {
                "renderer": "stabilityPlot",
                "title": f"{response} over {time_col} with the {conf * 100:g}% bound and the spec limit",
                "data": {
                    "series": curves,
                    "spec_limit": spec_limit,
                    "spec_side": spec_side,
                    "shelf_life": overall,
                    "x_label": time_col,
                    "y_label": response,
                    "confidence": conf,
                },
            }
        ],
        "conclusion": conclusion,
        "summary": f"Stability Study — {conclusion}",
    }


# ---------------------------------------------------------------------------
# categorical responses: shared encoding
# ---------------------------------------------------------------------------


def _binary_response(frame: pd.DataFrame, safe: str, name: str, options: dict) -> tuple[np.ndarray, str, str]:
    """(0/1 array, label modelled as the event, the other label)."""
    raw = frame[safe]
    labels = sorted(pd.unique(raw.astype(str)))
    if len(labels) != 2:
        raise ProcedureError(
            f"A binary response needs exactly 2 distinct values in '{name}'; found {len(labels)} "
            f"({', '.join(labels[:8])}{'…' if len(labels) > 8 else ''})."
        )
    chosen = option(options, "event_value", None)
    event = str(chosen) if chosen is not None and str(chosen) in labels else labels[-1]
    other = [label for label in labels if label != event][0]
    y = (raw.astype(str) == event).to_numpy(dtype=float)
    return y, event, other


def _design(spec: _Spec, continuous: list[str], categorical: list[str], interactions: bool) -> tuple[pd.DataFrame, list[str]]:
    """Design matrix with an intercept, built by patsy so categorical predictors and interactions
    are handled the same way as in the OLS path."""
    import patsy

    terms = [spec.safe[c] for c in continuous] + [f"C({spec.safe[c]})" for c in categorical]
    if interactions and len(terms) >= 2:
        terms += [f"{a}:{b}" for a, b in combinations(terms, 2)]
    formula = " + ".join(terms)
    try:
        exog = patsy.dmatrix(formula, spec.frame, return_type="dataframe")
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The predictors could not be assembled into a model matrix: {err}") from err
    return exog, list(exog.columns)


def _odds_ratio_rows(params, bse, pvalues, conf_int, names: list[str], spec: _Spec, conf: float, *, label: str = "Odds Ratio") -> list[dict[str, Any]]:
    rows = []
    for i, name in enumerate(names):
        is_intercept = name in ("Intercept", "const")
        coef = float(params[i])
        row: dict[str, Any] = {
            "Term": "Constant" if is_intercept else _pretty_term(name, spec),
            "Coef": coef,
            "SE Coef": float(bse[i]),
            "Z-Value": float(coef / bse[i]) if bse[i] else None,
            "P-Value": float(pvalues[i]),
        }
        if not is_intercept:
            low, high = float(conf_int[i][0]), float(conf_int[i][1])
            row[label] = math.exp(coef) if abs(coef) < 700 else None
            row[f"{conf * 100:g}% CI for {label}"] = ci_text(math.exp(low) if abs(low) < 700 else None, math.exp(high) if abs(high) < 700 else None, 4)
        rows.append(row)
    return rows


def _classification_rows(y: np.ndarray, probabilities: np.ndarray, event: str, other: str, cutoff: float = 0.5) -> tuple[list[dict[str, Any]], dict[str, float]]:
    predicted_event = probabilities >= cutoff
    actual_event = y > 0.5
    tp = int(np.sum(predicted_event & actual_event))
    fp = int(np.sum(predicted_event & ~actual_event))
    fn = int(np.sum(~predicted_event & actual_event))
    tn = int(np.sum(~predicted_event & ~actual_event))
    n = tp + fp + fn + tn
    rows = [
        {"Actual": event, f"Predicted {event}": tp, f"Predicted {other}": fn, "Total": tp + fn},
        {"Actual": other, f"Predicted {event}": fp, f"Predicted {other}": tn, "Total": fp + tn},
        {"Actual": "Total", f"Predicted {event}": tp + fp, f"Predicted {other}": fn + tn, "Total": n},
    ]
    metrics = {
        "correct": (tp + tn) / n * 100 if n else 0.0,
        "sensitivity": tp / (tp + fn) * 100 if (tp + fn) else None,
        "specificity": tn / (tn + fp) * 100 if (tn + fp) else None,
    }
    return rows, metrics


def _roc(y: np.ndarray, probabilities: np.ndarray) -> tuple[list[dict[str, float]], float]:
    order = np.argsort(-probabilities)
    truth = y[order] > 0.5
    positives = int(truth.sum())
    negatives = int((~truth).sum())
    if positives == 0 or negatives == 0:
        return [], float("nan")
    tp = 0
    fp = 0
    curve = [{"x": 0.0, "y": 0.0}]
    for is_event in truth:
        if is_event:
            tp += 1
        else:
            fp += 1
        curve.append({"x": fp / negatives, "y": tp / positives})
    area = 0.0
    for a, b in zip(curve, curve[1:]):
        area += (b["x"] - a["x"]) * (a["y"] + b["y"]) / 2
    return curve, float(area)


def _hosmer_lemeshow(y: np.ndarray, probabilities: np.ndarray, groups: int = 10) -> tuple[float, int, float, list[dict[str, Any]]] | None:
    """Deciles of risk. Groups are formed on the ranked predicted probability, with ties kept
    together, so a model with few distinct predictions simply gets fewer groups."""
    n = len(y)
    if n < 20:
        return None
    order = np.argsort(probabilities)
    p_sorted = probabilities[order]
    y_sorted = y[order]
    edges = np.unique(np.linspace(0, n, min(groups, n) + 1).astype(int))
    rows = []
    statistic = 0.0
    used = 0
    for start, end in zip(edges, edges[1:]):
        if end <= start:
            continue
        observed = float(np.sum(y_sorted[start:end]))
        expected = float(np.sum(p_sorted[start:end]))
        size = end - start
        if expected <= 0 or expected >= size:
            continue
        statistic += (observed - expected) ** 2 / (expected * (1 - expected / size))
        used += 1
        rows.append({"Group": used, "N": int(size), "Observed events": observed, "Expected events": expected})
    dof = used - 2
    if dof < 1:
        return None
    return statistic, dof, float(st.chi2.sf(statistic, dof)), rows


# ---------------------------------------------------------------------------
# 9. Binary Fitted Line Plot / 10. Binary Logistic
# ---------------------------------------------------------------------------


def _binary_fitted_line(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Binary Fitted Line Plot needs a binary response and one predictor.")
    response, predictor = columns[0], columns[1]
    spec = _model_frame(df, response, [predictor], [], what="Binary Fitted Line Plot", numeric_response=False)
    y, event, other = _binary_response(spec.frame, spec.safe[response], response, options)
    x = spec.frame[spec.safe[predictor]].to_numpy(dtype=float)

    exog = sm.add_constant(x)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = sm.Logit(y, exog).fit(disp=0)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The logistic fit did not converge: {err}") from err

    intercept, slope = float(model.params[0]), float(model.params[1])
    grid = np.linspace(float(np.min(x)), float(np.max(x)), 160)
    probabilities = 1 / (1 + np.exp(-(intercept + slope * grid)))
    fitted_p = np.asarray(model.predict(exog), dtype=float)
    curve_rows, auc = _roc(y, fitted_p)

    equation = f"P({response} = {event}) = exp(η) / (1 + exp(η)), η = {g(intercept, 5)} {'-' if slope < 0 else '+'} {g(abs(slope), 5)} {predictor}"
    odds_ratio = math.exp(slope) if abs(slope) < 700 else None
    conclusion = (
        f"Logistic fit of P({response} = {event}) on {predictor} (n = {spec.rows_used}, {int(y.sum())} event(s)). "
        f"Each 1-unit rise in {predictor} multiplies the odds by {g(odds_ratio, 4)} (p = {p_text(float(model.pvalues[1]))}); "
        f"pseudo R² = {float(model.prsquared) * 100:.2f}%, AUC = {g(auc, 3)}."
    )
    return {
        "procedure": "binary_fitted_line",
        "title": f"Binary Fitted Line Plot: {response} versus {predictor}",
        "method": f"Binary logistic regression, logit link; '{event}' modelled as the event (reference '{other}')",
        "event": event,
        "equation": equation,
        "n": spec.rows_used,
        "odds_ratio": odds_ratio,
        "p_value": float(model.pvalues[1]),
        "pseudo_r_squared": float(model.prsquared),
        "tables": [
            {
                "title": "Coefficients",
                "rows": [
                    {"Term": "Constant", "Coef": intercept, "SE Coef": float(model.bse[0]), "Z-Value": float(model.tvalues[0]), "P-Value": float(model.pvalues[0])},
                    {"Term": predictor, "Coef": slope, "SE Coef": float(model.bse[1]), "Z-Value": float(model.tvalues[1]), "P-Value": float(model.pvalues[1]), "Odds Ratio": odds_ratio},
                ],
            },
            {"title": "Model Summary", "rows": [{"N": spec.rows_used, "Events": int(y.sum()), "Deviance": float(model.deviance) if hasattr(model, "deviance") else float(-2 * model.llf), "Pseudo R-sq (McFadden)": float(model.prsquared) * 100, "AUC": auc}]},
            {"title": "Fitted Equation", "rows": [{"Equation": equation}]},
        ],
        "highlights": [
            {"label": "Odds ratio", "value": odds_ratio},
            {"label": "P-Value", "value": float(model.pvalues[1]), "tone": "positive" if model.pvalues[1] < 0.05 else None},
            {"label": "AUC", "value": auc},
        ],
        "graphs": [
            {
                "renderer": "binaryFittedLine",
                "title": f"Fitted probability of {response} = {event} against {predictor}",
                "data": {
                    "points": [{"x": float(a), "y": float(b)} for a, b in zip(x, y)],
                    "curve": [{"x": float(a), "y": float(b)} for a, b in zip(grid, probabilities)],
                    "x_label": predictor,
                    "y_label": f"P({response} = {event})",
                    "equation": equation,
                    "event": event,
                    "other": other,
                },
            }
        ],
        "conclusion": conclusion,
        "summary": f"Binary Fitted Line Plot — {conclusion}",
    }


def _binary_logistic(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, continuous, categorical, interactions = _model_options(columns, options)
    conf = confidence(options)
    spec = _model_frame(df, response, continuous, categorical, what="Binary Logistic Regression", numeric_response=False, interactions=interactions)
    y, event, other = _binary_response(spec.frame, spec.safe[response], response, options)
    exog, names = _design(spec, continuous, categorical, interactions)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = sm.Logit(y, exog).fit(disp=0, maxiter=200)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(
            f"The logistic model did not converge: {err}. A predictor that separates the response perfectly, "
            f"or a categorical level with no events, will do this."
        ) from err

    conf_int = np.asarray(model.conf_int(alpha=1 - conf))
    coef_rows = _odds_ratio_rows(model.params.values, model.bse.values, model.pvalues.values, conf_int, names, spec, conf)
    probabilities = np.asarray(model.predict(exog), dtype=float)
    classification, metrics = _classification_rows(y, probabilities, event, other)
    curve, auc = _roc(y, probabilities)

    n = len(y)
    p = exog.shape[1]
    deviance = float(-2 * model.llf)
    null_deviance = float(-2 * model.llnull)
    pearson = float(np.sum((y - probabilities) ** 2 / np.clip(probabilities * (1 - probabilities), 1e-12, None)))
    dof = n - p
    gof_rows = [
        {"Test": "Deviance", "Chi-Square": deviance, "DF": dof, "P-Value": float(st.chi2.sf(deviance, dof)) if dof > 0 else None},
        {"Test": "Pearson", "Chi-Square": pearson, "DF": dof, "P-Value": float(st.chi2.sf(pearson, dof)) if dof > 0 else None},
    ]
    hl = _hosmer_lemeshow(y, probabilities)
    if hl is not None:
        statistic, hl_dof, hl_p, _groups = hl
        gof_rows.append({"Test": "Hosmer-Lemeshow", "Chi-Square": statistic, "DF": hl_dof, "P-Value": hl_p})

    deviance_test_p = float(st.chi2.sf(null_deviance - deviance, model.df_model)) if model.df_model else None
    strongest = max((r for r in coef_rows if "Odds Ratio" in r and r["Odds Ratio"] is not None), key=lambda r: abs(math.log(r["Odds Ratio"])), default=None)

    conclusion = (
        f"P({response} = {event}) on {len(continuous) + len(categorical)} predictor(s), n = {n} with {int(y.sum())} event(s). "
        f"Model test: chi-square = {g(null_deviance - deviance, 4)}, p = {p_text(deviance_test_p)}; "
        f"pseudo R² = {float(model.prsquared) * 100:.2f}%, AUC = {g(auc, 3)}, {metrics['correct']:.1f}% correctly classified at a 0.5 cutoff. "
        + (f"Largest effect: {strongest['Term']} with an odds ratio of {g(strongest['Odds Ratio'], 4)} (p = {p_text(strongest['P-Value'])})." if strongest else "")
    )
    return {
        "procedure": "binary_logistic",
        "title": f"Binary Logistic Regression: {response} versus {', '.join(continuous + categorical)}",
        "method": f"statsmodels Logit (logit link); '{event}' modelled as the event, '{other}' as the reference"
        + (" with all two-way interactions" if interactions else ""),
        "response": response,
        "event": event,
        "confidence_level": conf,
        "n": n,
        "events": int(y.sum()),
        "auc": auc,
        "pseudo_r_squared": float(model.prsquared),
        "p_value": deviance_test_p,
        "percent_correct": metrics["correct"],
        "tables": [
            {"title": "Coefficients and Odds Ratios", "rows": coef_rows},
            {
                "title": "Model Summary",
                "rows": [
                    {
                        "Deviance": deviance,
                        "DF": dof,
                        "Null deviance": null_deviance,
                        "Deviance R-sq": (1 - deviance / null_deviance) * 100 if null_deviance else None,
                        "Pseudo R-sq (McFadden)": float(model.prsquared) * 100,
                        "AIC": float(model.aic),
                        "AUC": auc,
                    }
                ],
            },
            {"title": "Goodness-of-Fit Tests", "rows": gof_rows},
            {"title": f"Classification at a 0.5 cutoff ({metrics['correct']:.1f}% correct)", "rows": classification},
        ],
        "highlights": [
            {"label": "AUC", "value": auc},
            {"label": "% correct", "value": metrics["correct"], "suffix": "%"},
            {"label": "Pseudo R-sq", "value": float(model.prsquared) * 100, "suffix": "%"},
            {"label": "Model P-Value", "value": deviance_test_p, "tone": "positive" if (deviance_test_p is not None and deviance_test_p < 0.05) else None},
        ],
        "graphs": [
            {
                "renderer": "rocCurve",
                "title": f"ROC curve (AUC = {g(auc, 3)})",
                "data": {"curve": curve, "auc": auc, "x_label": "1 − specificity (false positive rate)", "y_label": "sensitivity (true positive rate)"},
            }
        ],
        "conclusion": conclusion,
        "summary": f"Binary Logistic Regression — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 11. Ordinal / 12. Nominal Logistic
# ---------------------------------------------------------------------------


def _ordered_levels(frame: pd.DataFrame, safe: str, name: str, options: dict) -> list[str]:
    present = sorted(pd.unique(frame[safe].astype(str)))
    supplied = list_option(options, "level_order")
    if supplied:
        unknown = [level for level in supplied if level not in present]
        if unknown:
            raise ProcedureError(f"Level(s) {', '.join(unknown)} are not in '{name}'. Present: {', '.join(present)}.")
        missing = [level for level in present if level not in supplied]
        if missing:
            raise ProcedureError(f"The level order is missing {', '.join(missing)} — list every level of '{name}', lowest first.")
        return supplied
    return present


def _ordinal_logistic(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, continuous, categorical, interactions = _model_options(columns, options)
    conf = confidence(options)
    spec = _model_frame(df, response, continuous, categorical, what="Ordinal Logistic Regression", numeric_response=False, interactions=interactions)
    y_safe = spec.safe[response]
    levels = _ordered_levels(spec.frame, y_safe, response, options)
    if len(levels) < 3:
        raise ProcedureError(
            f"Ordinal logistic regression needs at least 3 ordered levels in '{response}'; found {len(levels)} "
            f"({', '.join(levels)}). With 2 levels use Binary Logistic Regression."
        )
    # A Series wrapping the Categorical, not the bare Categorical: OrderedModel casts the latter to
    # an object array and dies with "Pandas data cast to numpy dtype of object".
    endog = pd.Series(
        pd.Categorical(spec.frame[y_safe].astype(str), categories=levels, ordered=True),
        index=spec.frame.index,
    )
    exog, names = _design(spec, continuous, categorical, interactions)
    exog = exog.drop(columns=[c for c in exog.columns if c == "Intercept"])  # OrderedModel carries the cutpoints instead
    names = list(exog.columns)
    if exog.shape[1] == 0:
        raise ProcedureError("Ordinal logistic regression needs at least one predictor term.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = OrderedModel(endog, exog, distr="logit").fit(method="bfgs", disp=0, maxiter=200)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The ordinal model did not converge: {err}") from err

    n_terms = exog.shape[1]
    params = model.params.values
    bse = model.bse.values
    pvalues = model.pvalues.values
    conf_int = np.asarray(model.conf_int(alpha=1 - conf))
    coef_rows = _odds_ratio_rows(params[:n_terms], bse[:n_terms], pvalues[:n_terms], conf_int[:n_terms], names, spec, conf)

    # transform_threshold_params lives on the model, not the results wrapper; it turns the
    # unconstrained increments statsmodels fits back into ordered cutpoints.
    thresholds = model.model.transform_threshold_params(params[n_terms:])
    finite = [t for t in thresholds if np.isfinite(t)]
    threshold_rows = [
        {"Threshold": f"{levels[i]} | {levels[i + 1]}", "Estimate": float(value)}
        for i, value in enumerate(finite)
        if i + 1 < len(levels)
    ]

    llnull = _ordinal_null_loglike(endog, levels)
    chi_square = 2 * (float(model.llf) - llnull) if llnull is not None else None
    dof = n_terms
    model_p = float(st.chi2.sf(chi_square, dof)) if (chi_square is not None and dof > 0) else None
    pseudo = 1 - float(model.llf) / llnull if llnull else None

    strongest = max((r for r in coef_rows if r.get("Odds Ratio")), key=lambda r: abs(math.log(r["Odds Ratio"])), default=None)
    conclusion = (
        f"Proportional-odds model for {response} ({' < '.join(levels)}), n = {spec.rows_used}. "
        f"Model test: chi-square = {g(chi_square, 4)}, p = {p_text(model_p)}"
        + (f", pseudo R² = {pseudo * 100:.2f}%. " if pseudo is not None else ". ")
        + (f"Largest effect: {strongest['Term']} with an odds ratio of {g(strongest['Odds Ratio'], 4)} (p = {p_text(strongest['P-Value'])})." if strongest else "")
    )
    return {
        "procedure": "ordinal_logistic",
        "title": f"Ordinal Logistic Regression: {response} versus {', '.join(continuous + categorical)}",
        "method": f"statsmodels OrderedModel, proportional odds with a logit link. Level order (lowest first): {' < '.join(levels)}. "
        f"One odds ratio per predictor applies to every cutpoint — that is the proportional-odds assumption.",
        "response": response,
        "levels": levels,
        "n": spec.rows_used,
        "confidence_level": conf,
        "p_value": model_p,
        "tables": [
            {"title": "Coefficients and Odds Ratios", "rows": coef_rows},
            {"title": "Threshold (cutpoint) estimates", "rows": threshold_rows},
            {
                "title": "Model Summary",
                "rows": [{"N": spec.rows_used, "Log-likelihood": float(model.llf), "Chi-Square (model)": chi_square, "DF": dof, "P-Value": model_p, "Pseudo R-sq (McFadden)": None if pseudo is None else pseudo * 100, "AIC": float(model.aic)}],
            },
        ],
        "highlights": [
            {"label": "Levels", "value": len(levels), "decimals": 0},
            {"label": "Model P-Value", "value": model_p, "tone": "positive" if (model_p is not None and model_p < 0.05) else None},
            {"label": "Pseudo R-sq", "value": None if pseudo is None else pseudo * 100, "suffix": "%"},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"Ordinal Logistic Regression — {conclusion}",
    }


def _ordinal_null_loglike(endog: pd.Categorical, levels: list[str]) -> float | None:
    counts = pd.Series(endog).value_counts().reindex(levels).fillna(0).to_numpy(dtype=float)
    total = counts.sum()
    if total <= 0:
        return None
    shares = counts / total
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(counts > 0, counts * np.log(shares), 0.0)
    return float(np.sum(terms))


def _nominal_logistic(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, continuous, categorical, interactions = _model_options(columns, options)
    conf = confidence(options)
    spec = _model_frame(df, response, continuous, categorical, what="Nominal Logistic Regression", numeric_response=False, interactions=interactions)
    y_safe = spec.safe[response]
    present = sorted(pd.unique(spec.frame[y_safe].astype(str)))
    if len(present) < 3:
        raise ProcedureError(
            f"Nominal logistic regression needs at least 3 outcome levels in '{response}'; found {len(present)}. "
            f"With 2 levels use Binary Logistic Regression."
        )
    reference = option(options, "reference_level", None)
    reference = str(reference) if reference is not None and str(reference) in present else present[0]
    ordered = [reference] + [level for level in present if level != reference]

    codes = pd.Categorical(spec.frame[y_safe].astype(str), categories=ordered).codes
    exog, names = _design(spec, continuous, categorical, interactions)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = sm.MNLogit(codes, exog).fit(disp=0, maxiter=200)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The nominal model did not converge: {err}") from err

    params = np.asarray(model.params)
    bse = np.asarray(model.bse)
    pvalues = np.asarray(model.pvalues)
    conf_int = np.asarray(model.conf_int(alpha=1 - conf))
    tables = []
    all_rows = []
    for j in range(params.shape[1]):
        level = ordered[j + 1]
        # conf_int comes back stacked per outcome; index by (outcome, term)
        bounds = [[float(conf_int[j * len(names) + i][0]), float(conf_int[j * len(names) + i][1])] for i in range(len(names))] if conf_int.ndim == 2 and conf_int.shape[0] == params.shape[1] * len(names) else [[float("nan"), float("nan")]] * len(names)
        rows = _odds_ratio_rows(params[:, j], bse[:, j], pvalues[:, j], bounds, names, spec, conf)
        for row in rows:
            row["Outcome"] = f"{level} vs {reference}"
        tables.append({"title": f"Coefficients and Odds Ratios: {level} versus {reference}", "rows": rows})
        all_rows.extend(rows)

    llnull = float(model.llnull)
    chi_square = 2 * (float(model.llf) - llnull)
    dof = int(model.df_model)
    model_p = float(st.chi2.sf(chi_square, dof)) if dof > 0 else None
    pseudo = float(model.prsquared)
    tables.append(
        {
            "title": "Model Summary",
            "rows": [{"N": spec.rows_used, "Outcome levels": len(ordered), "Reference": reference, "Log-likelihood": float(model.llf), "Chi-Square (model)": chi_square, "DF": dof, "P-Value": model_p, "Pseudo R-sq (McFadden)": pseudo * 100, "AIC": float(model.aic)}],
        }
    )

    strongest = max((r for r in all_rows if r.get("Odds Ratio")), key=lambda r: abs(math.log(r["Odds Ratio"])), default=None)
    conclusion = (
        f"Nominal (multinomial) logit for {response} with {len(ordered)} level(s), reference '{reference}', n = {spec.rows_used}. "
        f"Model test: chi-square = {g(chi_square, 4)} on {dof} DF, p = {p_text(model_p)}; pseudo R² = {pseudo * 100:.2f}%. "
        + (f"Largest effect: {strongest['Term']} for {strongest['Outcome']}, odds ratio {g(strongest['Odds Ratio'], 4)} (p = {p_text(strongest['P-Value'])})." if strongest else "")
    )
    return {
        "procedure": "nominal_logistic",
        "title": f"Nominal Logistic Regression: {response} versus {', '.join(continuous + categorical)}",
        "method": f"statsmodels MNLogit; one logit per non-reference level against '{reference}'",
        "response": response,
        "reference_level": reference,
        "levels": ordered,
        "n": spec.rows_used,
        "confidence_level": conf,
        "p_value": model_p,
        "tables": tables,
        "highlights": [
            {"label": "Outcome levels", "value": len(ordered), "decimals": 0},
            {"label": "Model P-Value", "value": model_p, "tone": "positive" if (model_p is not None and model_p < 0.05) else None},
            {"label": "Pseudo R-sq", "value": pseudo * 100, "suffix": "%"},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"Nominal Logistic Regression — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 13. Poisson Regression
# ---------------------------------------------------------------------------


def _poisson_regression(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, continuous, categorical, interactions = _model_options(columns, options)
    conf = confidence(options)
    exposure_col = option(options, "exposure_column", None)
    extra = [str(exposure_col)] if exposure_col else []
    spec = _model_frame(df, response, continuous, categorical, what="Poisson Regression", interactions=interactions, extra=extra)

    y = spec.frame[spec.safe[response]].to_numpy(dtype=float)
    if np.any(y < 0) or np.any(y != np.floor(y)):
        raise ProcedureError(f"'{response}' must contain whole, non-negative counts for Poisson regression.")

    offset = None
    if exposure_col:
        exposure = spec.frame[spec.safe[str(exposure_col)]].to_numpy(dtype=float)
        if np.any(exposure <= 0):
            raise ProcedureError(f"Exposure column '{exposure_col}' must be greater than 0 in every used row.")
        offset = np.log(exposure)

    exog, names = _design(spec, continuous, categorical, interactions)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = sm.GLM(y, exog, family=sm.families.Poisson(), offset=offset).fit()
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The Poisson model did not converge: {err}") from err

    conf_int = np.asarray(model.conf_int(alpha=1 - conf))
    coef_rows = _odds_ratio_rows(model.params.values, model.bse.values, model.pvalues.values, conf_int, names, spec, conf, label="Rate Ratio")

    deviance = float(model.deviance)
    pearson = float(model.pearson_chi2)
    dof = int(model.df_resid)
    null_deviance = float(model.null_deviance)
    model_chi = null_deviance - deviance
    model_dof = int(model.df_model)
    model_p = float(st.chi2.sf(model_chi, model_dof)) if model_dof > 0 else None
    dispersion = deviance / dof if dof > 0 else None

    fitted = np.asarray(model.fittedvalues, dtype=float)
    deviance_resid = np.asarray(model.resid_deviance, dtype=float)
    gof_rows = [
        {"Test": "Deviance", "Chi-Square": deviance, "DF": dof, "P-Value": float(st.chi2.sf(deviance, dof)) if dof > 0 else None},
        {"Test": "Pearson", "Chi-Square": pearson, "DF": dof, "P-Value": float(st.chi2.sf(pearson, dof)) if dof > 0 else None},
    ]

    notes = []
    if dispersion is not None and dispersion > 1.5:
        notes.append(f"Deviance/DF is {g(dispersion, 3)} — well above 1, which points at overdispersion; a negative-binomial model would fit better.")
    if exposure_col:
        notes.append(f"log({exposure_col}) is used as an offset, so the coefficients describe rates per unit of {exposure_col}.")

    strongest = max((r for r in coef_rows if r.get("Rate Ratio")), key=lambda r: abs(math.log(r["Rate Ratio"])), default=None)
    conclusion = (
        f"Poisson model for {response}"
        + (f" per unit of {exposure_col}" if exposure_col else "")
        + f" on {len(continuous) + len(categorical)} predictor(s), n = {spec.rows_used}. "
        f"Model test: chi-square = {g(model_chi, 4)} on {model_dof} DF, p = {p_text(model_p)}; deviance/DF = {g(dispersion, 3)}. "
        + (f"Largest effect: {strongest['Term']} with a rate ratio of {g(strongest['Rate Ratio'], 4)} (p = {p_text(strongest['P-Value'])})." if strongest else "")
    )
    return {
        "procedure": "poisson_regression",
        "title": f"Poisson Regression: {response} versus {', '.join(continuous + categorical)}",
        "method": "statsmodels GLM, Poisson family with a log link"
        + (f"; log({exposure_col}) as an offset" if exposure_col else "")
        + (" with all two-way interactions" if interactions else ""),
        "response": response,
        "exposure_column": str(exposure_col) if exposure_col else None,
        "n": spec.rows_used,
        "confidence_level": conf,
        "p_value": model_p,
        "deviance": deviance,
        "dispersion": dispersion,
        "note": " ".join(notes) or None,
        "tables": [
            {"title": "Coefficients and Incidence Rate Ratios", "rows": coef_rows},
            {
                "title": "Model Summary",
                "rows": [{"N": spec.rows_used, "Deviance": deviance, "DF": dof, "Deviance/DF": dispersion, "Null deviance": null_deviance, "Chi-Square (model)": model_chi, "P-Value": model_p, "AIC": float(model.aic)}],
            },
            {"title": "Goodness-of-Fit Tests", "rows": gof_rows},
        ],
        "highlights": [
            {"label": "Model P-Value", "value": model_p, "tone": "positive" if (model_p is not None and model_p < 0.05) else None},
            {"label": "Deviance/DF", "value": dispersion},
            {"label": "N", "value": spec.rows_used, "decimals": 0},
        ],
        "graphs": _residual_graphs(spec, deviance_resid, fitted, label="deviance residual"),
        "conclusion": conclusion,
        "summary": f"Poisson Regression — {conclusion}",
    }


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_HANDLERS = {
    "fitted_line": _fitted_line,
    "fit_model": _fit_model,
    "predict": _predict,
    "best_subsets": _best_subsets,
    "stepwise": _stepwise,
    "nonlinear": _nonlinear,
    "orthogonal": _orthogonal,
    "pls": _pls,
    "stability": _stability,
    "binary_fitted_line": _binary_fitted_line,
    "binary_logistic": _binary_logistic,
    "ordinal_logistic": _ordinal_logistic,
    "nominal_logistic": _nominal_logistic,
    "poisson_regression": _poisson_regression,
}


def compute(df: pd.DataFrame, procedure: str, columns: list[str] | None, options: dict | None) -> dict:
    """Run one Regression procedure. `columns` is ordered [response, *predictors]; `options` holds
    everything else, including `n_continuous` which splits the predictors into continuous and
    categorical without having to guess from dtypes."""
    handler = _HANDLERS.get(procedure)
    if handler is None:
        raise ProcedureError(f"Unknown procedure '{procedure}'. Expected one of: {', '.join(PROCEDURES)}.")
    result = handler(df, list(columns or []), dict(options or {}))
    return json_safe(result)
