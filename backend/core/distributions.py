"""The distribution catalogue, in Minitab's own parameterisation.

One place defines every distribution the app knows, and three features read it: Calc > Random Data
generates from it, Calc > Probability Distributions evaluates it, and Graph > Probability
Distribution Plot draws it. Adding a distribution once makes it appear in all three.

The parameterisation is Minitab's, not scipy's, wherever they differ — a lognormal is given by the
location and scale OF ITS LOG, an exponential by its mean rather than a rate, a Weibull by shape
and scale. `build()` does that translation in one place so nothing else has to know about it.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy import stats as st

from backend.core.procedures import ProcedureError


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    integer: bool = False
    hint: str = ""


@dataclass(frozen=True)
class Distribution:
    id: str
    label: str
    params: tuple[Param, ...]
    discrete: bool
    build: Callable[[dict[str, float]], Any]
    describe: Callable[[dict[str, float]], str]
    # Distributions the plot and the probability dialog cannot handle from parameters alone.
    special: bool = False


def _p(values: dict[str, float], key: str, default: float) -> float:
    raw = values.get(key, default)
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ProcedureError(f"Parameter '{key}' must be a number; got '{raw}'.") from None


def _positive(value: float, what: str) -> float:
    if not (value > 0):
        raise ProcedureError(f"{what} must be greater than 0; got {value:g}.")
    return value


def _probability(value: float, what: str = "Event probability") -> float:
    if not 0 <= value <= 1:
        raise ProcedureError(f"{what} must be between 0 and 1; got {value:g}.")
    return value


def _g(value: float) -> str:
    return f"{value:g}"


# ---------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------


def _normal(v):
    mean, sd = _p(v, "mean", 0.0), _positive(_p(v, "sd", 1.0), "Standard deviation")
    return st.norm(loc=mean, scale=sd)


def _uniform(v):
    lower, upper = _p(v, "lower", 0.0), _p(v, "upper", 1.0)
    if upper <= lower:
        raise ProcedureError(f"Upper endpoint must be greater than the lower endpoint; got {_g(lower)} and {_g(upper)}.")
    return st.uniform(loc=lower, scale=upper - lower)


def _triangular(v):
    lower, mode, upper = _p(v, "lower", 0.0), _p(v, "mode", 0.5), _p(v, "upper", 1.0)
    if not lower <= mode <= upper or upper <= lower:
        raise ProcedureError(f"A triangular distribution needs lower ≤ mode ≤ upper with lower < upper; got {_g(lower)}, {_g(mode)}, {_g(upper)}.")
    return st.triang(c=(mode - lower) / (upper - lower), loc=lower, scale=upper - lower)


def _hypergeom(v):
    population = int(_p(v, "population", 50))
    successes = int(_p(v, "successes", 10))
    draws = int(_p(v, "draws", 10))
    if population < 1 or not 0 <= successes <= population or not 0 <= draws <= population:
        raise ProcedureError(
            f"Hypergeometric needs 0 ≤ event count ({successes}) ≤ population ({population}) and "
            f"0 ≤ sample size ({draws}) ≤ population."
        )
    return st.hypergeom(M=population, n=successes, N=draws)


def _integer(v):
    low, high = int(_p(v, "lower", 0)), int(_p(v, "upper", 10))
    if high < low:
        raise ProcedureError(f"The maximum must not be below the minimum; got {low} and {high}.")
    return st.randint(low=low, high=high + 1)  # scipy's high is exclusive; Minitab's is not


CATALOGUE: dict[str, Distribution] = {}


def _add(dist: Distribution) -> None:
    CATALOGUE[dist.id] = dist


_add(Distribution("normal", "Normal", (Param("mean", "Mean", 0.0), Param("sd", "Standard deviation", 1.0)), False, _normal, lambda v: f"Normal(mean={_g(_p(v,'mean',0))}, sd={_g(_p(v,'sd',1))})"))
_add(Distribution("chi_square", "Chi-Square", (Param("df", "Degrees of freedom", 5.0),), False, lambda v: st.chi2(df=_positive(_p(v, "df", 5.0), "Degrees of freedom")), lambda v: f"Chi-Square(df={_g(_p(v,'df',5))})"))
_add(Distribution("f", "F", (Param("df1", "Numerator degrees of freedom", 5.0), Param("df2", "Denominator degrees of freedom", 10.0)), False, lambda v: st.f(dfn=_positive(_p(v, "df1", 5.0), "Numerator DF"), dfd=_positive(_p(v, "df2", 10.0), "Denominator DF")), lambda v: f"F(df1={_g(_p(v,'df1',5))}, df2={_g(_p(v,'df2',10))})"))
_add(Distribution("t", "t", (Param("df", "Degrees of freedom", 10.0),), False, lambda v: st.t(df=_positive(_p(v, "df", 10.0), "Degrees of freedom")), lambda v: f"t(df={_g(_p(v,'df',10))})"))
_add(Distribution("uniform", "Uniform", (Param("lower", "Lower endpoint", 0.0), Param("upper", "Upper endpoint", 1.0)), False, _uniform, lambda v: f"Uniform({_g(_p(v,'lower',0))}, {_g(_p(v,'upper',1))})"))
_add(Distribution("bernoulli", "Bernoulli", (Param("p", "Event probability", 0.5),), True, lambda v: st.bernoulli(p=_probability(_p(v, "p", 0.5))), lambda v: f"Bernoulli(p={_g(_p(v,'p',0.5))})"))
_add(Distribution("binomial", "Binomial", (Param("n", "Number of trials", 20, integer=True), Param("p", "Event probability", 0.5)), True, lambda v: st.binom(n=int(_positive(_p(v, "n", 20), "Number of trials")), p=_probability(_p(v, "p", 0.5))), lambda v: f"Binomial(n={int(_p(v,'n',20))}, p={_g(_p(v,'p',0.5))})"))
_add(Distribution("geometric", "Geometric", (Param("p", "Event probability", 0.5, hint="Counts trials up to and including the first event."),), True, lambda v: st.geom(p=_probability(_p(v, "p", 0.5))), lambda v: f"Geometric(p={_g(_p(v,'p',0.5))})"))
_add(Distribution("negative_binomial", "Negative Binomial", (Param("p", "Event probability", 0.5), Param("r", "Number of events needed", 3, integer=True)), True, lambda v: st.nbinom(n=int(_positive(_p(v, "r", 3), "Number of events needed")), p=_probability(_p(v, "p", 0.5))), lambda v: f"NegBinomial(p={_g(_p(v,'p',0.5))}, r={int(_p(v,'r',3))})"))
_add(Distribution("hypergeometric", "Hypergeometric", (Param("population", "Population size (N)", 50, integer=True), Param("successes", "Event count in population (M)", 10, integer=True), Param("draws", "Sample size (n)", 10, integer=True)), True, _hypergeom, lambda v: f"Hypergeometric(N={int(_p(v,'population',50))}, M={int(_p(v,'successes',10))}, n={int(_p(v,'draws',10))})"))
_add(Distribution("integer", "Integer", (Param("lower", "Minimum value", 0, integer=True), Param("upper", "Maximum value", 10, integer=True)), True, _integer, lambda v: f"Integer({int(_p(v,'lower',0))} to {int(_p(v,'upper',10))})"))
_add(Distribution("poisson", "Poisson", (Param("mean", "Mean", 4.0),), True, lambda v: st.poisson(mu=_positive(_p(v, "mean", 4.0), "Poisson mean")), lambda v: f"Poisson(mean={_g(_p(v,'mean',4))})"))
_add(Distribution("beta", "Beta", (Param("a", "First shape parameter", 2.0), Param("b", "Second shape parameter", 3.0)), False, lambda v: st.beta(a=_positive(_p(v, "a", 2.0), "First shape parameter"), b=_positive(_p(v, "b", 3.0), "Second shape parameter")), lambda v: f"Beta(a={_g(_p(v,'a',2))}, b={_g(_p(v,'b',3))})"))
_add(Distribution("cauchy", "Cauchy", (Param("location", "Location", 0.0), Param("scale", "Scale", 1.0)), False, lambda v: st.cauchy(loc=_p(v, "location", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale")), lambda v: f"Cauchy(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',1))})"))
_add(Distribution("exponential", "Exponential", (Param("mean", "Mean", 1.0), Param("threshold", "Threshold", 0.0)), False, lambda v: st.expon(loc=_p(v, "threshold", 0.0), scale=_positive(_p(v, "mean", 1.0), "Mean")), lambda v: f"Exponential(mean={_g(_p(v,'mean',1))}, threshold={_g(_p(v,'threshold',0))})"))
_add(Distribution("gamma", "Gamma", (Param("shape", "Shape parameter", 2.0), Param("scale", "Scale parameter", 1.0), Param("threshold", "Threshold", 0.0)), False, lambda v: st.gamma(a=_positive(_p(v, "shape", 2.0), "Shape parameter"), loc=_p(v, "threshold", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale parameter")), lambda v: f"Gamma(shape={_g(_p(v,'shape',2))}, scale={_g(_p(v,'scale',1))})"))
_add(Distribution("laplace", "Laplace", (Param("location", "Location", 0.0), Param("scale", "Scale", 1.0)), False, lambda v: st.laplace(loc=_p(v, "location", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale")), lambda v: f"Laplace(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',1))})"))
_add(Distribution("largest_extreme_value", "Largest Extreme Value", (Param("location", "Location", 0.0), Param("scale", "Scale", 1.0)), False, lambda v: st.gumbel_r(loc=_p(v, "location", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale")), lambda v: f"LargestEV(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',1))})"))
_add(Distribution("logistic", "Logistic", (Param("location", "Location", 0.0), Param("scale", "Scale", 1.0)), False, lambda v: st.logistic(loc=_p(v, "location", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale")), lambda v: f"Logistic(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',1))})"))
# Loglogistic and lognormal are given by the location and scale OF THE LOG, which is Minitab's
# convention and not scipy's — hence exp() on the scale argument.
_add(Distribution("loglogistic", "Loglogistic", (Param("location", "Location (of the log)", 0.0), Param("scale", "Scale (of the log)", 0.5)), False, lambda v: st.fisk(c=1.0 / _positive(_p(v, "scale", 0.5), "Scale"), scale=math.exp(_p(v, "location", 0.0))), lambda v: f"Loglogistic(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',0.5))})"))
_add(Distribution("lognormal", "Lognormal", (Param("location", "Location (of the log)", 0.0), Param("scale", "Scale (of the log)", 1.0)), False, lambda v: st.lognorm(s=_positive(_p(v, "scale", 1.0), "Scale"), scale=math.exp(_p(v, "location", 0.0))), lambda v: f"Lognormal(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',1))})"))
_add(Distribution("smallest_extreme_value", "Smallest Extreme Value", (Param("location", "Location", 0.0), Param("scale", "Scale", 1.0)), False, lambda v: st.gumbel_l(loc=_p(v, "location", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale")), lambda v: f"SmallestEV(loc={_g(_p(v,'location',0))}, scale={_g(_p(v,'scale',1))})"))
_add(Distribution("triangular", "Triangular", (Param("lower", "Lower endpoint", 0.0), Param("mode", "Mode", 0.5), Param("upper", "Upper endpoint", 1.0)), False, _triangular, lambda v: f"Triangular({_g(_p(v,'lower',0))}, {_g(_p(v,'mode',0.5))}, {_g(_p(v,'upper',1))})"))
_add(Distribution("weibull", "Weibull", (Param("shape", "Shape parameter", 2.0), Param("scale", "Scale parameter", 1.0), Param("threshold", "Threshold", 0.0)), False, lambda v: st.weibull_min(c=_positive(_p(v, "shape", 2.0), "Shape parameter"), loc=_p(v, "threshold", 0.0), scale=_positive(_p(v, "scale", 1.0), "Scale parameter")), lambda v: f"Weibull(shape={_g(_p(v,'shape',2))}, scale={_g(_p(v,'scale',1))})"))

# Two that cannot be built from scalar parameters: their "parameters" are columns of the worksheet.
_add(Distribution("discrete", "Discrete", (), True, lambda v: (_ for _ in ()).throw(ProcedureError("A discrete distribution is defined by its value and probability columns.")), lambda v: "Discrete(values, probabilities)", special=True))
_add(Distribution("multivariate_normal", "Multivariate Normal", (), False, lambda v: (_ for _ in ()).throw(ProcedureError("A multivariate normal is defined by a mean vector and a covariance matrix.")), lambda v: "Multivariate Normal", special=True))

# Menu order, matching Minitab's Random Data submenu.
ORDER = (
    "normal",
    "multivariate_normal",
    "chi_square",
    "f",
    "t",
    "uniform",
    "bernoulli",
    "binomial",
    "geometric",
    "negative_binomial",
    "hypergeometric",
    "discrete",
    "integer",
    "poisson",
    "beta",
    "cauchy",
    "exponential",
    "gamma",
    "laplace",
    "largest_extreme_value",
    "logistic",
    "loglogistic",
    "lognormal",
    "smallest_extreme_value",
    "triangular",
    "weibull",
)


def get(name: str) -> Distribution:
    key = str(name or "").lower()
    if key not in CATALOGUE:
        raise ProcedureError(f"Unknown distribution '{name}'. Known distributions: {', '.join(ORDER)}.")
    return CATALOGUE[key]


def frozen(name: str, params: dict[str, float]):
    dist = get(name)
    if dist.special:
        raise ProcedureError(f"{dist.label} needs columns rather than parameters, so it cannot be evaluated here.")
    return dist.build(params or {})


def catalogue_payload() -> list[dict[str, Any]]:
    """What the frontend needs to build the parameter fields for every distribution."""
    return [
        {
            "id": key,
            "label": CATALOGUE[key].label,
            "discrete": CATALOGUE[key].discrete,
            "special": CATALOGUE[key].special,
            "params": [{"key": p.key, "label": p.label, "default": p.default, "integer": p.integer, "hint": p.hint} for p in CATALOGUE[key].params],
        }
        for key in ORDER
    ]
