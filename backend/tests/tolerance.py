"""The tolerance policy for the whole suite, in one place.

**Compare with RELATIVE tolerance, never with rounded strings.** `round(x, 4) == 1.2346` passes for
a value that is wrong in the fifth digit and fails for one that is right but lands on a tie; it also
hides which digit actually disagreed. Everything here compares `|actual - expected| <= rtol *
|expected| + atol` and reports the achieved relative error when it fails, because "agrees to 11
digits, wanted 15" is the useful sentence.

Three defaults, chosen for what limits each kind of number:

* `RTOL_ESTIMATE = 1e-8` — point estimates from closed-form arithmetic (means, standard deviations,
  regression coefficients, sums of squares). Double precision carries ~15-16 significant digits and
  a well-conditioned closed-form calculation loses only a few, so 8 digits is a floor that a correct
  implementation clears easily while a wrong formula does not.
* `RTOL_PVALUE = 1e-6` — p-values and anything else that comes out of a special-function evaluation
  (incomplete beta/gamma, the studentized range). scipy documents these to roughly this accuracy and
  they are not certified to more by any published source, so a tighter bound would be testing scipy's
  build rather than Gosset's use of it.
* `RTOL_ITERATIVE = 1e-6` — outputs of iterative fits (logistic and Poisson regression via IRLS,
  MixedLM, ARIMA/ETS). These stop at a convergence criterion, so their last digits are a property of
  the optimiser's tolerance, not of the model.

`ATOL_NEAR_ZERO = 1e-12` exists for the handful of certified values that are exactly zero (Wampler's
higher-order coefficients, a lag-1 autocorrelation of 0): relative tolerance is meaningless there.

**Relaxing a tolerance is allowed and must be explained.** The NIST StRD sets are graded by
difficulty on purpose, and the "Higher" ones (Filip, Wampler4, Wampler5, Longley) are designed so
that a naive normal-equations solver loses most of its digits. Where Gosset cannot hit the default,
the test passes an explicit `rtol` **with a comment naming the achieved number of digits** — knowing
and recording the numerical limit is part of validating, and silently widening a bound is not.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

# --- the policy ------------------------------------------------------------------------------

RTOL_ESTIMATE = 1e-8
RTOL_PVALUE = 1e-6
RTOL_ITERATIVE = 1e-6
ATOL_NEAR_ZERO = 1e-12


def relative_error(actual: float, expected: float) -> float:
    """|actual - expected| / |expected|, or the absolute error when expected is 0."""
    actual, expected = float(actual), float(expected)
    if expected == 0.0:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


def digits_agreeing(actual: float, expected: float) -> float:
    """How many significant decimal digits `actual` shares with `expected`.

    Reported in failure messages and in the reduced-precision notes for the hard NIST sets, which is
    the number NIST itself uses to grade a solver ("LRE", log relative error).
    """
    error = relative_error(actual, expected)
    if error == 0.0:
        return math.inf
    if error >= 1.0:
        return 0.0
    return -math.log10(error)


def assert_close(
    actual: Any,
    expected: Any,
    *,
    rtol: float = RTOL_ESTIMATE,
    atol: float = 0.0,
    what: str = "value",
) -> None:
    """Assert `actual == expected` to a relative tolerance, with a message that names the shortfall."""
    if actual is None:
        raise AssertionError(f"{what}: got None, expected {expected!r}")
    actual_f, expected_f = float(actual), float(expected)

    if math.isnan(expected_f):
        assert math.isnan(actual_f), f"{what}: got {actual_f!r}, expected NaN"
        return
    if math.isinf(expected_f):
        assert actual_f == expected_f, f"{what}: got {actual_f!r}, expected {expected_f!r}"
        return
    assert not math.isnan(actual_f), f"{what}: got NaN, expected {expected_f!r}"

    if abs(actual_f - expected_f) <= rtol * abs(expected_f) + atol:
        return
    raise AssertionError(
        f"{what}: got {actual_f!r}, expected {expected_f!r}\n"
        f"  relative error {relative_error(actual_f, expected_f):.3e} exceeds rtol {rtol:.3e}"
        f" (atol {atol:.3e})\n"
        f"  agrees to {digits_agreeing(actual_f, expected_f):.2f} significant digits"
    )


def assert_all_close(
    actual: Sequence[Any],
    expected: Sequence[Any],
    *,
    rtol: float = RTOL_ESTIMATE,
    atol: float = 0.0,
    what: str = "values",
) -> None:
    actual, expected = list(actual), list(expected)
    assert len(actual) == len(expected), f"{what}: got {len(actual)} values, expected {len(expected)}"
    for index, (a, e) in enumerate(zip(actual, expected)):
        assert_close(a, e, rtol=rtol, atol=atol, what=f"{what}[{index}]")


def worst_digits(pairs: Iterable[tuple[float, float]]) -> float:
    """The fewest significant digits any (actual, expected) pair agrees to.

    Used by the reduced-precision NIST tests, which assert a floor and then record what was actually
    achieved so a regression in conditioning shows up as a changed number rather than a silent pass.
    """
    return min((digits_agreeing(a, e) for a, e in pairs), default=math.inf)


# --- pulling numbers out of a result payload ---------------------------------------------------
#
# Every procedure returns the same shape (`tables: [{title, rows}]`, `highlights`, loose scalars),
# so the suite has one set of accessors rather than each test reaching into dictionaries by hand.


def table(result: Mapping[str, Any], title: str) -> list[dict[str, Any]]:
    """The rows of the table whose title starts with `title` (titles carry counts: "... (3 shown)")."""
    for entry in result.get("tables") or []:
        if str(entry.get("title", "")).startswith(title):
            return list(entry.get("rows") or [])
    available = [str(e.get("title")) for e in result.get("tables") or []]
    raise AssertionError(f"no table titled {title!r}; this result has {available}")


def row_where(rows: Sequence[Mapping[str, Any]], key: str, value: Any) -> dict[str, Any]:
    """The single row whose `key` equals `value`, with the near-misses listed when there isn't one."""
    matches = [dict(r) for r in rows if str(r.get(key, "")).strip() == str(value).strip()]
    if len(matches) == 1:
        return matches[0]
    seen = [str(r.get(key)) for r in rows]
    raise AssertionError(f"expected exactly one row with {key}={value!r}, found {len(matches)}; rows have {seen}")


def coefficients(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The Coefficients table keyed by term, for `coefficients(res)["x1"]["Coef"]`."""
    return {str(row["Term"]).strip(): dict(row) for row in table(result, "Coefficients")}
