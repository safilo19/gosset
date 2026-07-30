"""Predictive analytics: decision tree, random forest, gradient boosting (Phase 6).

Plain Python — no MCP or web-framework code. Every model here is scored via cross-validation
(not a single train/test split) so the reported metric is an honest out-of-sample estimate even
on the small datasets this tool is meant for; a final fit on the full data is used only to extract
feature importances and (for a single decision tree) the top splits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text

# ---------------------------------------------------------------------------
# shared: data prep, task detection, cross-validated scoring, importances
# ---------------------------------------------------------------------------


def _prepare_xy(df: pd.DataFrame, target: str, features: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    non_numeric_features = [f for f in features if not pd.api.types.is_numeric_dtype(df[f])]
    if non_numeric_features:
        raise ValueError(
            f"Feature(s) {', '.join(non_numeric_features)} are not numeric. Tree-based models here need numeric "
            f"features — encode categorical columns first (e.g. one-hot/label encoding), then try again."
        )

    data = df[[target] + features].dropna()
    min_rows = len(features) + 2
    if len(data) < min_rows:
        raise ValueError(
            f"Not enough complete rows to fit a model: {len(data)} row(s) with no missing values across "
            f"{target} and {features}, but at least {min_rows} are needed for {len(features)} feature(s)."
        )
    return data[features], data[target]


def detect_task_type(y: pd.Series) -> str:
    """Numeric with more than 10 distinct values -> regression; otherwise (text, or few distinct
    values even if numeric, e.g. a 0/1 flag) -> classification."""
    if not pd.api.types.is_numeric_dtype(y):
        return "classification"
    if y.nunique() <= 10:
        return "classification"
    return "regression"


def _cv_folds(n_samples: int, task_type: str, y: pd.Series) -> int:
    """5-fold CV, capped down for small datasets — classification is capped by the smallest
    class's size (StratifiedKFold can't split a class into more folds than it has rows)."""
    if task_type == "classification":
        folds = min(5, int(y.value_counts().min()))
    else:
        folds = min(5, n_samples // 2)
    if folds < 2:
        raise ValueError(
            f"Not enough data to cross-validate this model ({n_samples} usable row(s)). Classification needs at "
            f"least 2 rows in every class; regression needs at least 4 rows total."
        )
    return folds


def _score_estimator(estimator_factory, X: pd.DataFrame, y: pd.Series, task_type: str, folds: int):
    """Returns (metric_label, metric_value, secondary_metric_label, secondary_metric_value) —
    accuracy/F1 for classification, R²/RMSE for regression — via k-fold cross-validation."""
    if task_type == "classification":
        primary = cross_val_score(estimator_factory(), X, y, cv=folds, scoring="accuracy").mean()
        secondary = cross_val_score(estimator_factory(), X, y, cv=folds, scoring="f1_weighted").mean()
        return "Accuracy", float(primary), "F1 (weighted)", float(secondary)
    primary = cross_val_score(estimator_factory(), X, y, cv=folds, scoring="r2").mean()
    secondary = -cross_val_score(estimator_factory(), X, y, cv=folds, scoring="neg_root_mean_squared_error").mean()
    return "R²", float(primary), "RMSE", float(secondary)


@dataclass
class FeatureImportanceItem:
    feature: str
    importance: float


def _feature_importance_items(estimator, features: list[str]) -> list[FeatureImportanceItem]:
    items = [FeatureImportanceItem(feature=f, importance=float(v)) for f, v in zip(features, estimator.feature_importances_)]
    items.sort(key=lambda it: it.importance, reverse=True)
    return items


# ---------------------------------------------------------------------------
# decision tree / random forest / gradient boosting — same shape, one estimator factory
# ---------------------------------------------------------------------------

_TREE_MODEL_LABELS = {
    "decision_tree": "Decision Tree",
    "random_forest": "Random Forest",
    "gradient_boosting": "Gradient Boosting",
}


def _make_tree_estimator(model_type: str, task_type: str):
    if model_type == "decision_tree":
        cls = DecisionTreeClassifier if task_type == "classification" else DecisionTreeRegressor
        return cls(max_depth=5, random_state=42)
    if model_type == "random_forest":
        cls = RandomForestClassifier if task_type == "classification" else RandomForestRegressor
        return cls(n_estimators=200, random_state=42)
    if model_type == "gradient_boosting":
        cls = GradientBoostingClassifier if task_type == "classification" else GradientBoostingRegressor
        return cls(random_state=42)
    raise ValueError(f"Unknown model_type '{model_type}'.")


@dataclass
class PredictiveOutcome:
    model_type: str
    model_label: str
    task_type_used: str
    method_reason: str
    n_obs: int
    metric_label: str
    metric_value: float
    secondary_metric_label: str
    secondary_metric_value: float
    feature_importances: list[FeatureImportanceItem]
    tree_summary: str | None = None
    target_encoding: dict | None = None
    summary: str = ""
    content_lines: list[str] = field(default_factory=list)


def _fit_tree_model(df: pd.DataFrame, target: str, features: list[str], task_type: str, model_type: str) -> PredictiveOutcome:
    X, y = _prepare_xy(df, target, features)

    if task_type == "auto":
        resolved_task = detect_task_type(y)
        kind = "non-numeric" if not pd.api.types.is_numeric_dtype(y) else "numeric"
        reason = (
            f"Target '{target}' is {kind} with {y.nunique()} unique value(s); treating this as a "
            f"{resolved_task} task."
        )
    else:
        resolved_task = task_type
        reason = f"Using the requested task_type='{task_type}'."

    if resolved_task == "regression" and not pd.api.types.is_numeric_dtype(y):
        raise ValueError(
            f"Regression needs a numeric target; '{target}' has dtype {y.dtype}. Try task_type='classification' "
            f"or 'auto'."
        )

    folds = _cv_folds(len(X), resolved_task, y)
    metric_label, metric_value, secondary_label, secondary_value = _score_estimator(
        lambda: _make_tree_estimator(model_type, resolved_task), X, y, resolved_task, folds
    )

    final_model = _make_tree_estimator(model_type, resolved_task)
    final_model.fit(X, y)
    importances = _feature_importance_items(final_model, features)

    tree_summary = None
    if model_type == "decision_tree":
        tree_summary = export_text(final_model, feature_names=list(features), max_depth=2)

    label = _TREE_MODEL_LABELS[model_type]
    lines = [
        f"{label} ({resolved_task}) on target '{target}' using {features} (n={len(X)}, {folds}-fold CV).",
        f"{metric_label} = {metric_value:.3g}, {secondary_label} = {secondary_value:.3g}.",
        reason,
        "Top features by importance: " + ", ".join(f"{it.feature} ({it.importance:.3g})" for it in importances[:3]),
    ]
    if tree_summary:
        lines.append(f"Top splits:\n{tree_summary.rstrip()}")

    return PredictiveOutcome(
        model_type=model_type,
        model_label=label,
        task_type_used=resolved_task,
        method_reason=reason,
        n_obs=len(X),
        metric_label=metric_label,
        metric_value=metric_value,
        secondary_metric_label=secondary_label,
        secondary_metric_value=secondary_value,
        feature_importances=importances,
        tree_summary=tree_summary,
        summary=" ".join(lines[:4]),
        content_lines=lines,
    )


def fit_decision_tree(df: pd.DataFrame, target: str, features: list[str], task_type: str = "auto") -> PredictiveOutcome:
    return _fit_tree_model(df, target, features, task_type, "decision_tree")


def fit_random_forest(df: pd.DataFrame, target: str, features: list[str], task_type: str = "auto") -> PredictiveOutcome:
    return _fit_tree_model(df, target, features, task_type, "random_forest")


def fit_gradient_boosting(df: pd.DataFrame, target: str, features: list[str], task_type: str = "auto") -> PredictiveOutcome:
    return _fit_tree_model(df, target, features, task_type, "gradient_boosting")


# ---------------------------------------------------------------------------
# MARS (Multivariate Adaptive Regression Splines) — SKIPPED, not implemented.
#
# TODO: MARS was attempted and could not be installed in this environment.
# There is no MARS estimator in scikit-learn itself. The community implementation is
# `sklearn-contrib-py-earth` (PyPI name; imports as `pyearth`) — `pip install py-earth` doesn't
# exist as a package at all ("No matching distribution found"). The correctly-named
# `pip install sklearn-contrib-py-earth` DOES exist on PyPI, but it ships as a source
# distribution with Cython extensions that must compile locally, and the build failed with:
#
#     error: Microsoft Visual C++ 14.0 or greater is required. Get it with
#     "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/
#
# i.e. this Windows machine has no C/C++ compiler toolchain installed, which pip needs to build
# pyearth's native extensions. Installing Visual C++ Build Tools would fix this, but that's a
# substantial system-level change (a multi-GB toolchain install) that shouldn't happen as a side
# effect of adding one optional model — per the instructions for this session, MARS is skipped
# rather than blocking the rest of the Predictive Analytics module on this.
#
# If MARS is wanted later: either (a) install Visual C++ Build Tools and then
# `pip install sklearn-contrib-py-earth`, or (b) use a pure-Python alternative with no compiled
# extensions (e.g. `py-earth`'s spiritual successor `pyearth`-free options like implementing MARS'
# forward/backward-pass algorithm directly, or a maintained pure-Python package if one exists at
# the time). Once installed, `fit_mars(df, target, features)` should follow the exact same shape
# as `_fit_tree_model` above: cross-validated R² via `cross_val_score`, then a final `.fit()` on
# all data for `Earth().summary()` (the basis functions) and coefficient-magnitude-based feature
# importance (Earth doesn't expose `.feature_importances_`, so approximate it from
# `abs(coef)` per basis function, aggregated back to the originating feature).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AutoML — cross-validated comparison across every applicable model for the task
# ---------------------------------------------------------------------------

_MODEL_EXPLANATIONS = {
    "Linear Regression": "the relationship between the features and the target looks roughly linear",
    "Logistic Regression": "the classes separate along a roughly linear boundary in the features",
    "Decision Tree": "the relationship follows a few clear threshold-based rules rather than a smooth trend",
    "Random Forest": "the relationship is non-linear, and averaging many trees reduces overfitting versus a single tree",
    "Gradient Boosting": "the relationship is non-linear, and building trees sequentially captured patterns the other models missed",
}


@dataclass
class ModelComparisonRow:
    model: str
    score: float


@dataclass
class AutoMLOutcome:
    task_type_used: str
    method_reason: str
    n_obs: int
    metric_label: str
    results: list[ModelComparisonRow]
    best_model: str
    best_score: float
    summary: str = ""
    content_lines: list[str] = field(default_factory=list)


def run_automl(df: pd.DataFrame, target: str, features: list[str], task_type: str = "auto") -> AutoMLOutcome:
    """Cross-validates every applicable model for the detected task and ranks them by mean score.

    Every candidate — including linear/logistic regression — is scored the exact same way (k-fold
    cross_val_score), rather than comparing this tool's in-sample statsmodels R² (from
    core/regression.py) against the other models' out-of-sample CV scores; mixing the two would
    flatter linear regression and produce a misleading "best model" pick, which defeats the point
    of AutoML. So this reimplements linear/logistic regression via sklearn purely for a fair,
    apples-to-apples comparison — core/regression.py itself is untouched and still used everywhere
    else (its own tool, and by anything reusing its richer p-value/VIF output).
    """
    X, y = _prepare_xy(df, target, features)

    if task_type == "auto":
        resolved_task = detect_task_type(y)
        kind = "non-numeric" if not pd.api.types.is_numeric_dtype(y) else "numeric"
        reason = f"Target '{target}' is {kind} with {y.nunique()} unique value(s); treating this as a {resolved_task} task."
    else:
        resolved_task = task_type
        reason = f"Using the requested task_type='{task_type}'."

    if resolved_task == "regression" and not pd.api.types.is_numeric_dtype(y):
        raise ValueError(
            f"Regression needs a numeric target; '{target}' has dtype {y.dtype}. Try task_type='classification' "
            f"or 'auto'."
        )

    folds = _cv_folds(len(X), resolved_task, y)

    if resolved_task == "classification":
        candidates = {
            "Logistic Regression": lambda: LogisticRegression(max_iter=5000),
            "Decision Tree": lambda: _make_tree_estimator("decision_tree", "classification"),
            "Random Forest": lambda: _make_tree_estimator("random_forest", "classification"),
            "Gradient Boosting": lambda: _make_tree_estimator("gradient_boosting", "classification"),
        }
        scoring, metric_label = "accuracy", "Accuracy"
    else:
        candidates = {
            "Linear Regression": lambda: LinearRegression(),
            "Decision Tree": lambda: _make_tree_estimator("decision_tree", "regression"),
            "Random Forest": lambda: _make_tree_estimator("random_forest", "regression"),
            "Gradient Boosting": lambda: _make_tree_estimator("gradient_boosting", "regression"),
        }
        scoring, metric_label = "r2", "R²"

    results = [
        ModelComparisonRow(model=name, score=float(cross_val_score(factory(), X, y, cv=folds, scoring=scoring).mean()))
        for name, factory in candidates.items()
    ]
    results.sort(key=lambda r: r.score, reverse=True)
    best = results[0]
    explanation = _MODEL_EXPLANATIONS.get(best.model, "it best captured the underlying pattern in this data")

    lines = [
        f"AutoML ({resolved_task}) on target '{target}' using {features} (n={len(X)}, {folds}-fold CV).",
        reason,
        f"Model comparison ({metric_label}): " + ", ".join(f"{r.model}={r.score:.3g}" for r in results),
        f"{best.model} performed best with {metric_label}={best.score:.3g}, likely because {explanation}.",
    ]

    return AutoMLOutcome(
        task_type_used=resolved_task,
        method_reason=reason,
        n_obs=len(X),
        metric_label=metric_label,
        results=results,
        best_model=best.model,
        best_score=best.score,
        summary=" ".join(lines),
        content_lines=lines,
    )
