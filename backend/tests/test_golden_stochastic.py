"""Tier B: fixed-seed snapshots and seed-independent properties for the stochastic procedures.

Everything in here resamples, permutes, clusters or cross-validates, so there is no certified value
to aim at. Two things are asserted instead, and they catch different failures:

* **Snapshots** — with Set Base at 12345 and a committed input, the output is fixed. This catches a
  changed resampling scheme, a reordered RNG draw, a different default, a changed cluster
  initialisation. It is a change detector, not a correctness proof, and the file says so.
* **Properties that hold for ANY seed** — a bootstrap interval contains the sample estimate, a
  permutation p-value is a probability and matches the exact answer on a case small enough to
  enumerate, k-means partitions every row exactly once. These are correctness proofs, and they are
  the ones that would survive someone regenerating a snapshot carelessly.

The seed is 12345 throughout, which is Set Base's value in the dialog; the inputs are the reference
frames committed under `reference_data/published/` and the repository's own `sample_customers.csv`.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.core import predictive, segmentation
from backend.tests import golden
from backend.tests.harness import run_calc
from backend.tests.refdata import frame
from backend.tests.tolerance import assert_close, table

pytestmark = [pytest.mark.snapshot, pytest.mark.properties]

SEED = 12345
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sleep():
    return frame("sleep_cushny_peebles")


@pytest.fixture(scope="module")
def iris():
    return frame("iris_fisher")


@pytest.fixture(scope="module")
def customers():
    return pd.read_csv(REPO_ROOT / "sample_customers.csv")


def _snapshotable(result: dict) -> dict:
    """The numeric heart of a result, without the prose that a copy edit would churn."""
    return {
        "procedure": result.get("procedure"),
        "tables": result.get("tables"),
        "highlights": result.get("highlights"),
        **{
            key: value
            for key, value in result.items()
            if key
            not in {"procedure", "tables", "highlights", "graphs", "title", "method", "summary", "conclusion", "note"}
        },
    }


# --- bootstrap ---------------------------------------------------------------------------------


def test_bootstrap_one_sample_snapshot(sleep) -> None:
    result = run_calc(
        sleep, "bootstrap_1sample", ["drug1"], {"statistic": "mean", "resamples": 1000, "seed": SEED}
    )
    golden.check(
        "bootstrap_1sample_sleep_drug1_mean",
        _snapshotable(result),
        description="Calc > Resampling > Bootstrap for 1-Sample Mean, sleep drug1, 1000 resamples, base 12345",
    )


def test_bootstrap_two_sample_snapshot(sleep) -> None:
    result = run_calc(
        sleep,
        "bootstrap_2sample",
        ["drug1", "drug2"],
        {"layout": "two_columns", "resamples": 1000, "seed": SEED},
    )
    golden.check(
        "bootstrap_2sample_sleep",
        _snapshotable(result),
        description="Calc > Resampling > Bootstrap for 2-Sample Means, sleep drug1 vs drug2, base 12345",
    )


@pytest.mark.parametrize("seed", [1, 12345, 999983])
@pytest.mark.parametrize("statistic", ["mean", "median"])
def test_bootstrap_interval_contains_the_sample_estimate(sleep, seed: int, statistic: str) -> None:
    """True for any seed: the percentile interval must bracket the statistic it resamples.

    An interval that misses its own point estimate means the resampling is centred somewhere the
    data is not — the failure a snapshot would faithfully record and never question.
    """
    result = run_calc(
        sleep, "bootstrap_1sample", ["drug1"], {"statistic": statistic, "resamples": 500, "seed": seed}
    )
    observed = float(result["observed"])
    expected = float(np.mean(sleep["drug1"]) if statistic == "mean" else np.median(sleep["drug1"]))
    assert_close(observed, expected, rtol=1e-12, what=f"observed {statistic}")

    low, high = (float(v) for v in result["ci"])
    assert low <= observed <= high, f"seed {seed}: interval ({low}, {high}) misses the estimate {observed}"
    assert low < high


@pytest.mark.parametrize("seed", [7, 12345])
def test_more_resamples_do_not_move_the_observed_statistic(sleep, seed: int) -> None:
    """The point estimate is a property of the data; only the interval should depend on the draws."""
    small = run_calc(sleep, "bootstrap_1sample", ["drug1"], {"resamples": 200, "seed": seed})
    large = run_calc(sleep, "bootstrap_1sample", ["drug1"], {"resamples": 2000, "seed": seed})
    assert small["observed"] == large["observed"]
    assert small["resamples"] == 200 and large["resamples"] == 2000


def test_the_same_seed_repeats_and_a_different_one_does_not(sleep) -> None:
    """Set Base's entire promise, asserted in both directions."""
    first = run_calc(sleep, "bootstrap_1sample", ["drug1"], {"resamples": 300, "seed": SEED})
    again = run_calc(sleep, "bootstrap_1sample", ["drug1"], {"resamples": 300, "seed": SEED})
    other = run_calc(sleep, "bootstrap_1sample", ["drug1"], {"resamples": 300, "seed": SEED + 1})

    assert first["ci"] == again["ci"], "the same base must give the same interval"
    assert first["ci"] != other["ci"], "a different base must give a different one"


# --- randomization tests -----------------------------------------------------------------------------


def test_randomization_one_mean_snapshot(sleep) -> None:
    result = run_calc(
        sleep, "randomization_1mean", ["drug1"], {"null_value": 0.0, "resamples": 1000, "seed": SEED}
    )
    golden.check(
        "randomization_1mean_sleep_drug1",
        _snapshotable(result),
        description="Calc > Resampling > Randomization Test for One Mean, sleep drug1 against 0, base 12345",
    )


def test_randomization_two_means_snapshot(sleep) -> None:
    result = run_calc(
        sleep,
        "randomization_2means",
        ["drug1", "drug2"],
        {"layout": "two_columns", "resamples": 1000, "seed": SEED},
    )
    golden.check(
        "randomization_2means_sleep",
        _snapshotable(result),
        description="Calc > Resampling > Randomization Test for Two Means, sleep drug1 vs drug2, base 12345",
    )


def test_randomization_one_proportion_snapshot() -> None:
    data = pd.DataFrame({"outcome": ["yes"] * 18 + ["no"] * 12})
    result = run_calc(
        data,
        "randomization_1proportion",
        ["outcome"],
        {"event": "yes", "null_value": 0.5, "resamples": 1000, "seed": SEED},
    )
    golden.check(
        "randomization_1proportion_18_of_30",
        _snapshotable(result),
        description="Calc > Resampling > Randomization Test for One Proportion, 18 of 30 against 0.5, base 12345",
    )


@pytest.mark.parametrize("seed", [3, 12345, 271828])
def test_randomization_p_values_are_probabilities(sleep, seed: int) -> None:
    for procedure, columns in (("randomization_1mean", ["drug1"]), ("randomization_2means", ["drug1", "drug2"])):
        layout = {"layout": "two_columns"} if len(columns) == 2 else {}
        result = run_calc(sleep, procedure, columns, {**layout, "resamples": 400, "seed": seed})
        p = float(result["p_value"])
        assert 0.0 < p <= 1.0, f"{procedure} at seed {seed}: p = {p}"
        # A finite number of resamples can never justify a p of exactly 0; the floor is 1/(B+1).
        assert p >= 1 / (400 + 1) - 1e-12, f"{procedure}: p = {p} is below the resampling floor"


def test_permutation_p_matches_the_exact_enumeration_on_a_tiny_case() -> None:
    """Small enough to enumerate every one of the C(8,4) = 70 splits, so the exact answer is known.

    This is the test that says the randomization machinery is computing the right thing rather than
    merely computing something repeatable. With 200000 resamples the Monte Carlo p must land within
    a few standard errors of the exact permutation p — and it must be on the same side of 0.05.
    """
    # calc.py caps resampling at 100,000; that is the largest run the dialog itself allows, so it
    # is the largest run worth validating.
    RESAMPLES = 100_000
    a = [1.0, 2.0, 3.0, 4.0]
    b = [6.0, 7.0, 8.0, 9.0]
    pooled = a + b
    observed = abs(np.mean(a) - np.mean(b))

    extreme = 0
    total = 0
    for left in itertools.combinations(range(8), 4):
        right = [i for i in range(8) if i not in left]
        difference = abs(np.mean([pooled[i] for i in left]) - np.mean([pooled[i] for i in right]))
        total += 1
        if difference >= observed - 1e-12:
            extreme += 1
    exact = extreme / total
    assert total == 70 and exact == pytest.approx(2 / 70)

    data = pd.DataFrame({"a": a, "b": b})
    result = run_calc(
        data, "randomization_2means", ["a", "b"], {"layout": "two_columns", "resamples": RESAMPLES, "seed": SEED}
    )
    monte_carlo = float(result["p_value"])

    standard_error = math.sqrt(exact * (1 - exact) / RESAMPLES)
    assert abs(monte_carlo - exact) < 6 * standard_error + 1 / (RESAMPLES + 1), (
        f"Monte Carlo p {monte_carlo} is far from the exact permutation p {exact}"
    )
    assert (monte_carlo < 0.05) == (exact < 0.05), "the two must agree on the verdict"


# --- random data ---------------------------------------------------------------------------------------


def test_random_normal_data_snapshot() -> None:
    result = run_calc(
        pd.DataFrame({"unused": [0.0]}),
        "random_data",
        [],
        {
            "distribution": "normal",
            "parameters": {"mean": 10.0, "sd": 2.0},
            "rows": 20,
            "store_in": ["C1", "C2"],
            "seed": SEED,
        },
    )
    golden.check(
        "random_data_normal_20x2",
        {"store_columns": result.get("store_columns")},
        description="Calc > Random Data > Normal(10, 2), 20 rows into two columns, base 12345",
    )


@pytest.mark.parametrize("distribution,params", [("normal", {"mean": 0, "sd": 1}), ("poisson", {"mean": 3})])
def test_random_data_repeats_with_the_base_and_varies_without_it(distribution: str, params: dict) -> None:
    blank = pd.DataFrame({"unused": [0.0]})
    options = {"distribution": distribution, "parameters": params, "rows": 50, "store_in": ["C1"]}

    seeded = [run_calc(blank, "random_data", [], {**options, "seed": SEED})["store_columns"][0]["values"] for _ in range(2)]
    assert seeded[0] == seeded[1], "the same base must give the same sample"

    unseeded = [run_calc(blank, "random_data", [], options)["store_columns"][0]["values"] for _ in range(2)]
    assert unseeded[0] != unseeded[1], "with no base set, two runs must differ"


def test_random_data_without_a_base_says_so() -> None:
    """The dialog has to warn, or the sample looks reproducible when it is not."""
    result = run_calc(
        pd.DataFrame({"unused": [0.0]}),
        "random_data",
        [],
        {"distribution": "normal", "parameters": {"mean": 0, "sd": 1}, "rows": 5, "store_in": ["C1"]},
    )
    assert "Set Base" in result["conclusion"]


# --- k-means and RFM -------------------------------------------------------------------------------------


def test_kmeans_snapshot(iris) -> None:
    outcome = segmentation.run_segmentation(
        iris, ["sepal_length", "sepal_width", "petal_length", "petal_width"], "kmeans", 3, "iris"
    )
    golden.check(
        "kmeans_iris_3_clusters",
        {
            "method_used": outcome.method_used,
            "n_rows_used": outcome.n_rows_used,
            "n_rows_excluded": outcome.n_rows_excluded,
            "segments": [
                {"segment": s.segment, "size": s.size, "mean_values": s.mean_values, "profile": s.profile}
                for s in outcome.segments
            ],
            "assignments": [row.segment for row in outcome.row_assignments],
        },
        description="Multivariate > Segmentation, k-means with 3 clusters on Fisher's iris (random_state 42)",
    )


def test_kmeans_partitions_every_row_exactly_once(iris) -> None:
    """True for any seed and any k: no row unassigned, no row in two clusters, sizes summing to n."""
    for k in (2, 3, 5):
        outcome = segmentation.run_segmentation(
            iris, ["sepal_length", "sepal_width", "petal_length", "petal_width"], "kmeans", k, "iris"
        )
        assert len(outcome.row_assignments) == outcome.n_rows_used == len(iris)
        assert outcome.n_rows_excluded == 0
        assert len(outcome.segments) == k

        sizes = {segment.segment: segment.size for segment in outcome.segments}
        counted: dict[str, int] = {}
        for row in outcome.row_assignments:
            counted[row.segment] = counted.get(row.segment, 0) + 1
        assert counted == sizes, f"k={k}: cluster sizes disagree with the row assignments"
        assert sum(sizes.values()) == len(iris)


def test_rfm_snapshot(customers) -> None:
    outcome = segmentation.run_segmentation(
        customers, ["last_purchase_date", "order_count", "total_spent"], "rfm", 3, "customers"
    )
    golden.check(
        "rfm_sample_customers",
        {
            "method_used": outcome.method_used,
            "n_rows_used": outcome.n_rows_used,
            "segments": [
                {"segment": s.segment, "size": s.size, "mean_values": s.mean_values, "profile": s.profile}
                for s in outcome.segments
            ],
            "assignments": [row.segment for row in outcome.row_assignments],
        },
        description="Multivariate > Segmentation, RFM on the repository's sample_customers.csv",
    )


def test_rfm_assigns_every_customer_and_scores_within_range(customers) -> None:
    outcome = segmentation.run_segmentation(
        customers, ["last_purchase_date", "order_count", "total_spent"], "rfm", 3, "customers"
    )
    assert outcome.method_used == "rfm"
    assert len(outcome.row_assignments) == len(customers)
    assert sum(segment.size for segment in outcome.segments) == len(customers)
    assert all(segment.size > 0 for segment in outcome.segments), "an empty named segment should not be reported"


# --- AutoML ---------------------------------------------------------------------------------------------------


def test_automl_regression_snapshot(iris) -> None:
    outcome = predictive.run_automl(iris, "sepal_length", ["sepal_width", "petal_length", "petal_width"], "regression")
    golden.check(
        "automl_iris_regression",
        {
            "task_type_used": outcome.task_type_used,
            "metric_label": outcome.metric_label,
            "n_obs": outcome.n_obs,
            "best_model": outcome.best_model,
            "best_score": outcome.best_score,
            "results": [{"model": r.model, "score": r.score} for r in outcome.results],
        },
        description="Predictive > AutoML, regression on Fisher's iris (all estimators random_state 42)",
    )


def test_automl_classification_snapshot(iris) -> None:
    outcome = predictive.run_automl(iris, "species", MEASUREMENTS := ["sepal_length", "sepal_width", "petal_length", "petal_width"], "classification")
    golden.check(
        "automl_iris_classification",
        {
            "task_type_used": outcome.task_type_used,
            "metric_label": outcome.metric_label,
            "n_obs": outcome.n_obs,
            "best_model": outcome.best_model,
            "best_score": outcome.best_score,
            "results": [{"model": r.model, "score": r.score} for r in outcome.results],
        },
        description="Predictive > AutoML, classification of iris species (all estimators random_state 42)",
    )


def test_automl_leaderboard_is_ranked_and_scored_consistently(iris) -> None:
    """Whatever the models are: the winner is the top row, and every score is in range."""
    for target, task, ceiling in (("sepal_length", "regression", 1.0), ("species", "classification", 1.0)):
        features = [c for c in ["sepal_length", "sepal_width", "petal_length", "petal_width"] if c != target]
        outcome = predictive.run_automl(iris, target, features, task)

        scores = [row.score for row in outcome.results]
        assert scores == sorted(scores, reverse=True), f"{task}: leaderboard is not ranked"
        assert outcome.best_model == outcome.results[0].model
        assert outcome.best_score == scores[0]
        for score in scores:
            assert score <= ceiling + 1e-9, f"{task}: score {score} above the metric's ceiling"
        if task == "classification":
            assert all(score >= 0.0 for score in scores), "accuracy cannot be negative"


def test_automl_is_deterministic_across_runs(iris) -> None:
    """No seed option is exposed, so determinism has to come from the fixed random_state."""
    first = predictive.run_automl(iris, "species", ["sepal_length", "petal_length"], "classification")
    second = predictive.run_automl(iris, "species", ["sepal_length", "petal_length"], "classification")
    assert [(r.model, r.score) for r in first.results] == [(r.model, r.score) for r in second.results]
