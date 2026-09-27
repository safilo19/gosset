"""NIST StRD Linear Least Squares against Stat > Regression > Fit Regression Model.

Eleven certified sets, graded by NIST from Lower to Higher difficulty. The Higher ones are the point
of the collection: Longley is the near-collinear economic series that broke the regression routines
of the 1960s, and Filip is a degree-10 polynomial whose design matrix has a condition number around
1e15 — several well-known packages decline to fit it at all.

Gosset fits through statsmodels' OLS, which solves with a pseudo-inverse (SVD). That is stable
enough for eight of the nine fittable sets and *not* enough for Filip, where the SVD's default rank
cut-off discards a singular value, the model silently loses a degree of freedom, and the returned
coefficients are a minimum-norm solution rather than the least-squares one. That is recorded below
as a strict xfail plus a test that pins the failure MODE, not papered over with a loose tolerance —
NIST's grading exists so a package can say where its arithmetic stops, and this is where Gosset's
stops.

Every reduced-precision allowance carries the number of significant digits measured on this build,
and `test_reduced_precision_notes_are_honest` keeps those numbers within two digits of reality so a
stale note cannot quietly become a tolerance that tests nothing.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.tests.harness import run_regression
from backend.tests.nist.strd import REGRESSION_SETS, regression
from backend.tests.tolerance import (
    RTOL_ESTIMATE,
    assert_close,
    coefficients,
    digits_agreeing,
    row_where,
    table,
    worst_digits,
)

pytestmark = pytest.mark.nist

# NoInt1 and NoInt2 certify a model with NO constant term (y = B1*x). Gosset's Fit Regression Model
# always includes one — Minitab's "Fit intercept" checkbox has no equivalent — so those two sets
# cannot be run against their certified values at all. They are downloaded and parsed anyway so the
# gap is visible here and in VALIDATION.md; `test_no_intercept_is_a_known_gap` proves the option is
# still absent and will fail the day it lands, which is when to wire the certified values up.
NO_INTERCEPT = {"NoInt1", "NoInt2"}

# Filip is not merely imprecise here — it is wrong. See FILIP_REASON and the pinning test below.
FILIP_REASON = (
    "statsmodels' pinv solve treats Filip's design matrix as rank 10 of 11, so the fit silently "
    "drops a degree of freedom and returns a minimum-norm solution: 0 correct digits in every "
    "coefficient, R-squared wrong in the 3rd digit, and no warning to the user. A QR solve of the "
    "same matrix recovers ~7.9 digits, so this is the solver's rank cut-off, not the data."
)

FITTABLE = [
    pytest.param(name, difficulty, marks=[pytest.mark.xfail(strict=True, reason=FILIP_REASON)])
    if name == "Filip"
    else pytest.param(name, difficulty)
    for name, difficulty in REGRESSION_SETS
    if name not in NO_INTERCEPT
]

# REDUCED PRECISION, three sets. Measured on this build (Python 3.11.15, numpy 2.4.6,
# statsmodels 0.14.6, scipy 1.17.1); each rtol sits an order of magnitude below the measured
# agreement so a differently-built BLAS cannot turn a correct answer red.
#
#   Pontius   — an uncentred quadratic in x ~ 1e6, so x^2 ~ 1e12: the SVD solve returns 6.2 correct
#               digits on the intercept where a QR solve of the same matrix returns 12.2.
#   Wampler4  — y = 1 + x + ... + x^5 with noise of amplitude 1e4 added on purpose.
#   Wampler5  — the same with noise of 1e6; the signal is swamped by construction.
#
# Only the coefficients need the allowance. Their standard deviations, the residual SD, R² and F are
# all ratios or aggregates, are far better conditioned, and clear the default 1e-8 on every set.
COEFFICIENT_RTOL = {
    "Pontius": 1e-6,
    "Wampler4": 1e-7,
    "Wampler5": 1e-5,
}

# Worst-coefficient agreement in significant digits, measured, asserted as a floor. Most sit at the
# number VALIDATION.md quotes for this build. The two most ill-conditioned sets — Wampler4 and
# Wampler5, whose signal is swamped by 1e4/1e6 noise on purpose — are the exception: a Linux BLAS
# reaches ~7.85 and ~5.85 digits where this build reaches ~8.03 and ~6.04, so their floors carry a
# ~1-digit margin below the measured agreement, exactly as COEFFICIENT_RTOL does, so a
# differently-built BLAS cannot turn a correct answer red. `test_reduced_precision_notes_are_honest`
# still holds each floor within four digits of what the build actually achieves.
COEFFICIENT_DIGIT_FLOOR = {
    "Norris": 12.0,
    "Pontius": 6.0,
    "Longley": 10.0,
    "Wampler1": 9.0,
    "Wampler2": 10.0,
    "Wampler3": 9.0,
    "Wampler4": 7.0,
    "Wampler5": 5.0,
}

# Wampler1 and Wampler2 fit their polynomial exactly: NIST certifies a residual SS of 0 and prints
# the F statistic as the word "Infinity". Nothing about them can be compared relatively.
EXACT_FIT = {"Wampler1", "Wampler2"}


def _fit(name: str):
    dataset = regression(name)
    frame = dataset.frame
    predictors = [column for column in frame.columns if column != "y"]
    result = run_regression(
        frame,
        "fit_model",
        ["y", *predictors],
        {"n_continuous": len(predictors), "graph_residuals": False},
    )
    return dataset, result, ["Constant", *predictors]


@pytest.mark.parametrize("name,difficulty", FITTABLE)
def test_certified_coefficients(name: str, difficulty: str) -> None:
    dataset, result, terms = _fit(name)
    coefs = coefficients(result)
    assert list(coefs) == terms, f"{name}: unexpected term list {list(coefs)}"

    rtol = COEFFICIENT_RTOL.get(name, RTOL_ESTIMATE)
    pairs = []
    for term, certified in zip(terms, dataset.coefficients):
        got = coefs[term]["Coef"]
        assert_close(got, certified, rtol=rtol, what=f"{name} {term}")
        pairs.append((got, certified))

    floor = COEFFICIENT_DIGIT_FLOOR.get(name)
    if floor is not None:
        achieved = worst_digits(pairs)
        assert achieved >= floor, f"{name}: coefficients agree to only {achieved:.2f} digits (floor {floor})"


@pytest.mark.parametrize("name,difficulty", FITTABLE)
def test_certified_coefficient_standard_deviations(name: str, difficulty: str) -> None:
    dataset, result, terms = _fit(name)
    coefs = coefficients(result)

    if name in EXACT_FIT:
        # An exact fit has certified SDs of 0, so a relative comparison is meaningless; what matters
        # is that Gosset reports something negligible beside the coefficients themselves.
        scale = max(abs(c) for c in dataset.coefficients)
        for term in terms:
            assert abs(coefs[term]["SE Coef"]) < 1e-6 * scale, f"{name} {term}: SE should be ~0 for an exact fit"
        return

    for term, certified in zip(terms, dataset.coefficient_sds):
        assert_close(coefs[term]["SE Coef"], certified, rtol=RTOL_ESTIMATE, what=f"{name} SE({term})")


@pytest.mark.parametrize("name,difficulty", FITTABLE)
def test_certified_residual_standard_deviation(name: str, difficulty: str) -> None:
    dataset, result, _ = _fit(name)
    if name in EXACT_FIT:
        assert abs(result["s"]) < 1e-6, f"{name}: residual SD should be ~0, got {result['s']}"
        return
    assert_close(result["s"], dataset.residual_sd, rtol=RTOL_ESTIMATE, what=f"{name} residual SD")


@pytest.mark.parametrize("name,difficulty", FITTABLE)
def test_certified_r_squared(name: str, difficulty: str) -> None:
    dataset, result, _ = _fit(name)
    assert_close(result["r_squared"], dataset.r_squared, rtol=RTOL_ESTIMATE, what=f"{name} R-squared")


@pytest.mark.parametrize("name,difficulty", FITTABLE)
def test_certified_anova_table(name: str, difficulty: str) -> None:
    dataset, result, terms = _fit(name)
    rows = table(result, "Analysis of Variance")
    regression_row = row_where(rows, "Source", "Regression")
    error_row = row_where(rows, "Source", "Error")

    assert regression_row["DF"] == dataset.regression_df
    assert error_row["DF"] == dataset.residual_df

    assert_close(regression_row["Adj SS"], dataset.regression_ss, rtol=RTOL_ESTIMATE, what=f"{name} regression SS")
    assert_close(regression_row["Adj MS"], dataset.regression_ms, rtol=RTOL_ESTIMATE, what=f"{name} regression MS")

    if name in EXACT_FIT:
        assert math.isinf(dataset.f_statistic)
        assert error_row["Adj SS"] < 1e-6 * regression_row["Adj SS"], f"{name}: residual SS should be ~0"
        return

    assert_close(error_row["Adj SS"], dataset.residual_ss, rtol=RTOL_ESTIMATE, what=f"{name} residual SS")
    assert_close(error_row["Adj MS"], dataset.residual_ms, rtol=RTOL_ESTIMATE, what=f"{name} residual MS")
    assert_close(regression_row["F-Value"], dataset.f_statistic, rtol=RTOL_ESTIMATE, what=f"{name} F")


@pytest.mark.parametrize("name", sorted(COEFFICIENT_DIGIT_FLOOR))
def test_reduced_precision_notes_are_honest(name: str) -> None:
    """The recorded floors must be reachable but not trivially so.

    A floor far below what the code achieves is a floor that has stopped testing anything, and a
    documented "6 digits" that is really 13 misrepresents the engine in VALIDATION.md. Keeping each
    number within four digits of reality makes drift in either direction fail.
    """
    dataset, result, terms = _fit(name)
    coefs = coefficients(result)
    achieved = worst_digits([(coefs[t]["Coef"], c) for t, c in zip(terms, dataset.coefficients)])
    floor = COEFFICIENT_DIGIT_FLOOR[name]
    assert floor <= achieved <= floor + 4.0, (
        f"{name}: documented floor {floor} but the fit achieves {achieved:.2f} digits — "
        "update COEFFICIENT_DIGIT_FLOOR and the note in VALIDATION.md"
    )


# --- the two documented gaps -------------------------------------------------------------------


def test_filip_rank_deficiency_is_the_known_failure() -> None:
    """Pin Filip's failure MODE, so "we can't fit it" cannot decay into "we don't know why".

    The xfail markers above record that Filip's certified values are not met. This records the
    reason: the model comes back with one degree of freedom missing. That is a user-visible defect
    independent of any tolerance — an 11-term model reported as a 10-term one, with no warning — and
    if it is ever fixed this test fails and the xfails become real passes.
    """
    dataset, result, terms = _fit("Filip")
    rows = table(result, "Analysis of Variance")
    reported_df = row_where(rows, "Source", "Regression")["DF"]

    assert dataset.n_parameters == 11
    assert reported_df == 9, (
        f"Filip now reports {reported_df} regression DF (certified: {dataset.regression_df}). "
        "If the solver was changed, drop the xfail markers and re-measure the digit floors."
    )

    # And the arithmetic that proves it is the solver, not the data: a QR solve of the identical
    # design matrix recovers the certified coefficients to ~8 digits.
    frame = dataset.frame
    design = np.column_stack([np.ones(len(frame))] + [frame[t].to_numpy(float) for t in terms[1:]])
    q, r = np.linalg.qr(design)
    beta = np.linalg.solve(r, q.T @ frame["y"].to_numpy(float))
    achieved = worst_digits(list(zip(beta, dataset.coefficients)))
    assert achieved >= 7.0, f"QR only reaches {achieved:.2f} digits on Filip — revisit FILIP_REASON"


def test_no_intercept_is_a_known_gap() -> None:
    """NoInt1/NoInt2 certify a through-the-origin fit that Gosset cannot be asked for.

    Proven behaviourally rather than by reading the source: pass an intercept-suppressing option
    under every spelling and the Constant term is still there, because nothing reads it.
    """
    dataset = regression("NoInt1")
    frame = dataset.frame
    for spelling in ("fit_intercept", "intercept", "no_intercept", "through_origin"):
        result = run_regression(
            frame,
            "fit_model",
            ["y", "x1"],
            {"n_continuous": 1, "graph_residuals": False, spelling: False},
        )
        assert "Constant" in coefficients(result), (
            f"'{spelling}' now suppresses the intercept — validate it against the certified "
            "NoInt1/NoInt2 values and move them out of NO_INTERCEPT"
        )


def test_norris_reaches_full_double_precision() -> None:
    """The Lower-difficulty benchmark: nothing about Norris should cost any digits.

    This is the canary for the solver. If someone moves the fit to normal equations, the Higher sets
    fail loudly — but Norris would degrade quietly from ~13 digits to ~9 and still pass a 1e-8
    tolerance. Asserting the floor is what catches that.
    """
    dataset, result, terms = _fit("Norris")
    coefs = coefficients(result)
    achieved = worst_digits([(coefs[t]["Coef"], c) for t, c in zip(terms, dataset.coefficients)])
    assert achieved >= 12.0, f"Norris coefficients agree to only {achieved:.2f} digits"
    assert digits_agreeing(result["r_squared"], dataset.r_squared) >= 14.0
