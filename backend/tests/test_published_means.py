"""Published worked examples for the mean, variance and normality dialogs.

Student's sleep data is the natural spine here: it is the dataset Student used in the 1908 paper
that introduced the t-test, it is paired, and R ships it as the documented example for
`t.test(..., paired = TRUE)`, so the paired result is a published number rather than a
reimplementation. Everything else is derived from the textbook formula in
`backend/tests/reference_impl.py`, written out longhand — a check against a second call to
`scipy.stats.ttest_ind` would only prove the arguments were spelled right.
"""

from __future__ import annotations

import math

import pytest

from backend.tests import reference_impl as ref
from backend.tests.harness import run_basic_stats
from backend.tests.refdata import citation, expected, frame
from backend.tests.tolerance import (
    RTOL_ESTIMATE,
    RTOL_PVALUE,
    assert_close,
    row_where,
    table,
)

pytestmark = pytest.mark.published

CASE = "sleep_cushny_peebles"


@pytest.fixture(scope="module")
def sleep():
    return frame(CASE)


@pytest.fixture(scope="module")
def values(sleep):
    return sleep["drug1"].tolist(), sleep["drug2"].tolist()


def test_the_reference_file_cites_its_source() -> None:
    assert "Student" in citation(CASE) or "Cushny" in citation(CASE)
    assert expected(CASE)["kind"] == "published"


# --- paired t: the published case ---------------------------------------------------------------


def test_paired_t_matches_the_published_result(sleep) -> None:
    """Student (1908) / R's documented `t.test(extra ~ group, paired = TRUE)`: t = -4.0621, p = 0.002833."""
    published = expected(CASE)
    result = run_basic_stats(sleep, "paired_t", ["drug1", "drug2"], {})

    assert_close(result["statistic"], published["paired_t_statistic"], rtol=RTOL_ESTIMATE, what="paired t")
    assert_close(result["p_value"], published["paired_p_value"], rtol=RTOL_PVALUE, what="paired p")

    row = table(result, "Test")[0]
    assert row["DF"] == published["paired_df"]
    assert_close(row["T-Value"], published["paired_t_statistic"], rtol=RTOL_ESTIMATE, what="paired t (table)")


def test_paired_t_equals_the_longhand_formula(values) -> None:
    """A paired t IS a one-sample t on the differences — asserted, not assumed."""
    a, b = values
    t, df, p = ref.paired_t(a, b)
    result = run_basic_stats(frame(CASE), "paired_t", ["drug1", "drug2"], {})
    assert_close(result["statistic"], t, rtol=RTOL_ESTIMATE, what="paired t vs longhand")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="paired p vs longhand")
    assert table(result, "Test")[0]["DF"] == df


def test_paired_t_against_a_nonzero_hypothesized_difference(values) -> None:
    a, b = values
    t, _, p = ref.paired_t(a, b, mu0=-1.0)
    result = run_basic_stats(frame(CASE), "paired_t", ["drug1", "drug2"], {"hypothesized_mean": -1.0})
    assert_close(result["statistic"], t, rtol=RTOL_ESTIMATE, what="paired t (mu0=-1)")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="paired p (mu0=-1)")


# --- two-sample t ---------------------------------------------------------------------------------


def test_welch_two_sample_t_matches_the_published_result(sleep) -> None:
    """Welch is the default two-sample test, and the df formula is where a sign flip hides."""
    published = expected(CASE)
    result = run_basic_stats(sleep, "t2", ["drug1", "drug2"], {"layout": "two_columns"})

    assert_close(result["statistic"], published["welch_t_statistic"], rtol=RTOL_ESTIMATE, what="Welch t")
    assert_close(result["degrees_of_freedom"], published["welch_df"], rtol=RTOL_ESTIMATE, what="Welch df")
    assert_close(result["p_value"], published["welch_p_value"], rtol=RTOL_PVALUE, what="Welch p")


def test_welch_degrees_of_freedom_equal_the_satterthwaite_formula(values) -> None:
    """Written out longhand: (v1+v2)^2 / (v1^2/(n1-1) + v2^2/(n2-1)), Welch (1947)."""
    a, b = values
    t, df, p = ref.welch_t(a, b)
    result = run_basic_stats(frame(CASE), "t2", ["drug1", "drug2"], {"layout": "two_columns"})
    assert_close(result["statistic"], t, rtol=RTOL_ESTIMATE, what="Welch t vs longhand")
    assert_close(result["degrees_of_freedom"], df, rtol=RTOL_ESTIMATE, what="Welch df vs longhand")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="Welch p vs longhand")
    # The Welch df must sit strictly between the smaller group's df and the pooled df, always.
    assert min(len(a), len(b)) - 1 <= df <= len(a) + len(b) - 2


def test_pooled_two_sample_t_matches_the_published_result(sleep) -> None:
    published = expected(CASE)
    result = run_basic_stats(sleep, "t2", ["drug1", "drug2"], {"layout": "two_columns", "equal_variances": True})
    assert_close(result["statistic"], published["pooled_t_statistic"], rtol=RTOL_ESTIMATE, what="pooled t")
    assert result["degrees_of_freedom"] == published["pooled_df"]
    assert_close(result["p_value"], published["pooled_p_value"], rtol=RTOL_PVALUE, what="pooled p")


def test_pooled_two_sample_t_equals_the_longhand_formula(values) -> None:
    a, b = values
    t, df, p = ref.pooled_t(a, b)
    result = run_basic_stats(frame(CASE), "t2", ["drug1", "drug2"], {"layout": "two_columns", "equal_variances": True})
    assert_close(result["statistic"], t, rtol=RTOL_ESTIMATE, what="pooled t vs longhand")
    assert result["degrees_of_freedom"] == df
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="pooled p vs longhand")


# --- one-sample t and z -----------------------------------------------------------------------------


def test_one_sample_t_equals_the_longhand_formula(values) -> None:
    a, _ = values
    for mu0 in (0.0, 1.0, -0.5):
        t, df, p = ref.one_sample_t(a, mu0)
        result = run_basic_stats(frame(CASE), "t1", ["drug1"], {"hypothesized_mean": mu0})
        assert_close(result["statistic"], t, rtol=RTOL_ESTIMATE, what=f"1-sample t (mu0={mu0})")
        assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what=f"1-sample p (mu0={mu0})")
        assert table(result, "Test")[0]["DF"] == df


def test_one_sample_z_uses_the_normal_tail_and_the_known_sigma(values) -> None:
    """The whole difference between 1-Sample Z and 1-Sample T: sigma is given, so there is no df.

    Getting this wrong is invisible on large n and wrong by a lot on n = 10, which is why the pair
    is tested on the same column with the same hypothesis.
    """
    a, _ = values
    sigma = 2.0
    z, p = ref.one_sample_z(a, 0.0, sigma)
    result = run_basic_stats(frame(CASE), "z1", ["drug1"], {"hypothesized_mean": 0.0, "sigma": sigma})
    assert_close(result["statistic"], z, rtol=RTOL_ESTIMATE, what="1-sample z")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="1-sample z p")
    assert "DF" not in table(result, "Test")[0], "a Z test has no degrees of freedom"

    t_result = run_basic_stats(frame(CASE), "t1", ["drug1"], {"hypothesized_mean": 0.0})
    assert t_result["p_value"] != result["p_value"], "Z and T must not agree on n = 10"


def test_one_sided_alternatives_halve_the_two_sided_p(values) -> None:
    """A one-sided p is the corresponding tail; the pair must add to 1 across the two directions."""
    less = run_basic_stats(frame(CASE), "t1", ["drug1"], {"alternative": "less"})
    greater = run_basic_stats(frame(CASE), "t1", ["drug1"], {"alternative": "greater"})
    assert_close(less["p_value"] + greater["p_value"], 1.0, rtol=RTOL_PVALUE, what="one-sided p pair")

    two_sided = run_basic_stats(frame(CASE), "t1", ["drug1"], {})
    assert_close(
        2 * min(less["p_value"], greater["p_value"]), two_sided["p_value"], rtol=RTOL_PVALUE, what="two-sided p"
    )


# --- variances ---------------------------------------------------------------------------------------


def test_two_variances_f_test_equals_the_longhand_ratio(values) -> None:
    a, b = values
    f, df1, df2, p = ref.variance_ratio_f(a, b)
    result = run_basic_stats(frame(CASE), "var2", ["drug1", "drug2"], {"layout": "two_columns"})
    assert_close(result["statistic"], f, rtol=RTOL_ESTIMATE, what="F ratio")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="F p")
    assert_close(result["ratio"], ref.variance(a) / ref.variance(b), rtol=RTOL_ESTIMATE, what="variance ratio")
    assert df1 == len(a) - 1 and df2 == len(b) - 1


def test_two_variances_reports_levene_alongside_f(values) -> None:
    """Both tests are shown because they answer the same question under different assumptions."""
    a, b = values
    _, _, _, levene_p = ref.levene_median([a, b])
    result = run_basic_stats(frame(CASE), "var2", ["drug1", "drug2"], {"layout": "two_columns"})
    assert_close(result["levene_p_value"], levene_p, rtol=RTOL_PVALUE, what="Levene p")


def test_one_variance_chi_square_against_a_hypothesised_value(values) -> None:
    """chi2 = (n-1) s^2 / sigma0^2 on n-1 df — the definition, written out here."""
    from scipy import stats as st

    a, _ = values
    sigma0_sq = 4.0
    n = len(a)
    statistic = (n - 1) * ref.variance(a) / sigma0_sq
    p = 2 * min(float(st.chi2.cdf(statistic, n - 1)), float(st.chi2.sf(statistic, n - 1)))

    result = run_basic_stats(
        frame(CASE), "var1", ["drug1"], {"hypothesized_kind": "variance", "hypothesized_value": sigma0_sq}
    )
    assert_close(result["statistic"], statistic, rtol=RTOL_ESTIMATE, what="1-variance chi-square")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="1-variance p")


# --- normality ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,label",
    [
        ("anderson_darling", "Anderson-Darling"),
        ("kolmogorov_smirnov", "Kolmogorov-Smirnov"),
        ("shapiro_wilk", "Shapiro-Wilk"),
    ],
)
def test_normality_tests_run_and_label_their_substitution(method: str, label: str) -> None:
    """All three normality tests, on a sample nobody disputes is roughly normal.

    The statistics themselves come from scipy/statsmodels and are validated there; what this pins is
    that the right test is being run under the right name, that the p-value is a probability, and —
    for Anderson-Darling — that Gosset says out loud where its p-value comes from, since scipy
    reports only critical values and the parity substitution has to be visible in the UI.
    """
    result = run_basic_stats(frame(CASE), "normality", ["drug1"], {"method": method})
    assert result["normality_method"] == method
    assert label in table(result, "Test")[0]["Method"]
    assert 0.0 <= result["p_value"] <= 1.0
    assert result["statistic"] > 0

    if method == "anderson_darling":
        assert "D'Agostino" in result["method"], "the A-D p-value substitution must be labelled"


def test_shapiro_wilk_agrees_with_scipy_on_the_published_sample() -> None:
    """Shapiro-Wilk has no closed form worth reimplementing; this pins the wiring, not the algorithm."""
    from scipy import stats as st

    a = frame(CASE)["drug1"].tolist()
    statistic, p = st.shapiro(a)
    result = run_basic_stats(frame(CASE), "normality", ["drug1"], {"method": "shapiro_wilk"})
    assert_close(result["statistic"], float(statistic), rtol=RTOL_ESTIMATE, what="Shapiro-Wilk W")
    assert_close(result["p_value"], float(p), rtol=RTOL_PVALUE, what="Shapiro-Wilk p")


# --- descriptives ------------------------------------------------------------------------------------------


def test_descriptives_match_the_longhand_moments(values) -> None:
    a, _ = values
    result = run_basic_stats(frame(CASE), "display_descriptives", ["drug1"], {})
    row = row_where(table(result, "Statistics"), "Variable", "drug1")
    assert row["N"] == len(a)
    assert_close(row["Mean"], ref.mean(a), rtol=RTOL_ESTIMATE, what="mean")
    assert_close(row["StDev"], ref.stdev(a), rtol=RTOL_ESTIMATE, what="stdev")
    assert_close(row["SE Mean"], ref.stdev(a) / math.sqrt(len(a)), rtol=RTOL_ESTIMATE, what="se mean")
