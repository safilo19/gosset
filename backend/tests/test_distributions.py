"""The probability engine: all 26 distributions, at published points and against their own axioms.

Two layers.

**Published table values.** The standard points that appear in every set of statistical tables —
the normal 1.96 and 2.5758, t and chi-square and F percentage points from Fisher & Yates and from
Pearson & Hartley, the binomial and Poisson terms that can be written as exact fractions. These are
numbers a reader can look up, which is what makes them a reference rather than a snapshot.

**Axioms, for every distribution in the catalogue.** A table value can only be quoted for a handful
of points, but the properties below must hold for all 26 at every point, and they are what catches a
mis-transcribed parameterisation:

* `CDF(InvCDF(p)) == p` across a grid of p — the round-trip that a swapped scale/shape parameter
  breaks immediately;
* the CDF is monotone non-decreasing and lands in [0, 1];
* the PDF integrates (or the PMF sums) to 1;
* the PDF is non-negative.

The parameterisation itself is the real risk here. Gosset follows Minitab, not scipy: a lognormal is
given by the location and scale OF ITS LOG, an exponential by its MEAN rather than a rate, a Weibull
by shape and scale. Each of those three gets an explicit test against the value the Minitab
convention implies, because a silently rate-vs-mean exponential passes every axiom above.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import integrate

from backend.core import distributions
from backend.tests.harness import run_calc
from backend.tests.tolerance import RTOL_ESTIMATE, RTOL_PVALUE, assert_close

pytestmark = pytest.mark.published

BLANK = pd.DataFrame({"unused": [0.0]})

# Every distribution that can be evaluated from scalar parameters — the two "special" ones
# (Discrete, Multivariate Normal) are defined by worksheet columns and are excluded by design.
EVALUABLE = [key for key in distributions.ORDER if not distributions.CATALOGUE[key].special]
SPECIAL = [key for key in distributions.ORDER if distributions.CATALOGUE[key].special]


def evaluate(distribution: str, mode: str, x: float, params: dict | None = None) -> float:
    result = run_calc(
        BLANK,
        "probability",
        [],
        {
            "distribution": distribution,
            "mode": mode,
            "parameters": params or _defaults(distribution),
            "input_value": x,
        },
    )
    return float(result["value"])


def _defaults(distribution: str) -> dict[str, float]:
    return {p.key: p.default for p in distributions.CATALOGUE[distribution].params}


# --- the catalogue itself -------------------------------------------------------------------------


def test_the_catalogue_holds_all_twenty_six_distributions() -> None:
    assert len(distributions.ORDER) == 26
    assert set(distributions.ORDER) == set(distributions.CATALOGUE)
    assert len(EVALUABLE) == 24 and len(SPECIAL) == 2


@pytest.mark.parametrize("name", SPECIAL)
def test_special_distributions_refuse_scalar_evaluation_with_a_reason(name: str) -> None:
    """Discrete and Multivariate Normal are defined by columns; the refusal must say so."""
    from backend.core.procedures import ProcedureError

    with pytest.raises(ProcedureError) as caught:
        distributions.frozen(name, {})
    assert "column" in str(caught.value).lower()


# --- published table values -------------------------------------------------------------------------

# (distribution, params, mode, x, expected, source)
TABLE_VALUES = [
    ("normal", {"mean": 0, "sd": 1}, "cdf", 1.959963984540054, 0.975, "the 97.5th normal percentile"),
    ("normal", {"mean": 0, "sd": 1}, "cdf", 2.5758293035489004, 0.995, "the 99.5th normal percentile"),
    ("normal", {"mean": 0, "sd": 1}, "cdf", 0.0, 0.5, "symmetry about the mean"),
    ("normal", {"mean": 0, "sd": 1}, "pdf", 0.0, 0.3989422804014327, "1/sqrt(2*pi)"),
    ("normal", {"mean": 0, "sd": 1}, "icdf", 0.975, 1.959963984540054, "the classic 1.96"),
    ("normal", {"mean": 100, "sd": 15}, "cdf", 130.0, 0.9772498680518208, "two standard deviations"),
    ("t", {"df": 1}, "cdf", 1.0, 0.75, "the t with 1 df is Cauchy: F(1) = 3/4 exactly"),
    ("t", {"df": 10}, "icdf", 0.975, 2.2281388519649385, "the 5% two-sided t point for 10 df, 2.228"),
    ("t", {"df": 30}, "icdf", 0.975, 2.0422724563012373, "2.042 in every t table"),
    ("chi_square", {"df": 1}, "icdf", 0.95, 3.841458820694124, "3.841, the 5% point on 1 df"),
    ("chi_square", {"df": 2}, "cdf", 2.0, 0.6321205588285577, "chi-square on 2 df is exponential: 1 - e^-1"),
    ("chi_square", {"df": 10}, "icdf", 0.95, 18.307038053275146, "18.307 on 10 df"),
    ("f", {"df1": 1, "df2": 1}, "icdf", 0.95, 161.44767639282416, "161.4, the classic F(1,1) 5% point"),
    ("f", {"df1": 3, "df2": 12}, "icdf", 0.95, 3.4902948382268133, "3.49 on (3, 12) df"),
    ("uniform", {"lower": 0, "upper": 1}, "cdf", 0.25, 0.25, "F(x) = x on the unit interval"),
    ("exponential", {"mean": 1, "threshold": 0}, "cdf", 1.0, 0.6321205588285577, "1 - e^-1"),
    ("binomial", {"n": 10, "p": 0.5}, "pdf", 5.0, 0.24609375, "C(10,5)/1024 = 252/1024, exact"),
    ("binomial", {"n": 10, "p": 0.5}, "cdf", 3.0, 0.171875, "176/1024, exact"),
    ("poisson", {"mean": 1}, "pdf", 0.0, 0.36787944117144233, "e^-1"),
    ("poisson", {"mean": 4}, "cdf", 4.0, 0.6288369351798734, "the standard Poisson table entry"),
    ("bernoulli", {"p": 0.3}, "pdf", 1.0, 0.3, "the probability itself"),
    ("geometric", {"p": 0.5}, "pdf", 3.0, 0.125, "(1/2)^3, counting trials to the first event"),
    ("beta", {"a": 1, "b": 1}, "cdf", 0.4, 0.4, "Beta(1,1) is uniform"),
    ("cauchy", {"location": 0, "scale": 1}, "cdf", 1.0, 0.75, "arctan(1)/pi + 1/2 = 3/4"),
    ("laplace", {"location": 0, "scale": 1}, "cdf", 0.0, 0.5, "symmetry"),
    ("logistic", {"location": 0, "scale": 1}, "cdf", 0.0, 0.5, "symmetry"),
    ("triangular", {"lower": 0, "mode": 0.5, "upper": 1}, "cdf", 0.5, 0.5, "the mode of a symmetric triangle"),
    ("weibull", {"shape": 1, "scale": 1, "threshold": 0}, "cdf", 1.0, 0.6321205588285577, "shape 1 is exponential"),
    ("hypergeometric", {"population": 50, "successes": 10, "draws": 10}, "pdf", 0.0, math.comb(40, 10) / math.comb(50, 10), "C(40,10)/C(50,10)"),
    ("integer", {"lower": 1, "upper": 6}, "pdf", 3.0, 1 / 6, "a fair die"),
]


@pytest.mark.parametrize(
    "name,params,mode,x,value,source",
    TABLE_VALUES,
    ids=[f"{c[0]}-{c[2]}-{c[3]:g}" for c in TABLE_VALUES],
)
def test_published_table_value(name: str, params: dict, mode: str, x: float, value: float, source: str) -> None:
    assert_close(evaluate(name, mode, x, params), value, rtol=RTOL_PVALUE, what=f"{name} {mode}({x}) [{source}]")


def test_binomial_terms_match_their_exact_rational_values() -> None:
    """C(10,k)/2^10 is a dyadic rational, exactly representable in binary floating point.

    Gosset does NOT reproduce them bit for bit — scipy evaluates a binomial term through log-gamma,
    so k = 0 comes back as 0.000976562499999999 against an exact 0.0009765625, a difference in the
    last two bits. That is the expected cost of the gamma route and is asserted as such: 1e-12 is
    tight enough that a genuinely wrong term cannot hide, and loose enough not to fail on the two
    bits. The exact values are computed here with `Fraction` rather than typed in.
    """
    from fractions import Fraction

    for k in range(11):
        exact = float(Fraction(math.comb(10, k), 2**10))
        assert_close(
            evaluate("binomial", "pdf", float(k), {"n": 10, "p": 0.5}), exact, rtol=1e-12, what=f"C(10,{k})/1024"
        )
    total = sum(evaluate("binomial", "pdf", float(k), {"n": 10, "p": 0.5}) for k in range(11))
    assert_close(total, 1.0, rtol=1e-12, what="binomial terms sum")


# --- axioms, for every evaluable distribution ---------------------------------------------------------

PROBABILITY_GRID = [0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.999]


@pytest.mark.parametrize("name", EVALUABLE)
def test_cdf_of_inverse_cdf_returns_the_probability(name: str) -> None:
    """The round-trip. For a discrete distribution the inverse is a step function, so the identity
    holds as CDF(InvCDF(p)) >= p with no smaller value doing the same — asserted in that form."""
    discrete = distributions.CATALOGUE[name].discrete
    for p in PROBABILITY_GRID:
        x = evaluate(name, "icdf", p)
        back = evaluate(name, "cdf", x)
        if discrete:
            assert back >= p - 1e-12, f"{name}: CDF(InvCDF({p})) = {back} < {p}"
            below = evaluate(name, "cdf", x - 1)
            assert below < p + 1e-12, f"{name}: InvCDF({p}) = {x} is not the smallest such value"
        else:
            assert_close(back, p, rtol=1e-7, what=f"{name} CDF(InvCDF({p}))")


@pytest.mark.parametrize("name", EVALUABLE)
def test_cdf_is_monotone_and_bounded(name: str) -> None:
    """Evaluated on integers for a discrete distribution and on a fine grid for a continuous one.

    The integer restriction is not a dodge — a discrete CDF is only defined as a step function, and
    scipy's hypergeometric returns NaN between the steps (pinned separately below).
    """
    frozen = distributions.frozen(name, _defaults(name))
    low, high = float(frozen.ppf(1e-6)), float(frozen.ppf(1 - 1e-6))
    if distributions.CATALOGUE[name].discrete:
        grid = [float(k) for k in range(int(low) - 2, int(high) + 3)]
    else:
        grid = list(np.linspace(low - 1, high + 1, 60))

    previous = -np.inf
    for x in grid:
        value = evaluate(name, "cdf", float(x))
        assert value is not None and not math.isnan(value), f"{name}: CDF({x}) came back as {value}"
        assert -1e-12 <= value <= 1 + 1e-12, f"{name}: CDF({x}) = {value} is not a probability"
        assert value >= previous - 1e-12, f"{name}: CDF decreased at x = {x}"
        previous = value


@pytest.mark.xfail(
    strict=True,
    reason=(
        "scipy's hypergeom.cdf returns NaN for a non-integer argument, where binom and poisson floor "
        "it. Gosset passes the user's value straight through, so Calc > Probability Distributions > "
        "Hypergeometric with a cumulative probability at x = 3.3 shows a blank cell instead of F(3). "
        "Every other discrete distribution in the catalogue handles it. Fix: floor the input for a "
        "discrete CDF in calc.py::_probability."
    ),
)
def test_hypergeometric_cdf_handles_a_non_integer_argument() -> None:
    value = evaluate("hypergeometric", "cdf", 3.3, {"population": 50, "successes": 10, "draws": 10})
    step = evaluate("hypergeometric", "cdf", 3.0, {"population": 50, "successes": 10, "draws": 10})
    assert value is not None and not math.isnan(value)
    assert_close(value, step, rtol=1e-12, what="hypergeometric CDF at 3.3")


@pytest.mark.parametrize("name", [n for n in EVALUABLE if distributions.CATALOGUE[n].discrete and n != "hypergeometric"])
def test_other_discrete_cdfs_floor_a_non_integer_argument(name: str) -> None:
    """The behaviour the hypergeometric is missing, on every distribution that has it."""
    at_fraction = evaluate(name, "cdf", 2.5)
    at_integer = evaluate(name, "cdf", 2.0)
    assert at_fraction is not None and not math.isnan(at_fraction)
    assert_close(at_fraction, at_integer, rtol=1e-12, what=f"{name} CDF floors 2.5 to 2")


@pytest.mark.parametrize("name", EVALUABLE)
def test_density_is_non_negative(name: str) -> None:
    frozen = distributions.frozen(name, _defaults(name))
    for p in (0.01, 0.25, 0.5, 0.75, 0.99):
        x = float(frozen.ppf(p))
        assert evaluate(name, "pdf", x) >= -1e-15, f"{name}: negative density at {x}"


@pytest.mark.parametrize("name", EVALUABLE)
def test_density_integrates_to_one(name: str) -> None:
    """Numerically for the continuous ones, as an exact sum for the discrete ones.

    This is the property that catches a parameterisation translated wrongly: a scipy `scale` fed a
    Minitab "scale of the log" still produces a valid-looking curve, but one whose mass is somewhere
    else entirely — and the round-trip test above would still pass, because it is self-consistent.
    """
    catalogue_entry = distributions.CATALOGUE[name]
    frozen = distributions.frozen(name, _defaults(name))

    if catalogue_entry.discrete:
        low, high = int(frozen.ppf(1e-12)), int(frozen.ppf(1 - 1e-12))
        total = sum(evaluate(name, "pdf", float(k)) for k in range(low, high + 1))
        assert_close(total, 1.0, rtol=1e-8, what=f"{name} PMF sum over [{low}, {high}]")
        return

    # Integrate between the p and 1-p quantiles and expect exactly the 1 - 2p of mass that lies
    # between them. Integrating "everything" is not an option for the Cauchy, whose 1e-9 quantiles
    # are at +/-3e8 and whose density there is small enough that quad reports divergence.
    tail = 1e-4
    low, high = float(frozen.ppf(tail)), float(frozen.ppf(1 - tail))
    total, error = integrate.quad(lambda x: evaluate(name, "pdf", float(x)), low, high, limit=400)
    assert_close(
        total, 1 - 2 * tail, rtol=max(1e-6, 10 * error), what=f"{name} PDF integral over [{low:g}, {high:g}]"
    )


@pytest.mark.parametrize("name", EVALUABLE)
def test_cdf_agrees_with_the_integral_of_the_pdf(name: str) -> None:
    """F(b) - F(a) must equal the area under f between a and b. Ties the two modes together."""
    catalogue_entry = distributions.CATALOGUE[name]
    frozen = distributions.frozen(name, _defaults(name))
    a, b = float(frozen.ppf(0.2)), float(frozen.ppf(0.7))

    if catalogue_entry.discrete:
        low, high = int(math.ceil(a)), int(math.floor(b))
        total = sum(evaluate(name, "pdf", float(k)) for k in range(low, high + 1))
        assert_close(
            evaluate(name, "cdf", float(high)) - evaluate(name, "cdf", float(low - 1)),
            total,
            rtol=1e-9,
            what=f"{name} CDF difference vs PMF sum",
        )
        return

    area, error = integrate.quad(lambda x: evaluate(name, "pdf", float(x)), a, b, limit=200)
    assert_close(
        evaluate(name, "cdf", b) - evaluate(name, "cdf", a),
        area,
        rtol=max(1e-7, 10 * error),
        what=f"{name} CDF difference vs PDF integral",
    )


# --- the Minitab parameterisation, where it differs from scipy's -------------------------------------


def test_exponential_is_parameterised_by_its_mean_not_its_rate() -> None:
    """Minitab's exponential takes the MEAN. With mean = 4, the median is 4*ln(2) = 2.7726.

    A rate-parameterised implementation would put the median at ln(2)/4 = 0.173 and would still pass
    every axiom above, because it would be a perfectly valid exponential — just the wrong one.
    """
    median = evaluate("exponential", "icdf", 0.5, {"mean": 4, "threshold": 0})
    assert_close(median, 4 * math.log(2), rtol=RTOL_ESTIMATE, what="exponential median")
    assert_close(evaluate("exponential", "cdf", 4.0, {"mean": 4, "threshold": 0}), 1 - math.exp(-1), rtol=RTOL_ESTIMATE, what="F(mean)")


def test_exponential_threshold_shifts_the_distribution() -> None:
    shifted = evaluate("exponential", "cdf", 6.0, {"mean": 4, "threshold": 2})
    assert_close(shifted, 1 - math.exp(-1), rtol=RTOL_ESTIMATE, what="shifted exponential")
    assert evaluate("exponential", "cdf", 1.0, {"mean": 4, "threshold": 2}) == 0.0


def test_lognormal_is_parameterised_by_the_location_and_scale_of_its_log() -> None:
    """Minitab's convention. With location 1 and scale 0.5, log(X) ~ Normal(1, 0.5), so the median
    of X is exp(1) and P(X <= exp(1 + 0.5)) = 0.8413."""
    location, scale = 1.0, 0.5
    params = {"location": location, "scale": scale}
    assert_close(evaluate("lognormal", "icdf", 0.5, params), math.exp(location), rtol=RTOL_ESTIMATE, what="lognormal median")
    assert_close(
        evaluate("lognormal", "cdf", math.exp(location + scale), params),
        0.8413447460685429,
        rtol=RTOL_PVALUE,
        what="lognormal at one log-sd above",
    )


def test_loglogistic_is_parameterised_the_same_way() -> None:
    location = 2.0
    assert_close(
        evaluate("loglogistic", "icdf", 0.5, {"location": location, "scale": 0.5}),
        math.exp(location),
        rtol=RTOL_ESTIMATE,
        what="loglogistic median",
    )


def test_weibull_takes_shape_and_scale_with_shape_one_being_exponential() -> None:
    for scale in (1.0, 3.5):
        assert_close(
            evaluate("weibull", "cdf", scale, {"shape": 1, "scale": scale, "threshold": 0}),
            1 - math.exp(-1),
            rtol=RTOL_ESTIMATE,
            what=f"Weibull(1, {scale}) at its scale",
        )
    # Shape 2 is Rayleigh: F(scale) is still 1 - e^-1, which is the definition of the scale.
    assert_close(
        evaluate("weibull", "cdf", 2.0, {"shape": 2, "scale": 2, "threshold": 0}),
        1 - math.exp(-1),
        rtol=RTOL_ESTIMATE,
        what="Weibull(2, 2) at its scale",
    )


def test_integer_distribution_includes_both_endpoints() -> None:
    """scipy's `randint` upper bound is exclusive and Minitab's is not — an off-by-one that would
    make a six-sided die produce fives at best."""
    for face in range(1, 7):
        assert_close(evaluate("integer", "pdf", float(face), {"lower": 1, "upper": 6}), 1 / 6, rtol=1e-12, what=f"die face {face}")
    assert evaluate("integer", "pdf", 7.0, {"lower": 1, "upper": 6}) == 0.0
    assert_close(evaluate("integer", "cdf", 6.0, {"lower": 1, "upper": 6}), 1.0, rtol=1e-12, what="die CDF at 6")


def test_geometric_counts_trials_including_the_first_event() -> None:
    """Minitab's geometric has support {1, 2, 3, ...}, not {0, 1, 2, ...}."""
    assert evaluate("geometric", "pdf", 0.0, {"p": 0.5}) == 0.0
    assert_close(evaluate("geometric", "pdf", 1.0, {"p": 0.5}), 0.5, rtol=1e-12, what="P(first trial)")
    assert distributions.CATALOGUE["geometric"].params[0].hint, "the convention must be stated in the dialog"


# --- input validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize("p", [-0.1, 1.5])
def test_inverse_cdf_rejects_a_probability_outside_zero_to_one(p: float) -> None:
    from backend.core.procedures import ProcedureError

    with pytest.raises(ProcedureError) as caught:
        evaluate("normal", "icdf", p)
    assert "between 0 and 1" in str(caught.value)


@pytest.mark.parametrize(
    "name,params",
    [
        ("normal", {"mean": 0, "sd": 0}),
        ("normal", {"mean": 0, "sd": -1}),
        ("uniform", {"lower": 5, "upper": 5}),
        ("binomial", {"n": 10, "p": 1.5}),
        ("triangular", {"lower": 0, "mode": 2, "upper": 1}),
        ("hypergeometric", {"population": 10, "successes": 20, "draws": 5}),
    ],
)
def test_impossible_parameters_are_refused_with_an_actionable_message(name: str, params: dict) -> None:
    from backend.core.procedures import ProcedureError

    with pytest.raises(ProcedureError) as caught:
        distributions.frozen(name, params)
    message = str(caught.value)
    assert message.endswith(".") and len(message) > 20, f"unhelpful refusal: {message!r}"


def test_the_catalogue_payload_matches_the_catalogue() -> None:
    """One source of truth: Random Data and Probability Distributions read the same list, so the
    payload the frontend builds its fields from cannot drift from what the backend will accept."""
    payload = distributions.catalogue_payload()
    assert [entry["id"] for entry in payload] == list(distributions.ORDER)
    for entry in payload:
        catalogue_entry = distributions.CATALOGUE[entry["id"]]
        assert entry["discrete"] == catalogue_entry.discrete
        assert entry["special"] == catalogue_entry.special
        assert [p["key"] for p in entry["params"]] == [p.key for p in catalogue_entry.params]
