"""Published worked examples for the proportion, rate, count and outlier dialogs.

The reference values here are unusually strong, because most of these tests have EXACT small-sample
forms that can be evaluated in rational arithmetic:

* the two-sided exact binomial p-value is a finite sum of binomial terms, computed with `Fraction`
  so the reference owes nothing to floating point;
* Clopper-Pearson limits are Beta quantiles, which is the definition rather than a reimplementation;
* Pearson's chi-square on a contingency table is sum (O-E)^2/E over margins, written out;
* Grubbs' G is max|x - xbar| / s against the NIST handbook's own worked answer.
"""

from __future__ import annotations

import math
from fractions import Fraction

import pandas as pd
import pytest

from backend.core import tests as v1_tests
from backend.tests import reference_impl as ref
from backend.tests.harness import run_basic_stats
from backend.tests.properties import check_result_invariants
from backend.tests.refdata import expected, frame, load
from backend.tests.tolerance import RTOL_ESTIMATE, RTOL_PVALUE, assert_close, row_where, table

pytestmark = pytest.mark.published


# --- proportions -------------------------------------------------------------------------------

PROPORTIONS = "proportions_clopper_pearson"


def _blank(rows: int = 1) -> pd.DataFrame:
    """Summarised input needs no worksheet, but `compute` still takes one."""
    return pd.DataFrame({"unused": [0] * rows})


def test_one_proportion_exact_p_value_is_the_exact_binomial_sum() -> None:
    """3 events in 10 trials against p = 0.5. The exact two-sided p is 176/512 = 0.34375, EXACTLY.

    Computed here as a rational sum of binomial terms, so a floating-point drift in Gosset's tail
    calculation shows up rather than being absorbed by a tolerance.
    """
    data = load(PROPORTIONS)["data"]
    events, trials, p0 = data["case1_events"], data["case1_trials"], data["case1_hypothesized_p"]

    exact = Fraction(0)
    p = Fraction(1, 2)
    pmf = [math.comb(trials, k) * p**k * (1 - p) ** (trials - k) for k in range(trials + 1)]
    for value in pmf:
        if value <= pmf[events]:
            exact += value
    assert exact == Fraction(11, 32), "the closed-form check itself must be right"

    result = run_basic_stats(
        _blank(),
        "prop1",
        [],
        {"input": "summarized", "events": events, "trials": trials, "hypothesized_p": p0, "method": "exact"},
    )
    assert result["p_value"] == float(exact), "an exact test should reproduce the rational value bit for bit"


def test_one_proportion_exact_interval_is_clopper_pearson() -> None:
    """The published exact 95% interval for 3/10 is (0.0667, 0.6525) — a pair of Beta quantiles."""
    data = load(PROPORTIONS)["data"]
    events, trials = data["case1_events"], data["case1_trials"]
    low, high = ref.clopper_pearson(events, trials, alpha=0.05)

    result = run_basic_stats(
        _blank(),
        "prop1",
        [],
        {"input": "summarized", "events": events, "trials": trials, "method": "exact"},
    )
    row = table(result, "Descriptive Statistics")[0]
    text = row["95% CI for the proportion"]
    got_low, got_high = (float(part) for part in text.strip("()").split(","))

    assert_close(got_low, low, rtol=0, atol=1e-5, what="Clopper-Pearson lower")
    assert_close(got_high, high, rtol=0, atol=1e-5, what="Clopper-Pearson upper")
    assert abs(low - 0.0667) < 5e-4 and abs(high - 0.6525) < 5e-4, "against the published interval"
    assert 0.0 <= low <= row["Sample p"] <= high <= 1.0


def test_one_proportion_normal_method_is_the_wald_interval_and_score_test() -> None:
    """The approximate method must differ from the exact one on n = 10, and match the Wald formula."""
    data = load(PROPORTIONS)["data"]
    events, trials = data["case2_events"], data["case2_trials"]
    low, high = ref.wald_interval(events, trials)

    result = run_basic_stats(
        _blank(),
        "prop1",
        [],
        {"input": "summarized", "events": events, "trials": trials, "hypothesized_p": 0.75, "method": "normal"},
    )
    text = table(result, "Descriptive Statistics")[0]["95% CI for the proportion"]
    got_low, got_high = (float(part) for part in text.strip("()").split(","))
    assert_close(got_low, low, rtol=0, atol=1e-5, what="Wald lower")
    assert_close(got_high, high, rtol=0, atol=1e-5, what="Wald upper")

    # The test statistic uses the NULL standard error, not the sample one — a classic mix-up.
    p0 = 0.75
    z = (events / trials - p0) / math.sqrt(p0 * (1 - p0) / trials)
    from scipy import stats as st

    assert_close(result["p_value"], 2 * float(st.norm.sf(abs(z))), rtol=RTOL_PVALUE, what="score-test p")


def test_exact_and_normal_methods_disagree_on_a_small_sample() -> None:
    data = load(PROPORTIONS)["data"]
    kwargs = {"input": "summarized", "events": data["case1_events"], "trials": data["case1_trials"]}
    exact = run_basic_stats(_blank(), "prop1", [], {**kwargs, "method": "exact"})
    normal = run_basic_stats(_blank(), "prop1", [], {**kwargs, "method": "normal"})
    assert exact["p_value"] != normal["p_value"], "n = 10 is exactly where the approximation bites"


def test_two_proportions_normal_approximation_matches_the_longhand_z() -> None:
    """Unpooled by default: SE = sqrt(p1(1-p1)/n1 + p2(1-p2)/n2)."""
    from scipy import stats as st

    data = load(PROPORTIONS)["data"]
    (e1, e2), (n1, n2) = data["two_sample_events"], data["two_sample_trials"]
    p1, p2 = e1 / n1, e2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = (p1 - p2) / se

    result = run_basic_stats(
        _blank(),
        "prop2",
        [],
        {"input": "summarized", "events1": e1, "trials1": n1, "events2": e2, "trials2": n2},
    )
    assert_close(result["statistic"], z, rtol=RTOL_ESTIMATE, what="2-proportion z")
    assert_close(result["p_value"], 2 * float(st.norm.sf(abs(z))), rtol=RTOL_PVALUE, what="2-proportion p")


def test_two_proportions_pooled_option_uses_the_pooled_standard_error() -> None:
    from scipy import stats as st

    data = load(PROPORTIONS)["data"]
    (e1, e2), (n1, n2) = data["two_sample_events"], data["two_sample_trials"]
    pooled = (e1 + e2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (e1 / n1 - e2 / n2) / se

    result = run_basic_stats(
        _blank(),
        "prop2",
        [],
        {"input": "summarized", "events1": e1, "trials1": n1, "events2": e2, "trials2": n2, "pooled": True},
    )
    assert_close(result["statistic"], z, rtol=RTOL_ESTIMATE, what="pooled 2-proportion z")
    assert_close(result["p_value"], 2 * float(st.norm.sf(abs(z))), rtol=RTOL_PVALUE, what="pooled p")


# --- Poisson rates and goodness of fit -----------------------------------------------------------

HORSE_KICKS = "horse_kicks_bortkiewicz"


@pytest.fixture(scope="module")
def horse_kicks():
    return frame(HORSE_KICKS)


def test_horse_kick_mean_is_the_published_rate(horse_kicks) -> None:
    """Bortkiewicz (1898): 122 deaths over 200 corps-years, a mean of 0.61."""
    published = expected(HORSE_KICKS)
    deaths = horse_kicks["deaths"].tolist()
    assert len(deaths) == published["corps_years"] == 200
    assert sum(deaths) == published["total_deaths"] == 122
    assert_close(ref.mean(deaths), published["mean"], rtol=RTOL_ESTIMATE, what="horse-kick mean")

    result = run_basic_stats(horse_kicks, "display_descriptives", ["deaths"], {})
    assert_close(
        row_where(table(result, "Statistics"), "Variable", "deaths")["Mean"],
        published["mean"],
        rtol=RTOL_ESTIMATE,
        what="mean via Descriptives",
    )


def test_one_sample_poisson_rate_against_the_published_mean(horse_kicks) -> None:
    """A rate tested against its own estimate must not be significant — the sanity anchor."""
    result = run_basic_stats(horse_kicks, "poisson1", ["deaths"], {"hypothesized_rate": 0.61, "method": "exact"})
    assert result["p_value"] > 0.9, f"testing 0.61 against 0.61 should be about as unsurprising as possible"

    far = run_basic_stats(horse_kicks, "poisson1", ["deaths"], {"hypothesized_rate": 1.0, "method": "exact"})
    assert far["p_value"] < 1e-6, "0.61 against a hypothesised 1.0 over 200 corps-years is decisive"


def test_poisson_goodness_of_fit_reproduces_the_published_frequency_table(horse_kicks) -> None:
    """The observed counts must be Bortkiewicz's 109/65/22/3/1, and the expected ones must come from
    the fitted mean — this is the table the whole example is famous for."""
    published_table = load(HORSE_KICKS)["data"]["frequency_table"]
    result = run_basic_stats(horse_kicks, "poisson_gof", ["deaths"], {})

    counts_table = next(t for t in result["tables"] if any("Observed" in str(k) for k in (t["rows"][0] or {})))
    observed = [row for row in counts_table["rows"]]
    assert sum(int(row["Observed"]) for row in observed) == 200

    # The lowest category is 0 deaths and must hold the published 109.
    first = observed[0]
    assert int(first["Observed"]) == published_table[0] == 109

    # Expected counts are n * Poisson(mean).pmf(k) for the ungrouped categories.
    from scipy import stats as st

    fitted = st.poisson(mu=ref.mean(horse_kicks["deaths"].tolist()))
    assert_close(float(first["Expected"]), 200 * float(fitted.pmf(0)), rtol=1e-6, what="expected count for 0")
    assert 0.0 <= result["p_value"] <= 1.0


def test_poisson_goodness_of_fit_statistic_is_the_chi_square_sum(horse_kicks) -> None:
    result = run_basic_stats(horse_kicks, "poisson_gof", ["deaths"], {})
    counts_table = next(t for t in result["tables"] if any("Observed" in str(k) for k in (t["rows"][0] or {})))
    observed = [float(row["Observed"]) for row in counts_table["rows"]]
    expected_counts = [float(row["Expected"]) for row in counts_table["rows"]]

    statistic = sum((o - e) ** 2 / e for o, e in zip(observed, expected_counts))
    assert_close(result["statistic"], statistic, rtol=1e-9, what="Poisson GOF chi-square")
    # One df is spent on the estimated mean, on top of the usual k-1.
    assert result["degrees_of_freedom"] == len(observed) - 2


# --- chi-square test of independence ---------------------------------------------------------------

SMOKING = "beijing_smoking_lung_cancer"


def test_chi_square_independence_matches_the_longhand_formula() -> None:
    """Liu (1992), Beijing stratum: 126 / 100 / 35 / 61. Statistic derived from the margins here."""
    counts = load(SMOKING)["data"]
    rows = [
        [counts["smoker_cancer"], counts["smoker_no_cancer"]],
        [counts["nonsmoker_cancer"], counts["nonsmoker_no_cancer"]],
    ]
    statistic, df, p = ref.chi_square_independence(rows)

    records = (
        [{"smoker": "yes", "cancer": "yes"}] * counts["smoker_cancer"]
        + [{"smoker": "yes", "cancer": "no"}] * counts["smoker_no_cancer"]
        + [{"smoker": "no", "cancer": "yes"}] * counts["nonsmoker_cancer"]
        + [{"smoker": "no", "cancer": "no"}] * counts["nonsmoker_no_cancer"]
    )
    worksheet = pd.DataFrame(records)
    assert len(worksheet) == expected(SMOKING)["total"] == 322

    outcome = v1_tests.run_hypothesis_test(worksheet, "chi_square", ["smoker", "cancer"], 0.05)
    check_result_invariants(
        {"statistic": outcome.statistic, "P-Value": outcome.p_value, "DF": outcome.degrees_of_freedom},
        context="chi_square",
    )

    # scipy applies Yates' continuity correction to a 2x2 by default; the uncorrected statistic is
    # the one the longhand formula gives, so both are checked rather than one being assumed.
    corrected = sum(
        (abs(o - e) - 0.5) ** 2 / e
        for o, e in zip(
            [rows[0][0], rows[0][1], rows[1][0], rows[1][1]],
            _expected_counts(rows),
        )
    )
    assert outcome.degrees_of_freedom == df == 1
    assert abs(outcome.statistic - statistic) < 1e-9 or abs(outcome.statistic - corrected) < 1e-9, (
        f"chi-square {outcome.statistic} matches neither the plain ({statistic}) nor the "
        f"Yates-corrected ({corrected}) formula"
    )
    assert 0.0 <= outcome.p_value <= 1.0
    assert outcome.p_value < 0.01, "smoking and lung cancer are strongly associated in this stratum"


def _expected_counts(rows: list[list[int]]) -> list[float]:
    total = sum(sum(row) for row in rows)
    row_totals = [sum(row) for row in rows]
    col_totals = [sum(row[j] for row in rows) for j in range(len(rows[0]))]
    return [row_totals[i] * col_totals[j] / total for i in range(len(rows)) for j in range(len(rows[0]))]


def test_chi_square_goodness_of_fit_is_a_known_gap() -> None:
    """Gosset offers a POISSON goodness-of-fit test but no general chi-square GOF.

    Mendel's peas (315/101/108/32 against 9:3:3:1) is the canonical example and cannot be run.
    Recorded here and in VALIDATION.md rather than left as an unexplained absence; when the
    procedure is added, this test fails and the certified example is waiting.
    """
    from backend.core import basic_stats

    assert "chi_square_gof" not in basic_stats.PROCEDURES
    assert "poisson_gof" in basic_stats.PROCEDURES

    # The reference answer, ready for the day it can be used: chi-square 0.4700, p = 0.9254.
    statistic, df, p = ref.chi_square_goodness_of_fit([315, 101, 108, 32], [312.75, 104.25, 104.25, 34.75])
    assert abs(statistic - 0.4700) < 5e-4 and df == 3 and abs(p - 0.9254) < 5e-4


# --- outliers ---------------------------------------------------------------------------------------

GRUBBS = "grubbs_mass_spectrometer"


def test_grubbs_matches_the_nist_handbook_worked_answer() -> None:
    """NIST/SEMATECH e-Handbook 1.3.5.17: G = 2.4687 for 245.57, critical value 2.126 at 5%."""
    published = expected(GRUBBS)
    data = frame(GRUBBS)
    result = run_basic_stats(data, "outlier", ["measurement"], {"method": "grubbs"})

    # The handbook prints G to four decimals (2.4687); Gosset computes 2.468765, so the comparison
    # is against the printed precision. The full-precision check is the longhand one below.
    assert_close(result["statistic"], published["grubbs_g"], rtol=0, atol=1e-4, what="Grubbs G")
    assert_close(
        result["critical_value"], published["grubbs_critical_5pct"], rtol=0, atol=5e-3, what="Grubbs critical value"
    )
    assert result["significant"] is published["significant"]


def test_grubbs_matches_the_longhand_definition() -> None:
    """G = max|x - xbar| / s, and the flagged point is the one that maximises it."""
    values = frame(GRUBBS)["measurement"].tolist()
    g, p, index = ref.grubbs(values)
    result = run_basic_stats(frame(GRUBBS), "outlier", ["measurement"], {"method": "grubbs"})

    assert_close(result["statistic"], g, rtol=RTOL_ESTIMATE, what="Grubbs G vs longhand")
    assert values[index] == expected(GRUBBS)["outlier_value"]
    assert 0.0 <= result["p_value"] <= 1.0
    assert result["p_value"] < 0.05


def test_dixon_matches_the_gap_over_range_ratio() -> None:
    """Dixon (1953) Q = gap / range for the extreme end, checked on the same eight points."""
    values = frame(GRUBBS)["measurement"].tolist()
    q = ref.dixon_q(values)
    result = run_basic_stats(frame(GRUBBS), "outlier", ["measurement"], {"method": "dixon"})
    assert_close(result["statistic"], q, rtol=RTOL_ESTIMATE, what="Dixon Q")
    assert 0.0 <= result["statistic"] <= 1.0, "a gap-over-range ratio cannot leave [0, 1]"


def test_dixon_is_labelled_as_a_table_based_substitution() -> None:
    """Minitab parity rule: where the p-value comes from tables rather than a formula, say so."""
    result = run_basic_stats(frame(GRUBBS), "outlier", ["measurement"], {"method": "dixon"})
    assert "table" in result["method"].lower() or "critical" in result["method"].lower(), result["method"]
