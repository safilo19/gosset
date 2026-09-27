"""Published worked examples for the ANOVA dialogs.

Fisher's iris carries most of this. It is the dataset the multivariate literature is written on, its
one-way MANOVA statistic (Wilks' lambda 0.023439, F = 199.145 on 8 and 288 df) is reproduced
everywhere including statsmodels' own MANOVA example, and its three species give a clean k = 3
comparison problem for Tukey and Dunnett.

Where no published number exists — Type III sums of squares on an unbalanced design, the grouping
letters — the expected value is derived here from the definition: Type III SS for a term is the drop
in residual sum of squares when that term alone is removed from the full model under sum-to-zero
coding, and that is computed with plain numpy rather than by calling `anova_lm` again.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from backend.tests import reference_impl as ref
from backend.tests.harness import run_anova
from backend.tests.refdata import expected, frame
from backend.tests.tolerance import (
    RTOL_ESTIMATE,
    RTOL_PVALUE,
    assert_close,
    row_where,
    table,
)

pytestmark = pytest.mark.published

IRIS = "iris_fisher"
MEASUREMENTS = ["sepal_length", "sepal_width", "petal_length", "petal_width"]


@pytest.fixture(scope="module")
def iris():
    return frame(IRIS)


@pytest.fixture(scope="module")
def species_groups(iris):
    return [iris.loc[iris["species"] == name, "sepal_length"].tolist() for name in sorted(iris["species"].unique())]


# --- one-way ANOVA ----------------------------------------------------------------------------------


def test_one_way_matches_the_longhand_sums_of_squares(iris, species_groups) -> None:
    f, df_between, df_within, p = ref.one_way_f(species_groups)
    result = run_anova(iris, "one_way", ["sepal_length", "species"], {"graph": False})

    assert_close(result["f_value"], f, rtol=RTOL_ESTIMATE, what="one-way F")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="one-way p")

    rows = table(result, "Analysis of Variance")
    assert row_where(rows, "Source", "species")["DF"] == df_between == 2
    assert row_where(rows, "Source", "Error")["DF"] == df_within == 147

    grand = ref.mean([v for g in species_groups for v in g])
    ss_between = sum(len(g) * (ref.mean(g) - grand) ** 2 for g in species_groups)
    ss_within = sum(sum((v - ref.mean(g)) ** 2 for v in g) for g in species_groups)
    assert_close(row_where(rows, "Source", "species")["Adj SS"], ss_between, rtol=RTOL_ESTIMATE, what="SS(species)")
    assert_close(row_where(rows, "Source", "Error")["Adj SS"], ss_within, rtol=RTOL_ESTIMATE, what="SS(error)")


def test_welch_one_way_does_not_pool_variances(iris, species_groups) -> None:
    """Welch (1951). The pooled and unpooled F must differ on iris, whose species variances differ."""
    f, df1, df2, p = ref.welch_anova(species_groups)
    result = run_anova(iris, "one_way", ["sepal_length", "species"], {"equal_variances": False, "graph": False})

    assert_close(result["f_value"], f, rtol=RTOL_ESTIMATE, what="Welch ANOVA F")
    assert_close(result["p_value"], p, rtol=RTOL_PVALUE, what="Welch ANOVA p")

    pooled = run_anova(iris, "one_way", ["sepal_length", "species"], {"graph": False})
    assert abs(pooled["f_value"] - result["f_value"]) > 1.0, "Welch must not silently pool"


def test_model_summary_r_squared_is_the_sum_of_squares_ratio(iris, species_groups) -> None:
    result = run_anova(iris, "one_way", ["sepal_length", "species"], {"graph": False})
    rows = table(result, "Analysis of Variance")
    between = row_where(rows, "Source", "species")["Adj SS"]
    total = row_where(rows, "Source", "Total")["Adj SS"]
    assert_close(result["r_squared"], between / total, rtol=RTOL_ESTIMATE, what="R-squared")


# --- multiple comparisons ------------------------------------------------------------------------------


def test_tukey_q_values_and_intervals_match_the_definition(iris, species_groups) -> None:
    """q = |difference| / sqrt(MSE/n) for equal n, and the adjusted p is the studentized range tail.

    Trap 14 in the project notes: `psturng` floors its p-values at 0.001, which would flatten every
    strongly significant comparison to the same number. All three iris comparisons are far past that
    floor, so this test would catch a regression to the floored implementation immediately.
    """
    from scipy import stats as st

    _, _, df_within, _ = ref.one_way_f(species_groups)
    mse = sum(sum((v - ref.mean(g)) ** 2 for v in g) for g in species_groups) / df_within
    names = sorted(iris["species"].unique())
    n = len(species_groups[0])

    result = run_anova(iris, "one_way", ["sepal_length", "species"], {"comparisons": "tukey", "graph": False})
    rows = table(result, "Tukey's simultaneous test (family error rate controlled): tests")

    assert len(rows) == 3, "three species give three pairwise comparisons"
    for row in rows:
        left, right = [part.strip() for part in str(row["Comparison"]).replace("−", "-").split(" - ")]
        a = species_groups[names.index(left)]
        b = species_groups[names.index(right)]
        difference = ref.mean(a) - ref.mean(b)
        se_difference = (mse * (1 / len(a) + 1 / len(b))) ** 0.5
        q = abs(difference) / (mse / n) ** 0.5

        assert_close(row["Difference"], difference, rtol=RTOL_ESTIMATE, what=f"diff {row['Comparison']}")
        assert_close(row["SE"], se_difference, rtol=RTOL_ESTIMATE, what=f"SE {row['Comparison']}")
        assert_close(row["Q-Value"], q, rtol=RTOL_ESTIMATE, what=f"q {row['Comparison']}")

        adjusted = float(st.studentized_range.sf(q, len(names), df_within))
        assert_close(row["Adjusted P-Value"], adjusted, rtol=1e-5, what=f"adjusted p {row['Comparison']}")
        assert row["Adjusted P-Value"] < 1e-4, "these comparisons are far past psturng's 0.001 floor"


def test_tukey_p_values_are_not_all_identical(iris) -> None:
    """The specific damage psturng's floor did: strongly significant comparisons losing their order."""
    result = run_anova(iris, "one_way", ["sepal_length", "species"], {"comparisons": "tukey", "graph": False})
    rows = table(result, "Tukey's simultaneous test (family error rate controlled): tests")
    values = sorted(row["Adjusted P-Value"] for row in rows)
    assert len(set(values)) > 1, f"all Tukey p-values collapsed to the same number: {values}"


def test_tukey_grouping_letters_partition_the_levels(iris) -> None:
    """Every level gets at least one letter, and levels sharing a letter are not separated."""
    result = run_anova(iris, "one_way", ["sepal_length", "species"], {"comparisons": "tukey", "graph": False})
    grouping = table(result, "Tukey's simultaneous test (family error rate controlled): grouping")
    tests = table(result, "Tukey's simultaneous test (family error rate controlled): tests")

    assert len(grouping) == 3
    letters = {str(row["Level"]): set(str(row["Grouping"]).replace(" ", "")) for row in grouping}
    assert all(letters.values()), "every level needs a grouping letter"

    significant = {
        tuple(sorted(part.strip() for part in str(row["Comparison"]).replace("−", "-").split(" - ")))
        for row in tests
        if row["Adjusted P-Value"] < 0.05
    }
    for left, right in itertools.combinations(letters, 2):
        shares_letter = bool(letters[left] & letters[right])
        pair = tuple(sorted((left, right)))
        assert shares_letter != (pair in significant), (
            f"{left}/{right}: grouping letters and the pairwise test disagree"
        )


def test_dunnett_compares_every_level_with_one_control(iris) -> None:
    """Dunnett's is k-1 comparisons against a named control, not all k(k-1)/2 pairs."""
    result = run_anova(
        iris,
        "one_way",
        ["sepal_length", "species"],
        {"comparisons": "dunnett", "control": "setosa", "graph": False},
    )
    rows = [t for t in result["tables"] if "Dunnett" in t["title"] and "tests" in t["title"]]
    assert rows, f"no Dunnett tests table; got {[t['title'] for t in result['tables']]}"
    comparisons = [str(row["Comparison"]) for row in rows[0]["rows"]]
    assert len(comparisons) == 2, f"k-1 = 2 comparisons expected, got {comparisons}"
    assert all("setosa" in c for c in comparisons)


# --- equal variances ------------------------------------------------------------------------------------


def test_bartlett_and_levene_match_their_longhand_formulas(iris, species_groups) -> None:
    """Bartlett (1937) with its 1/C correction, and Brown-Forsythe median-centred Levene."""
    bartlett_statistic, bartlett_df, bartlett_p = ref.bartlett(species_groups)
    levene_f, levene_df1, levene_df2, levene_p = ref.levene_median(species_groups)

    result = run_anova(iris, "equal_variances", ["sepal_length", "species"], {})
    rows = table(result, "Tests")
    bartlett_row = next(r for r in rows if "Bartlett" in r["Method"])
    levene_row = next(r for r in rows if "Levene" in r["Method"])

    assert bartlett_row["DF"] == bartlett_df == 2
    assert_close(bartlett_row["Test statistic"], bartlett_statistic, rtol=RTOL_ESTIMATE, what="Bartlett")
    assert_close(bartlett_row["P-Value"], bartlett_p, rtol=RTOL_PVALUE, what="Bartlett p")

    assert levene_row["DF"] == f"{levene_df1}, {levene_df2}"
    assert_close(levene_row["Test statistic"], levene_f, rtol=RTOL_ESTIMATE, what="Levene")
    assert_close(levene_row["P-Value"], levene_p, rtol=RTOL_PVALUE, what="Levene p")


def test_levene_is_median_centred_not_mean_centred(iris, species_groups) -> None:
    """Minitab's "Levene" is Brown-Forsythe. The two disagree, and the label must match the maths."""
    median_f, *_ = ref.levene_median(species_groups)
    mean_centred = [[abs(v - ref.mean(g)) for v in g] for g in species_groups]
    mean_f, *_ = ref.one_way_f(mean_centred)
    assert abs(median_f - mean_f) > 1e-6, "the two centrings should differ on this data"

    result = run_anova(iris, "equal_variances", ["sepal_length", "species"], {})
    row = next(r for r in table(result, "Tests") if "Levene" in r["Method"])
    assert_close(row["Test statistic"], median_f, rtol=RTOL_ESTIMATE, what="Levene (median-centred)")
    assert "median" in row["Method"].lower(), "the centring must be named in the UI"


# --- MANOVA ------------------------------------------------------------------------------------------------


def test_manova_matches_the_published_wilks_lambda(iris) -> None:
    """Fisher's iris, four responses on species: Wilks' lambda 0.023439, F = 199.145 on 8 and 288."""
    published = expected(IRIS)
    result = run_anova(iris, "manova", [*MEASUREMENTS, "species"], {"n_responses": 4})
    rows = table(result, "Term: species")
    wilks = row_where(rows, "Statistic", "Wilks' lambda")

    assert_close(wilks["Value"], published["wilks_lambda"], rtol=1e-9, what="Wilks' lambda")
    assert_close(wilks["F-Value"], published["wilks_f"], rtol=1e-9, what="Wilks F")
    assert wilks["Num DF"] == published["wilks_num_df"]
    assert wilks["Den DF"] == published["wilks_den_df"]
    assert 0.0 < wilks["Value"] <= 1.0, "Wilks' lambda is a ratio of determinants in (0, 1]"


def test_manova_reports_all_four_statistics_consistently(iris) -> None:
    published = expected(IRIS)
    rows = table(run_anova(iris, "manova", [*MEASUREMENTS, "species"], {"n_responses": 4}), "Term: species")
    names = [row["Statistic"] for row in rows]
    assert names == ["Wilks' lambda", "Pillai's trace", "Hotelling-Lawley trace", "Roy's greatest root"]

    pillai = row_where(rows, "Statistic", "Pillai's trace")
    assert_close(pillai["Value"], published["pillai_trace"], rtol=1e-9, what="Pillai's trace")
    assert_close(pillai["F-Value"], published["pillai_f"], rtol=1e-9, what="Pillai F")
    # Pillai's trace is bounded above by s = min(p, df_hypothesis) = min(4, 2) = 2.
    assert 0.0 <= pillai["Value"] <= 2.0
    for row in rows:
        assert 0.0 <= row["P-Value"] <= 1.0


# --- GLM Type III on an unbalanced design ---------------------------------------------------------------------


def _unbalanced(iris):
    """Fisher's iris made deliberately unbalanced, in a stated and reproducible way.

    The first 20 virginica and the first 8 versicolor rows are dropped, leaving 50/42/30. No
    published Type III analysis of this frame exists — that is the point: Type III sums of squares
    only differ from Type I when the design is unbalanced, so a balanced published example could not
    tell the two apart, and the expected values are derived from the definition below instead.
    """
    virginica = iris.index[iris["species"] == "virginica"][:20]
    versicolor = iris.index[iris["species"] == "versicolor"][:8]
    return iris.drop(index=list(virginica) + list(versicolor)).reset_index(drop=True)


def _type_three_ss(frame_in, response: str, factor: str, covariate: str) -> dict[str, float]:
    """Type III SS from the definition: the rise in residual SS when one term is dropped.

    Sum-to-zero coding for the factor and a centred covariate, which is what makes "drop this term"
    a well-posed question in the presence of the others — the same coding `anova.py` uses.
    """
    levels = sorted(frame_in[factor].unique())
    y = frame_in[response].to_numpy(float)
    x = frame_in[covariate].to_numpy(float)
    x = x - x.mean()
    effects = np.column_stack(
        [(frame_in[factor] == level).to_numpy(float) - (frame_in[factor] == levels[-1]).to_numpy(float) for level in levels[:-1]]
    )
    intercept = np.ones((len(y), 1))

    def residual_ss(design: np.ndarray) -> float:
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual = y - design @ beta
        return float(residual @ residual)

    full = np.column_stack([intercept, effects, x])
    rss_full = residual_ss(full)
    return {
        factor: residual_ss(np.column_stack([intercept, x])) - rss_full,
        covariate: residual_ss(np.column_stack([intercept, effects])) - rss_full,
        "error": rss_full,
        "df_error": len(y) - full.shape[1],
    }


def test_glm_type_three_sums_of_squares_on_an_unbalanced_design(iris) -> None:
    unbalanced = _unbalanced(iris)
    counts = unbalanced["species"].value_counts().to_dict()
    assert len(set(counts.values())) > 1, "the design must actually be unbalanced for this to mean anything"

    hand = _type_three_ss(unbalanced, "sepal_length", "species", "petal_width")
    result = run_anova(
        unbalanced,
        "glm",
        ["sepal_length", "species", "petal_width"],
        {"n_factors": 1, "graph_residuals": False},
    )
    rows = table(result, "Analysis of Variance (Type III adjusted SS)")

    assert_close(row_where(rows, "Source", "species")["Adj SS"], hand["species"], rtol=1e-7, what="Type III SS(species)")
    assert_close(
        row_where(rows, "Source", "petal_width")["Adj SS"], hand["petal_width"], rtol=1e-7, what="Type III SS(petal_width)"
    )
    error_row = row_where(rows, "Source", "Error")
    assert_close(error_row["Adj SS"], hand["error"], rtol=1e-9, what="Type III SS(error)")
    assert error_row["DF"] == hand["df_error"]


def test_type_three_differs_from_sequential_sums_of_squares(iris) -> None:
    """Guards the guard: on an unbalanced design the two orderings must NOT agree.

    If they did, the test above would pass for a Type I implementation mislabelled Type III.
    """
    unbalanced = _unbalanced(iris)
    y = unbalanced["sepal_length"].to_numpy(float)
    x = unbalanced["petal_width"].to_numpy(float)
    levels = sorted(unbalanced["species"].unique())
    effects = np.column_stack(
        [(unbalanced["species"] == level).to_numpy(float) - (unbalanced["species"] == levels[-1]).to_numpy(float) for level in levels[:-1]]
    )
    intercept = np.ones((len(y), 1))

    def rss(design):
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual = y - design @ beta
        return float(residual @ residual)

    sequential_species = rss(intercept) - rss(np.column_stack([intercept, effects]))
    type_three = _type_three_ss(unbalanced, "sepal_length", "species", "petal_width")["species"]
    assert abs(sequential_species - type_three) > 1.0, (
        "Type I and Type III agree here, so this design does not distinguish them"
    )


def test_glm_centres_its_covariates(iris) -> None:
    """Project trap 12: an uncentred covariate in an interaction turns a main effect into a test at 0.

    Centring is on by default; turning it off must change the factor's Type III F, which is exactly
    the symptom the trap describes. If both fits agreed, centring would not be happening.
    """
    unbalanced = _unbalanced(iris)
    columns = ["sepal_length", "species", "petal_width"]
    centred = run_anova(
        unbalanced, "glm", columns, {"n_factors": 1, "interactions": True, "graph_residuals": False}
    )
    uncentred = run_anova(
        unbalanced,
        "glm",
        columns,
        {"n_factors": 1, "interactions": True, "center_covariates": False, "graph_residuals": False},
    )

    def species_f(result):
        return row_where(table(result, "Analysis of Variance (Type III adjusted SS)"), "Source", "species")["F-Value"]

    assert abs(species_f(centred) - species_f(uncentred)) > 1e-6, (
        "centring made no difference to the factor's Type III F, so covariates are not being centred"
    )
    # The residual error is identical either way — centring reparameterises, it does not refit.
    for result in (centred, uncentred):
        assert result["n"] == len(unbalanced)
    assert_close(centred["s"], uncentred["s"], rtol=1e-9, what="residual S is invariant to centring")
