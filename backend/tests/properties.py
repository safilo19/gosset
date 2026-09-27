"""Invariants every result payload must satisfy, whatever the procedure, input or seed.

Part of the point of a validation suite is the things it can check *without* a reference value. A
p-value outside [0, 1], an R² above 1, a negative standard error or a confidence interval whose
lower bound is above its upper bound are wrong on their face — no citation needed — and they are
exactly the shape of damage a refactor does.

Because every Gosset procedure returns the same envelope (`tables: [{title, rows}]`, `highlights`,
`graphs`, loose scalars), one recursive walker covers all of them. `backend/tests/harness.py` runs
this on the way out of every `compute()` call the suite makes, so the checks apply to ALL result
schemas rather than to the handful someone remembered to annotate.

The rules are keyed on how the app NAMES things, which is stable: "P-Value" is what the Minitab
parity spec makes every table call a p-value, "SE Coef" and "SE Mean" likewise. A rule that cannot
tell what it is looking at stays quiet — a false alarm here would train people to ignore the suite.
"""

from __future__ import annotations

import math
import re
from typing import Any

# A number this far outside a bound is floating-point dust, not a defect. Percentages get the
# same slack scaled up, since they are the same quantity times 100.
_SLOP = 1e-9

_CI_TEXT = re.compile(
    r"^\(\s*(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*\)$"
)


class InvariantError(AssertionError):
    """A result payload violated something that is true of every correct result."""


def _numeric(value: Any) -> float | None:
    """`value` as a float when it is a real number, else None. Booleans are not numbers here."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) else number
    return None


def _normalised(key: str) -> str:
    return re.sub(r"[\s_]+", " ", str(key).strip().lower())


# --- the rules -------------------------------------------------------------------------------


def _is_p_value(key: str) -> bool:
    key = _normalised(key)
    return key in {"p value", "p-value", "pvalue", "p", "adj p value", "adj p-value"} or key.endswith(
        (" p value", " p-value")
    )


def _is_probability(key: str) -> bool:
    key = _normalised(key)
    return key in {"probability", "cumulative probability", "confidence level", "alpha", "r squared", "r-squared"}


def _is_standard_error(key: str) -> bool:
    key = _normalised(key)
    if key in {"se", "se coef", "se mean", "se fit", "std error", "standard error", "stdev", "std dev", "s"}:
        return True
    return key.startswith(("se ", "std error", "standard error", "standard deviation")) or key.endswith(
        (" stdev", " std dev", " standard deviation")
    )


def _is_r_squared(key: str) -> bool:
    key = _normalised(key)
    return key in {
        "r sq",
        "r-sq",
        "r squared",
        "r-squared",
        "r sq(adj)",
        "r-sq(adj)",
        "r squared adj",
        "r sq(pred)",
        "r-sq(pred)",
        "adjusted r squared",
    }


def _is_count(key: str) -> bool:
    key = _normalised(key)
    return key in {"n", "n missing", "count", "observations", "rows", "df", "dof", "degrees of freedom"}


def _is_ci_text(key: str) -> bool:
    key = _normalised(key)
    return " ci" in f" {key}" or key.endswith(("ci", "interval")) or "confidence interval" in key


def _check_leaf(key: str, value: Any, path: str, problems: list[str]) -> None:
    number = _numeric(value)

    if isinstance(value, float) and math.isinf(value):
        problems.append(f"{path}: infinite value")
        return

    if number is None:
        if isinstance(value, str) and _is_ci_text(key):
            match = _CI_TEXT.match(value.strip())
            if match:
                low, high = float(match.group(1)), float(match.group(2))
                if low > high + _SLOP * max(1.0, abs(low)):
                    problems.append(f"{path}: confidence interval lower {low} above upper {high}")
        return

    if _is_p_value(key) or _is_probability(key):
        # R² lives in both lists; it is bounded above by 1 but can go negative for a model fitted
        # without an intercept or predicted (R-sq(pred)), so only the ceiling is universal.
        if _is_r_squared(key) or _normalised(key).startswith("r squared"):
            if number > 1 + _SLOP:
                problems.append(f"{path}: R-squared {number} exceeds 1")
        elif not (-_SLOP <= number <= 1 + _SLOP):
            problems.append(f"{path}: probability {number} outside [0, 1]")
        return

    if _is_r_squared(key):
        # Always a fraction here. Highlights carry R² as a percentage, but they say so with
        # `suffix: "%"`, and the dict branch below divides by 100 before calling this. Inferring
        # "it must be a percentage because it is above 1" would be exactly the wrong rule: it would
        # wave through an R-sq of 1.4 as "1.4%", which is the defect this check exists to find.
        if number > 1 + _SLOP:
            problems.append(f"{path}: R-squared {number} exceeds 1")
        return

    if _is_standard_error(key) and number < -_SLOP:
        problems.append(f"{path}: standard error/deviation {number} is negative")
        return

    if _is_count(key) and number < -_SLOP:
        problems.append(f"{path}: count {number} is negative")


def _walk(node: Any, path: str, problems: list[str]) -> None:
    if isinstance(node, dict):
        # A {"ci_low": .., "ci_high": ..} pair, however it is spelled.
        for low_key, high_key in (("ci_low", "ci_high"), ("lower", "upper"), ("ci_lower", "ci_upper")):
            low, high = _numeric(node.get(low_key)), _numeric(node.get(high_key))
            if low is not None and high is not None and low > high + _SLOP * max(1.0, abs(low)):
                problems.append(f"{path}.{low_key}={low} is above {high_key}={high}")

        # `{"label": "P-Value", "value": 0.03}` — a highlight names itself in a sibling key.
        # `{"label": "R-sq", "value": 99.99, "suffix": "%"}` — a highlight names itself in a sibling
        # key and declares its own scale. That declaration is the ONLY thing that turns a percentage
        # back into a fraction here; nothing is inferred from the magnitude.
        label = node.get("label") or node.get("Statistic")
        if isinstance(label, str) and "value" in node:
            value = node["value"]
            number = _numeric(value)
            if str(node.get("suffix") or "") == "%" and number is not None:
                value = number / 100.0
            _check_leaf(label, value, f"{path}.{label}", problems)

        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(value, (dict, list)):
                _walk(value, child, problems)
            else:
                _check_leaf(str(key), value, child, problems)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _walk(item, f"{path}[{index}]", problems)


def check_result_invariants(result: Any, *, context: str = "result") -> Any:
    """Raise InvariantError if `result` breaks any universal invariant; return it otherwise.

    Returns the payload so it can be used inline: `res = check_result_invariants(compute(...))`.
    """
    problems: list[str] = []
    _walk(result, context, problems)
    if problems:
        raise InvariantError(
            f"{len(problems)} invariant violation(s) in {context}:\n  " + "\n  ".join(sorted(set(problems)))
        )
    return result
