# Validation

This file is **generated** from `backend/tests/coverage.py` by `python -m backend.tests.generate_validation`, and `test_validation_manifest.py` fails if it drifts. It is generated rather than written so the unflattering rows cannot be quietly dropped: a procedure with no validation appears below because the registry says it has none.

**91 procedures.** 4 NIST-certified, 15 Published example, 13 Textbook formula, 10 Snapshot + properties, 49 Properties only.

**Read that carefully.** 32 of 91 procedures (35%) are checked against a value someone else computed. The other 59 are exercised and checked for internal consistency, and that is not the same thing: *Properties only* means nobody has confirmed the number is right, just that it is not obviously wrong. Those rows are a to-do list, not a clean bill of health.

## Summary

| Tier | Procedures | Share |
| --- | --- | --- |
| NIST-certified | 4 | 4% |
| Published example | 15 | 16% |
| Textbook formula | 13 | 14% |
| Snapshot + properties | 10 | 11% |
| Properties only | 49 | 54% |

## Reference data

**NIST StRD** — 31 certified datasets committed under `backend/tests/reference_data/nist/`, byte-exact copies of the published files so each can be diffed against its URL. Provenance (exact URL, retrieval date, what is certified, SHA-256) is in `manifest.json` and re-checked on every test run.

> National Institute of Standards and Technology, Information Technology Laboratory. Statistical Reference Datasets. https://www.itl.nist.gov/div898/strd/ (accessed 2026-07-30).

**Published examples** — 10 reference files under `backend/tests/reference_data/published/`, each a TOML file whose header comment carries the exact citation, what it certifies and the retrieval date:

| File | Source |
| --- | --- |
| `anscombe_quartet.toml` | Anscombe, F. J. (1973). The American Statistician 27(1):17-21 |
| `beijing_smoking_lung_cancer.toml` | Liu, Z. (1992). International Journal of Epidemiology 21:197-201 |
| `cpunish_executions.toml` | Agresti, A. (1996). An Introduction to Categorical Data Analysis. Wiley. |
| `grubbs_mass_spectrometer.toml` | NIST/SEMATECH e-Handbook of Statistical Methods, 1.3.5.17 |
| `horse_kicks_bortkiewicz.toml` | von Bortkiewicz, L. (1898). Das Gesetz der kleinen Zahlen. Teubner. |
| `iris_fisher.toml` | Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `nile_flow.toml` | Cobb, G. W. (1978). Biometrika 65:243-251 |
| `proportions_clopper_pearson.toml` | Clopper, C. J. and Pearson, E. S. (1934). Biometrika 26(4):404-413 |
| `sleep_cushny_peebles.toml` | Cushny & Peebles (1905); Student (1908) Biometrika 6(1):1-25 |
| `spector_grades.toml` | Spector, L. and Mazzeo, M. (1980). Journal of Economic Education 11:37-44 |

## Numerical limits

NIST grades its regression and ANOVA sets by difficulty on purpose, and the hard ones are where a package's arithmetic runs out. Measured on this build (Python 3.11, numpy 2.4, statsmodels 0.14, scipy 1.17), worst agreement in significant digits:

| Set | Difficulty | Digits | Note |
| --- | --- | --- | --- |
| Norris | Lower | 13.0 | full double precision |
| Pontius | Lower | 6.2 | uncentred quadratic in x ~ 1e6; a QR solve of the same matrix reaches 12.2 |
| Longley | Higher | 10.9 | the classic near-collinear case |
| Wampler1-3 | Higher | 9.4-10.2 |  |
| Wampler4 | Higher | 8.0 | signal swamped by 1e4 noise by construction |
| Wampler5 | Higher | 6.0 | signal swamped by 1e6 noise by construction |
| Filip | Higher | **0** | not fitted correctly — see Known issues |
| SmLs01-03 | Lower | 14.4-14.8 | one constant leading digit |
| SmLs04-06 | Average | 8.7-9.3 | seven constant leading digits |
| SmLs07-09 | Higher | 2.7-3.3 | thirteen constant leading digits. Converting those decimals to float64 costs ~4.0 digits before any statistic is computed, and the accumulation costs ~1.3 more; the budget is measured exactly in `test_smls07_precision_budget` |
| AtmWtAg | Average | 8.5 | between-group sum of squares of 3.6e-9 |
| NumAcc4 | Higher | 8.3 | univariate standard deviation of 0.1 on values of ~1e7 |

## Known issues the suite records

These are real defects found by this suite. Each is pinned by a strict `xfail`, so the day one is
fixed the suite says so rather than going quiet.

| What | Where | Effect |
| --- | --- | --- |
| **Filip is not fitted correctly** | `Stat > Regression > Fit Regression Model` | statsmodels' pseudo-inverse solve treats NIST's Filip design matrix as rank 10 of 11. The model silently loses a degree of freedom and returns a minimum-norm solution: **0 correct digits** in every coefficient and an R-squared wrong in the third digit, with no warning. A QR solve of the same matrix recovers ~7.9 digits, so this is the solver's rank cut-off rather than the data. Only reachable with a design matrix conditioned around 1e15 — a degree-10 polynomial in an uncentred x. |
| **R-squared reported on two different scales** | `Partial Least Squares`, `Best Subsets`, `Stepwise` | These three report R-squared as a percentage (75.99) where Fit Regression Model, Fitted Line Plot, One-Way ANOVA and the GLM report a fraction (0.7599). The arithmetic is right; the scale is not shared and nothing in the payload says which one applies. `report_engine/verdict.py` reads `r_squared` straight, so a PLS result's PDF verdict badge prints `R² = 79.366`. |
| **Saving a project rounds every float to ten decimal places** | `File > Save Project (.gsp)` | `datasets.json_safe_records` serialises with `DataFrame.to_json`, whose `double_precision` defaults to 10. The cut is on decimal places, so a worksheet of measurements is unaffected while a column of p-values or variance components is not: 1e-15 is written as `-0.0` and 3.638341875e-09 becomes `3.6e-09`. Nothing is said either way. |
| **Hypergeometric CDF is blank at a non-integer** | `Calc > Probability Distributions > Hypergeometric` | scipy's `hypergeom.cdf` returns NaN for a non-integer argument where `binom` and `poisson` floor it, and the value is passed straight through, so a cumulative probability at x = 3.3 shows an empty cell. Every other discrete distribution in the catalogue handles it. |

## Gaps

Procedures a reference dataset exists for, that Gosset cannot currently run:

| Certified data available | Why it cannot be used |
| --- | --- |
| NIST StRD **NoInt1**, **NoInt2** | Both certify a regression through the origin. Fit Regression Model always includes a constant — Minitab's "Fit intercept" checkbox has no equivalent. The datasets are committed and parsed; `test_no_intercept_is_a_known_gap` fails the day the option is added. |
| NIST StRD univariate **lag-1 autocorrelation** (9 sets) | There is no autocorrelation procedure. The nine certified r(1) values are parsed and unused; `test_lag1_autocorrelation_is_not_offered` fails the day one appears. |
| **Mendel's peas** (315/101/108/32 against 9:3:3:1) | There is a Poisson goodness-of-fit test but no general chi-square goodness-of-fit against arbitrary expected proportions. The reference answer is computed and asserted in the test that records the gap. |

## Coverage by tier

### NIST-certified (4)

Checked against a **NIST StRD certified value** — a dataset published by the National Institute of Standards and Technology together with results computed in multiple-precision arithmetic, for exactly this purpose.

| Procedure | Where | Reference |
| --- | --- | --- |
| `calc.column_statistics` | Calc > Column Statistics | NIST StRD Univariate Summary Statistics (9 sets) |
| `anova.one_way` | Stat > ANOVA > One-Way | NIST StRD Analysis of Variance (11 sets)<br>Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `basic_stats.display_descriptives` | Stat > Basic Statistics > Display Descriptive Statistics | NIST StRD Univariate Summary Statistics (9 sets)<br>Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `regression_models.fit_model` | Stat > Regression > Fit Regression Model | NIST StRD Linear Least Squares (9 fittable sets)<br>Anscombe, F. J. (1973). The American Statistician 27(1):17-21 |

### Published example (15)

Checked against a **number published in a cited source** — a textbook, a journal paper, or the documented output of the reference implementation that source describes.

| Procedure | Where | Reference |
| --- | --- | --- |
| `calc.probability` | Calc > Probability Distributions > (26 distributions) | Standard statistical tables; scipy's documented distributions |
| `anova.manova` | Stat > ANOVA > General MANOVA | Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `basic_stats.prop1` | Stat > Basic Statistics > 1 Proportion | Clopper & Pearson (1934). Biometrika 26(4):404-413 |
| `basic_stats.poisson1` | Stat > Basic Statistics > 1-Sample Poisson Rate | von Bortkiewicz, L. (1898). Das Gesetz der kleinen Zahlen |
| `basic_stats.t1` | Stat > Basic Statistics > 1-Sample t | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `basic_stats.t2` | Stat > Basic Statistics > 2-Sample t | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `basic_stats.correlation` | Stat > Basic Statistics > Correlation | Anscombe, F. J. (1973). The American Statistician 27(1):17-21<br>Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `basic_stats.normality` | Stat > Basic Statistics > Normality Test | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `basic_stats.outlier` | Stat > Basic Statistics > Outlier Test | NIST/SEMATECH e-Handbook 1.3.5.17; Grubbs (1969) Technometrics 11(1) |
| `basic_stats.paired_t` | Stat > Basic Statistics > Paired t | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `basic_stats.poisson_gof` | Stat > Basic Statistics > Poisson Goodness-of-Fit Test | von Bortkiewicz, L. (1898). Das Gesetz der kleinen Zahlen |
| `regression_models.binary_logistic` | Stat > Regression > Binary Logistic Regression | Spector & Mazzeo (1980). Journal of Economic Education 11:37-44 |
| `regression_models.fitted_line` | Stat > Regression > Fitted Line Plot | Anscombe, F. J. (1973). The American Statistician 27(1):17-21 |
| `regression_models.poisson_regression` | Stat > Regression > Poisson Regression | Agresti, A. (1996). An Introduction to Categorical Data Analysis |
| `tests.run_hypothesis_test` | Stat > Tables > Chi-Square Test for Association | Liu, Z. (1992). International Journal of Epidemiology 21:197-201 |

### Textbook formula (13)

Checked against a **textbook formula coded independently** in `backend/tests/reference_impl.py` — written out from the definition rather than by calling the same library function the app calls, which would prove only that the arguments were spelled right.

| Procedure | Where | Reference |
| --- | --- | --- |
| `calc.matrix_arithmetic` | Calc > Matrices > Arithmetic | — |
| `calc.matrix_from_columns` | Calc > Matrices > Copy Columns to Matrix | — |
| `calc.matrix_to_columns` | Calc > Matrices > Copy Matrix to Columns | — |
| `calc.matrix_diagonal` | Calc > Matrices > Diagonal | — |
| `calc.matrix_eigen` | Calc > Matrices > Eigen Analysis | — |
| `calc.matrix_invert` | Calc > Matrices > Invert | — |
| `calc.matrix_transpose` | Calc > Matrices > Transpose | — |
| `anova.glm` | Stat > ANOVA > General Linear Model > Fit General Linear Model | Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `anova.equal_variances` | Stat > ANOVA > Test for Equal Variances | Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `basic_stats.var1` | Stat > Basic Statistics > 1 Variance | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `basic_stats.z1` | Stat > Basic Statistics > 1-Sample Z | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |
| `basic_stats.prop2` | Stat > Basic Statistics > 2 Proportions | Clopper & Pearson (1934). Biometrika 26(4):404-413 |
| `basic_stats.var2` | Stat > Basic Statistics > 2 Variances | Cushny & Peebles (1905) / Student (1908), via R's `sleep` |

### Snapshot + properties (10)

**Fixed-seed golden snapshot plus seed-independent properties.** These procedures resample, cluster or cross-validate, so there is no reference value to aim at. The snapshot detects change; the properties (a bootstrap interval contains its estimate, a permutation p-value matches an exactly enumerable case, clusters partition every row) are the correctness part.

| Procedure | Where | Reference |
| --- | --- | --- |
| `calc.random_data` | Calc > Random Data > (26 distributions) | — |
| `calc.bootstrap_1sample` | Calc > Resampling > Bootstrapping for 1-Sample Mean | — |
| `calc.bootstrap_2sample` | Calc > Resampling > Bootstrapping for 2-Sample Means | — |
| `calc.randomization_1mean` | Calc > Resampling > Randomization Test for One Mean | — |
| `calc.randomization_1proportion` | Calc > Resampling > Randomization Test for One Proportion | — |
| `calc.randomization_2means` | Calc > Resampling > Randomization Test for Two Means | — |
| `calc.sample_columns` | Calc > Sample From Columns | — |
| `predictive.run_automl` | Predictive > AutoML | Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |
| `segmentation.run_rfm` | Stat > Multivariate > Segmentation (RFM) | — |
| `segmentation.run_kmeans` | Stat > Multivariate > Segmentation (k-means) | Fisher, R. A. (1936). Annals of Eugenics 7(2):179-188 |

### Properties only (49)

**Properties only.** Exercised by the coverage sweep and checked against the universal invariants — p-values in [0, 1], standard errors non-negative, R-squared at most 1, confidence intervals ordered, no NaN or Infinity reaching the payload — but not compared with a number anyone else computed.

| Procedure | Where | Reference |
| --- | --- | --- |
| `stats.compute_correlation` | Assistant / chat `correlation` | — |
| `stats.describe_columns` | Assistant / chat `describe` | — |
| `calc.calculator` | Calc > Calculator | — |
| `calc.validate_expression` | Calc > Calculator (live validation) | — |
| `calc.indicator_variables` | Calc > Make Indicator Variables | — |
| `calc.mesh_data` | Calc > Make Mesh Data | — |
| `calc.patterned_arbitrary` | Calc > Make Patterned Data > Arbitrary Set of Numbers | — |
| `calc.patterned_datetime` | Calc > Make Patterned Data > Date/Time Values | — |
| `calc.patterned_numbers` | Calc > Make Patterned Data > Simple Set of Numbers | — |
| `calc.patterned_text` | Calc > Make Patterned Data > Text Values | — |
| `calc.matrix_define` | Calc > Matrices > Define Constant Matrix | — |
| `calc.catalogue` | Calc > Random Data / Probability Distributions (shared catalogue) | _Not a statistic: the shared distribution list the two menus read, checked for consistency in test_distributions.py._ |
| `calc.row_statistics` | Calc > Row Statistics | — |
| `calc.standardize` | Calc > Standardize | — |
| `predictive.fit_decision_tree` | Predictive > Decision Tree | — |
| `predictive.fit_gradient_boosting` | Predictive > Gradient Boosting | — |
| `predictive.fit_random_forest` | Predictive > Random Forest | — |
| `regression.run_regression` | Predictive > Regression (v1) | _Superseded by Stat > Regression > Fit Regression Model, which is NIST-validated._ |
| `anova.anom` | Stat > ANOVA > Analysis of Means | — |
| `anova.balanced_anova` | Stat > ANOVA > Balanced ANOVA | — |
| `anova.nested_anova` | Stat > ANOVA > Fully Nested ANOVA | — |
| `anova.glm_comparisons` | Stat > ANOVA > General Linear Model > Comparisons | — |
| `anova.glm_contour` | Stat > ANOVA > General Linear Model > Contour Plot | — |
| `anova.glm_factorial_plots` | Stat > ANOVA > General Linear Model > Factorial Plots | — |
| `anova.glm_predict` | Stat > ANOVA > General Linear Model > Predict | — |
| `anova.glm_optimizer` | Stat > ANOVA > General Linear Model > Response Optimizer | — |
| `anova.glm_surface` | Stat > ANOVA > General Linear Model > Surface Plot | — |
| `anova.interaction_plot` | Stat > ANOVA > Interaction Plot | — |
| `anova.interval_plot` | Stat > ANOVA > Interval Plot | — |
| `anova.main_effects_plot` | Stat > ANOVA > Main Effects Plot | — |
| `anova.mixed_comparisons` | Stat > ANOVA > Mixed Effects Model > Comparisons | — |
| `anova.mixed_factorial_plots` | Stat > ANOVA > Mixed Effects Model > Factorial Plots | — |
| `anova.mixed_model` | Stat > ANOVA > Mixed Effects Model > Fit Mixed Effects Model | — |
| `anova.mixed_predict` | Stat > ANOVA > Mixed Effects Model > Predict | — |
| `basic_stats.poisson2` | Stat > Basic Statistics > 2-Sample Poisson Rate | — |
| `basic_stats.covariance` | Stat > Basic Statistics > Covariance | — |
| `basic_stats.graphical_summary` | Stat > Basic Statistics > Graphical Summary | — |
| `basic_stats.store_descriptives` | Stat > Basic Statistics > Store Descriptive Statistics | — |
| `regression_models.best_subsets` | Stat > Regression > Best Subsets | _Reports R-squared as a PERCENTAGE where Fit Regression Model, Fitted Line Plot, One-Way ANOVA and the GLM all report a fraction. See test_properties_sweep.py::test_the_r_squared_scale_is_inconsistent_across_three_procedures._ |
| `regression_models.binary_fitted_line` | Stat > Regression > Binary Fitted Line Plot | Spector & Mazzeo (1980). Journal of Economic Education 11:37-44 |
| `regression_models.nominal_logistic` | Stat > Regression > Nominal Logistic Regression | — |
| `regression_models.nonlinear` | Stat > Regression > Nonlinear Regression | — |
| `regression_models.ordinal_logistic` | Stat > Regression > Ordinal Logistic Regression | — |
| `regression_models.orthogonal` | Stat > Regression > Orthogonal Regression | — |
| `regression_models.pls` | Stat > Regression > Partial Least Squares | _Returns the top-level `r_squared` as a PERCENTAGE (79.37) where every other procedure returns a fraction. The on-screen highlight is right because it carries suffix '%', but report_engine/verdict.py reads `r_squared` straight and prints 'R2 = 79.366' on the PDF badge. See test_properties_sweep.py::test_pls_reports_r_squared_as_a_percentage._ |
| `regression_models.predict` | Stat > Regression > Predict | — |
| `regression_models.stability` | Stat > Regression > Stability Study | — |
| `regression_models.stepwise` | Stat > Regression > Stepwise | _Reports R-squared as a PERCENTAGE where Fit Regression Model, Fitted Line Plot, One-Way ANOVA and the GLM all report a fraction. See test_properties_sweep.py::test_the_r_squared_scale_is_inconsistent_across_three_procedures._ |
| `forecasting.run_forecast` | Stat > Time Series > Forecast | Cobb, G. W. (1978). Biometrika 65:243-251 (Nile), via statsmodels<br>_Cross-implementation check against a direct ETS/SARIMAX refit; no certified forecast exists._ |

### NOT YET VALIDATED (0)

**NOT YET VALIDATED.** No reference value, no snapshot, and not reached by the sweep.

None. Every procedure the app dispatches is at least reached by the coverage sweep — which is a low bar, and the *Properties only* section above is where the real gaps are.

## Running the suite

```
pip install -r requirements.txt -r requirements-dev.txt
pytest                                   # the whole suite, offline
pytest -m nist                           # only the NIST-certified checks
pytest -m published                      # only the cited worked examples
GOSSET_UPDATE_GOLDEN=1 pytest -m snapshot # regenerate the golden snapshots
```

The suite is offline and deterministic: every reference dataset is committed. `backend/tests/reference_data/nist/fetch_nist.py --write` re-downloads the NIST files and rewrites their manifest, and is deliberately not part of the test run.

A release cannot ship with a failing statistical test: `.github/workflows/release.yml` runs this suite before it builds an installer and stops if anything is red.
