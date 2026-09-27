"""Run every procedure in the coverage registry and apply the universal invariants to all of them.

This is the test that makes the property checks apply to ALL result schemas rather than to the ones
somebody remembered. `backend/tests/harness.py` runs `check_result_invariants` on the way out of
every `compute()` call, and the registry supplies a working invocation for every procedure the app
dispatches, so a p-value outside [0, 1], a negative standard error, an R² above 1 or a confidence
interval with its bounds the wrong way round fails here no matter which dialog produced it.

It is also the completeness check: `test_every_procedure_is_registered` compares the registry with
the `_HANDLERS` dicts themselves, so adding a procedure without recording how it is validated turns
the suite red. That is what stops VALIDATION.md drifting into fiction.
"""

from __future__ import annotations

import pytest

from backend.core import anova, basic_stats, calc, data_ops, regression_models
from backend.tests import coverage
from backend.tests.properties import InvariantError, check_result_invariants
from backend.tests.tolerance import assert_close

pytestmark = pytest.mark.properties

INVOCABLE = coverage.invocable()
CLEAN = [entry for entry in INVOCABLE if not entry.known_issue]


@pytest.mark.parametrize("entry", CLEAN, ids=[entry.key for entry in CLEAN])
def test_every_result_satisfies_the_universal_invariants(entry: coverage.Entry) -> None:
    """The harness raises `InvariantError` on the way out, so simply running the procedure is the test."""
    result = entry.invoke()
    assert result is not None
    if isinstance(result, dict):
        # Every Stat/Calc procedure returns the same envelope; a missing table list is a bug in
        # itself, because the frontend renderer and the exporters both read it.
        assert "tables" in result or "store_matrix" in result or "store_columns" in result, (
            f"{entry.key} returned neither tables nor a store payload: {sorted(result)}"
        )


@pytest.mark.parametrize("entry", CLEAN, ids=[entry.key for entry in CLEAN])
def test_every_result_is_json_safe(entry: coverage.Entry) -> None:
    """NaN and Infinity are not JSON, and a `.gsp` is JSON. `procedures.json_safe` is supposed to
    have removed them from every payload; this is where that promise is checked end to end."""
    import json

    result = entry.invoke()
    # allow_nan=False is the whole assertion: json.dumps raises ValueError on NaN or Infinity.
    text = json.dumps(result, allow_nan=False, default=str)
    assert len(text) > 2, f"{entry.key} serialised to nothing"


# --- the R-squared scale inconsistency, recorded rather than tolerated ----------------------------

# Three procedures report R-squared as a PERCENTAGE where every other one reports a fraction. The
# arithmetic is right in all three; the scale is not shared, and nothing in the result says which
# scale a given number is on.
PERCENT_SCALE = ["regression_models.pls", "regression_models.best_subsets", "regression_models.stepwise"]


@pytest.mark.parametrize("key", PERCENT_SCALE)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "R-squared is reported as a PERCENTAGE (e.g. 75.99) where fit_model, fitted_line, one_way "
        "and glm all report a fraction (0.7599). On screen the two render differently in the same "
        "session, and report_engine/verdict.py reads `r_squared` straight, so a PLS result's PDF "
        "verdict badge prints 'R2 = 79.366' instead of 'R2 = 0.794'. Fix: divide by 100 in the "
        "result payload and let the highlight's suffix carry the percent, as fit_model does."
    ),
)
def test_r_squared_is_reported_on_the_same_scale_everywhere(key: str) -> None:
    coverage.BY_KEY[key].invoke()


@pytest.mark.parametrize("key", PERCENT_SCALE)
def test_the_r_squared_scale_is_inconsistent_across_three_procedures(key: str) -> None:
    """Pins the defect's shape, so "it fails" cannot drift into "it fails differently".

    The value must still be a correct R-squared once divided by 100 — the bug is the scale, not the
    fit — which separates the two so a real regression could not hide behind this.
    """
    with pytest.raises(InvariantError) as caught:
        coverage.BY_KEY[key].invoke()
    message = str(caught.value)
    assert "R-squared" in message and "exceeds 1" in message, message

    for line in message.splitlines():
        if "R-squared" in line and "exceeds 1" in line:
            value = float(line.split("R-squared")[1].split("exceeds")[0])
            assert 0.0 <= value / 100.0 <= 1.0, f"{key}: {value} is not a percentage either"


def test_the_fraction_scale_procedures_are_the_majority() -> None:
    """The other side of the same coin: the procedures that get it right must stay right."""
    for key in ("regression_models.fit_model", "regression_models.fitted_line", "anova.one_way", "anova.glm"):
        result = coverage.BY_KEY[key].invoke()
        assert 0.0 <= result["r_squared"] <= 1.0, f"{key}: R-squared {result['r_squared']} is not a fraction"


# --- registry completeness ---------------------------------------------------------------------------

DISPATCHED = {
    "basic_stats": set(basic_stats.PROCEDURES),
    "regression_models": set(regression_models.PROCEDURES),
    "anova": set(anova.PROCEDURES),
    "calc": set(calc.PROCEDURES),
}


@pytest.mark.parametrize("module", sorted(DISPATCHED))
def test_every_procedure_is_registered(module: str) -> None:
    """Every procedure the app can dispatch must have a coverage entry — including an honest `none`.

    Without this, a new procedure would appear in the menus and be absent from VALIDATION.md, which
    is the exact failure mode the manifest exists to prevent.
    """
    registered = {entry.procedure for entry in coverage.REGISTRY if entry.module == module}
    missing = DISPATCHED[module] - registered
    extra = registered - DISPATCHED[module]
    assert not missing, (
        f"{module}: {sorted(missing)} are dispatched but not in backend/tests/coverage.py — "
        "add an entry with its validation tier (use tier='none' if it is not validated yet)"
    )
    assert not extra, f"{module}: {sorted(extra)} are registered but no longer dispatched"


def test_every_registry_entry_has_a_menu_path_and_a_valid_tier() -> None:
    for entry in coverage.REGISTRY:
        assert entry.tier in coverage.TIERS, f"{entry.key}: bad tier {entry.tier!r}"
        assert entry.menu and ">" in entry.menu or entry.menu.startswith(("Assistant", "Predictive")), (
            f"{entry.key}: menu path looks wrong ({entry.menu!r})"
        )
        if entry.tier in ("nist", "published"):
            assert entry.sources, f"{entry.key} claims tier {entry.tier} but cites no source"


def test_registry_keys_are_unique() -> None:
    keys = [entry.key for entry in coverage.REGISTRY]
    assert len(keys) == len(set(keys)), f"duplicate keys: {sorted({k for k in keys if keys.count(k) > 1})}"


def test_data_operations_are_all_covered_by_the_invariant_tests() -> None:
    """The Data menu has its own module; this only checks nothing there is forgotten."""
    from backend.tests import test_data_ops_invariants as data_op_tests

    assert set(data_ops.OPERATIONS) == set(data_op_tests.OPERATIONS_COVERED), (
        "Data operations missing from test_data_ops_invariants.OPERATIONS_COVERED: "
        f"{sorted(set(data_ops.OPERATIONS) - set(data_op_tests.OPERATIONS_COVERED))}"
    )


# --- a few invariants worth asserting directly, not just via the walker -------------------------------


def test_the_invariant_walker_actually_catches_what_it_claims_to() -> None:
    """Guards the guard. A property checker that silently passes everything is worse than none.

    Each payload below breaks exactly one universal rule, in the shape a real result would.
    """
    broken = [
        ({"tables": [{"title": "Test", "rows": [{"P-Value": 1.4}]}]}, "probability"),
        ({"tables": [{"title": "Test", "rows": [{"P-Value": -0.2}]}]}, "probability"),
        ({"tables": [{"title": "S", "rows": [{"SE Coef": -1.0}]}]}, "standard error"),
        ({"tables": [{"title": "S", "rows": [{"StDev": -0.5}]}]}, "standard error"),
        ({"tables": [{"title": "M", "rows": [{"R-sq": 1.4}]}]}, "R-squared"),
        ({"tables": [{"title": "M", "rows": [{"95% CI": "(5.0, 1.0)"}]}]}, "confidence interval"),
        ({"graphs": [{"data": {"groups": [{"ci_low": 9.0, "ci_high": 2.0}]}}]}, "above"),
        ({"highlights": [{"label": "P-Value", "value": 2.0}]}, "probability"),
        ({"value": float("inf")}, "infinite"),
    ]
    for payload, expected_fragment in broken:
        with pytest.raises(InvariantError) as caught:
            check_result_invariants(payload, context="synthetic")
        assert expected_fragment in str(caught.value), f"{payload} -> {caught.value}"


def test_the_invariant_walker_does_not_cry_wolf() -> None:
    """The other half: ordinary, correct payloads must pass silently, including the awkward ones.

    A negative adjusted R², an R² carried as a percentage in a highlight, a one-sided interval
    rendered as text and a fractional Welch df are all legitimate and have all been mistaken for
    faults by over-eager checkers.
    """
    fine = [
        {"tables": [{"title": "M", "rows": [{"R-sq": 0.42, "R-sq(adj)": -0.03, "R-sq(pred)": -1.2}]}]},
        {"highlights": [{"label": "R-sq", "value": 99.97, "suffix": "%"}]},
        {"tables": [{"title": "T", "rows": [{"DF": 17.7765, "P-Value": 0.0}]}]},
        {"tables": [{"title": "D", "rows": [{"95% CI for the mean": "1.5 ≤"}]}]},
        {"tables": [{"title": "D", "rows": [{"95% CI": "(-1.0251, 0.65631)"}]}]},
        {"tables": [{"title": "C", "rows": [{"Correlation": -0.97, "P-Value": 1e-300}]}]},
        {"tables": [{"title": "R", "rows": [{"Coef": -3482258.63, "SE Coef": 890420.38}]}]},
    ]
    for payload in fine:
        check_result_invariants(payload, context="synthetic")


def test_confidence_intervals_are_ordered_across_every_procedure() -> None:
    """Spelled out separately from the walker so the rule is visible in the test list, not only in
    the helper — this is one of the four properties the validation plan names explicitly."""
    for entry in CLEAN:
        result = entry.invoke()
        if not isinstance(result, dict):
            continue
        for graph in result.get("graphs") or []:
            for group in (graph.get("data") or {}).get("groups") or []:
                if "ci_low" in group and "ci_high" in group:
                    assert group["ci_low"] <= group["ci_high"], f"{entry.key}: {group}"


def test_reported_r_squared_never_exceeds_one() -> None:
    """Likewise named explicitly. PLS is the one exception and it is recorded above."""
    for entry in CLEAN:
        result = entry.invoke()
        if isinstance(result, dict) and isinstance(result.get("r_squared"), (int, float)):
            assert result["r_squared"] <= 1.0 + 1e-9, f"{entry.key}: R-squared {result['r_squared']}"


def test_every_reported_standard_error_is_non_negative() -> None:
    for entry in CLEAN:
        result = entry.invoke()
        if not isinstance(result, dict):
            continue
        for entry_table in result.get("tables") or []:
            for row in entry_table.get("rows") or []:
                for key, value in row.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        if str(key).strip() in {"SE", "SE Coef", "SE Mean", "SE Fit", "StDev"}:
                            assert value >= 0, f"{entry.key}: {key} = {value}"


def test_the_sweep_covers_a_meaningful_share_of_the_menu() -> None:
    """A sanity floor on the sweep itself: if invocations start silently dropping out, say so."""
    assert len(INVOCABLE) >= 75, f"only {len(INVOCABLE)} procedures are invocable in the registry"
    tiers = coverage.counts_by_tier()
    assert tiers["none"] == 0 or tiers["none"] < len(coverage.REGISTRY) // 4
    assert_close(sum(tiers.values()), len(coverage.REGISTRY), rtol=0, what="tier counts add up")
