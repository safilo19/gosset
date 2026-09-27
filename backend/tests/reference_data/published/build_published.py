"""Regenerate the published-example reference files that live beside this script.

Each `.toml` carries a header comment naming its SOURCE (exact citation), what it certifies and the
retrieval date, then the data itself and the expected values. The data is committed rather than
loaded from scikit-learn or statsmodels at test time so the suite does not silently change when a
package is upgraded — a reference dataset that moves is not a reference dataset.

Two kinds of expected value appear, and the `kind` field on each says which:

  "published"  — the number appears in the cited source (or in the reference implementation the
                 cited source documents, e.g. statsmodels' own Logit example output).
  "hand"       — the number is derived in the test itself from the textbook formula, written out
                 longhand rather than by calling the same library function Gosset calls. The file
                 records the formula and its citation; the arithmetic happens in the test.

Run from the repo root:

    python backend/tests/reference_data/published/build_published.py
"""

from __future__ import annotations

import datetime as _dt
import textwrap
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RETRIEVED = _dt.date.today().isoformat()


def _fmt(value: Any, indent: int = 0) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        items = [_fmt(v) for v in value]
        one_line = "[" + ", ".join(items) + "]"
        if len(one_line) <= 100:
            return one_line
        pad = " " * (indent + 2)
        return "[\n" + "".join(f"{pad}{item},\n" for item in items) + " " * indent + "]"
    raise TypeError(f"cannot serialise {type(value)}")


def write(name: str, header: str, sections: dict[str, dict[str, Any]]) -> None:
    lines = [line.rstrip() for line in textwrap.dedent(header).strip().splitlines()]
    out = ["# " + line if line else "#" for line in lines]
    out.append(f"# RETRIEVED: {RETRIEVED}")
    out.append("")
    for section, body in sections.items():
        out.append(f"[{section}]")
        for key, value in body.items():
            out.append(f"{key} = {_fmt(value)}")
        out.append("")
    (HERE / f"{name}.toml").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  wrote {name}.toml")


# --- 1. Student's sleep data -------------------------------------------------------------------

SLEEP_DRUG_1 = [0.7, -1.6, -0.2, -1.2, -0.1, 3.4, 3.7, 0.8, 0.0, 2.0]
SLEEP_DRUG_2 = [1.9, 0.8, 1.1, 0.1, -0.1, 4.4, 5.5, 1.6, 4.6, 3.4]


def build_sleep() -> None:
    write(
        "sleep_cushny_peebles",
        """
        SOURCE: Cushny, A. R. and Peebles, A. R. (1905). "The action of optical isomers: II.
          Hyoscines." The Journal of Physiology 32, 501-510. Reproduced by Student (1908), "The
          probable error of a mean", Biometrika 6(1), 1-25, as the worked example of the t-test,
          and distributed with R as the `sleep` dataset (R Core Team, `datasets` package).
        DATA: extra hours of sleep gained by 10 patients on each of two soporific drugs, in
          patient order, so the two columns are paired.
        CERTIFIES: the paired t-test result quoted by R's documented
          `t.test(extra ~ group, data = sleep, paired = TRUE)`: t = -4.0621 on 9 df, p = 0.002833;
          and Welch's two-sample t on the same columns: t = -1.8608, df = 17.7765, p = 0.079394.
          Everything else in this file is derived longhand in the test from the textbook formula.
        VALIDATES: paired_t, t1, z1, t2 (Welch and pooled), var1, var2, normality, descriptives.
        """,
        {
            "meta": {
                "name": "Student's sleep data",
                "citation": "Cushny & Peebles (1905); Student (1908) Biometrika 6(1):1-25",
                "n": len(SLEEP_DRUG_1),
            },
            "data": {"drug1": SLEEP_DRUG_1, "drug2": SLEEP_DRUG_2},
            "expected": {
                "kind": "published",
                "paired_t_statistic": -4.062127683382037,
                "paired_df": 9,
                "paired_p_value": 0.002832890197384272,
                "welch_t_statistic": -1.8608134674868526,
                "welch_df": 17.776473516178488,
                "welch_p_value": 0.0793941401873583,
                "pooled_t_statistic": -1.8608134674868524,
                "pooled_df": 18,
                "pooled_p_value": 0.07918671421593823,
            },
        },
    )


# --- 2. Anscombe's quartet ---------------------------------------------------------------------

ANSCOMBE_X123 = [10.0, 8.0, 13.0, 9.0, 11.0, 14.0, 6.0, 4.0, 12.0, 7.0, 5.0]
ANSCOMBE_X4 = [8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 19.0, 8.0, 8.0, 8.0]
ANSCOMBE_Y1 = [8.04, 6.95, 7.58, 8.81, 8.33, 9.96, 7.24, 4.26, 10.84, 4.82, 5.68]
ANSCOMBE_Y2 = [9.14, 8.14, 8.74, 8.77, 9.26, 8.10, 6.13, 3.10, 9.13, 7.26, 4.74]
ANSCOMBE_Y3 = [7.46, 6.77, 12.74, 7.11, 7.81, 8.84, 6.08, 5.39, 8.15, 6.42, 5.73]
ANSCOMBE_Y4 = [6.58, 5.76, 7.71, 8.84, 8.47, 7.04, 5.25, 12.50, 5.56, 7.91, 6.89]


def build_anscombe() -> None:
    write(
        "anscombe_quartet",
        """
        SOURCE: Anscombe, F. J. (1973). "Graphs in Statistical Analysis." The American Statistician
          27(1), 17-21, Table 1. Distributed with R as the `anscombe` dataset.
        DATA: four x/y pairs of 11 points each, constructed so that all four share the same simple
          linear regression while looking nothing like each other.
        CERTIFIES: the summary Anscombe prints as common to all four sets — intercept 3.00,
          slope 0.500, r-squared 0.667, standard error of slope 0.118, t = 4.24, regression sum of
          squares 27.50 on 1 df and residual sum of squares 13.75 on 9 df.
        NOTE ON PRECISION: the four sets are identical only to the precision Anscombe prints. The
          actual regression sums of squares are 27.51 / 27.50 / 27.47 / 27.49 and the r-squareds
          0.66654 / 0.66624 / 0.66632 / 0.66671. The tests therefore compare against these
          published figures with an ABSOLUTE tolerance matching the printed decimals, and compare
          against the longhand least-squares formulas at full precision separately.
        VALIDATES: fitted_line, fit_model, correlation.
        """,
        {
            "meta": {
                "name": "Anscombe's quartet",
                "citation": "Anscombe, F. J. (1973). The American Statistician 27(1):17-21",
                "n": 11,
            },
            "data": {
                "x1": ANSCOMBE_X123,
                "x2": ANSCOMBE_X123,
                "x3": ANSCOMBE_X123,
                "x4": ANSCOMBE_X4,
                "y1": ANSCOMBE_Y1,
                "y2": ANSCOMBE_Y2,
                "y3": ANSCOMBE_Y3,
                "y4": ANSCOMBE_Y4,
            },
            "expected": {
                "kind": "published",
                "intercept": 3.0,
                "slope": 0.5,
                "r_squared": 0.667,
                "se_slope": 0.118,
                "t_slope": 4.24,
                "regression_ss": 27.5,
                "residual_ss": 13.75,
                "atol_coefficient": 0.005,
                "atol_r_squared": 0.001,
                "atol_sum_of_squares": 0.03,
                "tolerance_note": (
                    "Anscombe rounds to 2-3 decimals in the paper, so these are compared with an "
                    "absolute tolerance matching the printed precision, not the suite default. The "
                    "full-precision check is against the longhand least-squares formulas instead."
                ),
            },
        },
    )


# --- 3. Fisher's iris --------------------------------------------------------------------------


def build_iris() -> None:
    from sklearn.datasets import load_iris

    frame = load_iris(as_frame=True).frame
    names = ["setosa", "versicolor", "virginica"]
    write(
        "iris_fisher",
        """
        SOURCE: Fisher, R. A. (1936). "The use of multiple measurements in taxonomic problems."
          Annals of Eugenics 7(2), 179-188; data collected by Anderson, E. (1935). Retrieved from
          the copy distributed with scikit-learn (`sklearn.datasets.load_iris`), which is the UCI
          Machine Learning Repository version.
        DATA: 150 flowers, 50 of each of three species, four measurements in centimetres.
        CERTIFIES: the one-way MANOVA of the four measurements on species, whose Wilks' lambda of
          0.023439 (F = 199.145 on 8 and 288 df) is the statistic reproduced across the literature
          and by statsmodels' own MANOVA example.
        VALIDATES: manova, one_way, glm, correlation, VIF, Tukey comparisons.
        NOTE: sklearn's copy has two values that differ from Fisher's printed table (rows 35 and
          38) — a discrepancy documented by UCI and inherited here deliberately, because the
          certified MANOVA statistic above is the one computed FROM this copy.
        """,
        {
            "meta": {
                "name": "Fisher's iris",
                "citation": "Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188",
                "n": 150,
            },
            "data": {
                "sepal_length": [float(v) for v in frame["sepal length (cm)"]],
                "sepal_width": [float(v) for v in frame["sepal width (cm)"]],
                "petal_length": [float(v) for v in frame["petal length (cm)"]],
                "petal_width": [float(v) for v in frame["petal width (cm)"]],
                "species": [names[int(v)] for v in frame["target"]],
            },
            "expected": {
                "kind": "published",
                "wilks_lambda": 0.023438630650878298,
                "wilks_f": 199.14534354008438,
                "wilks_num_df": 8,
                "wilks_den_df": 288.0,
                "pillai_trace": 1.1918988250414653,
                "pillai_f": 53.46648878461304,
            },
        },
    )


# --- 4. Spector & Mazzeo grades (logistic) -------------------------------------------------------


def build_spector() -> None:
    import statsmodels.api as sm

    data = sm.datasets.spector.load_pandas().data
    write(
        "spector_grades",
        """
        SOURCE: Spector, L. and Mazzeo, M. (1980). "Probit Analysis and Economic Education."
          Journal of Economic Education 11, 37-44. Retrieved from the copy distributed with
          statsmodels (`statsmodels.api.datasets.spector`), which is the dataset statsmodels uses
          as its own documented Logit example.
        DATA: 32 students. GRADE is 1 if the grade improved; PSI is 1 if the student was taught by
          a personalised system of instruction; GPA and TUCE are prior attainment scores.
        CERTIFIES: the maximum-likelihood logit coefficients printed in statsmodels' Logit example
          output: const -13.0213, GPA 2.8261, TUCE 0.0952, PSI 2.3787, and the corresponding odds
          ratios exp(coef). Log-likelihood at convergence -12.8896.
        VALIDATES: binary_logistic (coefficients, odds ratios), binary_fitted_line.
        """,
        {
            "meta": {
                "name": "Spector & Mazzeo economics grades",
                "citation": "Spector, L. and Mazzeo, M. (1980). Journal of Economic Education 11:37-44",
                "n": int(len(data)),
            },
            "data": {
                "gpa": [float(v) for v in data["GPA"]],
                "tuce": [float(v) for v in data["TUCE"]],
                "psi": [int(v) for v in data["PSI"]],
                "grade": [int(v) for v in data["GRADE"]],
            },
            "expected": {
                "kind": "published",
                "terms": ["Constant", "gpa", "tuce", "psi"],
                "coefficients": [-13.021347014669962, 2.8261124070685617, 0.09515765001172263, 2.378688367882394],
                "odds_ratios": [2.212774348e-06, 16.879714, 1.099832, 10.790733],
                "log_likelihood": -12.889633,
            },
        },
    )


# --- 5. Capital punishment (Poisson regression) --------------------------------------------------


CPUNISH_PREDICTORS = ["INCOME", "PERPOVERTY", "PERBLACK", "VC100k96", "SOUTH", "DEGREE"]


def _cpunish_irls():
    import statsmodels.api as sm

    from backend.tests.reference_impl import poisson_coefficients

    data = sm.datasets.cpunish.load_pandas().data
    return poisson_coefficients([data[c].to_numpy(float) for c in CPUNISH_PREDICTORS], data["EXECUTIONS"].to_numpy(float))


def build_cpunish() -> None:
    import statsmodels.api as sm

    data = sm.datasets.cpunish.load_pandas().data
    write(
        "cpunish_executions",
        """
        SOURCE: Agresti, A. (1996). An Introduction to Categorical Data Analysis. Wiley. Retrieved
          from the copy distributed with statsmodels (`statsmodels.api.datasets.cpunish`), which is
          the dataset statsmodels uses as its own documented Poisson GLM example.
        DATA: 17 US states in 1997 — executions carried out, median income, poverty rate, percent
          black, violent crime rate, a South indicator, and percent with a degree.
        CERTIFIES: the DATA is published; the coefficients below are NOT quoted from Agresti and
          are marked `kind = "reference-implementation"` accordingly. They come from fitting the
          log-link Poisson GLM with an intercept, and the test re-derives them from scratch with a
          plain Iteratively Reweighted Least Squares loop written out longhand — so what is being
          checked is Gosset against the IRLS definition, not Gosset against another call to the
          same library function.
        VALIDATES: poisson_regression (coefficients, incidence-rate ratios).
        """,
        {
            "meta": {
                "name": "US capital punishment, 1997",
                "citation": "Agresti, A. (1996). An Introduction to Categorical Data Analysis. Wiley.",
                "n": int(len(data)),
            },
            "data": {
                "executions": [int(v) for v in data["EXECUTIONS"]],
                "income": [float(v) for v in data["INCOME"]],
                "perpoverty": [float(v) for v in data["PERPOVERTY"]],
                "perblack": [float(v) for v in data["PERBLACK"]],
                "vc100k96": [float(v) for v in data["VC100k96"]],
                "south": [float(v) for v in data["SOUTH"]],
                "degree": [float(v) for v in data["DEGREE"]],
            },
            "expected": {
                "kind": "reference-implementation",
                "terms": ["Constant", "income", "perpoverty", "perblack", "vc100k96", "south", "degree"],
                "coefficients": [float(v) for v in _cpunish_irls()],
                "note": (
                    "Log-link Poisson GLM with an intercept, fitted by the longhand IRLS loop in "
                    "this script (the same loop the test re-runs). Not a published figure."
                ),
            },
        },
    )


# --- 6. Bortkiewicz's horse kicks (Poisson goodness of fit) ---------------------------------------


def build_horse_kicks() -> None:
    counts = [0] * 109 + [1] * 65 + [2] * 22 + [3] * 3 + [4] * 1
    write(
        "horse_kicks_bortkiewicz",
        """
        SOURCE: von Bortkiewicz, L. (1898). Das Gesetz der kleinen Zahlen. Leipzig: Teubner.
          The canonical Poisson example: deaths by horse kick in 14 corps of the Prussian army
          over 20 years, 200 corps-years in total.
        DATA: one row per corps-year, holding that year's number of deaths. The published frequency
          table is 0:109, 1:65, 2:22, 3:3, 4:1 — expanded to 200 rows here because Gosset's
          Poisson goodness-of-fit dialog takes a column of counts, not a frequency table.
        CERTIFIES: the sample mean of 0.61 deaths per corps-year that Bortkiewicz reports, and the
          Poisson fit that follows from it. The chi-square statistic itself is derived longhand in
          the test, since the published analysis predates the modern grouping convention.
        VALIDATES: poisson_gof, poisson1, display_descriptives.
        """,
        {
            "meta": {
                "name": "Prussian cavalry deaths by horse kick",
                "citation": "von Bortkiewicz, L. (1898). Das Gesetz der kleinen Zahlen. Teubner.",
                "n": 200,
            },
            "data": {"deaths": counts, "frequency_table": [109, 65, 22, 3, 1]},
            "expected": {"kind": "published", "mean": 0.61, "total_deaths": 122, "corps_years": 200},
        },
    )


# --- 7. Smoking and lung cancer in Beijing (chi-square independence) -------------------------------


def build_china_smoking() -> None:
    write(
        "beijing_smoking_lung_cancer",
        """
        SOURCE: Liu, Z. (1992). "Smoking and lung cancer incidence in China."
          International Journal of Epidemiology 21, 197-201. Retrieved from the copy distributed
          with statsmodels (`statsmodels.api.datasets.china_smoking`), Beijing stratum.
        DATA: a 2x2 table of 322 people — smoker yes/no against lung cancer yes/no.
          smoker & cancer 126, smoker & no cancer 100, non-smoker & cancer 35, neither 61.
          Expanded to one row per person, because the chi-square dialog cross-tabulates two columns.
        CERTIFIES: the 2x2 counts as published. The chi-square statistic, its Yates correction and
          the odds ratio are all derived longhand in the test from the counts.
        VALIDATES: chi_square (test of independence).
        """,
        {
            "meta": {
                "name": "Beijing smoking and lung cancer",
                "citation": "Liu, Z. (1992). International Journal of Epidemiology 21:197-201",
                "n": 322,
            },
            "data": {
                "smoker_cancer": 126,
                "smoker_no_cancer": 100,
                "nonsmoker_cancer": 35,
                "nonsmoker_no_cancer": 61,
            },
            "expected": {"kind": "hand", "total": 322},
        },
    )


# --- 8. Grubbs outlier example --------------------------------------------------------------------

GRUBBS_VALUES = [199.31, 199.53, 200.19, 200.82, 201.92, 201.95, 202.18, 245.57]


def build_grubbs() -> None:
    write(
        "grubbs_mass_spectrometer",
        """
        SOURCE: NIST/SEMATECH e-Handbook of Statistical Methods, section 1.3.5.17 "Detection of
          Outliers", Grubbs' test example. https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h1.htm
          The underlying test is Grubbs, F. E. (1969), "Procedures for Detecting Outlying
          Observations in Samples", Technometrics 11(1), 1-21.
        DATA: eight mass-spectrometer measurements, the last of which is the suspected outlier.
        CERTIFIES: the handbook's worked answer G = 2.4687 for the largest value, against a
          5% critical value of 2.126 for n = 8, so the outlier is flagged.
        VALIDATES: outlier (Grubbs), and the Dixon variant on the same data.
        """,
        {
            "meta": {
                "name": "NIST handbook Grubbs example",
                "citation": "NIST/SEMATECH e-Handbook of Statistical Methods, 1.3.5.17",
                "n": len(GRUBBS_VALUES),
            },
            "data": {"measurement": GRUBBS_VALUES},
            "expected": {
                "kind": "published",
                "grubbs_g": 2.4687,
                "grubbs_critical_5pct": 2.126,
                "outlier_value": 245.57,
                "significant": True,
            },
        },
    )


# --- 9. Clopper-Pearson proportion ----------------------------------------------------------------


def build_proportions() -> None:
    write(
        "proportions_clopper_pearson",
        """
        SOURCE: Clopper, C. J. and Pearson, E. S. (1934). "The use of confidence or fiducial limits
          illustrated in the case of the binomial." Biometrika 26(4), 404-413 — the exact interval
          Gosset labels "Exact (binomial)". The two cases below are the ones used throughout the
          literature to illustrate it.
        DATA: two summarised binomial samples.
        CERTIFIES: nothing is taken on trust here. The exact interval is the pair of Beta quantiles
          Clopper and Pearson define — lower = Beta(k, n-k+1) at alpha/2, upper = Beta(k+1, n-k) at
          1-alpha/2 — and the exact two-sided p-value is a sum of binomial terms, both of which the
          test computes independently of Gosset's code path.
        VALIDATES: prop1 (exact and normal), prop2.
        """,
        {
            "meta": {
                "name": "Clopper-Pearson exact binomial interval",
                "citation": "Clopper, C. J. and Pearson, E. S. (1934). Biometrika 26(4):404-413",
                "n": 2,
            },
            "data": {
                "case1_events": 3,
                "case1_trials": 10,
                "case1_hypothesized_p": 0.5,
                "case2_events": 82,
                "case2_trials": 100,
                "case2_hypothesized_p": 0.75,
                "two_sample_events": [51, 74],
                "two_sample_trials": [100, 100],
            },
            "expected": {"kind": "hand"},
        },
    )


# --- 10. Nile flow (forecasting) ------------------------------------------------------------------


def build_nile() -> None:
    import statsmodels.api as sm

    data = sm.datasets.nile.load_pandas().data
    write(
        "nile_flow",
        """
        SOURCE: Cobb, G. W. (1978). "The problem of the Nile: conditional solution to a change
          point problem." Biometrika 65, 243-251. Retrieved from the copy distributed with
          statsmodels (`statsmodels.api.datasets.nile`), one of statsmodels' own documented time
          series examples.
        DATA: annual flow volume of the Nile at Aswan, 1871-1970, 100 observations.
        CERTIFIES: nothing about the forecast VALUES is published to compare against, so this file
          supports property and cross-implementation checks rather than a certified number: the
          test refits the same ETS and ARIMA specifications directly through statsmodels and
          requires Gosset's forecasts to match, and requires the prediction intervals to bracket
          the point forecasts.
        VALIDATES: forecasting (ETS, ARIMA) as a cross-implementation check, not a certified one.
        """,
        {
            "meta": {
                "name": "Nile annual flow at Aswan",
                "citation": "Cobb, G. W. (1978). Biometrika 65:243-251",
                "n": int(len(data)),
            },
            "data": {
                "year": [int(v) for v in data["year"]],
                "volume": [float(v) for v in data["volume"]],
            },
            "expected": {"kind": "hand"},
        },
    )


if __name__ == "__main__":
    print("writing published reference data...")
    build_sleep()
    build_anscombe()
    build_iris()
    build_spector()
    build_cpunish()
    build_horse_kicks()
    build_china_smoking()
    build_grubbs()
    build_proportions()
    build_nile()
    print("done")
