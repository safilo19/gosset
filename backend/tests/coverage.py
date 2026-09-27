"""The coverage registry: every statistical procedure, how to run it, and how well it is validated.

This is the single source of truth behind three things, which is the point of it existing:

1. `test_properties_sweep.py` runs every entry and applies the universal invariants, so no procedure
   escapes the property checks just because nobody wrote a bespoke test for it;
2. `test_coverage_registry.py` asserts the registry names EVERY procedure the app dispatches, so
   adding one to `_HANDLERS` without recording its validation status fails the suite;
3. `generate_validation.py` renders VALIDATION.md from it, including the honest `NOT YET VALIDATED`
   rows — the gaps are generated, not curated, so they cannot be quietly dropped.

`tier` is one of:

  nist       — checked against a NIST StRD certified value
  published  — checked against a value published in a cited source
  reference  — checked against an independently coded textbook formula (see reference_impl.py)
  snapshot   — fixed-seed golden snapshot plus seed-independent properties
  properties — exercised by the sweep and the universal invariants only
  none       — NOT YET VALIDATED

A procedure at `properties` is not unvalidated: its outputs are checked to be probabilities,
non-negative errors, ordered intervals and so on. It is simply not checked against a number anyone
else computed, and VALIDATION.md says exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.tests import fixtures as fx
from backend.tests.harness import run_anova, run_basic_stats, run_calc, run_graph, run_regression

TIERS = ("nist", "published", "reference", "snapshot", "properties", "none")

TIER_LABEL = {
    "nist": "NIST-certified",
    "published": "Published example",
    "reference": "Textbook formula",
    "snapshot": "Snapshot + properties",
    "properties": "Properties only",
    "none": "NOT YET VALIDATED",
}


@dataclass(frozen=True)
class Entry:
    key: str  # "basic_stats.t1"
    menu: str  # where the user finds it
    tier: str
    sources: tuple[str, ...] = ()
    invoke: Callable[[], Any] | None = None
    note: str = ""
    # Set when the procedure is KNOWN to break a universal invariant. The sweep then requires the
    # violation to still happen, so the day it is fixed the suite says so instead of going quiet.
    known_issue: str = ""

    @property
    def module(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def procedure(self) -> str:
        return self.key.split(".", 1)[1]


REGISTRY: list[Entry] = []


def add(key: str, menu: str, tier: str, sources: tuple[str, ...] = (), invoke=None, note: str = "", known_issue: str = "") -> None:
    assert tier in TIERS, f"{key}: unknown tier {tier!r}"
    REGISTRY.append(Entry(key, menu, tier, sources, invoke, note, known_issue))


NIST_UNIVARIATE = ("NIST StRD Univariate Summary Statistics (9 sets)",)
NIST_LLS = ("NIST StRD Linear Least Squares (9 fittable sets)",)
NIST_ANOVA = ("NIST StRD Analysis of Variance (11 sets)",)
SLEEP = ("Cushny & Peebles (1905) / Student (1908), via R's `sleep`",)
ANSCOMBE = ("Anscombe, F. J. (1973). The American Statistician 27(1):17-21",)
IRIS = ("Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188",)
SPECTOR = ("Spector & Mazzeo (1980). Journal of Economic Education 11:37-44",)
AGRESTI = ("Agresti, A. (1996). An Introduction to Categorical Data Analysis",)
BORTKIEWICZ = ("von Bortkiewicz, L. (1898). Das Gesetz der kleinen Zahlen",)
LIU = ("Liu, Z. (1992). International Journal of Epidemiology 21:197-201",)
GRUBBS_SOURCE = ("NIST/SEMATECH e-Handbook 1.3.5.17; Grubbs (1969) Technometrics 11(1)",)
CLOPPER = ("Clopper & Pearson (1934). Biometrika 26(4):404-413",)
COBB = ("Cobb, G. W. (1978). Biometrika 65:243-251 (Nile), via statsmodels",)


# --- Stat > Basic Statistics ------------------------------------------------------------------

add("basic_stats.display_descriptives", "Stat > Basic Statistics > Display Descriptive Statistics", "nist",
    NIST_UNIVARIATE + SLEEP, lambda: run_basic_stats(fx.iris(), "display_descriptives", ["sepal_length", "sepal_width"], {"group_column": "species"}))
add("basic_stats.store_descriptives", "Stat > Basic Statistics > Store Descriptive Statistics", "properties",
    (), lambda: run_basic_stats(fx.iris(), "store_descriptives", ["sepal_length"], {"group_column": "species"}))
add("basic_stats.graphical_summary", "Stat > Basic Statistics > Graphical Summary", "properties",
    (), lambda: run_basic_stats(fx.sleep(), "graphical_summary", ["drug1"], {}))
add("basic_stats.z1", "Stat > Basic Statistics > 1-Sample Z", "reference",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "z1", ["drug1"], {"sigma": 2.0}))
add("basic_stats.t1", "Stat > Basic Statistics > 1-Sample t", "published",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "t1", ["drug1"], {}))
add("basic_stats.t2", "Stat > Basic Statistics > 2-Sample t", "published",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "t2", ["drug1", "drug2"], {"layout": "two_columns"}))
add("basic_stats.paired_t", "Stat > Basic Statistics > Paired t", "published",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "paired_t", ["drug1", "drug2"], {}))
add("basic_stats.prop1", "Stat > Basic Statistics > 1 Proportion", "published",
    CLOPPER, lambda: run_basic_stats(fx.blank(), "prop1", [], {"input": "summarized", "events": 3, "trials": 10}))
add("basic_stats.prop2", "Stat > Basic Statistics > 2 Proportions", "reference",
    CLOPPER, lambda: run_basic_stats(fx.blank(), "prop2", [], {"input": "summarized", "events1": 51, "trials1": 100, "events2": 74, "trials2": 100}))
add("basic_stats.poisson1", "Stat > Basic Statistics > 1-Sample Poisson Rate", "published",
    BORTKIEWICZ, lambda: run_basic_stats(fx.horse_kicks(), "poisson1", ["deaths"], {"hypothesized_rate": 0.61}))
add("basic_stats.poisson2", "Stat > Basic Statistics > 2-Sample Poisson Rate", "properties",
    (), lambda: run_basic_stats(fx.grid(), "poisson2", ["pest_count", "weed_count"], {}))
add("basic_stats.var1", "Stat > Basic Statistics > 1 Variance", "reference",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "var1", ["drug1"], {"hypothesized_value": 4.0}))
add("basic_stats.var2", "Stat > Basic Statistics > 2 Variances", "reference",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "var2", ["drug1", "drug2"], {"layout": "two_columns"}))
add("basic_stats.correlation", "Stat > Basic Statistics > Correlation", "published",
    ANSCOMBE + IRIS, lambda: run_basic_stats(fx.iris(), "correlation", ["sepal_length", "petal_length", "petal_width"], {}))
add("basic_stats.covariance", "Stat > Basic Statistics > Covariance", "properties",
    (), lambda: run_basic_stats(fx.iris(), "covariance", ["sepal_length", "petal_length"], {}))
add("basic_stats.normality", "Stat > Basic Statistics > Normality Test", "published",
    SLEEP, lambda: run_basic_stats(fx.sleep(), "normality", ["drug1"], {"method": "shapiro_wilk"}))
add("basic_stats.outlier", "Stat > Basic Statistics > Outlier Test", "published",
    GRUBBS_SOURCE, lambda: run_basic_stats(fx.iris(), "outlier", ["sepal_width"], {"method": "grubbs"}))
add("basic_stats.poisson_gof", "Stat > Basic Statistics > Poisson Goodness-of-Fit Test", "published",
    BORTKIEWICZ, lambda: run_basic_stats(fx.horse_kicks(), "poisson_gof", ["deaths"], {}))


# --- Stat > Regression ---------------------------------------------------------------------------


def _fit_for_predict():
    fitted = run_regression(fx.iris(), "fit_model", ["sepal_length", "petal_length"], {"n_continuous": 1, "graph_residuals": False})
    return run_regression(fx.iris(), "predict", [], {"spec": fitted["predict_spec"], "values": {"petal_length": 4.0}})


add("regression_models.fitted_line", "Stat > Regression > Fitted Line Plot", "published",
    ANSCOMBE, lambda: run_regression(fx.anscombe(), "fitted_line", ["y1", "x1"], {}))
add("regression_models.fit_model", "Stat > Regression > Fit Regression Model", "nist",
    NIST_LLS + ANSCOMBE, lambda: run_regression(fx.iris(), "fit_model", ["sepal_length", "sepal_width", "petal_length"], {"n_continuous": 2, "graph_residuals": False}))
add("regression_models.predict", "Stat > Regression > Predict", "properties", (), _fit_for_predict)
add("regression_models.best_subsets", "Stat > Regression > Best Subsets", "properties",
    (), lambda: run_regression(fx.iris(), "best_subsets", ["sepal_length", "sepal_width", "petal_length", "petal_width"], {"n_continuous": 3}),
    known_issue="exceeds 1", note="Reports R-squared as a PERCENTAGE where Fit Regression Model, Fitted Line Plot, One-Way ANOVA and the GLM all report a fraction. See test_properties_sweep.py::test_the_r_squared_scale_is_inconsistent_across_three_procedures.")
add("regression_models.stepwise", "Stat > Regression > Stepwise", "properties",
    (), lambda: run_regression(fx.iris(), "stepwise", ["sepal_length", "sepal_width", "petal_length", "petal_width"], {"n_continuous": 3, "graph_residuals": False}),
    known_issue="exceeds 1", note="Reports R-squared as a PERCENTAGE where Fit Regression Model, Fitted Line Plot, One-Way ANOVA and the GLM all report a fraction. See test_properties_sweep.py::test_the_r_squared_scale_is_inconsistent_across_three_procedures.")
add("regression_models.nonlinear", "Stat > Regression > Nonlinear Regression", "properties",
    (), lambda: run_regression(fx.stability(), "nonlinear", ["potency_pct", "month"], {"formula": "theta1 * exp(theta2 * month)", "starting_values": "theta1=100, theta2=-0.01"}))
add("regression_models.orthogonal", "Stat > Regression > Orthogonal Regression", "properties",
    (), lambda: run_regression(fx.anscombe(), "orthogonal", ["y1", "x1"], {"error_ratio": 1.0}))
add("regression_models.pls", "Stat > Regression > Partial Least Squares", "properties",
    (), lambda: run_regression(fx.iris(), "pls", ["sepal_length", "sepal_width", "petal_length", "petal_width"], {"n_continuous": 3, "components": 2}),
    known_issue="exceeds 1",
    note=(
        "Returns the top-level `r_squared` as a PERCENTAGE (79.37) where every other procedure "
        "returns a fraction. The on-screen highlight is right because it carries suffix '%', but "
        "report_engine/verdict.py reads `r_squared` straight and prints 'R2 = 79.366' on the PDF "
        "badge. See test_properties_sweep.py::test_pls_reports_r_squared_as_a_percentage."
    ))
add("regression_models.stability", "Stat > Regression > Stability Study", "properties",
    (), lambda: run_regression(fx.stability(), "stability", ["potency_pct", "month", "batch"], {"spec_limit": 90.0, "spec_side": "lower"}))
add("regression_models.binary_fitted_line", "Stat > Regression > Binary Fitted Line Plot", "properties",
    SPECTOR, lambda: run_regression(fx.spector(), "binary_fitted_line", ["grade", "gpa"], {}))
add("regression_models.binary_logistic", "Stat > Regression > Binary Logistic Regression", "published",
    SPECTOR, lambda: run_regression(fx.spector(), "binary_logistic", ["grade", "gpa", "tuce", "psi"], {"n_continuous": 3}))
add("regression_models.ordinal_logistic", "Stat > Regression > Ordinal Logistic Regression", "properties",
    (), lambda: run_regression(fx.ordinal(), "ordinal_logistic", ["grade", "x1", "x2"], {"n_continuous": 2}))
add("regression_models.nominal_logistic", "Stat > Regression > Nominal Logistic Regression", "properties",
    (), lambda: run_regression(fx.ordinal(), "nominal_logistic", ["grade", "x1", "x2"], {"n_continuous": 2}))
add("regression_models.poisson_regression", "Stat > Regression > Poisson Regression", "published",
    AGRESTI, lambda: run_regression(fx.cpunish(), "poisson_regression", ["executions", "income", "perpoverty", "perblack", "vc100k96", "south", "degree"], {"n_continuous": 6}))


# --- Stat > ANOVA ------------------------------------------------------------------------------------

# Two factors then two covariates: the contour and surface dialogs need two continuous
# predictors in the model, so the covariate pair is part of the fixture, not an afterthought.
GLM_COLUMNS = ["strength", "machine", "shift", "temp_c", "pressure_bar"]
GLM_OPTIONS = {"n_factors": 2, "graph_residuals": False}


def _glm_spec() -> dict:
    fitted = run_anova(fx.factorial(), "glm", GLM_COLUMNS, GLM_OPTIONS)
    return fitted["model_spec"]


def _mixed_spec() -> dict:
    fitted = run_anova(fx.factorial(), "mixed_model", ["strength", "machine", "operator"], {"n_fixed_factors": 1, "n_covariates": 0, "graph_residuals": False})
    return fitted["model_spec"]


add("anova.one_way", "Stat > ANOVA > One-Way", "nist",
    NIST_ANOVA + IRIS, lambda: run_anova(fx.iris(), "one_way", ["sepal_length", "species"], {"comparisons": "tukey", "graph": False}))
add("anova.equal_variances", "Stat > ANOVA > Test for Equal Variances", "reference",
    IRIS, lambda: run_anova(fx.iris(), "equal_variances", ["sepal_length", "species"], {}))
add("anova.balanced_anova", "Stat > ANOVA > Balanced ANOVA", "properties",
    (), lambda: run_anova(fx.factorial(), "balanced_anova", ["strength", "machine", "shift"], {"n_factors": 2, "graph_residuals": False}))
add("anova.nested_anova", "Stat > ANOVA > Fully Nested ANOVA", "properties",
    (), lambda: run_anova(fx.nested(), "nested_anova", ["purity_pct", "lot", "batch"], {"n_factors": 2}))
add("anova.manova", "Stat > ANOVA > General MANOVA", "published",
    IRIS, lambda: run_anova(fx.iris(), "manova", ["sepal_length", "sepal_width", "petal_length", "petal_width", "species"], {"n_responses": 4}))
add("anova.glm", "Stat > ANOVA > General Linear Model > Fit General Linear Model", "reference",
    IRIS, lambda: run_anova(fx.factorial(), "glm", GLM_COLUMNS, GLM_OPTIONS))
add("anova.glm_comparisons", "Stat > ANOVA > General Linear Model > Comparisons", "properties",
    (), lambda: run_anova(fx.factorial(), "glm_comparisons", [], {"model_spec": _glm_spec(), "factor": "machine", "method": "tukey"}))
add("anova.glm_predict", "Stat > ANOVA > General Linear Model > Predict", "properties",
    (), lambda: run_anova(fx.factorial(), "glm_predict", [], {"model_spec": _glm_spec(), "values": {"machine": "M1", "shift": "Day", "temp_c": 75.0}}))
add("anova.glm_factorial_plots", "Stat > ANOVA > General Linear Model > Factorial Plots", "properties",
    (), lambda: run_anova(fx.factorial(), "glm_factorial_plots", [], {"model_spec": _glm_spec()}))
add("anova.glm_contour", "Stat > ANOVA > General Linear Model > Contour Plot", "properties",
    (), lambda: run_anova(fx.factorial(), "glm_contour", [], {"model_spec": _glm_spec(), "x_factor": "temp_c", "y_factor": "pressure_bar"}))
add("anova.glm_surface", "Stat > ANOVA > General Linear Model > Surface Plot", "properties",
    (), lambda: run_anova(fx.factorial(), "glm_surface", [], {"model_spec": _glm_spec(), "x_factor": "temp_c", "y_factor": "pressure_bar"}))
add("anova.glm_optimizer", "Stat > ANOVA > General Linear Model > Response Optimizer", "properties",
    (), lambda: run_anova(fx.factorial(), "glm_optimizer", [], {"model_spec": _glm_spec(), "goal": "maximize"}))
add("anova.mixed_model", "Stat > ANOVA > Mixed Effects Model > Fit Mixed Effects Model", "properties",
    (), lambda: run_anova(fx.factorial(), "mixed_model", ["strength", "machine", "operator"], {"n_fixed_factors": 1, "n_covariates": 0, "graph_residuals": False}))
add("anova.mixed_comparisons", "Stat > ANOVA > Mixed Effects Model > Comparisons", "properties",
    (), lambda: run_anova(fx.factorial(), "mixed_comparisons", [], {"model_spec": _mixed_spec(), "factor": "machine", "method": "tukey"}))
add("anova.mixed_predict", "Stat > ANOVA > Mixed Effects Model > Predict", "properties",
    (), lambda: run_anova(fx.factorial(), "mixed_predict", [], {"model_spec": _mixed_spec(), "values": {"machine": "M1", "operator": "Ann"}}))
add("anova.mixed_factorial_plots", "Stat > ANOVA > Mixed Effects Model > Factorial Plots", "properties",
    (), lambda: run_anova(fx.factorial(), "mixed_factorial_plots", [], {"model_spec": _mixed_spec()}))
add("anova.interval_plot", "Stat > ANOVA > Interval Plot", "properties",
    (), lambda: run_anova(fx.iris(), "interval_plot", ["sepal_length", "species"], {}))
add("anova.main_effects_plot", "Stat > ANOVA > Main Effects Plot", "properties",
    (), lambda: run_anova(fx.factorial(), "main_effects_plot", ["strength", "machine", "shift"], {}))
add("anova.interaction_plot", "Stat > ANOVA > Interaction Plot", "properties",
    (), lambda: run_anova(fx.factorial(), "interaction_plot", ["strength", "machine", "shift"], {}))
add("anova.anom", "Stat > ANOVA > Analysis of Means", "properties",
    (), lambda: run_anova(fx.iris(), "anom", ["sepal_length", "species"], {}))


# --- Calc --------------------------------------------------------------------------------------------

MATRIX_A = [[4.0, 7.0], [2.0, 6.0]]

add("calc.calculator", "Calc > Calculator", "properties",
    (), lambda: run_calc(fx.iris(), "calculator", [], {"expression": "sepal_length * 2 + 1", "store_in": "C9"}))
add("calc.validate_expression", "Calc > Calculator (live validation)", "properties",
    (), lambda: run_calc(fx.iris(), "validate_expression", [], {"expression": "MEAN(sepal_length)"}))
add("calc.catalogue", "Calc > Random Data / Probability Distributions (shared catalogue)", "properties",
    (), lambda: run_calc(fx.blank(), "catalogue", [], {}),
    note="Not a statistic: the shared distribution list the two menus read, checked for consistency in test_distributions.py.")
add("calc.column_statistics", "Calc > Column Statistics", "nist",
    NIST_UNIVARIATE, lambda: run_calc(fx.iris(), "column_statistics", ["sepal_length"], {"statistic": "mean"}))
add("calc.row_statistics", "Calc > Row Statistics", "properties",
    (), lambda: run_calc(fx.iris(), "row_statistics", ["sepal_length", "sepal_width"], {"statistic": "mean", "store_in": "C9"}))
add("calc.standardize", "Calc > Standardize", "properties",
    (), lambda: run_calc(fx.iris(), "standardize", ["sepal_length"], {"method": "z", "store_in": ["C9"]}))
add("calc.patterned_numbers", "Calc > Make Patterned Data > Simple Set of Numbers", "properties",
    (), lambda: run_calc(fx.blank(), "patterned_numbers", [], {"start": 1, "end": 10, "step": 1, "store_in": "C1"}))
add("calc.patterned_arbitrary", "Calc > Make Patterned Data > Arbitrary Set of Numbers", "properties",
    (), lambda: run_calc(fx.blank(), "patterned_arbitrary", [], {"values": "1 2 3", "store_in": "C1"}))
add("calc.patterned_text", "Calc > Make Patterned Data > Text Values", "properties",
    (), lambda: run_calc(fx.blank(), "patterned_text", [], {"values": "a b c", "store_in": "C1"}))
add("calc.patterned_datetime", "Calc > Make Patterned Data > Date/Time Values", "properties",
    (), lambda: run_calc(fx.blank(), "patterned_datetime", [], {"mode": "simple", "from": "2026-01-01", "to": "2026-01-10", "store_in": "C1"}))
add("calc.mesh_data", "Calc > Make Mesh Data", "properties",
    (), lambda: run_calc(fx.blank(), "mesh_data", [], {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1, "x_points": 4, "y_points": 4, "store_x": "C1", "store_y": "C2"}))
add("calc.indicator_variables", "Calc > Make Indicator Variables", "properties",
    (), lambda: run_calc(fx.iris(), "indicator_variables", ["species"], {}))
add("calc.sample_columns", "Calc > Sample From Columns", "snapshot",
    (), lambda: run_calc(fx.iris(), "sample_columns", ["sepal_length"], {"rows": 10, "seed": 12345, "store_in": ["C9"]}))
add("calc.random_data", "Calc > Random Data > (26 distributions)", "snapshot",
    (), lambda: run_calc(fx.blank(), "random_data", [], {"distribution": "normal", "parameters": {"mean": 0, "sd": 1}, "rows": 10, "store_in": ["C1"], "seed": 12345}))
add("calc.probability", "Calc > Probability Distributions > (26 distributions)", "published",
    ("Standard statistical tables; scipy's documented distributions",), lambda: run_calc(fx.blank(), "probability", [], {"distribution": "normal", "mode": "cdf", "parameters": {"mean": 0, "sd": 1}, "input_value": 1.96}))
add("calc.bootstrap_1sample", "Calc > Resampling > Bootstrapping for 1-Sample Mean", "snapshot",
    (), lambda: run_calc(fx.sleep(), "bootstrap_1sample", ["drug1"], {"resamples": 200, "seed": 12345}))
add("calc.bootstrap_2sample", "Calc > Resampling > Bootstrapping for 2-Sample Means", "snapshot",
    (), lambda: run_calc(fx.sleep(), "bootstrap_2sample", ["drug1", "drug2"], {"layout": "two_columns", "resamples": 200, "seed": 12345}))
add("calc.randomization_1mean", "Calc > Resampling > Randomization Test for One Mean", "snapshot",
    (), lambda: run_calc(fx.sleep(), "randomization_1mean", ["drug1"], {"resamples": 200, "seed": 12345}))
add("calc.randomization_1proportion", "Calc > Resampling > Randomization Test for One Proportion", "snapshot",
    (), lambda: run_calc(fx.iris(), "randomization_1proportion", ["species"], {"event": "setosa", "null_value": 0.3333, "resamples": 200, "seed": 12345}))
add("calc.randomization_2means", "Calc > Resampling > Randomization Test for Two Means", "snapshot",
    (), lambda: run_calc(fx.sleep(), "randomization_2means", ["drug1", "drug2"], {"layout": "two_columns", "resamples": 200, "seed": 12345}))
add("calc.matrix_from_columns", "Calc > Matrices > Copy Columns to Matrix", "reference",
    (), lambda: run_calc(fx.anscombe(), "matrix_from_columns", ["x1", "y1"], {"store_in": "M1"}))
add("calc.matrix_to_columns", "Calc > Matrices > Copy Matrix to Columns", "reference",
    (), lambda: run_calc(fx.blank(), "matrix_to_columns", [], {"matrix": MATRIX_A, "store_prefix": "C"}))
add("calc.matrix_transpose", "Calc > Matrices > Transpose", "reference",
    (), lambda: run_calc(fx.blank(), "matrix_transpose", [], {"matrix": MATRIX_A, "store_in": "M2"}))
add("calc.matrix_invert", "Calc > Matrices > Invert", "reference",
    (), lambda: run_calc(fx.blank(), "matrix_invert", [], {"matrix": MATRIX_A, "store_in": "M2"}))
add("calc.matrix_diagonal", "Calc > Matrices > Diagonal", "reference",
    (), lambda: run_calc(fx.blank(), "matrix_diagonal", [], {"direction": "extract", "matrix": MATRIX_A, "store_in": "C1"}))
add("calc.matrix_define", "Calc > Matrices > Define Constant Matrix", "properties",
    (), lambda: run_calc(fx.blank(), "matrix_define", [], {"rows": 2, "columns": 2, "value": 1.0, "store_in": "M1"}))
add("calc.matrix_eigen", "Calc > Matrices > Eigen Analysis", "reference",
    (), lambda: run_calc(fx.blank(), "matrix_eigen", [], {"matrix": [[2.0, 1.0], [1.0, 2.0]], "store_values_in": "K1", "store_vectors_in": "M2"}))
add("calc.matrix_arithmetic", "Calc > Matrices > Arithmetic", "reference",
    (), lambda: run_calc(fx.blank(), "matrix_arithmetic", [], {"operation": "multiply", "left": MATRIX_A, "right": MATRIX_A, "store_in": "M3"}))


# --- the v1 analyses, which do not go through a compute() dispatch --------------------------------------

add("forecasting.run_forecast", "Stat > Time Series > Forecast", "properties",
    COBB, None, note="Cross-implementation check against a direct ETS/SARIMAX refit; no certified forecast exists.")
add("segmentation.run_kmeans", "Stat > Multivariate > Segmentation (k-means)", "snapshot", IRIS, None)
add("segmentation.run_rfm", "Stat > Multivariate > Segmentation (RFM)", "snapshot", (), None)
add("predictive.run_automl", "Predictive > AutoML", "snapshot", IRIS, None)
add("predictive.fit_decision_tree", "Predictive > Decision Tree", "properties", (), None)
add("predictive.fit_random_forest", "Predictive > Random Forest", "properties", (), None)
add("predictive.fit_gradient_boosting", "Predictive > Gradient Boosting", "properties", (), None)
add("regression.run_regression", "Predictive > Regression (v1)", "properties", (), None,
    note="Superseded by Stat > Regression > Fit Regression Model, which is NIST-validated.")
add("stats.describe_columns", "Assistant / chat `describe`", "properties", (), None)
add("stats.compute_correlation", "Assistant / chat `correlation`", "properties", (), None)
add("tests.run_hypothesis_test", "Stat > Tables > Chi-Square Test for Association", "published", LIU, None)


BY_KEY = {entry.key: entry for entry in REGISTRY}


def invocable() -> list[Entry]:
    return [entry for entry in REGISTRY if entry.invoke is not None]


def counts_by_tier() -> dict[str, int]:
    out = {tier: 0 for tier in TIERS}
    for entry in REGISTRY:
        out[entry.tier] += 1
    return out
