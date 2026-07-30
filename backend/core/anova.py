"""Stat > ANOVA — one-way through the general linear model, mixed effects, MANOVA and ANOM.

Same contract as basic_stats.py and regression_models.py: one `compute(df, procedure, columns,
options)` dispatching on `procedure`, every result shaped as tables / highlights / graphs /
narrative so the frontend only lays it out.

Two things are worth knowing before reading:

*Contrast coding.* Every model here is fitted with sum-to-zero coding (`C(f, Sum)`), not treatment
coding. That is what makes `anova_lm(typ=3)` produce genuine Type III adjusted sums of squares, and
it is also what Minitab's GLM does — its coefficients are deviations from the grand mean, not
differences from a reference level.

*Estimated marginal means.* Comparisons, factorial plots, contour/surface and the optimizer all
work off `_emm_rows`, which builds a patsy design row for every cell of a reference grid and
averages them. The result is a contrast vector L, so the estimate is L·β and its standard error
comes from L·cov·Lᵀ — proper least-squares means that account for the other terms in the model,
rather than raw cell averages.

*Statelessness.* Nothing here is cached between calls. The GLM and mixed model return a `model_spec`
that the frontend keeps; every downstream dialog sends it back and the model is refitted. Refitting
costs milliseconds and means a result window can outlive any server-side state — the same choice
the Regression menu's Predict panel already makes.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import itertools
import math
import re
import warnings
from typing import Any, Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from patsy import build_design_matrices
from scipy import optimize
from scipy import stats as st
from statsmodels.multivariate.manova import MANOVA
from statsmodels.regression.mixed_linear_model import MixedLM
from statsmodels.stats.anova import anova_lm
from statsmodels.stats.libqsturng import psturng, qsturng

from backend.core import graphs as graphs_core
from backend.core.procedures import (
    ProcedureError,
    check_group_column,
    ci_text,
    confidence,
    float_option,
    g,
    int_option,
    json_safe,
    list_option,
    option,
    p_text,
    require_columns,
)

PROCEDURES = (
    "one_way",
    "equal_variances",
    "balanced_anova",
    "nested_anova",
    "manova",
    "glm",
    "glm_comparisons",
    "glm_predict",
    "glm_factorial_plots",
    "glm_contour",
    "glm_surface",
    "glm_optimizer",
    "mixed_model",
    "mixed_comparisons",
    "mixed_predict",
    "mixed_factorial_plots",
    "interval_plot",
    "main_effects_plot",
    "interaction_plot",
    "anom",
)

COMPARISON_METHODS = ("tukey", "fisher", "dunnett", "games_howell")
MAX_GRID_CELLS = 4000  # the reference grid an EMM averages over
MAX_LEVELS = 40


# ---------------------------------------------------------------------------
# model frames: real column names in, patsy-safe identifiers out
# ---------------------------------------------------------------------------


class Spec:
    """A model's complete-case frame under safe identifiers, plus the map back to real names.

    Worksheet columns are routinely called `yield (kg)` or `C1`; a patsy formula cannot quote those
    reliably, so every column is renamed `y0` / `x{i}` / `f{i}` for fitting and mapped back for
    display. Same device as regression_models.py, kept separate because the ANOVA models need
    explicit term lists rather than a single "interactions" flag.
    """

    def __init__(self, frame: pd.DataFrame, response: str, covariates: list[str], factors: list[str]):
        self.frame = frame
        self.response = response
        self.covariates = covariates
        self.factors = factors
        # Centre covariates inside the formula (patsy's `center`, a stateful transform) rather
        # than in the frame. A covariate that appears in an interaction makes the other term's
        # "main effect" a test at covariate = 0 — which for a temperature in 60–90 °C is an
        # extrapolation nobody asked for. Doing it in the formula means design_info re-applies the
        # very same shift to every prediction grid, so nothing downstream can drift out of step.
        self.center = True
        self.safe: dict[str, str] = {}
        self.real: dict[str, str] = {}
        self.rows_used = 0
        self.rows_dropped = 0
        self.row_labels: list[int] = []
        self.levels: dict[str, list[str]] = {}
        self.means: dict[str, float] = {}
        self.ranges: dict[str, tuple[float, float]] = {}


def build_spec(
    df: pd.DataFrame,
    response: str,
    covariates: list[str],
    factors: list[str],
    *,
    what: str,
    extra_responses: list[str] | None = None,
) -> Spec:
    if not response and not extra_responses:
        raise ProcedureError(f"{what} needs a response column.")
    predictors = list(dict.fromkeys([*covariates, *factors]))
    responses = [r for r in [response, *(extra_responses or [])] if r]
    require_columns(df, [*responses, *predictors])
    clash = [p for p in predictors if p in responses]
    if clash:
        raise ProcedureError(f"'{clash[0]}' cannot be both a response and a predictor.")
    if not predictors:
        raise ProcedureError(f"{what} needs at least one factor or covariate.")

    spec = Spec(pd.DataFrame(), response, covariates, factors)
    columns: dict[str, pd.Series] = {}

    def register(name: str, safe: str, as_numeric: bool) -> None:
        spec.safe[name] = safe
        spec.real[safe] = name
        columns[safe] = pd.to_numeric(df[name], errors="coerce") if as_numeric else df[name].astype("object")

    for i, name in enumerate(responses):
        register(name, f"y{i}", True)
    for i, name in enumerate(covariates):
        register(name, f"x{i}", True)
    for i, name in enumerate(factors):
        register(name, f"f{i}", False)

    frame = pd.DataFrame(columns)
    for name in factors:  # a blank string in a factor column is a missing value, not a level
        safe = spec.safe[name]
        frame[safe] = frame[safe].where(frame[safe].notna() & (frame[safe].astype(str).str.strip() != ""), np.nan)
    before = len(frame)
    frame = frame.dropna()
    if frame.empty:
        raise ProcedureError(f"{what} found no rows where the response and every predictor have a value.")

    for name in factors:
        frame[spec.safe[name]] = frame[spec.safe[name]].astype(str)
        levels = sorted(frame[spec.safe[name]].unique().tolist())
        if len(levels) < 2:
            raise ProcedureError(f"Factor '{name}' has only {len(levels)} level in the usable rows — it cannot be fitted.")
        if len(levels) > MAX_LEVELS:
            raise ProcedureError(f"Factor '{name}' has {len(levels)} levels; that is too many to fit as a factor.")
        spec.levels[name] = levels
    for name in covariates:
        series = frame[spec.safe[name]]
        if series.notna().sum() == 0:
            raise ProcedureError(f"Covariate '{name}' has no numeric values.")
        spec.means[name] = float(series.mean())
        spec.ranges[name] = (float(series.min()), float(series.max()))

    spec.frame = frame
    spec.rows_used = len(frame)
    spec.rows_dropped = before - len(frame)
    spec.row_labels = [int(i) + 1 for i in frame.index]  # worksheet rows are 1-based
    return spec


_TOKEN = re.compile(r"\b([xyf]\d+)\b")


def pretty(label: str, spec: Spec) -> str:
    """`C(f0, Sum)[S.North]:center(x1)` -> `field=North * temperature_c`."""
    out = str(label)
    out = re.sub(r"center\(([xyf]\d+)\)", lambda m: m.group(1), out)
    out = re.sub(r"C\(([xyf]\d+)(?:,\s*Sum)?\)\[[TS]\.([^\]]+)\]", lambda m: f"{spec.real.get(m.group(1), m.group(1))}={m.group(2)}", out)
    out = re.sub(r"C\(([xyf]\d+)(?:,\s*Sum)?\)", lambda m: spec.real.get(m.group(1), m.group(1)), out)
    out = _TOKEN.sub(lambda m: spec.real.get(m.group(1), m.group(1)), out)
    return out.replace(":", " * ")


def encode(name: str, spec: Spec) -> str:
    """One predictor as patsy writes it: sum-to-zero coding for a factor, optional centring for a
    covariate. Both are stateful in design_info, so a prediction grid built later gets the same
    contrasts and the same shift without being told about them."""
    if name in spec.factors:
        return f"C({spec.safe[name]}, Sum)"
    return f"center({spec.safe[name]})" if spec.center else spec.safe[name]


def safe_term(term: str, spec: Spec) -> str:
    """'machine*shift' (real names, '*' between parts) -> 'C(f0, Sum):C(f1, Sum)'."""
    parts = [p.strip() for p in re.split(r"[*:]", term) if p.strip()]
    encoded = []
    for part in parts:
        if part not in spec.safe:
            raise ProcedureError(f"Term '{term}' names '{part}', which is not one of the chosen factors or covariates.")
        encoded.append(encode(part, spec))
    return ":".join(encoded)


def model_terms(spec: Spec, terms: list[str] | None, interactions: bool) -> list[str]:
    """The right-hand side of the formula. `terms` (real names) wins when given; otherwise the main
    effects, plus every two-way interaction when the 'all two-way' box is ticked."""
    if terms:
        return [safe_term(t, spec) for t in terms]
    main = [encode(c, spec) for c in spec.covariates] + [encode(f, spec) for f in spec.factors]
    if not interactions or len(main) < 2:
        return main
    return main + [f"{a}:{b}" for a, b in itertools.combinations(main, 2)]


def fit_ols(spec: Spec, terms: list[str], *, what: str = "The model"):
    if not terms:
        raise ProcedureError(f"{what} has no terms to fit.")
    formula = f"{spec.safe[spec.response]} ~ " + " + ".join(terms)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = smf.ols(formula, data=spec.frame).fit()
    except Exception as err:  # noqa: BLE001 - patsy/linalg failures become a user-facing message
        raise ProcedureError(f"{what} could not be fitted: {err}") from err
    if model.df_resid <= 0 or not np.isfinite(model.mse_resid):
        raise ProcedureError(
            f"{what} has no degrees of freedom left for error — there are as many terms as observations. "
            "Drop a term or an interaction, or add rows."
        )
    return model


# ---------------------------------------------------------------------------
# estimated marginal means
# ---------------------------------------------------------------------------


def _grid_rows(spec: Spec, fixed: dict[str, Any]) -> pd.DataFrame:
    """Every combination of the factors NOT pinned in `fixed`, with covariates at their means
    unless pinned. This is the reference grid an estimated marginal mean averages over."""
    free = [f for f in spec.factors if f not in fixed]
    combos = [spec.levels[f] for f in free]
    total = int(np.prod([len(c) for c in combos])) if combos else 1
    if total > MAX_GRID_CELLS:
        raise ProcedureError(
            f"Averaging over {total} factor-level combinations is too many. Fit the model with fewer factors, "
            "or fewer levels, before asking for marginal means."
        )

    base: dict[str, Any] = {}
    for name in spec.covariates:
        base[spec.safe[name]] = float(fixed.get(name, spec.means[name]))
    for name in spec.factors:
        if name in fixed:
            base[spec.safe[name]] = str(fixed[name])

    rows = []
    for combo in itertools.product(*combos) if combos else [()]:
        row = dict(base)
        for name, level in zip(free, combo):
            row[spec.safe[name]] = str(level)
        rows.append(row)
    return pd.DataFrame(rows)


def _design(model, rows: pd.DataFrame) -> np.ndarray:
    design_info = model.model.data.design_info
    try:
        return np.asarray(build_design_matrices([design_info], rows, return_type="matrix")[0], dtype=float)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The model could not be evaluated at those settings: {err}") from err


def emm_contrast(model, spec: Spec, fixed: dict[str, Any]) -> np.ndarray:
    """The contrast vector L whose L·β is the marginal mean at `fixed`."""
    return _design(model, _grid_rows(spec, fixed)).mean(axis=0)


def emm_rows(model, spec: Spec, factor: str, conf: float, *, at: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One estimated marginal mean per level of `factor`, each with its contrast vector."""
    if factor not in spec.factors:
        raise ProcedureError(f"'{factor}' is not one of the model's factors.")
    params = np.asarray(model.params, dtype=float)
    cov = np.asarray(model.cov_params(), dtype=float)
    crit = float(st.t.ppf(0.5 + conf / 2, model.df_resid))
    out = []
    for level in spec.levels[factor]:
        contrast = emm_contrast(model, spec, {**(at or {}), factor: level})
        est = float(contrast @ params)
        se = float(np.sqrt(max(contrast @ cov @ contrast, 0.0)))
        out.append(
            {
                "level": level,
                "mean": est,
                "se": se,
                "low": est - crit * se,
                "high": est + crit * se,
                "contrast": contrast,
                "n": int((spec.frame[spec.safe[factor]] == level).sum()),
            }
        )
    return out


# ---------------------------------------------------------------------------
# multiple comparisons
# ---------------------------------------------------------------------------


def grouping_letters(labels: list[str], means: list[float], different: set[tuple[str, str]]) -> dict[str, str]:
    """Compact letter display (Piepho's insert-and-absorb): start with one group holding every
    level, split it on each significant pair, then drop any group contained in another. Levels that
    share a letter are the ones the test could NOT separate."""
    order = [lab for _, lab in sorted(zip(means, labels), key=lambda p: -p[0])]
    groups: list[set[str]] = [set(order)]
    for a, b in ((x, y) for x in order for y in order if x < y):
        if (a, b) not in different and (b, a) not in different:
            continue
        for group in list(groups):
            if a in group and b in group:
                groups.remove(group)
                groups.append(group - {a})
                groups.append(group - {b})
    # absorb: a group wholly inside another carries no information of its own
    groups = [gr for gr in groups if gr and not any(gr < other for other in groups)]
    deduped: list[set[str]] = []
    for group in groups:
        if group not in deduped:
            deduped.append(group)
    # order the letters by the highest mean each group contains, so 'A' is the top group
    rank = {label: i for i, label in enumerate(order)}
    deduped.sort(key=lambda gr: min(rank[x] for x in gr))

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    letters: dict[str, list[str]] = {label: [] for label in labels}
    for i, group in enumerate(deduped):
        mark = alphabet[i] if i < len(alphabet) else f"({i + 1})"
        for label in group:
            letters[label].append(mark)
    return {label: "".join(marks) for label, marks in letters.items()}


def _difference_chart(rows: list[dict[str, Any]], conf: float, response: str) -> dict:
    """The signature comparison chart: one confidence interval per pairwise difference, with zero
    marked. An interval that clears zero is a difference the method called significant."""
    entries = [r for r in rows if r.get("_low") is not None and r.get("_high") is not None]
    if not entries:
        return {}
    return {
        "renderer": "differenceIntervals",
        "title": f"Confidence intervals for the pairwise differences ({conf * 100:g}%)",
        "data": {
            "rows": [
                {"label": r["Comparison"], "difference": r["_diff"], "low": r["_low"], "high": r["_high"], "significant": bool(r["_significant"])}
                for r in entries
            ],
            "confidence": conf,
            "value_label": f"difference in mean {response}",
        },
    }


def _comparison_tables(
    pairs: list[dict[str, Any]],
    labels: list[str],
    means: list[float],
    letters_of: dict[str, str],
    ns: dict[str, int],
    method_label: str,
) -> tuple[list[dict], list[dict]]:
    grouping = [
        {"Level": label, "N": ns.get(label, 0), "Mean": mean, "Grouping": letters_of.get(label, "")}
        for label, mean in sorted(zip(labels, means), key=lambda p: -p[1])
    ]
    public = [{k: v for k, v in row.items() if not k.startswith("_")} for row in pairs]
    return (
        [
            {"title": f"{method_label}: grouping information", "rows": grouping},
            {"title": f"{method_label}: tests for differences of means", "rows": public},
        ],
        grouping,
    )


def _control_tables(
    pairs: list[dict[str, Any]],
    labels: list[str],
    means: list[float],
    ns: dict[str, int],
    control: str,
    method_label: str,
) -> tuple[list[dict], list[dict]]:
    """Dunnett compares every level with the control and nothing else, so it cannot support
    grouping letters: letters would claim that two non-control levels are alike when the test never
    looked at that pair. The summary says what Dunnett actually answers instead."""
    differs = {row["Comparison"].split(" − ")[0]: bool(row["_significant"]) for row in pairs}
    summary = [
        {
            "Level": label,
            "N": ns.get(label, 0),
            "Mean": mean,
            "Difference from control": (mean - dict(zip(labels, means))[control]) if label != control else 0.0,
            "Differs from control": "control" if label == control else ("yes" if differs.get(label) else "no"),
        }
        for label, mean in sorted(zip(labels, means), key=lambda p: -p[1])
    ]
    public = [{k: v for k, v in row.items() if not k.startswith("_")} for row in pairs]
    return (
        [
            {"title": f"{method_label}: levels versus the control", "rows": summary},
            {"title": f"{method_label}: tests against the control", "rows": public},
        ],
        summary,
    )


def compare_groups(
    groups: list[dict[str, Any]],
    mse: float,
    df_error: float,
    method: str,
    conf: float,
    response: str,
    *,
    control: str | None = None,
    samples: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Pairwise comparisons from raw group summaries — the one-way path.

    Tukey, Fisher LSD and Games-Howell are computed here from n / mean / variance; Dunnett is
    delegated to scipy.stats.dunnett, which needs the samples themselves.
    """
    labels = [gr["label"] for gr in groups]
    means = [float(gr["mean"]) for gr in groups]
    ns = {gr["label"]: int(gr["n"]) for gr in groups}
    k = len(groups)
    if k < 2:
        raise ProcedureError("Comparisons need at least two groups.")
    alpha = 1 - conf
    by_label = {gr["label"]: gr for gr in groups}

    rows: list[dict[str, Any]] = []
    different: set[tuple[str, str]] = set()

    if method == "dunnett":
        if not control or control not in by_label:
            raise ProcedureError(f"Dunnett's test needs a control level. Choose one of: {', '.join(labels)}.")
        if not samples:
            raise ProcedureError("Dunnett's test needs the raw observations.")
        others = [lab for lab in labels if lab != control]
        try:
            outcome = st.dunnett(*[samples[lab] for lab in others], control=samples[control], alternative="two-sided")
            interval = outcome.confidence_interval(confidence_level=conf)
        except Exception as err:  # noqa: BLE001
            raise ProcedureError(f"Dunnett's test could not be computed: {err}") from err
        for i, label in enumerate(others):
            diff = float(by_label[label]["mean"] - by_label[control]["mean"])
            low, high = float(interval.low[i]), float(interval.high[i])
            p = float(np.atleast_1d(outcome.pvalue)[i])
            significant = p < alpha
            if significant:
                different.add((label, control))
            rows.append(
                {
                    "Comparison": f"{label} − {control}",
                    "Difference": diff,
                    "SE": float(np.sqrt(mse * (1 / ns[label] + 1 / ns[control]))),
                    "T-Value": float(np.atleast_1d(outcome.statistic)[i]),
                    "Adjusted P-Value": p,
                    f"{conf * 100:g}% CI": ci_text(low, high, 5),
                    "_diff": diff,
                    "_low": low,
                    "_high": high,
                    "_significant": significant,
                }
            )
        method_label = f"Dunnett's test versus the control level '{control}'"
    else:
        for a, b in itertools.combinations(labels, 2):
            ga, gb = by_label[a], by_label[b]
            diff = float(ga["mean"] - gb["mean"])
            if method == "games_howell":
                va, vb = float(ga["var"]) / ga["n"], float(gb["var"]) / gb["n"]
                se = math.sqrt(va + vb)
                denom = (va**2) / max(ga["n"] - 1, 1) + (vb**2) / max(gb["n"] - 1, 1)
                df_pair = ((va + vb) ** 2 / denom) if denom > 0 else float(df_error)
            else:
                se = math.sqrt(mse * (1 / ga["n"] + 1 / gb["n"]))
                df_pair = float(df_error)
            if se <= 0 or not np.isfinite(se):
                continue

            if method == "fisher":
                t = diff / se
                p = float(2 * st.t.sf(abs(t), df_pair))
                crit = float(st.t.ppf(0.5 + conf / 2, df_pair))
                stat_label, stat = "T-Value", t
            else:  # tukey and games-howell both use the studentised range
                q = abs(diff) / (se / math.sqrt(2))
                p = _srange_p(q, k, df_pair)
                crit = _srange_crit(conf, k, df_pair) / math.sqrt(2)
                stat_label, stat = "Q-Value", q
            low, high = diff - crit * se, diff + crit * se
            significant = p < alpha
            if significant:
                different.add((a, b))
            rows.append(
                {
                    "Comparison": f"{a} − {b}",
                    "Difference": diff,
                    "SE": se,
                    "DF": df_pair,
                    stat_label: stat,
                    "Adjusted P-Value" if method != "fisher" else "P-Value": p,
                    f"{conf * 100:g}% CI": ci_text(low, high, 5),
                    "_diff": diff,
                    "_low": low,
                    "_high": high,
                    "_significant": significant,
                }
            )
        method_label = {
            "tukey": "Tukey's simultaneous test (family error rate controlled)",
            "fisher": "Fisher's individual LSD (no adjustment for multiplicity)",
            "games_howell": "Games-Howell (does not assume equal variances)",
        }[method]

    if method == "dunnett":
        tables, grouping = _control_tables(rows, labels, means, ns, control or labels[0], method_label)
    else:
        tables, grouping = _comparison_tables(rows, labels, means, grouping_letters(labels, means, different), ns, method_label)
    return {
        "tables": tables,
        "grouping": grouping,
        "pairs": rows,
        "chart": _difference_chart(rows, conf, response),
        "method_label": method_label,
        "n_significant": len(different),
    }


def _srange_p(q: float, k: int, df: float) -> float:
    """Upper tail of the studentised range. scipy's `studentized_range` is exact; statsmodels'
    older `psturng` is a lookup table that floors at 0.001, which turns every strongly significant
    comparison into the same "0.001" and loses the ordering between them."""
    try:
        return float(min(max(float(st.studentized_range.sf(max(q, 0.0), k, max(df, 1.0))), 0.0), 1.0))
    except Exception:  # noqa: BLE001 - fall back on the table, then on a Bonferroni bound
        try:
            return float(min(max(float(np.atleast_1d(psturng(max(q, 0.0), k, max(df, 2.0)))[0]), 0.0), 1.0))
        except Exception:  # noqa: BLE001
            return float(min(1.0, 2 * st.t.sf(abs(q) / math.sqrt(2), max(df, 1)) * k * (k - 1) / 2))


def _srange_crit(conf: float, k: int, df: float) -> float:
    """q(conf, k, df) — the studentised-range critical value a Tukey interval is built from."""
    try:
        return float(st.studentized_range.ppf(conf, k, max(df, 1.0)))
    except Exception:  # noqa: BLE001
        return float(qsturng(conf, k, max(df, 2.0)))


def compare_emms(model, spec: Spec, factor: str, method: str, conf: float, response: str) -> dict[str, Any]:
    """Pairwise comparisons of a factor's estimated marginal means — the GLM / mixed path.

    Differences are contrasts of the fitted model, so they are adjusted for every other term; that
    is what makes them least-squares means rather than raw cell averages.
    """
    if method not in ("tukey", "fisher"):
        raise ProcedureError("Comparisons from a fitted model support Tukey and Fisher LSD. Use One-Way ANOVA for Dunnett or Games-Howell.")
    entries = emm_rows(model, spec, factor, conf)
    params = np.asarray(model.params, dtype=float)
    cov = np.asarray(model.cov_params(), dtype=float)
    df_error = float(model.df_resid)
    k = len(entries)
    alpha = 1 - conf
    labels = [e["level"] for e in entries]
    means = [e["mean"] for e in entries]
    ns = {e["level"]: e["n"] for e in entries}

    rows: list[dict[str, Any]] = []
    different: set[tuple[str, str]] = set()
    for ea, eb in itertools.combinations(entries, 2):
        d = ea["contrast"] - eb["contrast"]
        diff = float(d @ params)
        se = float(np.sqrt(max(d @ cov @ d, 0.0)))
        if se <= 0 or not np.isfinite(se):
            continue
        if method == "fisher":
            t = diff / se
            p = float(2 * st.t.sf(abs(t), df_error))
            crit = float(st.t.ppf(0.5 + conf / 2, df_error))
            stat_key, stat = "T-Value", t
            p_key = "P-Value"
        else:
            q = abs(diff) / (se / math.sqrt(2))
            p = _srange_p(q, k, df_error)
            crit = _srange_crit(conf, k, df_error) / math.sqrt(2)
            stat_key, stat = "Q-Value", q
            p_key = "Adjusted P-Value"
        low, high = diff - crit * se, diff + crit * se
        significant = p < alpha
        if significant:
            different.add((ea["level"], eb["level"]))
        rows.append(
            {
                "Comparison": f"{ea['level']} − {eb['level']}",
                "Difference": diff,
                "SE": se,
                "DF": df_error,
                stat_key: stat,
                p_key: p,
                f"{conf * 100:g}% CI": ci_text(low, high, 5),
                "_diff": diff,
                "_low": low,
                "_high": high,
                "_significant": significant,
            }
        )

    letters = grouping_letters(labels, means, different)
    method_label = (
        "Tukey's simultaneous test on the fitted (least-squares) means"
        if method == "tukey"
        else "Fisher's individual LSD on the fitted (least-squares) means"
    )
    tables, grouping = _comparison_tables(rows, labels, means, letters, ns, method_label)
    tables.insert(
        0,
        {
            "title": f"Estimated marginal means for {factor}",
            "rows": [
                {"Level": e["level"], "N": e["n"], "Fitted Mean": e["mean"], "SE": e["se"], f"{conf * 100:g}% CI": ci_text(e["low"], e["high"], 5)}
                for e in entries
            ],
        },
    )
    return {
        "tables": tables,
        "grouping": grouping,
        "pairs": rows,
        "chart": _difference_chart(rows, conf, response),
        "method_label": method_label,
        "n_significant": len(different),
        "emms": entries,
    }


# ---------------------------------------------------------------------------
# shared output blocks
# ---------------------------------------------------------------------------


def model_summary_rows(model) -> list[dict[str, Any]]:
    return [
        {
            "S": math.sqrt(float(model.mse_resid)),
            "R-sq": float(model.rsquared),
            "R-sq(adj)": float(model.rsquared_adj),
        }
    ]


def anova_table(model, spec: Spec, *, typ: int = 3) -> list[dict[str, Any]]:
    """Minitab's ANOVA block. Type III (adjusted) sums of squares by default, which is only correct
    because every factor is fitted with sum-to-zero coding — see the module docstring."""
    rows: list[dict[str, Any]] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            table = anova_lm(model, typ=typ)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The ANOVA table could not be computed for this design: {err}") from err

    label_col = "Adj SS" if typ == 3 else "Seq SS"
    ms_col = "Adj MS" if typ == 3 else "Seq MS"
    for label, row in table.iterrows():
        name = str(label)
        if name in ("Residual", "Intercept"):
            continue
        dfree = float(row["df"])
        rows.append(
            {
                "Source": pretty(name, spec),
                "DF": int(dfree),
                label_col: float(row["sum_sq"]),
                ms_col: float(row["sum_sq"] / dfree) if dfree else None,
                "F-Value": None if pd.isna(row.get("F")) else float(row["F"]),
                "P-Value": None if pd.isna(row.get("PR(>F)")) else float(row["PR(>F)"]),
            }
        )
    rows.append({"Source": "Error", "DF": int(model.df_resid), label_col: float(model.ssr), ms_col: float(model.mse_resid), "F-Value": None, "P-Value": None})
    rows.append(
        {
            "Source": "Total",
            "DF": int(model.df_model + model.df_resid),
            label_col: float(model.centered_tss),
            ms_col: None,
            "F-Value": None,
            "P-Value": None,
        }
    )
    return rows


def coefficient_rows(model, spec: Spec, conf: float) -> list[dict[str, Any]]:
    low, high = model.conf_int(alpha=1 - conf).T.values
    rows = []
    for i, name in enumerate(model.model.exog_names):
        rows.append(
            {
                "Term": "Constant" if name == "Intercept" else pretty(name, spec),
                "Coef": float(model.params.iloc[i]),
                "SE Coef": float(model.bse.iloc[i]),
                f"{conf * 100:g}% CI": ci_text(float(low[i]), float(high[i]), 5),
                "T-Value": float(model.tvalues.iloc[i]),
                "P-Value": float(model.pvalues.iloc[i]),
            }
        )
    return rows


def unusual_rows(model, spec: Spec) -> tuple[list[dict[str, Any]], int, int]:
    from statsmodels.stats.outliers_influence import OLSInfluence

    influence = OLSInfluence(model)
    std_resid = np.asarray(influence.resid_studentized_internal, dtype=float)
    leverage = np.asarray(influence.hat_matrix_diag, dtype=float)
    fitted = np.asarray(model.fittedvalues, dtype=float)
    observed = np.asarray(model.model.endog, dtype=float)
    n = len(std_resid)
    p = int(model.df_model) + 1
    cut = min(0.99, 3.0 * p / n) if n else 1.0

    rows, large, high = [], 0, 0
    for i in range(n):
        is_large = abs(std_resid[i]) > 2
        is_high = leverage[i] > cut
        large += int(is_large)
        high += int(is_high)
        if not (is_large or is_high):
            continue
        rows.append(
            {
                "Row": spec.row_labels[i],
                spec.response: float(observed[i]),
                "Fit": float(fitted[i]),
                "Resid": float(observed[i] - fitted[i]),
                "Std Resid": float(std_resid[i]),
                "Flag": ("R" if is_large else "") + ("X" if is_high else ""),
            }
        )
    rows.sort(key=lambda r: abs(r["Std Resid"]), reverse=True)
    return rows[:40], large, high


def _probability_points(values: np.ndarray) -> dict:
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    sd = float(np.std(x, ddof=1)) if n > 1 else 0.0
    mean = float(np.mean(x))
    i = np.arange(1, n + 1)
    z = st.norm.ppf((i - 0.3) / (n + 0.4))
    return {
        "points": [{"x": float(xi), "y": float(zi)} for xi, zi in zip(x, z)],
        "line": [{"x": mean + sd * float(z[0]), "y": float(z[0])}, {"x": mean + sd * float(z[-1]), "y": float(z[-1])}],
        "x_label": "residual",
        "y_label": "normal score (z)",
        "n": n,
        "r_squared": float(np.corrcoef(x, z)[0, 1] ** 2) if n > 2 and sd > 0 else None,
    }


def four_in_one(resid: np.ndarray, fitted: np.ndarray, row_labels: list[int], response: str) -> dict:
    return {
        "renderer": "fourInOne",
        "title": "Residual plots (four in one)",
        "data": {
            "normal": _probability_points(resid),
            "versus_fits": {
                "points": [{"x": float(f), "y": float(r)} for f, r in zip(fitted, resid)],
                "x_label": f"fitted {response}",
                "y_label": "residual",
            },
            "histogram": graphs_core.compute(pd.DataFrame({"residual": resid}), "histogram", ["residual"], {}),
            "versus_order": {
                "points": [{"x": int(row), "y": float(r)} for row, r in zip(row_labels, resid)],
                "x_label": "observation order (worksheet row)",
                "y_label": "residual",
            },
        },
    }


def _group_summaries(df: pd.DataFrame, value_col: str, group_col: str, what: str) -> tuple[list[dict], dict[str, np.ndarray]]:
    require_columns(df, [value_col, group_col])
    # The choke point for every stacked-layout procedure here — one-way ANOVA, Test for Equal
    # Variances, ANOM, the interval / individual-value / main-effects plots — so the degenerate-group
    # check is applied once and none of them can be asked to compare 96 one-row "groups". `swap` names
    # this menu's two column fields, which is what makes the dialog able to offer the exchange.
    check_group_column(df, group_col, what=what, value_column=value_col, swap=("response", "factor"))
    values = pd.to_numeric(df[value_col], errors="coerce")
    labels = df[group_col].astype("object")
    frame = pd.DataFrame({"v": values, "g": labels}).dropna()
    frame = frame[frame["g"].astype(str).str.strip() != ""]
    if frame.empty:
        raise ProcedureError(f"{what} found no rows where '{value_col}' is numeric and '{group_col}' has a value.")
    frame["g"] = frame["g"].astype(str)

    groups, samples = [], {}
    for label in sorted(frame["g"].unique().tolist()):
        sample = frame.loc[frame["g"] == label, "v"].to_numpy(dtype=float)
        if sample.size < 1:
            continue
        samples[label] = sample
        groups.append(
            {
                "label": label,
                "n": int(sample.size),
                "mean": float(np.mean(sample)),
                "var": float(np.var(sample, ddof=1)) if sample.size > 1 else 0.0,
                "sd": float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0,
            }
        )
    if len(groups) < 2:
        raise ProcedureError(f"{what} needs at least two groups; '{group_col}' has {len(groups)} usable one(s).")
    return groups, samples


def _samples_from_columns(df: pd.DataFrame, columns: list[str], what: str) -> tuple[list[dict], dict[str, np.ndarray]]:
    """The 'response data in separate columns' layout: each chosen column is one group."""
    require_columns(df, columns)
    groups, samples = [], {}
    for column in columns:
        sample = pd.to_numeric(df[column], errors="coerce").dropna().to_numpy(dtype=float)
        if sample.size == 0:
            raise ProcedureError(f"{what} found no numeric values in '{column}'.")
        samples[column] = sample
        groups.append(
            {
                "label": column,
                "n": int(sample.size),
                "mean": float(np.mean(sample)),
                "var": float(np.var(sample, ddof=1)) if sample.size > 1 else 0.0,
                "sd": float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0,
            }
        )
    if len(groups) < 2:
        raise ProcedureError(f"{what} needs at least two columns of response data.")
    return groups, samples


def _interval_graph(groups: list[dict], conf: float, value_label: str, group_label: str, *, title: str | None = None) -> dict:
    crit_groups = []
    for i, gr in enumerate(groups):
        n = gr["n"]
        se = math.sqrt(gr["var"] / n) if n > 1 and gr["var"] > 0 else 0.0
        half = float(st.t.ppf(0.5 + conf / 2, n - 1)) * se if n > 1 and se > 0 else 0.0
        crit_groups.append(
            {"label": gr["label"], "index": i, "mean": gr["mean"], "se": se, "ci_low": gr["mean"] - half, "ci_high": gr["mean"] + half, "n": n}
        )
    return {
        "renderer": "interval",
        "title": title or f"Interval plot of {value_label}",
        "data": {
            "groups": crit_groups,
            "labels": [gr["label"] for gr in groups],
            "confidence": conf,
            "value_label": value_label,
            "group_label": group_label,
        },
    }


def _raw_graphs(options: dict, samples: dict[str, np.ndarray], groups: list[dict], conf: float, value_label: str, group_label: str) -> list[dict]:
    """The optional plots every one-way-shaped dialog offers, in Minitab's own order."""
    out = []
    if option(options, "graph_interval", True):
        out.append(_interval_graph(groups, conf, value_label, group_label))
    if option(options, "graph_individual", False):
        out.append(
            {
                "renderer": "individualValue",
                "title": f"Individual value plot of {value_label}",
                "data": {
                    "groups": [
                        {"label": label, "index": i, "values": [float(v) for v in samples[label]], "mean": float(np.mean(samples[label])), "n": int(samples[label].size)}
                        for i, label in enumerate(samples)
                    ],
                    "labels": list(samples.keys()),
                    "value_label": value_label,
                    "group_label": group_label,
                },
            }
        )
    if option(options, "graph_boxplot", False):
        frame = pd.DataFrame(
            {"__v": np.concatenate([samples[k] for k in samples]), "__g": np.concatenate([[k] * len(samples[k]) for k in samples])}
        )
        out.append(
            {
                "renderer": "boxplot",
                "title": f"Boxplot of {value_label}",
                "data": graphs_core.compute(frame, "boxplot", ["__v"], {"group_column": "__g"}) | {"value_label": value_label, "group_label": group_label},
            }
        )
    return out


# ---------------------------------------------------------------------------
# 1. One-Way ANOVA
# ---------------------------------------------------------------------------


def _one_way(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    layout = str(option(options, "layout", "one_column"))
    conf = confidence(options)
    alpha = 1 - conf
    equal_var = bool(option(options, "equal_variances", True))

    if layout == "columns":
        response_label = str(option(options, "value_label", "response") or "response")
        groups, samples = _samples_from_columns(df, columns, "One-Way ANOVA")
        group_label = "sample"
        long_value, long_group = response_label, group_label
        frame = pd.DataFrame(
            {"__v": np.concatenate([samples[k] for k in samples]), "__g": np.concatenate([[k] * len(samples[k]) for k in samples])}
        )
    else:
        if len(columns) < 2:
            raise ProcedureError("With the response in one column, choose both the response and the factor column.")
        response_label, group_label = columns[0], columns[1]
        groups, samples = _group_summaries(df, response_label, group_label, "One-Way ANOVA")
        long_value, long_group = response_label, group_label
        frame = pd.DataFrame(
            {"__v": np.concatenate([samples[k] for k in samples]), "__g": np.concatenate([[k] * len(samples[k]) for k in samples])}
        )

    for gr in groups:
        if gr["n"] < 2:
            raise ProcedureError(f"Group '{gr['label']}' has only {gr['n']} observation — every group needs at least 2.")

    k = len(groups)
    n_total = sum(gr["n"] for gr in groups)
    grand = float(sum(gr["mean"] * gr["n"] for gr in groups) / n_total)
    ss_between = float(sum(gr["n"] * (gr["mean"] - grand) ** 2 for gr in groups))
    ss_within = float(sum((gr["n"] - 1) * gr["var"] for gr in groups))
    df_between, df_within = k - 1, n_total - k
    ms_between = ss_between / df_between
    ms_within = ss_within / df_within if df_within else float("nan")

    if equal_var:
        if ms_within <= 0:
            raise ProcedureError("Every group is constant, so there is no within-group variation to test against.")
        f_stat = ms_between / ms_within
        p_value = float(st.f.sf(f_stat, df_between, df_within))
        df_denominator = float(df_within)
        method = "One-way ANOVA (assumes equal variances)"
        anova_rows = [
            {"Source": long_group, "DF": df_between, "Adj SS": ss_between, "Adj MS": ms_between, "F-Value": f_stat, "P-Value": p_value},
            {"Source": "Error", "DF": df_within, "Adj SS": ss_within, "Adj MS": ms_within, "F-Value": None, "P-Value": None},
            {"Source": "Total", "DF": df_between + df_within, "Adj SS": ss_between + ss_within, "Adj MS": None, "F-Value": None, "P-Value": None},
        ]
    else:
        # Welch's ANOVA: each group weighted by its own precision, denominator DF adjusted.
        weights = [gr["n"] / gr["var"] if gr["var"] > 0 else np.inf for gr in groups]
        if any(not np.isfinite(w) for w in weights):
            raise ProcedureError("Welch's ANOVA needs every group to vary; at least one group is constant. Tick 'Assume equal variances' instead.")
        w_sum = float(sum(weights))
        weighted_grand = float(sum(w * gr["mean"] for w, gr in zip(weights, groups)) / w_sum)
        numerator = float(sum(w * (gr["mean"] - weighted_grand) ** 2 for w, gr in zip(weights, groups)) / (k - 1))
        # lam is Welch's Λ; the denominator DF is 1/Λ and the statistic is deflated by (1 + 2(k−2)Λ/3).
        lam = float(sum((1 - w / w_sum) ** 2 / (gr["n"] - 1) for w, gr in zip(weights, groups)) * 3 / (k**2 - 1))
        f_stat = numerator / (1 + (2 * (k - 2) / 3) * lam) if lam > 0 else numerator
        df_denominator = 1 / lam if lam > 0 else float(df_within)
        p_value = float(st.f.sf(f_stat, k - 1, df_denominator))
        method = "Welch's ANOVA (does not assume equal variances)"
        anova_rows = [
            {"Source": long_group, "DF": df_between, "Adj SS": None, "Adj MS": None, "F-Value": f_stat, "P-Value": p_value},
            {"Source": "Error (Welch-adjusted)", "DF": round(df_denominator, 3), "Adj SS": None, "Adj MS": None, "F-Value": None, "P-Value": None},
        ]

    s = math.sqrt(ms_within) if ms_within > 0 else 0.0
    ss_total = ss_between + ss_within
    r_squared = ss_between / ss_total if ss_total > 0 else 0.0
    r_squared_adj = 1 - (ss_within / df_within) / (ss_total / (n_total - 1)) if df_within and ss_total > 0 else 0.0

    crit = {gr["label"]: float(st.t.ppf(0.5 + conf / 2, gr["n"] - 1)) for gr in groups}
    # Minitab pools the error for the per-group intervals when equal variances are assumed, and
    # uses each group's own standard deviation when they are not.
    means_rows = []
    for gr in groups:
        if equal_var:
            se = math.sqrt(ms_within / gr["n"])
            half = float(st.t.ppf(0.5 + conf / 2, df_within)) * se
        else:
            se = math.sqrt(gr["var"] / gr["n"])
            half = crit[gr["label"]] * se
        means_rows.append(
            {
                "Level": gr["label"],
                "N": gr["n"],
                "Mean": gr["mean"],
                "StDev": gr["sd"],
                "SE Mean": se,
                f"{conf * 100:g}% CI": ci_text(gr["mean"] - half, gr["mean"] + half, 5),
            }
        )

    tables = [
        {"title": "Analysis of Variance", "rows": anova_rows},
        {"title": "Model Summary", "rows": [{"S": s, "R-sq": r_squared, "R-sq(adj)": r_squared_adj}]},
        {"title": f"Means ({'pooled StDev' if equal_var else 'individual StDev'})", "rows": means_rows},
    ]

    graphs = _raw_graphs(options, samples, groups, conf, long_value, long_group)

    comparison_note = None
    if option(options, "comparisons", "none") != "none":
        method_key = str(options["comparisons"])
        if method_key not in COMPARISON_METHODS:
            raise ProcedureError(f"Unknown comparison method '{method_key}'. Expected one of: {', '.join(COMPARISON_METHODS)}.")
        outcome = compare_groups(
            groups,
            ms_within,
            df_within,
            method_key,
            confidence(options, "comparison_confidence") if options.get("comparison_confidence") else conf,
            long_value,
            control=option(options, "control", None),
            samples=samples,
        )
        tables.extend(outcome["tables"])
        if outcome["chart"]:
            graphs.append(outcome["chart"])
        comparison_note = f"{outcome['method_label']}: {outcome['n_significant']} of {len(outcome['pairs'])} pairwise comparison(s) are significant."

    if option(options, "graph_residuals", False) and equal_var:
        fitted = np.concatenate([[gr["mean"]] * gr["n"] for gr in groups])
        observed = np.concatenate([samples[gr["label"]] for gr in groups])
        graphs.append(four_in_one(observed - fitted, fitted, list(range(1, len(observed) + 1)), long_value))

    significant, verdict = (p_value < alpha), None
    conclusion = (
        f"{method}: F = {g(f_stat, 5)} on {df_between} and {g(df_denominator, 5)} DF, p = {p_text(p_value)}. "
        + (
            f"At least one of the {k} group means differs at α = {g(alpha)}."
            if significant
            else f"No difference among the {k} group means is detected at α = {g(alpha)}."
        )
        + (f" {comparison_note}" if comparison_note else "")
    )
    return {
        "procedure": "one_way",
        "title": f"One-Way ANOVA: {long_value} versus {long_group}",
        "method": method,
        "response": long_value,
        "factor": long_group,
        "confidence_level": conf,
        "n": n_total,
        "groups": k,
        "f_value": f_stat,
        "p_value": p_value,
        "s": s,
        "r_squared": r_squared,
        "note": (f"{n_total} observations in {k} groups." if not equal_var else None),
        "tables": tables,
        "highlights": [
            {"label": "F-Value", "value": f_stat},
            {"label": "P-Value", "value": p_value, "tone": "positive" if significant else None},
            {"label": "R-sq", "value": r_squared * 100, "suffix": "%"},
            {"label": "S", "value": s},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"One-Way ANOVA — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 2. Test for Equal Variances
# ---------------------------------------------------------------------------


def _equal_variances(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    layout = str(option(options, "layout", "one_column"))
    conf = confidence(options)
    alpha = 1 - conf

    if layout == "columns":
        groups, samples = _samples_from_columns(df, columns, "Test for Equal Variances")
        value_label, group_label = str(option(options, "value_label", "response") or "response"), "sample"
    else:
        if len(columns) < 2:
            raise ProcedureError("With the response in one column, choose both the response and the factor column.")
        value_label, group_label = columns[0], columns[1]
        groups, samples = _group_summaries(df, value_label, group_label, "Test for Equal Variances")

    for gr in groups:
        if gr["n"] < 2:
            raise ProcedureError(f"Group '{gr['label']}' has only {gr['n']} observation — every group needs at least 2 to have a variance.")

    k = len(groups)
    ordered = [samples[gr["label"]] for gr in groups]

    bartlett = st.bartlett(*ordered)
    levene = st.levene(*ordered, center="median")

    # Bonferroni CIs for each group's standard deviation: the chi-square interval at α/k, so the
    # whole set of k intervals has family confidence `conf`. Non-overlap is the visual test.
    per_group = 1 - alpha / k
    rows = []
    chart_rows = []
    for gr in groups:
        n, sd = gr["n"], gr["sd"]
        dfree = n - 1
        lower = sd * math.sqrt(dfree / st.chi2.ppf(0.5 + per_group / 2, dfree)) if sd > 0 else 0.0
        upper = sd * math.sqrt(dfree / st.chi2.ppf(0.5 - per_group / 2, dfree)) if sd > 0 else 0.0
        rows.append({"Level": gr["label"], "N": n, "StDev": sd, "Variance": gr["var"], f"{conf * 100:g}% Bonferroni CI for StDev": ci_text(lower, upper, 5)})
        chart_rows.append({"label": gr["label"], "index": len(chart_rows), "mean": sd, "ci_low": lower, "ci_high": upper, "n": n, "se": 0.0})

    tests = [
        {
            "Method": "Bartlett (assumes normal distributions)",
            "Test statistic": float(bartlett.statistic),
            "DF": k - 1,
            "P-Value": float(bartlett.pvalue),
        },
        {
            "Method": "Levene, median-centred (any continuous distribution)",
            "Test statistic": float(levene.statistic),
            "DF": f"{k - 1}, {sum(gr['n'] for gr in groups) - k}",
            "P-Value": float(levene.pvalue),
        },
    ]

    graphs = [
        {
            "renderer": "interval",
            "title": f"{conf * 100:g}% Bonferroni confidence intervals for the standard deviations",
            "data": {
                "groups": chart_rows,
                "labels": [gr["label"] for gr in groups],
                "confidence": conf,
                "value_label": f"StDev of {value_label}",
                "group_label": group_label,
            },
        }
    ]
    graphs.extend(_raw_graphs({**options, "graph_interval": False}, samples, groups, conf, value_label, group_label))

    smallest = min(groups, key=lambda gr: gr["sd"])
    largest = max(groups, key=lambda gr: gr["sd"])
    p_headline = float(levene.pvalue)
    significant = p_headline < alpha
    conclusion = (
        f"Bartlett p = {p_text(float(bartlett.pvalue))}, Levene p = {p_text(p_headline)} across {k} groups. "
        + ("The standard deviations differ at " if significant else "No difference among the standard deviations is detected at ")
        + f"α = {g(alpha)}. "
        f"Smallest: {smallest['label']} ({g(smallest['sd'], 4)}); largest: {largest['label']} ({g(largest['sd'], 4)}); "
        f"ratio {g(largest['sd'] / smallest['sd'], 4) if smallest['sd'] > 0 else '∞'}."
    )
    return {
        "procedure": "equal_variances",
        "title": f"Test for Equal Variances: {value_label} versus {group_label}",
        "method": "Bartlett's test and Levene's test (median-centred), with Bonferroni intervals for each standard deviation",
        "confidence_level": conf,
        "groups": k,
        "p_value": p_headline,
        "tables": [
            {"title": "Standard deviations", "rows": rows},
            {"title": "Tests", "rows": tests},
        ],
        "highlights": [
            {"label": "Bartlett P", "value": float(bartlett.pvalue), "tone": "positive" if bartlett.pvalue < alpha else None},
            {"label": "Levene P", "value": p_headline, "tone": "positive" if significant else None},
            {"label": "Groups", "value": k, "decimals": 0},
            {"label": "Largest / smallest StDev", "value": (largest["sd"] / smallest["sd"]) if smallest["sd"] > 0 else None},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Test for Equal Variances — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 3. Balanced ANOVA
# ---------------------------------------------------------------------------


def _cell_counts(spec: Spec) -> pd.Series:
    keys = [spec.safe[f] for f in spec.factors]
    return spec.frame.groupby(keys, sort=True).size()


def _term_parts(term_label: str, spec: Spec) -> set[str]:
    """The set of real factor names a fitted term involves."""
    out = set()
    for match in _TOKEN.finditer(term_label):
        real = spec.real.get(match.group(1))
        if real in spec.factors or real in spec.covariates:
            out.add(real)
    return out


def _variance_components(
    term_rows: list[dict[str, Any]],
    parts_of: dict[str, set[str]],
    random_factors: list[str],
    mse: float,
    df_error: int,
    n_total: int,
    level_counts: dict[str, int],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Variance components from the balanced-design expected mean squares.

    For a random term T, E[MS(T)] = σ²(error) + c·σ²(T) with c = N / (number of level combinations
    of T), and the denominator is the mean square of the smallest term that strictly contains T
    (its "error term"), or the residual when nothing does. Negative estimates are truncated to 0,
    which is what every package does and what Minitab reports.
    """
    random_terms = [row for row in term_rows if parts_of[row["Source"]] and parts_of[row["Source"]] <= set(random_factors)]
    by_source = {row["Source"]: row for row in term_rows}

    def denominator(source: str) -> tuple[str, float, float]:
        mine = parts_of[source]
        containing = [
            other for other in term_rows if other["Source"] != source and mine < parts_of[other["Source"]] and parts_of[other["Source"]] <= set(random_factors)
        ]
        if containing:
            pick = min(containing, key=lambda r: len(parts_of[r["Source"]]))
            return pick["Source"], float(pick["MS"]), float(pick["DF"])
        return "Error", mse, float(df_error)

    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for row in random_terms:
        source = row["Source"]
        cells = int(np.prod([level_counts[p] for p in parts_of[source]])) if parts_of[source] else 1
        coefficient = n_total / cells if cells else 1
        denom_name, denom_ms, _ = denominator(source)
        raw = (float(row["MS"]) - denom_ms) / coefficient if coefficient else 0.0
        estimate = max(raw, 0.0)
        if raw < 0:
            notes.append(f"the estimate for {source} was negative ({g(raw, 3)}) and has been truncated to zero")
        rows.append({"Source": source, "Estimated Value": estimate, "Error term": denom_name, "EMS coefficient": coefficient, "_raw": raw})

    rows.append({"Source": "Error", "Estimated Value": mse, "Error term": "", "EMS coefficient": 1, "_raw": mse})
    total = sum(r["Estimated Value"] for r in rows)
    for r in rows:
        r["% of Total"] = (r["Estimated Value"] / total * 100) if total > 0 else None
        r.pop("_raw", None)
    return rows, notes


def _balanced_anova(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Balanced ANOVA needs a response and at least one factor.")
    response, factors = columns[0], [c for c in columns[1:] if c]
    random_factors = [f for f in list_option(options, "random_factors") if f in factors]
    conf = confidence(options)
    spec = build_spec(df, response, [], factors, what="Balanced ANOVA")

    counts = _cell_counts(spec)
    expected = int(np.prod([len(spec.levels[f]) for f in factors]))
    if len(counts) < expected or counts.nunique() != 1:
        raise ProcedureError(
            f"This design is not balanced: of {expected} factor-level combinations, {len(counts)} appear, with "
            f"{counts.min()}–{counts.max()} observations each. Balanced ANOVA needs equal counts in every cell — "
            "use Stat > ANOVA > General Linear Model, which handles unbalanced data."
        )

    terms = model_terms(spec, list_option(options, "terms") or None, bool(option(options, "interactions", True)))
    model = fit_ols(spec, terms, what="Balanced ANOVA")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table = anova_lm(model, typ=3)
    term_rows = []
    parts_of: dict[str, set[str]] = {}
    for label, row in table.iterrows():
        name = str(label)
        if name in ("Residual", "Intercept"):
            continue
        source = pretty(name, spec)
        dfree = float(row["df"])
        term_rows.append({"Source": source, "DF": int(dfree), "SS": float(row["sum_sq"]), "MS": float(row["sum_sq"] / dfree) if dfree else 0.0})
        parts_of[source] = _term_parts(name, spec)

    mse = float(model.mse_resid)
    df_error = int(model.df_resid)
    level_counts = {f: len(spec.levels[f]) for f in factors}

    # A fixed term is tested against the lowest-order interaction it has with a random factor, if
    # the model has one; otherwise against the residual. That is the standard rule for a balanced
    # design and the reason a random factor changes the F-values of the fixed terms above it.
    def error_term_for(source: str) -> tuple[str, float, float]:
        mine = parts_of[source]
        if not random_factors:
            return "Error", mse, float(df_error)
        candidates = [
            other
            for other in term_rows
            if other["Source"] != source and mine < parts_of[other["Source"]] and (parts_of[other["Source"]] - mine) & set(random_factors)
        ]
        if candidates:
            pick = min(candidates, key=lambda r: len(parts_of[r["Source"]]))
            return pick["Source"], float(pick["MS"]), float(pick["DF"])
        return "Error", mse, float(df_error)

    anova_rows = []
    for row in term_rows:
        source = row["Source"]
        kind = "random" if parts_of[source] and parts_of[source] <= set(random_factors) else "fixed"
        denom_name, denom_ms, denom_df = error_term_for(source)
        f_value = row["MS"] / denom_ms if denom_ms > 0 else None
        p_value = float(st.f.sf(f_value, row["DF"], denom_df)) if f_value and denom_df > 0 else None
        anova_rows.append(
            {
                "Source": source,
                "Type": kind,
                "DF": row["DF"],
                "Adj SS": row["SS"],
                "Adj MS": row["MS"],
                "F-Value": f_value,
                "P-Value": p_value,
                "Error term": denom_name,
            }
        )
    anova_rows.append({"Source": "Error", "Type": "", "DF": df_error, "Adj SS": float(model.ssr), "Adj MS": mse, "F-Value": None, "P-Value": None, "Error term": ""})
    anova_rows.append(
        {"Source": "Total", "Type": "", "DF": int(model.df_model + model.df_resid), "Adj SS": float(model.centered_tss), "Adj MS": None, "F-Value": None, "P-Value": None, "Error term": ""}
    )

    tables = [
        {"title": "Analysis of Variance", "rows": anova_rows},
        {"title": "Model Summary", "rows": model_summary_rows(model)},
    ]

    vc_method = str(option(options, "vc_method", "ems"))
    notes: list[str] = []
    if random_factors:
        if vc_method == "reml":
            vc_rows, vc_label = _reml_components(spec, terms, random_factors, mse)
        else:
            vc_rows, truncation_notes = _variance_components(term_rows, parts_of, random_factors, mse, df_error, spec.rows_used, level_counts)
            vc_label = "Variance components, estimated from the balanced-design expected mean squares"
            notes.extend(truncation_notes)
        tables.append({"title": vc_label, "rows": vc_rows})
    else:
        vc_label = None

    graphs = []
    if option(options, "graph_residuals", True):
        graphs.append(four_in_one(np.asarray(model.resid), np.asarray(model.fittedvalues), spec.row_labels, response))
    if option(options, "graph_main_effects", False):
        graphs.append(_fitted_main_effects(model, spec, conf))

    significant = [r for r in anova_rows if isinstance(r.get("P-Value"), float) and r["P-Value"] < 1 - conf]
    conclusion = (
        f"Balanced ANOVA on {spec.rows_used} observations, {counts.iloc[0]} per cell, "
        f"{len(factors)} factor(s) ({', '.join(factors)}"
        + (f"; random: {', '.join(random_factors)}" if random_factors else "; all fixed")
        + "). "
        + (f"Significant term(s): {', '.join(r['Source'] for r in significant)}." if significant else "No term is significant at this level.")
        + (f" {vc_label}." if vc_label else "")
    )
    if notes:
        conclusion += " Note: " + "; ".join(notes) + "."
    return {
        "procedure": "balanced_anova",
        "title": f"Balanced ANOVA: {response} versus {', '.join(factors)}",
        "method": "Type III adjusted sums of squares with sum-to-zero coding; F-tests use the expected-mean-square error term shown in the table",
        "response": response,
        "factors": factors,
        "random_factors": random_factors,
        "confidence_level": conf,
        "n": spec.rows_used,
        "note": f"{spec.rows_dropped} row(s) were dropped for missing values." if spec.rows_dropped else None,
        "tables": tables,
        "highlights": [
            {"label": "Observations", "value": spec.rows_used, "decimals": 0},
            {"label": "Per cell", "value": int(counts.iloc[0]), "decimals": 0},
            {"label": "R-sq", "value": float(model.rsquared) * 100, "suffix": "%"},
            {"label": "S", "value": math.sqrt(mse)},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Balanced ANOVA — {conclusion}",
    }


def _reml_components(spec: Spec, terms: list[str], random_factors: list[str], mse: float) -> tuple[list[dict[str, Any]], str]:
    """Variance components by REML (statsmodels MixedLM), the alternative to the EMS estimates."""
    fixed_terms = [t for t in terms if not (_term_parts(t, spec) and _term_parts(t, spec) <= set(random_factors))]
    formula = f"{spec.safe[spec.response]} ~ " + (" + ".join(fixed_terms) if fixed_terms else "1")
    frame = spec.frame.copy()
    frame["__grp"] = 1
    vc = {f: f"0 + C({spec.safe[f]})" for f in random_factors}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = MixedLM.from_formula(formula, groups="__grp", vc_formula=vc, data=frame).fit(reml=True)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The REML variance components could not be estimated: {err}") from err

    rows = []
    total = 0.0
    for name, value in fit.vcomp_and_scale() if hasattr(fit, "vcomp_and_scale") else []:
        rows.append({"Source": name, "Estimated Value": value})
    if not rows:
        for name, value in zip(vc.keys(), np.atleast_1d(fit.vcomp)):
            rows.append({"Source": name, "Estimated Value": float(value)})
    rows.append({"Source": "Error", "Estimated Value": float(fit.scale)})
    total = sum(r["Estimated Value"] for r in rows)
    for r in rows:
        r["% of Total"] = (r["Estimated Value"] / total * 100) if total > 0 else None
    return rows, "Variance components, estimated by REML (statsmodels MixedLM)"


# ---------------------------------------------------------------------------
# 4. Fully Nested ANOVA
# ---------------------------------------------------------------------------


def _nested_anova(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 3:
        raise ProcedureError("Fully Nested ANOVA needs a response and at least two nested factors.")
    response, factors = columns[0], [c for c in columns[1:] if c]
    if len(factors) > 4:
        raise ProcedureError("Fully Nested ANOVA takes at most four nested factors.")
    conf = confidence(options)
    spec = build_spec(df, response, [], factors, what="Fully Nested ANOVA")

    # Each level below the first is relabelled by its whole path, so 'batch 1' inside lot A is a
    # different level from 'batch 1' inside lot B — that is what "nested" means.
    frame = spec.frame.copy()
    nested_names = []
    path = []
    for i, factor in enumerate(factors):
        path.append(spec.safe[factor])
        key = f"n{i}"
        frame[key] = frame[path].astype(str).agg(" | ".join, axis=1)
        nested_names.append(key)

    y = spec.safe[spec.response]
    grand = float(frame[y].mean())
    n_total = len(frame)
    ss_total = float(((frame[y] - grand) ** 2).sum())

    # Sequential decomposition down the hierarchy: each level explains what the level above it left.
    rows: list[dict[str, Any]] = []
    previous_fit = pd.Series(grand, index=frame.index)
    previous_df = 1
    layers: list[dict[str, Any]] = []
    for i, key in enumerate(nested_names):
        fit = frame.groupby(key, sort=False)[y].transform("mean")
        ss = float(((fit - previous_fit) ** 2).sum())
        levels = int(frame[key].nunique())
        dfree = levels - previous_df
        if dfree <= 0:
            raise ProcedureError(
                f"'{factors[i]}' adds no degrees of freedom inside '{factors[i - 1] if i else ''}' — it has one level per parent, so it cannot be estimated."
            )
        source = factors[0] if i == 0 else f"{factors[i]} ({factors[i - 1]})"
        layers.append({"source": source, "factor": factors[i], "levels": levels, "df": dfree, "ss": ss, "ms": ss / dfree})
        previous_fit, previous_df = fit, levels

    ss_error = float(((frame[y] - previous_fit) ** 2).sum())
    df_error = n_total - previous_df
    if df_error <= 0:
        raise ProcedureError("The lowest nested factor has one observation per level, so there is no error term left. Drop a level of nesting.")
    mse = ss_error / df_error

    # Denominator for a level is the mean square of the level below it — the classic nested EMS rule.
    for i, layer in enumerate(layers):
        denom_ms, denom_df, denom_name = (layers[i + 1]["ms"], layers[i + 1]["df"], layers[i + 1]["source"]) if i + 1 < len(layers) else (mse, df_error, "Error")
        f_value = layer["ms"] / denom_ms if denom_ms > 0 else None
        p_value = float(st.f.sf(f_value, layer["df"], denom_df)) if f_value else None
        rows.append(
            {
                "Source": layer["source"],
                "DF": layer["df"],
                "Seq SS": layer["ss"],
                "Seq MS": layer["ms"],
                "F-Value": f_value,
                "P-Value": p_value,
                "Error term": denom_name,
            }
        )
    rows.append({"Source": "Error", "DF": df_error, "Seq SS": ss_error, "Seq MS": mse, "F-Value": None, "P-Value": None, "Error term": ""})
    rows.append({"Source": "Total", "DF": n_total - 1, "Seq SS": ss_total, "Seq MS": None, "F-Value": None, "P-Value": None, "Error term": ""})

    # Variance components: σ²(level) = (MS(level) − MS(below)) / (observations per level).
    vc_rows = []
    for i, layer in enumerate(layers):
        below_ms = layers[i + 1]["ms"] if i + 1 < len(layers) else mse
        per_level = n_total / layer["levels"]
        raw = (layer["ms"] - below_ms) / per_level if per_level else 0.0
        vc_rows.append({"Source": layer["source"], "Estimated Value": max(raw, 0.0), "_raw": raw})
    vc_rows.append({"Source": "Error", "Estimated Value": mse, "_raw": mse})
    total_vc = sum(r["Estimated Value"] for r in vc_rows)
    truncated = [r["Source"] for r in vc_rows if r["_raw"] < 0]
    for r in vc_rows:
        r["% of Total"] = (r["Estimated Value"] / total_vc * 100) if total_vc > 0 else None
        r["StDev"] = math.sqrt(r["Estimated Value"])
        r.pop("_raw")

    graphs = []
    if option(options, "graph_residuals", True):
        graphs.append(four_in_one(np.asarray(frame[y] - previous_fit), np.asarray(previous_fit), spec.row_labels, response))

    biggest = max((r for r in vc_rows if r["Source"] != "Error"), key=lambda r: r["Estimated Value"], default=None)
    conclusion = (
        f"Fully nested ANOVA of {response} over {' within '.join(reversed(factors))}, n = {n_total}. "
        + (
            f"{biggest['Source']} contributes the largest variance component ({g(biggest['Estimated Value'], 4)}, "
            f"{g(biggest['% of Total'], 3)}% of the total)."
            if biggest
            else ""
        )
        + (f" Negative estimates for {', '.join(truncated)} were truncated to zero." if truncated else "")
    )
    return {
        "procedure": "nested_anova",
        "title": f"Fully Nested ANOVA: {response} versus {', '.join(factors)}",
        "method": "Sequential (Type I) sums of squares down the nesting hierarchy; variance components from the nested expected mean squares",
        "response": response,
        "factors": factors,
        "n": n_total,
        "note": f"{spec.rows_dropped} row(s) were dropped for missing values." if spec.rows_dropped else None,
        "tables": [
            {"title": "Analysis of Variance", "rows": rows},
            {"title": "Variance Components", "rows": vc_rows},
        ],
        "highlights": [
            {"label": "Observations", "value": n_total, "decimals": 0},
            {"label": "Levels of nesting", "value": len(factors), "decimals": 0},
            {"label": biggest["Source"] if biggest else "Error", "value": (biggest["% of Total"] if biggest else 100), "suffix": "% of variance"},
            {"label": "S", "value": math.sqrt(mse)},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Fully Nested ANOVA — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 5. General MANOVA
# ---------------------------------------------------------------------------

_MV_STATS = ("Wilks' lambda", "Pillai's trace", "Hotelling-Lawley trace", "Roy's greatest root")


def _manova(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    n_responses = int_option(options, "n_responses", 0, what="Number of responses") or 0
    if n_responses < 2 or len(columns) <= n_responses:
        raise ProcedureError("General MANOVA needs at least two responses and at least one factor.")
    responses = columns[:n_responses]
    factors = [c for c in columns[n_responses:] if c]
    conf = confidence(options)

    spec = build_spec(df, responses[0], [], factors, what="General MANOVA", extra_responses=responses[1:])
    lhs = " + ".join(spec.safe[r] for r in responses)
    terms = model_terms(spec, list_option(options, "terms") or None, bool(option(options, "interactions", False)))
    formula = f"{lhs} ~ " + " + ".join(terms)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = MANOVA.from_formula(formula, data=spec.frame)
            test = fit.mv_test()
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The MANOVA could not be fitted: {err}") from err

    tables = []
    alpha = 1 - conf
    headline: list[str] = []
    for term_name, block in test.results.items():
        if str(term_name) == "Intercept":
            continue
        stats_table = block["stat"]
        rows = []
        for stat_name in _MV_STATS:
            if stat_name not in stats_table.index:
                continue
            row = stats_table.loc[stat_name]
            rows.append(
                {
                    "Statistic": stat_name,
                    "Value": float(row["Value"]),
                    "F-Value": float(row["F Value"]),
                    "Num DF": float(row["Num DF"]),
                    "Den DF": float(row["Den DF"]),
                    "P-Value": float(row["Pr > F"]),
                }
            )
        if not rows:
            continue
        label = pretty(str(term_name), spec)
        tables.append({"title": f"Term: {label}", "rows": rows})
        wilks = next((r for r in rows if r["Statistic"] == "Wilks' lambda"), rows[0])
        headline.append(f"{label}: Wilks' λ = {g(wilks['Value'], 4)}, F = {g(wilks['F-Value'], 4)}, p = {p_text(wilks['P-Value'])}")

    if not tables:
        raise ProcedureError("The MANOVA produced no testable terms. Check that each factor has at least two levels in the usable rows.")

    significant = [
        line for line, table in zip(headline, tables) if any(isinstance(r["P-Value"], float) and r["P-Value"] < alpha for r in table["rows"])
    ]
    conclusion = (
        f"MANOVA of {', '.join(responses)} on {', '.join(factors)}, n = {spec.rows_used}. " + " · ".join(headline) + ". "
        + (f"{len(significant)} of {len(tables)} term(s) are significant at α = {g(alpha)}." if tables else "")
    )
    first = tables[0]["rows"][0]
    return {
        "procedure": "manova",
        "title": f"General MANOVA: {', '.join(responses)} versus {', '.join(factors)}",
        "method": "statsmodels MANOVA; all four multivariate statistics reported per term with their F approximations",
        "responses": responses,
        "factors": factors,
        "n": spec.rows_used,
        "confidence_level": conf,
        "note": f"{spec.rows_dropped} row(s) were dropped for missing values." if spec.rows_dropped else None,
        "tables": tables,
        "highlights": [
            {"label": "Responses", "value": len(responses), "decimals": 0},
            {"label": "Terms tested", "value": len(tables), "decimals": 0},
            {"label": f"Wilks' λ ({tables[0]['title'].replace('Term: ', '')})", "value": first["Value"]},
            {"label": "P-Value", "value": first["P-Value"], "tone": "positive" if first["P-Value"] < alpha else None},
        ],
        "graphs": [],
        "conclusion": conclusion,
        "summary": f"General MANOVA — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 6. General Linear Model
# ---------------------------------------------------------------------------


def _glm_inputs(columns: list[str], options: dict) -> tuple[str, list[str], list[str]]:
    if not columns:
        raise ProcedureError("Fit General Linear Model needs a response.")
    response = columns[0]
    n_factors = int_option(options, "n_factors", 0, what="Number of factors") or 0
    rest = [c for c in columns[1:] if c]
    factors = rest[:n_factors]
    covariates = rest[n_factors:]
    if not factors and not covariates:
        raise ProcedureError("Fit General Linear Model needs at least one factor or covariate.")
    return response, factors, covariates


def _model_spec_payload(spec: Spec, terms_real: list[str], conf: float, kind: str) -> dict[str, Any]:
    """What the frontend stores so every downstream dialog can refit exactly this model."""
    return {
        "kind": kind,
        "response": spec.response,
        "factors": spec.factors,
        "covariates": spec.covariates,
        "terms": terms_real,
        "confidence": conf,
        "center": spec.center,
        "levels": {f: spec.levels[f] for f in spec.factors},
        "means": {c: spec.means[c] for c in spec.covariates},
        "ranges": {c: list(spec.ranges[c]) for c in spec.covariates},
    }


def _real_terms(terms: list[str], spec: Spec) -> list[str]:
    return [pretty(t, spec).replace(" * ", "*") for t in terms]


def _fitted_main_effects(model, spec: Spec, conf: float) -> dict:
    """Main-effects panels drawn from the FITTED model: each point is a marginal mean, not a raw
    average, so the other terms in the model are held constant across the panel."""
    params = np.asarray(model.params, dtype=float)
    grand = float(emm_contrast(model, spec, {}) @ params)
    panels = []
    for factor in spec.factors:
        entries = emm_rows(model, spec, factor, conf)
        panels.append(
            {
                "factor": factor,
                "labels": [e["level"] for e in entries],
                "points": [{"x": i, "label": e["level"], "y": e["mean"], "n": e["n"]} for i, e in enumerate(entries)],
            }
        )
    for covariate in spec.covariates:
        lo, hi = spec.ranges[covariate]
        xs = np.linspace(lo, hi, 5)
        points = []
        for i, value in enumerate(xs):
            contrast = emm_contrast(model, spec, {covariate: float(value)})
            points.append({"x": i, "label": f"{value:.4g}", "y": float(contrast @ params), "n": None})
        panels.append({"factor": covariate, "labels": [f"{v:.4g}" for v in xs], "points": points, "continuous": True})
    return {
        "renderer": "mainEffects",
        "title": f"Main effects plot for {spec.response} (fitted means)",
        "data": {"panels": panels, "grand_mean": grand, "value_label": spec.response, "n": spec.rows_used, "fitted": True},
    }


def _fitted_interactions(model, spec: Spec, conf: float) -> dict:
    params = np.asarray(model.params, dtype=float)
    panels = []
    for x_factor, trace_factor in itertools.combinations(spec.factors, 2):
        labels = spec.levels[x_factor]
        series = []
        for trace_level in spec.levels[trace_factor]:
            points = []
            for i, x_level in enumerate(labels):
                contrast = emm_contrast(model, spec, {x_factor: x_level, trace_factor: trace_level})
                points.append({"x": i, "label": x_level, "y": float(contrast @ params), "n": None})
            series.append({"label": f"{trace_factor} = {trace_level}", "points": points})
        panels.append({"x_factor": x_factor, "trace_factor": trace_factor, "labels": labels, "series": series})
    if not panels:
        return {}
    return {
        "renderer": "interactionPlot",
        "title": f"Interaction plot for {spec.response} (fitted means)",
        "data": {"panels": panels, "value_label": spec.response, "n": spec.rows_used, "fitted": True},
    }


def _glm(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, factors, covariates = _glm_inputs(columns, options)
    conf = confidence(options)
    spec = build_spec(df, response, covariates, factors, what="Fit General Linear Model")
    spec.center = bool(option(options, "center_covariates", True))
    terms = model_terms(spec, list_option(options, "terms") or None, bool(option(options, "interactions", False)))
    model = fit_ols(spec, terms, what="The general linear model")

    coef_rows = coefficient_rows(model, spec, conf)
    unusual, n_large, n_high = unusual_rows(model, spec)
    anova_rows = anova_table(model, spec, typ=3)

    tables = [
        {"title": "Analysis of Variance (Type III adjusted SS)", "rows": anova_rows},
        {"title": "Model Summary", "rows": model_summary_rows(model)},
        {"title": "Coefficients", "rows": coef_rows},
    ]
    if unusual:
        tables.append({"title": f"Fits and Diagnostics for Unusual Observations ({len(unusual)} shown)", "rows": unusual})

    graphs = []
    if option(options, "graph_residuals", True):
        graphs.append(four_in_one(np.asarray(model.resid), np.asarray(model.fittedvalues), spec.row_labels, response))
    if option(options, "graph_main_effects", False):
        graphs.append(_fitted_main_effects(model, spec, conf))
    if option(options, "graph_interactions", False) and len(spec.factors) >= 2:
        panel = _fitted_interactions(model, spec, conf)
        if panel:
            graphs.append(panel)

    notes = []
    if spec.rows_dropped:
        notes.append(f"{spec.rows_dropped} row(s) were dropped for missing values.")
    if n_large or n_high:
        notes.append(f"{n_large} observation(s) have a standardised residual beyond ±2 (R) and {n_high} have high leverage (X).")

    significant = [r for r in anova_rows if isinstance(r.get("P-Value"), float) and r["P-Value"] < 1 - conf and r["Source"] not in ("Error", "Total")]
    conclusion = (
        f"{response} on {len(factors)} factor(s) and {len(covariates)} covariate(s), n = {spec.rows_used}. "
        f"R² = {model.rsquared * 100:.2f}%, R²(adj) = {model.rsquared_adj * 100:.2f}%, S = {g(math.sqrt(model.mse_resid), 4)}. "
        + (f"Significant term(s): {', '.join(r['Source'] for r in significant)}." if significant else "No term is significant at this level.")
    )
    return {
        "procedure": "glm",
        "title": f"General Linear Model: {response} versus {', '.join(factors + covariates)}",
        "method": (
            "Least squares with sum-to-zero coding for the factors and covariates centred at their means; "
            "Type III (adjusted) sums of squares"
        ),
        "response": response,
        "factors": factors,
        "covariates": covariates,
        "confidence_level": conf,
        "n": spec.rows_used,
        "s": math.sqrt(float(model.mse_resid)),
        "r_squared": float(model.rsquared),
        "note": " ".join(notes) or None,
        "model_spec": _model_spec_payload(spec, _real_terms(terms, spec), conf, "glm"),
        "predict_spec": _model_spec_payload(spec, _real_terms(terms, spec), conf, "glm"),
        "tables": tables,
        "highlights": [
            {"label": "R-sq", "value": float(model.rsquared) * 100, "suffix": "%"},
            {"label": "R-sq(adj)", "value": float(model.rsquared_adj) * 100, "suffix": "%"},
            {"label": "S", "value": math.sqrt(float(model.mse_resid))},
            {"label": "Observations", "value": spec.rows_used, "decimals": 0},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"General Linear Model — {conclusion}",
    }


# ---------------------------------------------------------------------------
# the stored model: everything below refits from a model_spec the frontend kept
# ---------------------------------------------------------------------------


def _restore(df: pd.DataFrame, options: dict, *, what: str) -> tuple[Spec, Any, dict[str, Any], float]:
    stored = option(options, "model_spec", None)
    if not isinstance(stored, dict):
        raise ProcedureError(f"{what} needs a fitted model. Run Fit General Linear Model (or Fit Mixed Effects Model) first.")
    response = str(stored.get("response") or "")
    factors = [str(f) for f in stored.get("factors") or []]
    covariates = [str(c) for c in stored.get("covariates") or []]
    conf = confidence({"confidence": stored.get("confidence", 0.95)})
    spec = build_spec(df, response, covariates, factors, what=what)
    spec.center = bool(stored.get("center", True))
    terms = [safe_term(t, spec) for t in stored.get("terms") or []] or model_terms(spec, None, False)
    model = fit_ols(spec, terms, what=what)
    return spec, model, stored, conf


def _glm_comparisons(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    spec, model, stored, conf = _restore(df, options, what="Comparisons")
    factor = str(option(options, "factor", "") or "")
    if not factor:
        raise ProcedureError(f"Choose the factor whose level means should be compared. The model has: {', '.join(spec.factors)}.")
    method = str(option(options, "method", "tukey"))
    conf = confidence(options) if options.get("confidence") else conf

    outcome = compare_emms(model, spec, factor, method, conf, spec.response)
    graphs = [outcome["chart"]] if outcome["chart"] else []
    entries = outcome["emms"]
    graphs.insert(
        0,
        {
            "renderer": "interval",
            "title": f"Fitted means for {factor} with {conf * 100:g}% confidence intervals",
            "data": {
                "groups": [
                    {"label": e["level"], "index": i, "mean": e["mean"], "se": e["se"], "ci_low": e["low"], "ci_high": e["high"], "n": e["n"]}
                    for i, e in enumerate(entries)
                ],
                "labels": [e["level"] for e in entries],
                "confidence": conf,
                "value_label": f"fitted mean {spec.response}",
                "group_label": factor,
            },
        },
    )
    top = outcome["grouping"][0]
    conclusion = (
        f"{outcome['method_label']} on {factor} ({len(entries)} levels), from the stored model of {spec.response}. "
        f"{outcome['n_significant']} of {len(outcome['pairs'])} pairwise comparison(s) are significant at α = {g(1 - conf)}. "
        f"Highest fitted mean: {top['Level']} ({g(top['Mean'], 5)}, group {top['Grouping']}). "
        "Levels sharing a grouping letter could not be separated."
    )
    return {
        "procedure": "glm_comparisons",
        "title": f"Comparisons for {factor} ({stored.get('kind', 'glm').upper()})",
        "method": outcome["method_label"],
        "confidence_level": conf,
        "factor": factor,
        "n": spec.rows_used,
        "tables": outcome["tables"],
        "highlights": [
            {"label": "Levels", "value": len(entries), "decimals": 0},
            {"label": "Significant pairs", "value": outcome["n_significant"], "decimals": 0},
            {"label": "Comparisons", "value": len(outcome["pairs"]), "decimals": 0},
            {"label": f"Top: {top['Level']}", "value": top["Mean"]},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Comparisons — {conclusion}",
    }


def _settings_row(spec: Spec, values: dict[str, Any], what: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixed: dict[str, Any] = {}
    display: dict[str, Any] = {}
    for name in spec.covariates:
        raw = values.get(name, spec.means[name])
        if raw in (None, ""):
            raise ProcedureError(f"Enter a value for '{name}'.")
        try:
            fixed[name] = float(raw)
        except (TypeError, ValueError):
            raise ProcedureError(f"'{name}' needs a numeric value; got '{raw}'.") from None
        display[name] = fixed[name]
    for name in spec.factors:
        raw = values.get(name)
        if raw in (None, ""):
            raise ProcedureError(f"Choose a level for '{name}'.")
        if str(raw) not in spec.levels[name]:
            raise ProcedureError(f"'{raw}' is not a level of '{name}'. Fitted levels: {', '.join(spec.levels[name])}.")
        fixed[name] = str(raw)
        display[name] = str(raw)
    return fixed, display


def _glm_predict(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    spec, model, stored, conf = _restore(df, options, what="Predict")
    values = option(options, "values", None) or {}
    if not isinstance(values, dict):
        raise ProcedureError("Predict needs a value for each factor and covariate.")
    fixed, display = _settings_row(spec, values, "Predict")

    row = {spec.safe[k]: v for k, v in fixed.items()}
    frame = pd.DataFrame([row])
    try:
        prediction = model.get_prediction(frame).summary_frame(alpha=1 - conf)
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The prediction could not be computed: {err}") from err

    fit = float(prediction["mean"].iloc[0])
    se_fit = float(prediction["mean_se"].iloc[0])
    ci = (float(prediction["mean_ci_lower"].iloc[0]), float(prediction["mean_ci_upper"].iloc[0]))
    pi = (float(prediction["obs_ci_lower"].iloc[0]), float(prediction["obs_ci_upper"].iloc[0]))
    pct = f"{conf * 100:g}%"
    return {
        "procedure": "glm_predict",
        "title": f"Prediction for {spec.response}",
        "settings": display,
        "fit": fit,
        "se_fit": se_fit,
        "ci": list(ci),
        "pi": list(pi),
        "confidence_level": conf,
        "tables": [
            {"title": "Settings", "rows": [display]},
            {"title": "Prediction", "rows": [{"Fit": fit, "SE Fit": se_fit, f"{pct} CI": ci_text(*ci, 5), f"{pct} PI": ci_text(*pi, 5)}]},
        ],
        "conclusion": f"Predicted {spec.response} = {g(fit, 5)} (SE {g(se_fit, 4)}); {pct} CI {ci_text(*ci, 5)}, {pct} PI {ci_text(*pi, 5)}.",
        "summary": f"Predicted {spec.response} = {g(fit, 5)} for {', '.join(f'{k}={v}' for k, v in display.items())}.",
    }


def _glm_factorial_plots(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    spec, model, stored, conf = _restore(df, options, what="Factorial Plots")
    graphs = []
    if option(options, "main_effects", True):
        graphs.append(_fitted_main_effects(model, spec, conf))
    if option(options, "interactions", True) and len(spec.factors) >= 2:
        panel = _fitted_interactions(model, spec, conf)
        if panel:
            graphs.append(panel)
    if not graphs:
        raise ProcedureError("Nothing to plot: tick main effects, or interactions (which need at least two factors in the model).")

    params = np.asarray(model.params, dtype=float)
    rows = []
    for factor in spec.factors:
        for entry in emm_rows(model, spec, factor, conf):
            rows.append(
                {
                    "Term": factor,
                    "Level": entry["level"],
                    "N": entry["n"],
                    "Fitted Mean": entry["mean"],
                    "SE": entry["se"],
                    f"{conf * 100:g}% CI": ci_text(entry["low"], entry["high"], 5),
                }
            )
    grand = float(emm_contrast(model, spec, {}) @ params)
    return {
        "procedure": "glm_factorial_plots",
        "title": f"Factorial Plots for {spec.response}",
        "method": "Fitted (least-squares) means from the stored model — every panel holds the other terms constant, which raw group means do not",
        "confidence_level": conf,
        "n": spec.rows_used,
        "tables": [{"title": "Fitted means by factor level", "rows": rows}] if rows else [],
        "highlights": [
            {"label": "Overall fitted mean", "value": grand},
            {"label": "Factors", "value": len(spec.factors), "decimals": 0},
            {"label": "Covariates", "value": len(spec.covariates), "decimals": 0},
            {"label": "Observations", "value": spec.rows_used, "decimals": 0},
        ],
        "graphs": graphs,
        "conclusion": (
            f"Fitted means for {spec.response} across {', '.join(spec.factors + spec.covariates) or 'the model terms'}, "
            f"overall fitted mean {g(grand, 5)}. Non-parallel lines in an interaction panel are the interaction."
        ),
        "summary": f"Factorial Plots for {spec.response} (fitted means).",
    }


def _surface_grid(model, spec: Spec, options: dict, what: str) -> dict[str, Any]:
    available = spec.covariates
    if len(available) < 2:
        raise ProcedureError(f"{what} needs two continuous predictors in the model; it has {len(available)} ({', '.join(available) or 'none'}).")
    x_name = str(option(options, "x", available[0]) or available[0])
    y_name = str(option(options, "y", available[1]) or available[1])
    if x_name not in available or y_name not in available:
        raise ProcedureError(f"Choose two of the model's covariates. Available: {', '.join(available)}.")
    if x_name == y_name:
        raise ProcedureError("Choose two different predictors for the two axes.")

    resolution = int_option(options, "resolution", 40, what="Grid resolution") or 40
    resolution = max(10, min(resolution, 80))
    holds = option(options, "holds", None) or {}

    fixed: dict[str, Any] = {}
    held_rows = []
    for name in spec.covariates:
        if name in (x_name, y_name):
            continue
        value = float(holds.get(name, spec.means[name]))
        fixed[name] = value
        held_rows.append({"Predictor": name, "Held at": value})
    for name in spec.factors:
        level = str(holds.get(name) or spec.levels[name][0])
        if level not in spec.levels[name]:
            raise ProcedureError(f"'{level}' is not a level of '{name}'.")
        fixed[name] = level
        held_rows.append({"Predictor": name, "Held at": level})

    lo_x, hi_x = spec.ranges[x_name]
    lo_y, hi_y = spec.ranges[y_name]
    xs = np.linspace(lo_x, hi_x, resolution)
    ys = np.linspace(lo_y, hi_y, resolution)
    params = np.asarray(model.params, dtype=float)

    rows = []
    for y_value in ys:
        for x_value in xs:
            row = {spec.safe[k]: v for k, v in fixed.items()}
            row[spec.safe[x_name]] = float(x_value)
            row[spec.safe[y_name]] = float(y_value)
            rows.append(row)
    design = _design(model, pd.DataFrame(rows))
    z = (design @ params).reshape(len(ys), len(xs))

    return {
        "x": [float(v) for v in xs],
        "y": [float(v) for v in ys],
        "z": [[float(v) for v in row] for row in z],
        "x_label": x_name,
        "y_label": y_name,
        "z_label": f"fitted {spec.response}",
        "n": spec.rows_used,
        "held": held_rows,
        "z_min": float(np.min(z)),
        "z_max": float(np.max(z)),
        "x_name": x_name,
        "y_name": y_name,
    }


def _glm_surface_like(df: pd.DataFrame, options: dict, *, renderer: str, procedure: str, noun: str) -> dict:
    spec, model, stored, conf = _restore(df, options, what=noun)
    grid = _surface_grid(model, spec, options, noun)
    held = grid.pop("held")
    x_name, y_name = grid.pop("x_name"), grid.pop("y_name")
    return {
        "procedure": procedure,
        "title": f"{noun} of {spec.response} versus {x_name} and {y_name}",
        "method": f"Fitted response over the two chosen predictors; every other predictor is held at the value shown, and the surface is the model's prediction, not the data",
        "confidence_level": conf,
        "n": spec.rows_used,
        "tables": [{"title": "Held values", "rows": held}] if held else [],
        "highlights": [
            {"label": "Lowest fitted", "value": grid["z_min"]},
            {"label": "Highest fitted", "value": grid["z_max"]},
            {"label": "Grid", "value": len(grid["x"]), "decimals": 0, "suffix": f"×{len(grid['y'])}"},
            {"label": "Observations", "value": spec.rows_used, "decimals": 0},
        ],
        "graphs": [{"renderer": renderer, "title": f"{noun}: fitted {spec.response}", "data": grid}],
        "conclusion": (
            f"Fitted {spec.response} over {x_name} × {y_name} ranges from {g(grid['z_min'], 5)} to {g(grid['z_max'], 5)}"
            + (", with " + ", ".join("{} = {}".format(r["Predictor"], r["Held at"]) for r in held) + " held constant." if held else ".")
        ),
        "summary": f"{noun} of fitted {spec.response} over {x_name} and {y_name}.",
    }


def _glm_contour(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    return _glm_surface_like(df, options, renderer="contour", procedure="glm_contour", noun="Contour Plot")


def _glm_surface(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    return _glm_surface_like(df, options, renderer="surface", procedure="glm_surface", noun="Surface Plot")


# ---------------------------------------------------------------------------
# 7. Response Optimizer
# ---------------------------------------------------------------------------


def _desirability(y: np.ndarray, goal: str, lower: float, target: float, upper: float, weight: float) -> np.ndarray:
    """Derringer-Suich desirability: 0 where the response is unacceptable, 1 where it is ideal."""
    y = np.asarray(y, dtype=float)
    d = np.zeros_like(y)
    if goal == "maximize":
        span = target - lower
        if span <= 0:
            return np.where(y >= target, 1.0, 0.0)
        d = np.clip((y - lower) / span, 0.0, 1.0) ** weight
        d = np.where(y >= target, 1.0, d)
    elif goal == "minimize":
        span = upper - target
        if span <= 0:
            return np.where(y <= target, 1.0, 0.0)
        d = np.clip((upper - y) / span, 0.0, 1.0) ** weight
        d = np.where(y <= target, 1.0, d)
    else:  # target
        low_span, high_span = target - lower, upper - target
        below = np.clip((y - lower) / low_span, 0.0, 1.0) ** weight if low_span > 0 else (y >= lower).astype(float)
        above = np.clip((upper - y) / high_span, 0.0, 1.0) ** weight if high_span > 0 else (y <= upper).astype(float)
        d = np.where(y <= target, below, above)
        d = np.where((y < lower) | (y > upper), 0.0, d)
    return np.clip(d, 0.0, 1.0)


def _glm_optimizer(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    spec, model, stored, conf = _restore(df, options, what="Response Optimizer")
    goal = str(option(options, "goal", "maximize"))
    if goal not in ("maximize", "minimize", "target"):
        raise ProcedureError("The goal must be maximize, minimize or target.")
    if not spec.covariates and not spec.factors:
        raise ProcedureError("The stored model has nothing to optimise over.")

    observed = np.asarray(spec.frame[spec.safe[spec.response]], dtype=float)
    obs_lo, obs_hi = float(observed.min()), float(observed.max())
    lower = float_option(options, "lower", obs_lo, what="Lower bound")
    upper = float_option(options, "upper", obs_hi, what="Upper bound")
    default_target = obs_hi if goal == "maximize" else obs_lo if goal == "minimize" else float(np.mean(observed))
    target = float_option(options, "target", default_target, what="Target")
    weight = float_option(options, "weight", 1.0, what="Importance weight") or 1.0
    if weight <= 0:
        raise ProcedureError("The importance weight must be greater than zero.")
    if goal == "target" and not (lower < target < upper):
        raise ProcedureError(f"For a target goal the bounds must straddle the target: lower {g(lower)} < target {g(target)} < upper {g(upper)}.")

    params = np.asarray(model.params, dtype=float)
    covariates = spec.covariates
    bounds = [spec.ranges[c] for c in covariates]

    def predict(levels: dict[str, str], x: np.ndarray) -> float:
        row = {spec.safe[name]: float(value) for name, value in zip(covariates, np.atleast_1d(x))}
        row.update({spec.safe[name]: level for name, level in levels.items()})
        return float(_design(model, pd.DataFrame([row]))[0] @ params)

    def negative_desirability(x: np.ndarray, levels: dict[str, str]) -> float:
        return -float(_desirability(np.array([predict(levels, x)]), goal, lower, target, upper, weight)[0])

    # Categorical factors are enumerated exhaustively (there are never many level combinations);
    # the continuous predictors are optimised inside each combination from several starts, because
    # a desirability surface that saturates at 0 or 1 has large flat regions a single start sticks in.
    factor_combos = list(itertools.product(*[spec.levels[f] for f in spec.factors])) if spec.factors else [()]
    if len(factor_combos) > 500:
        raise ProcedureError(f"The model has {len(factor_combos)} factor-level combinations to search; that is too many to optimise over.")

    starts = max(3, int_option(options, "starts", 8, what="Optimisation restarts") or 8)
    best = {"desirability": -1.0}
    for combo in factor_combos:
        levels = dict(zip(spec.factors, combo))
        if not covariates:
            value = predict(levels, np.array([]))
            d = float(_desirability(np.array([value]), goal, lower, target, upper, weight)[0])
            if d > best["desirability"]:
                best = {"desirability": d, "levels": levels, "x": np.array([]), "fit": value}
            continue
        grid = [np.linspace(lo, hi, starts) for lo, hi in bounds]
        seeds = [np.array([axis[i % len(axis)] for axis in grid]) for i in range(starts)]
        seeds.append(np.array([spec.means[c] for c in covariates]))
        for seed in seeds:
            try:
                result = optimize.minimize(negative_desirability, seed, args=(levels,), bounds=bounds, method="L-BFGS-B")
            except Exception:  # noqa: BLE001 - a failed start is simply not a candidate
                continue
            d = -float(result.fun)
            if d > best["desirability"]:
                best = {"desirability": d, "levels": levels, "x": np.asarray(result.x, dtype=float), "fit": predict(levels, result.x)}

    if best["desirability"] < 0:
        raise ProcedureError("The optimiser could not evaluate the model anywhere in the predictor ranges.")

    optimum = {**{c: float(v) for c, v in zip(covariates, best["x"])}, **best["levels"]}
    fixed_for_ci = {c: float(v) for c, v in zip(covariates, best["x"])}
    fixed_for_ci.update(best["levels"])
    row = {spec.safe[k]: v for k, v in fixed_for_ci.items()}
    prediction = model.get_prediction(pd.DataFrame([row])).summary_frame(alpha=1 - conf)
    fit = float(prediction["mean"].iloc[0])
    ci = (float(prediction["mean_ci_lower"].iloc[0]), float(prediction["mean_ci_upper"].iloc[0]))
    pi = (float(prediction["obs_ci_lower"].iloc[0]), float(prediction["obs_ci_upper"].iloc[0]))

    settings_rows = [{"Predictor": name, "Optimal setting": optimum[name], "Range searched": f"{g(spec.ranges[name][0], 4)} to {g(spec.ranges[name][1], 4)}"} for name in covariates]
    settings_rows += [{"Predictor": name, "Optimal setting": optimum[name], "Range searched": ", ".join(spec.levels[name])} for name in spec.factors]

    # Per-predictor desirability profile: sweep one predictor across its range with everything
    # else held at the optimum — Minitab's optimisation plot, one panel per predictor.
    panels = []
    for name in covariates:
        lo, hi = spec.ranges[name]
        xs = np.linspace(lo, hi, 41)
        ys, ds = [], []
        for value in xs:
            x = np.array([value if c == name else optimum[c] for c in covariates], dtype=float)
            prediction_value = predict(best["levels"], x)
            ys.append(prediction_value)
            ds.append(float(_desirability(np.array([prediction_value]), goal, lower, target, upper, weight)[0]))
        panels.append(
            {
                "predictor": name,
                "continuous": True,
                "optimum": optimum[name],
                "points": [{"x": float(x), "y": float(y), "d": float(d)} for x, y, d in zip(xs, ys, ds)],
            }
        )
    for name in spec.factors:
        points = []
        for level in spec.levels[name]:
            levels = {**best["levels"], name: level}
            value = predict(levels, best["x"])
            points.append(
                {"x": spec.levels[name].index(level), "label": level, "y": value, "d": float(_desirability(np.array([value]), goal, lower, target, upper, weight)[0])}
            )
        panels.append({"predictor": name, "continuous": False, "optimum": optimum[name], "labels": spec.levels[name], "points": points})

    pct = f"{conf * 100:g}%"
    goal_text = {"maximize": f"maximise (ideal at or above {g(target, 5)})", "minimize": f"minimise (ideal at or below {g(target, 5)})", "target": f"hit {g(target, 5)}"}[goal]
    conclusion = (
        f"Optimal settings give a fitted {spec.response} of {g(fit, 5)} with desirability {g(best['desirability'], 4)} "
        f"(goal: {goal_text}). {pct} CI {ci_text(*ci, 5)}, {pct} PI {ci_text(*pi, 5)}. "
        + ", ".join(f"{k} = {g(v, 5) if isinstance(v, float) else v}" for k, v in optimum.items())
        + "."
    )
    return {
        "procedure": "glm_optimizer",
        "title": f"Response Optimizer: {spec.response}",
        "method": (
            f"Derringer-Suich desirability (weight {g(weight)}) over the fitted model, maximised with L-BFGS-B from "
            f"{starts + 1} starting points per factor-level combination"
        ),
        "confidence_level": conf,
        "goal": goal,
        "desirability": best["desirability"],
        "fit": fit,
        "n": spec.rows_used,
        "tables": [
            {"title": "Optimal settings", "rows": settings_rows},
            {
                "title": "Predicted response at the optimum",
                "rows": [{"Fit": fit, f"{pct} CI": ci_text(*ci, 5), f"{pct} PI": ci_text(*pi, 5), "Desirability": best["desirability"]}],
            },
            {
                "title": "Desirability definition",
                "rows": [{"Goal": goal, "Lower": lower, "Target": target, "Upper": upper, "Weight": weight}],
            },
        ],
        "highlights": [
            {"label": "Desirability", "value": best["desirability"], "tone": "positive" if best["desirability"] > 0.8 else None},
            {"label": f"Fitted {spec.response}", "value": fit},
            {"label": "Goal", "value": goal, "decimals": 0},
            {"label": "Predictors optimised", "value": len(covariates) + len(spec.factors), "decimals": 0},
        ],
        "graphs": [
            {
                "renderer": "desirabilityProfile",
                "title": "Desirability profile — one panel per predictor, others held at the optimum",
                "data": {"panels": panels, "response": spec.response, "goal": goal, "desirability": best["desirability"], "fit": fit},
            }
        ],
        "conclusion": conclusion,
        "summary": f"Response Optimizer — {conclusion}",
    }


# ---------------------------------------------------------------------------
# 8. Mixed Effects Model
# ---------------------------------------------------------------------------


def _mixed_inputs(columns: list[str], options: dict) -> tuple[str, list[str], list[str], list[str]]:
    if not columns:
        raise ProcedureError("Fit Mixed Effects Model needs a response.")
    response = columns[0]
    n_fixed_factors = int_option(options, "n_fixed_factors", 0, what="Number of fixed factors") or 0
    n_covariates = int_option(options, "n_covariates", 0, what="Number of covariates") or 0
    rest = [c for c in columns[1:] if c]
    fixed_factors = rest[:n_fixed_factors]
    covariates = rest[n_fixed_factors : n_fixed_factors + n_covariates]
    random_factors = rest[n_fixed_factors + n_covariates :]
    if not random_factors:
        raise ProcedureError("A mixed effects model needs at least one random factor.")
    return response, fixed_factors, covariates, random_factors


def _fit_mixed(df: pd.DataFrame, response: str, fixed_factors: list[str], covariates: list[str], random_factors: list[str], options: dict):
    spec = build_spec(df, response, covariates, list(dict.fromkeys([*fixed_factors, *random_factors])), what="Fit Mixed Effects Model")
    # The random factors are in the spec so their columns are in the frame, but they must not enter
    # the fixed part of the formula — that is exactly what makes them random.
    fixed_terms = model_terms(spec, list_option(options, "terms") or None, bool(option(options, "interactions", False)))
    keep = [term for term in fixed_terms if not (_term_parts(term, spec) & set(random_factors))]
    formula = f"{spec.safe[response]} ~ " + (" + ".join(keep) if keep else "1")

    frame = spec.frame.copy()
    slopes = [s for s in list_option(options, "random_slopes") if s in covariates]
    method = str(option(options, "method", "reml"))

    # One random factor is MixedLM's native case: it becomes `groups`, and random slopes ride on
    # re_formula. With more than one, `groups` cannot carry them — and passing a vc_formula
    # alongside a grouping factor makes statsmodels silently drop that factor's own intercept, so
    # the first random factor would contribute nothing at all. Instead every random factor becomes
    # a variance component inside a single dummy group, which is the standard idiom for crossed
    # random effects and treats them all alike.
    if len(random_factors) == 1:
        groups_factor = random_factors[0]
        groups = frame[spec.safe[groups_factor]]
        re_formula = ("~ " + " + ".join(spec.safe[s] for s in slopes)) if slopes else None
        vc = None
        re_names = [f"{groups_factor} (intercept)"] + [f"{groups_factor} × {s} (slope)" for s in slopes]
        vc_names: list[str] = []
        n_groups_label = f"{groups_factor}"
    else:
        groups_factor = None
        frame["__all"] = 1
        groups = frame["__all"]
        re_formula = "0"
        vc = {f: f"0 + C({spec.safe[f]})" for f in random_factors}
        for slope in slopes:
            vc[f"{random_factors[0]} × {slope} (slope)"] = f"0 + C({spec.safe[random_factors[0]]}):{spec.safe[slope]}"
        re_names = []
        vc_names = list(vc.keys())
        n_groups_label = ", ".join(random_factors)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = MixedLM.from_formula(formula, groups=groups, re_formula=re_formula, vc_formula=vc, data=frame)
            fit = model.fit(reml=(method != "ml"))
    except Exception as err:  # noqa: BLE001
        raise ProcedureError(f"The mixed effects model could not be fitted: {err}") from err
    levels = {f: int(spec.frame[spec.safe[f]].nunique()) for f in random_factors}
    return spec, fit, keep, groups_factor, slopes, method, re_names, vc_names, levels, n_groups_label


def _mixed_model(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    response, fixed_factors, covariates, random_factors = _mixed_inputs(columns, options)
    conf = confidence(options)
    spec, fit, fixed_terms, groups_factor, slopes, method, re_names, vc_names, levels, n_groups_label = _fit_mixed(
        df, response, fixed_factors, covariates, random_factors, options
    )

    crit = float(st.norm.ppf(0.5 + conf / 2))
    coef_rows = []
    for name in fit.params.index:
        if name.startswith("Group") or "Var" in str(name) or "Cov" in str(name):
            continue
        estimate = float(fit.params[name])
        se = float(fit.bse[name]) if name in fit.bse.index else float("nan")
        coef_rows.append(
            {
                "Term": "Constant" if name == "Intercept" else pretty(str(name), spec),
                "Coef": estimate,
                "SE Coef": se,
                f"{conf * 100:g}% CI": ci_text(estimate - crit * se, estimate + crit * se, 5),
                "Z-Value": float(fit.tvalues[name]) if name in fit.tvalues.index else None,
                "P-Value": float(fit.pvalues[name]) if name in fit.pvalues.index else None,
            }
        )

    # Variance components: the grouping factor's intercept variance, any extra random factors'
    # components, and the residual.
    # statsmodels does not expose exog_re_names on every version, and reading it as None silently
    # dropped the random slopes from this table. The names are known from how the fit was built.
    vc_rows = []
    cov_re = np.atleast_2d(np.asarray(fit.cov_re, dtype=float))
    for i in range(cov_re.shape[0]):
        label = re_names[i] if i < len(re_names) else f"{groups_factor} (random term {i + 1})"
        variance = float(cov_re[i, i]) * float(fit.scale)
        vc_rows.append({"Source": label, "Variance": variance, "StDev": math.sqrt(max(variance, 0.0))})
    # cov_re is scaled by the residual variance; its off-diagonal is the intercept-slope covariance,
    # which is what says whether groups that start high also climb faster.
    for i, j in itertools.combinations(range(cov_re.shape[0]), 2):
        covariance = float(cov_re[i, j]) * float(fit.scale)
        sd_i, sd_j = math.sqrt(max(float(cov_re[i, i]) * float(fit.scale), 0.0)), math.sqrt(max(float(cov_re[j, j]) * float(fit.scale), 0.0))
        correlation = covariance / (sd_i * sd_j) if sd_i > 0 and sd_j > 0 else None
        vc_rows.append(
            {
                "Source": f"  covariance: {re_names[i] if i < len(re_names) else i} with {re_names[j] if j < len(re_names) else j}",
                "Variance": covariance,
                "StDev": None,
                "Correlation": correlation,
            }
        )
    for name, value in zip(vc_names, np.atleast_1d(np.asarray(fit.vcomp, dtype=float))):
        variance = float(value) * float(fit.scale)
        vc_rows.append({"Source": name, "Variance": variance, "StDev": math.sqrt(max(variance, 0.0))})
    vc_rows.append({"Source": "Residual", "Variance": float(fit.scale), "StDev": math.sqrt(float(fit.scale))})
    # A covariance row is not a share of anything, so it is left out of the total it would distort.
    is_variance = [not str(r["Source"]).startswith("  covariance") for r in vc_rows]
    total = sum(r["Variance"] for r, keep in zip(vc_rows, is_variance) if keep)
    for r, keep in zip(vc_rows, is_variance):
        r["% of Total"] = (r["Variance"] / total * 100) if keep and total > 0 else None

    loglike = float(fit.llf)
    # statsmodels leaves AIC/BIC as NaN under REML, because a REML likelihood is not comparable
    # across models with different fixed parts. They are still the right thing for comparing
    # random structures, so they are computed here and counted the way REML requires: only the
    # covariance parameters, not the fixed effects.
    reml = method != "ml"
    n_cov_params = len(np.atleast_1d(fit.params)) - len(fit.fe_params) if hasattr(fit, "fe_params") else 1
    k_params = max(1, n_cov_params + 1) if reml else len(np.atleast_1d(fit.params)) + 1
    aic = float(fit.aic) if np.isfinite(fit.aic) else -2 * loglike + 2 * k_params
    bic = float(fit.bic) if np.isfinite(fit.bic) else -2 * loglike + k_params * math.log(spec.rows_used)
    summary_rows = [
        {
            "Method": "REML" if reml else "Maximum likelihood",
            "Log-likelihood": loglike,
            "AIC": aic,
            "BIC": bic,
            "Groups": " · ".join(f"{name}: {count}" for name, count in levels.items()),
            "Observations": int(spec.rows_used),
        }
    ]

    graphs = []
    if option(options, "graph_residuals", True):
        resid = np.asarray(fit.resid, dtype=float)
        fitted = np.asarray(fit.fittedvalues, dtype=float)
        graphs.append(four_in_one(resid, fitted, spec.row_labels, response))

    significant = [r for r in coef_rows if r["Term"] != "Constant" and isinstance(r["P-Value"], float) and r["P-Value"] < 1 - conf]
    biggest = max((r for r in vc_rows if r["Source"] != "Residual"), key=lambda r: r["Variance"], default=None)
    conclusion = (
        f"{response} with {len(fixed_factors)} fixed factor(s), {len(covariates)} covariate(s) and "
        f"{len(random_factors)} random factor(s), n = {spec.rows_used} over "
        + " and ".join(f"{count} level(s) of {name}" for name, count in levels.items())
        + ". "
        f"{'REML' if method != 'ml' else 'ML'} log-likelihood {g(loglike, 6)}. "
        + (f"Significant fixed term(s): {', '.join(r['Term'] for r in significant)}. " if significant else "No fixed term is significant at this level. ")
        + (f"{biggest['Source']} accounts for {g(biggest['% of Total'], 3)}% of the variance." if biggest else "")
    )
    # The fixed part is refitted as OLS for the downstream dialogs — comparisons and factorial
    # plots need a design matrix and a covariance of the fixed effects, which is what they use.
    model_spec = _model_spec_payload(spec, _real_terms(fixed_terms, spec), conf, "mixed")
    model_spec["factors"] = [f for f in spec.factors if f not in random_factors]
    model_spec["random_factors"] = random_factors
    return {
        "procedure": "mixed_model",
        "title": f"Mixed Effects Model: {response} versus {', '.join(fixed_factors + covariates) or '(intercept only)'}",
        "method": (
            f"statsmodels MixedLM, {'REML' if method != 'ml' else 'maximum likelihood'}; random intercept(s) for {n_groups_label}"
            + (f" with random slope(s) for {', '.join(slopes)}" if slopes else "")
            + ("; fitted as crossed variance components inside one group, so no random factor loses its intercept" if len(random_factors) > 1 else "")
            + (". AIC/BIC count only the covariance parameters, as a REML likelihood requires — they compare random structures, not fixed ones" if reml else "")
        ),
        "response": response,
        "fixed_factors": fixed_factors,
        "covariates": covariates,
        "random_factors": random_factors,
        "confidence_level": conf,
        "n": spec.rows_used,
        "note": f"{spec.rows_dropped} row(s) were dropped for missing values." if spec.rows_dropped else None,
        "model_spec": model_spec,
        "tables": [
            {"title": "Model Summary", "rows": summary_rows},
            {"title": "Fixed Effects", "rows": coef_rows},
            {"title": "Variance Components", "rows": vc_rows},
        ],
        "highlights": [
            {"label": "Random levels", "value": sum(levels.values()), "decimals": 0},
            {"label": "AIC", "value": aic},
            {"label": "Residual StDev", "value": math.sqrt(float(fit.scale))},
            {"label": biggest["Source"] if biggest else "Residual", "value": (biggest["% of Total"] if biggest else 100), "suffix": "% of variance"},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Mixed Effects Model — {conclusion}",
    }


def _mixed_downstream_note() -> str:
    return (
        "Computed from the fixed part of the stored mixed model, refitted by least squares: the marginal means and their "
        "differences are the same contrasts, but their standard errors ignore the random structure, so they are slightly "
        "optimistic. Read the variance components in the model output alongside them."
    )


def _mixed_comparisons(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    result = _glm_comparisons(df, columns, options)
    result["procedure"] = "mixed_comparisons"
    result["note"] = _mixed_downstream_note()
    return result


def _mixed_predict(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    result = _glm_predict(df, columns, options)
    result["procedure"] = "mixed_predict"
    result["note"] = _mixed_downstream_note()
    return result


def _mixed_factorial_plots(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    result = _glm_factorial_plots(df, columns, options)
    result["procedure"] = "mixed_factorial_plots"
    result["note"] = _mixed_downstream_note()
    return result


# ---------------------------------------------------------------------------
# 9. standalone plots (the Graph menu's own computations, surfaced here too)
# ---------------------------------------------------------------------------


def _delegated_plot(df: pd.DataFrame, columns: list[str], options: dict, *, graph_type: str, renderer: str, procedure: str, noun: str) -> dict:
    data = graphs_core.compute(df, graph_type, columns, options)
    value_label = data.get("value_label") or (columns[0] if columns else "response")
    factors = [c for c in columns[1:] if c] or ([options.get("group_column")] if options.get("group_column") else [])
    tables = []
    if graph_type == "interval":
        tables.append(
            {
                "title": "Group means",
                "rows": [
                    {"Level": gr["label"], "N": gr["n"], "Mean": gr["mean"], "SE Mean": gr["se"], f"{data['confidence'] * 100:g}% CI": ci_text(gr["ci_low"], gr["ci_high"], 5)}
                    for gr in data["groups"]
                ],
            }
        )
    elif graph_type == "main_effects":
        tables.append(
            {
                "title": "Means by factor level",
                "rows": [
                    {"Factor": panel["factor"], "Level": point["label"], "N": point["n"], "Mean": point["y"]}
                    for panel in data["panels"]
                    for point in panel["points"]
                ],
            }
        )
    return {
        "procedure": procedure,
        "title": f"{noun}: {value_label}" + (f" versus {', '.join(str(f) for f in factors if f)}" if factors else ""),
        "method": "Raw group means from the worksheet — not adjusted for any model",
        "n": data.get("n"),
        "tables": tables,
        "highlights": [],
        "graphs": [{"renderer": renderer, "title": f"{noun} of {value_label}", "data": data}],
        "conclusion": f"{noun} of {value_label}" + (f" by {', '.join(str(f) for f in factors if f)}." if factors else "."),
        "summary": f"{noun} of {value_label}.",
    }


def _interval_plot(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) > 1 and not options.get("group_column"):
        options = {**options, "group_column": columns[1]}
    return _delegated_plot(df, columns[:1], options, graph_type="interval", renderer="interval", procedure="interval_plot", noun="Interval Plot")


def _main_effects_plot(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    return _delegated_plot(df, columns, options, graph_type="main_effects", renderer="mainEffects", procedure="main_effects_plot", noun="Main Effects Plot")


def _interaction_plot(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    return _delegated_plot(df, columns, options, graph_type="interaction", renderer="interactionPlot", procedure="interaction_plot", noun="Interaction Plot")


# ---------------------------------------------------------------------------
# 10. Analysis of Means
# ---------------------------------------------------------------------------


def _anom(df: pd.DataFrame, columns: list[str], options: dict) -> dict:
    if len(columns) < 2:
        raise ProcedureError("Analysis of Means needs a response and a factor column.")
    response, factor = columns[0], columns[1]
    alpha = float_option(options, "alpha", 0.05, what="Significance level") or 0.05
    if not 0 < alpha < 0.5:
        raise ProcedureError(f"The significance level must be between 0 and 0.5; got {g(alpha)}.")

    groups, samples = _group_summaries(df, response, factor, "Analysis of Means")
    for gr in groups:
        if gr["n"] < 2:
            raise ProcedureError(f"Group '{gr['label']}' has only {gr['n']} observation — ANOM needs at least 2 per group.")

    k = len(groups)
    n_total = sum(gr["n"] for gr in groups)
    grand = float(sum(gr["mean"] * gr["n"] for gr in groups) / n_total)
    df_error = n_total - k
    mse = float(sum((gr["n"] - 1) * gr["var"] for gr in groups) / df_error)
    s = math.sqrt(mse)
    if s <= 0:
        raise ProcedureError("Every group is constant, so there is no variation to set decision limits from.")

    # Nelson's exact h(α, k, ν) is not in scipy. The Bonferroni-adjusted t bound —
    # h = t(1 − α/(2k), ν) — is the standard conservative substitute, and it is what the output says
    # it is using. Limits are slightly wider than Minitab's exact ones, so ANOM here never calls a
    # group significant that the exact table would not.
    h = float(st.t.ppf(1 - alpha / (2 * k), df_error))

    rows = []
    chart_groups = []
    exceeded = []
    for i, gr in enumerate(groups):
        half = h * s * math.sqrt((k - 1) / (k * gr["n"]))
        udl, ldl = grand + half, grand - half
        outside = gr["mean"] > udl or gr["mean"] < ldl
        if outside:
            exceeded.append(gr["label"])
        rows.append(
            {
                "Level": gr["label"],
                "N": gr["n"],
                "Mean": gr["mean"],
                "Lower decision limit": ldl,
                "Upper decision limit": udl,
                "Outside limits": "yes" if outside else "",
            }
        )
        chart_groups.append({"label": gr["label"], "index": i, "mean": gr["mean"], "ldl": ldl, "udl": udl, "n": gr["n"], "outside": outside})

    graphs = [
        {
            "renderer": "anomChart",
            "title": f"Analysis of Means for {response} (α = {g(alpha)})",
            "data": {
                "groups": chart_groups,
                "labels": [gr["label"] for gr in groups],
                "center": grand,
                "alpha": alpha,
                "value_label": response,
                "group_label": factor,
            },
        }
    ]
    graphs.extend(_raw_graphs({**options, "graph_interval": option(options, "graph_interval", False)}, samples, groups, 1 - alpha, response, factor))

    conclusion = (
        f"ANOM for {response} across {k} levels of {factor}, centre line {g(grand, 5)}, pooled s = {g(s, 4)} on {df_error} DF. "
        + (
            f"{len(exceeded)} level(s) fall outside the decision limits at α = {g(alpha)}: {', '.join(exceeded)}."
            if exceeded
            else f"No level falls outside the decision limits at α = {g(alpha)}."
        )
    )
    return {
        "procedure": "anom",
        "title": f"Analysis of Means: {response} versus {factor}",
        "method": (
            f"One-way ANOM for normally distributed data. Decision limits are X̄ ± h·s·√((k−1)/(k·nᵢ)) with "
            f"h = t(1 − α/2k, ν) = {g(h, 5)} — the Bonferroni-adjusted t bound standing in for Nelson's exact h, "
            "which is a table scipy does not carry. The limits are therefore slightly conservative."
        ),
        "response": response,
        "factor": factor,
        "alpha": alpha,
        "n": n_total,
        "center": grand,
        "tables": [{"title": "Decision limits", "rows": rows}],
        "highlights": [
            {"label": "Centre line", "value": grand},
            {"label": "Levels outside limits", "value": len(exceeded), "decimals": 0, "tone": "negative" if exceeded else None},
            {"label": "Pooled StDev", "value": s},
            {"label": "h (Bonferroni t)", "value": h},
        ],
        "graphs": graphs,
        "conclusion": conclusion,
        "summary": f"Analysis of Means — {conclusion}",
    }


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[pd.DataFrame, list[str], dict], dict]] = {
    "one_way": _one_way,
    "equal_variances": _equal_variances,
    "balanced_anova": _balanced_anova,
    "nested_anova": _nested_anova,
    "manova": _manova,
    "glm": _glm,
    "glm_comparisons": _glm_comparisons,
    "glm_predict": _glm_predict,
    "glm_factorial_plots": _glm_factorial_plots,
    "glm_contour": _glm_contour,
    "glm_surface": _glm_surface,
    "glm_optimizer": _glm_optimizer,
    "mixed_model": _mixed_model,
    "mixed_comparisons": _mixed_comparisons,
    "mixed_predict": _mixed_predict,
    "mixed_factorial_plots": _mixed_factorial_plots,
    "interval_plot": _interval_plot,
    "main_effects_plot": _main_effects_plot,
    "interaction_plot": _interaction_plot,
    "anom": _anom,
}


# The procedures that take (response, factor) positionally in the stacked layout. Listed so the
# grouping WARNING can be attached once here; the outright refusal already happens inside
# _group_summaries, which every one of them goes through.
_STACKED_GROUP_PROCEDURES = frozenset(
    {"one_way", "equal_variances", "interval_plot", "individual_value_plot", "main_effects_plot", "anom"}
)


def compute(df: pd.DataFrame, procedure: str, columns: list[str] | None, options: dict | None) -> dict:
    handler = _HANDLERS.get(procedure)
    if handler is None:
        raise ProcedureError(f"'{procedure}' is not an ANOVA procedure. Known procedures: {', '.join(PROCEDURES)}.")
    if df is None or df.empty:
        raise ProcedureError("The worksheet is empty.")
    cols = [str(c) for c in (columns or [])]
    opts = dict(options or {})
    result = handler(df, cols, opts)

    # A crowded-but-legal grouping column is reported alongside the result rather than refused: 22
    # levels is a real analysis with an unreadable axis, and the person should be told which it is.
    if procedure in _STACKED_GROUP_PROCEDURES and len(cols) >= 2 and str(opts.get("layout", "one_column")) != "columns":
        warning = check_group_column(df, cols[1], what="This procedure", value_column=cols[0], swap=("response", "factor"))
        if warning and not result.get("warnings"):
            result["warnings"] = [warning]
    return json_safe(result)
