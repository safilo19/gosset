"""Published worked examples for the Regression dialogs.

Three sources, each chosen because someone else has already published the answer:

* Anscombe's quartet (1973) — four datasets constructed to share one regression. The paper prints
  the fit, so intercept 3.00 / slope 0.500 / R² 0.667 are quoted values, and the fact that all four
  agree is itself the assertion. It is also the sharpest possible test that a regression routine is
  fitting rather than describing: sets II, III and IV are a parabola, an outlier-driven line and a
  single leverage point, and all three must still come back with the same coefficients.
* Spector & Mazzeo (1980) — statsmodels' own documented Logit example, so the coefficients are
  published output; the odds ratios follow by exponentiation and the fit is re-derived here from a
  longhand IRLS loop.
* Agresti's capital-punishment counts — the log-link Poisson GLM, again re-derived by longhand IRLS.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.tests import reference_impl as ref
from backend.tests.harness import run_basic_stats, run_regression
from backend.tests.refdata import expected, frame
from backend.tests.tolerance import (
    RTOL_ESTIMATE,
    RTOL_ITERATIVE,
    RTOL_PVALUE,
    assert_close,
    coefficients,
    row_where,
    table,
)

pytestmark = pytest.mark.published


# --- Anscombe's quartet ---------------------------------------------------------------------------

ANSCOMBE = "anscombe_quartet"
SETS = [("x1", "y1"), ("x2", "y2"), ("x3", "y3"), ("x4", "y4")]


@pytest.fixture(scope="module")
def anscombe():
    return frame(ANSCOMBE)


@pytest.mark.parametrize("x,y", SETS)
def test_anscombe_all_four_share_the_published_regression(anscombe, x: str, y: str) -> None:
    """Intercept 3.00, slope 0.500, R² 0.667 — for every one of the four, as Anscombe printed them.

    Compared with an absolute tolerance because the paper rounds to 2-3 decimals; asserting to 1e-8
    against a printed 0.667 would be asserting against the rounding, not the fit.
    """
    published = expected(ANSCOMBE)
    atol = published["atol_coefficient"]
    result = run_regression(anscombe, "fitted_line", [y, x], {})
    coefs = coefficients(result)

    assert_close(coefs["Constant"]["Coef"], published["intercept"], rtol=0, atol=atol, what=f"{y} intercept")
    assert_close(coefs[x]["Coef"], published["slope"], rtol=0, atol=atol, what=f"{y} slope")
    assert_close(result["r_squared"], published["r_squared"], rtol=0, atol=published["atol_r_squared"], what=f"{y} R-squared")
    assert_close(coefs[x]["SE Coef"], published["se_slope"], rtol=0, atol=5e-4, what=f"{y} SE(slope)")
    assert_close(coefs[x]["T-Value"], published["t_slope"], rtol=0, atol=atol, what=f"{y} t(slope)")


@pytest.mark.parametrize("x,y", SETS)
def test_anscombe_anova_split_matches_the_published_sums_of_squares(anscombe, x: str, y: str) -> None:
    published = expected(ANSCOMBE)
    atol = published["atol_sum_of_squares"]
    rows = table(run_regression(anscombe, "fitted_line", [y, x], {}), "Analysis of Variance")
    regression_row = row_where(rows, "Source", "Regression")
    error_row = row_where(rows, "Source", "Error")
    assert_close(regression_row["SS"], published["regression_ss"], rtol=0, atol=atol, what=f"{y} SS(reg)")
    assert_close(error_row["SS"], published["residual_ss"], rtol=0, atol=atol, what=f"{y} SS(err)")
    # And exactly, against the longhand split: SS(reg) + SS(err) = SS(total).
    hand = ref.simple_regression(anscombe[x], anscombe[y])
    assert_close(regression_row["SS"], hand["ss_regression"], rtol=RTOL_ESTIMATE, what=f"{y} SS(reg) exact")
    assert_close(error_row["SS"], hand["ss_residual"], rtol=RTOL_ESTIMATE, what=f"{y} SS(err) exact")
    assert_close(
        row_where(rows, "Source", "Total")["SS"], hand["ss_total"], rtol=RTOL_ESTIMATE, what=f"{y} SS(total)"
    )


@pytest.mark.parametrize("x,y", SETS)
def test_anscombe_matches_the_longhand_least_squares_formulas(anscombe, x: str, y: str) -> None:
    """Slope = Sxy/Sxx and the rest, to full precision — where the published values are rounded."""
    hand = ref.simple_regression(anscombe[x], anscombe[y])
    result = run_regression(anscombe, "fitted_line", [y, x], {})
    coefs = coefficients(result)

    assert_close(coefs["Constant"]["Coef"], hand["intercept"], rtol=RTOL_ESTIMATE, what=f"{y} intercept")
    assert_close(coefs[x]["Coef"], hand["slope"], rtol=RTOL_ESTIMATE, what=f"{y} slope")
    assert_close(coefs[x]["SE Coef"], hand["se_slope"], rtol=RTOL_ESTIMATE, what=f"{y} SE(slope)")
    assert_close(coefs["Constant"]["SE Coef"], hand["se_intercept"], rtol=RTOL_ESTIMATE, what=f"{y} SE(intercept)")
    assert_close(result["s"], hand["s"], rtol=RTOL_ESTIMATE, what=f"{y} S")
    assert_close(result["r_squared"], hand["r_squared"], rtol=RTOL_ESTIMATE, what=f"{y} R-squared")
    assert_close(result["p_value"], 2 * float(_t_sf(abs(hand["t_slope"]), 9)), rtol=RTOL_PVALUE, what=f"{y} p")


def _t_sf(t: float, df: int) -> float:
    from scipy import stats as st

    return float(st.t.sf(t, df))


@pytest.mark.parametrize("x,y", SETS)
def test_anscombe_correlation_matches_the_longhand_formula(anscombe, x: str, y: str) -> None:
    """r = Sxy/sqrt(Sxx Syy) and its t test on n-2 df, both written out longhand.

    The matrix table renders each cell as display text ("0.816\\np = 0.00217"); the numbers live in
    the "Pairs, strongest first" table, which is what an export reads, so that is what is asserted.
    """
    r, df, p = ref.pearson_r(anscombe[x], anscombe[y])
    result = run_basic_stats(anscombe, "correlation", [x, y], {})
    pair = table(result, "Pairs, strongest first")[0]

    assert pair["N"] == 11 and df == 9
    assert_close(pair["Correlation"], r, rtol=RTOL_ESTIMATE, what=f"r({x},{y})")
    assert_close(pair["P-Value"], p, rtol=RTOL_PVALUE, what=f"p({x},{y})")
    assert abs(pair["Correlation"]) <= 1.0

    # Anscombe's fourth published identity: all four correlations are 0.816.
    assert abs(pair["Correlation"] - 0.816) < 1e-3


def test_anscombe_quartet_is_the_point_all_four_agree(anscombe) -> None:
    """One assertion for Anscombe's actual claim: four different pictures, one regression."""
    fits = [
        coefficients(run_regression(anscombe, "fitted_line", [y, x], {}))
        for x, y in SETS
    ]
    slopes = [f[x]["Coef"] for f, (x, _) in zip(fits, SETS)]
    intercepts = [f["Constant"]["Coef"] for f in fits]
    assert max(slopes) - min(slopes) < 5e-3, f"slopes should be indistinguishable: {slopes}"
    assert max(intercepts) - min(intercepts) < 5e-3, f"intercepts should be indistinguishable: {intercepts}"


# --- Spector & Mazzeo: binary logistic ----------------------------------------------------------------

SPECTOR = "spector_grades"


@pytest.fixture(scope="module")
def spector():
    return frame(SPECTOR)


def test_logistic_coefficients_match_the_published_output(spector) -> None:
    """statsmodels' documented Logit example: const -13.0213, GPA 2.8261, TUCE 0.0952, PSI 2.3787."""
    published = expected(SPECTOR)
    result = run_regression(spector, "binary_logistic", ["grade", "gpa", "tuce", "psi"], {"n_continuous": 3})
    coefs = coefficients(result)

    for term, value in zip(published["terms"], published["coefficients"]):
        assert_close(coefs[term]["Coef"], value, rtol=RTOL_ITERATIVE, what=f"logit {term}")


def test_logistic_coefficients_match_a_longhand_irls_fit(spector) -> None:
    """Re-derived from McCullagh & Nelder's IRLS definition rather than by calling Logit again."""
    beta = ref.logistic_coefficients(
        [spector["gpa"], spector["tuce"], spector["psi"]], spector["grade"].tolist()
    )
    result = run_regression(spector, "binary_logistic", ["grade", "gpa", "tuce", "psi"], {"n_continuous": 3})
    coefs = coefficients(result)
    for term, value in zip(["Constant", "gpa", "tuce", "psi"], beta):
        assert_close(coefs[term]["Coef"], float(value), rtol=RTOL_ITERATIVE, what=f"logit {term} vs IRLS")


def test_logistic_odds_ratios_are_exp_of_the_coefficients(spector) -> None:
    """An odds ratio that is not exp(coef) is the single most common logistic reporting bug."""
    result = run_regression(spector, "binary_logistic", ["grade", "gpa", "tuce", "psi"], {"n_continuous": 3})
    for term, row in coefficients(result).items():
        if term == "Constant" or "Odds Ratio" not in row:
            continue
        assert_close(row["Odds Ratio"], math.exp(row["Coef"]), rtol=RTOL_ESTIMATE, what=f"OR({term})")
        assert row["Odds Ratio"] > 0


def test_logistic_log_likelihood_and_deviance_agree(spector) -> None:
    """Deviance = -2 * log-likelihood for a binary logit; the two are printed separately."""
    beta = ref.logistic_coefficients(
        [spector["gpa"], spector["tuce"], spector["psi"]], spector["grade"].tolist()
    )
    log_likelihood = ref.logistic_log_likelihood(
        [spector["gpa"], spector["tuce"], spector["psi"]], spector["grade"].tolist(), beta
    )
    result = run_regression(spector, "binary_logistic", ["grade", "gpa", "tuce", "psi"], {"n_continuous": 3})
    summary = table(result, "Model Summary")[0]
    assert_close(summary["Deviance"], -2 * log_likelihood, rtol=RTOL_ITERATIVE, what="deviance")
    assert summary["DF"] == len(spector) - 4


# --- Agresti's capital punishment: Poisson regression ---------------------------------------------------

CPUNISH = "cpunish_executions"
CPUNISH_PREDICTORS = ["income", "perpoverty", "perblack", "vc100k96", "south", "degree"]


@pytest.fixture(scope="module")
def cpunish():
    return frame(CPUNISH)


def test_poisson_regression_matches_a_longhand_irls_fit(cpunish) -> None:
    reference = expected(CPUNISH)
    assert reference["kind"] == "reference-implementation", "this file must not claim a published figure"

    beta = ref.poisson_coefficients([cpunish[c] for c in CPUNISH_PREDICTORS], cpunish["executions"].tolist())
    result = run_regression(
        cpunish, "poisson_regression", ["executions", *CPUNISH_PREDICTORS], {"n_continuous": len(CPUNISH_PREDICTORS)}
    )
    coefs = coefficients(result)
    for term, value in zip(reference["terms"], beta):
        assert_close(coefs[term]["Coef"], float(value), rtol=RTOL_ITERATIVE, what=f"poisson {term} vs IRLS")
        assert_close(coefs[term]["Coef"], reference["coefficients"][reference["terms"].index(term)],
                     rtol=RTOL_ITERATIVE, what=f"poisson {term} vs recorded")


def test_poisson_rate_ratios_are_exp_of_the_coefficients(cpunish) -> None:
    result = run_regression(
        cpunish, "poisson_regression", ["executions", *CPUNISH_PREDICTORS], {"n_continuous": len(CPUNISH_PREDICTORS)}
    )
    for term, row in coefficients(result).items():
        if "Rate Ratio" not in row:
            continue
        assert_close(row["Rate Ratio"], math.exp(row["Coef"]), rtol=RTOL_ESTIMATE, what=f"IRR({term})")


def test_poisson_deviance_matches_the_saturated_model_definition(cpunish) -> None:
    """D = 2 * sum(y log(y/mu) - (y - mu)) — the Poisson deviance, written out."""
    beta = ref.poisson_coefficients([cpunish[c] for c in CPUNISH_PREDICTORS], cpunish["executions"].tolist())
    design = np.column_stack([np.ones(len(cpunish))] + [cpunish[c].to_numpy(float) for c in CPUNISH_PREDICTORS])
    mu = np.exp(design @ beta)
    y = cpunish["executions"].to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(y > 0, y * np.log(y / mu), 0.0) - (y - mu)
    deviance = 2 * float(terms.sum())

    result = run_regression(
        cpunish, "poisson_regression", ["executions", *CPUNISH_PREDICTORS], {"n_continuous": len(CPUNISH_PREDICTORS)}
    )
    assert_close(result["deviance"], deviance, rtol=1e-5, what="Poisson deviance")


# --- variance inflation factors ---------------------------------------------------------------------------


def test_vif_matches_the_longhand_auxiliary_regressions() -> None:
    """VIF_j = 1/(1 - R²_j) from regressing predictor j on the others.

    Fisher's iris is the right test bed: petal length and petal width correlate at about 0.96, so
    their VIFs are large, and a routine that computed the VIF from the wrong auxiliary fit would
    still produce plausible-looking small numbers.
    """
    iris = frame("iris_fisher")
    predictors = ["sepal_width", "petal_length", "petal_width"]
    hand = ref.vif([iris[c] for c in predictors])

    result = run_regression(
        iris, "fit_model", ["sepal_length", *predictors], {"n_continuous": 3, "graph_residuals": False}
    )
    coefs = coefficients(result)
    for name, value in zip(predictors, hand):
        assert "VIF" in coefs[name], "a multi-predictor fit must report VIF"
        assert_close(coefs[name]["VIF"], value, rtol=RTOL_ESTIMATE, what=f"VIF({name})")
        assert value >= 1.0

    assert max(hand) > 10.0, "the petal measurements should show real collinearity"
