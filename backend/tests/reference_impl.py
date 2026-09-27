"""Textbook formulas, written out longhand, as an independent second opinion.

The weakest possible "validation" is to check that Gosset's `scipy.stats.ttest_ind` agrees with the
test's `scipy.stats.ttest_ind`. That proves the arguments were spelled right and nothing else. Every
function here therefore implements the formula from its definition — sums, means, square roots — and
touches scipy only for distribution tails (`t.sf`, `chi2.sf`, `beta.ppf`), which is arithmetic no
sensible test would reimplement and which is itself validated separately in
`test_distributions.py` against published table values.

Each function names the source of the formula it implements. Where a definition has variants that
disagree (Levene centring, Dixon's ratio, Bartlett's correction factor) the variant is stated,
because "the p-values differ" is otherwise indistinguishable from "one of us is wrong".
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Sequence

import numpy as np
from scipy import stats as st


# --- means -------------------------------------------------------------------------------------


def mean(values: Sequence[float]) -> float:
    values = [float(v) for v in values]
    return sum(values) / len(values)


def variance(values: Sequence[float]) -> float:
    """Sample variance, denominator n-1, two-pass (deviations from the mean)."""
    values = [float(v) for v in values]
    centre = mean(values)
    return sum((v - centre) ** 2 for v in values) / (len(values) - 1)


def stdev(values: Sequence[float]) -> float:
    return math.sqrt(variance(values))


# --- t tests -----------------------------------------------------------------------------------


def one_sample_t(values: Sequence[float], mu0: float = 0.0) -> tuple[float, int, float]:
    """t = (xbar - mu0) / (s / sqrt(n)); Student (1908). Returns (t, df, two-sided p)."""
    n = len(values)
    t = (mean(values) - mu0) / (stdev(values) / math.sqrt(n))
    df = n - 1
    return t, df, 2 * float(st.t.sf(abs(t), df))


def one_sample_z(values: Sequence[float], mu0: float, sigma: float) -> tuple[float, float]:
    """z = (xbar - mu0) / (sigma / sqrt(n)) with sigma KNOWN, so no df and a normal tail."""
    z = (mean(values) - mu0) / (sigma / math.sqrt(len(values)))
    return z, 2 * float(st.norm.sf(abs(z)))


def paired_t(a: Sequence[float], b: Sequence[float], mu0: float = 0.0) -> tuple[float, int, float]:
    """A one-sample t on the differences — which is all a paired t-test is."""
    differences = [float(x) - float(y) for x, y in zip(a, b)]
    assert len(differences) == len(a) == len(b)
    return one_sample_t(differences, mu0)


def pooled_t(a: Sequence[float], b: Sequence[float], d0: float = 0.0) -> tuple[float, int, float]:
    """Two-sample t assuming equal variances, pooling with weights n-1."""
    n1, n2 = len(a), len(b)
    s_pooled_sq = ((n1 - 1) * variance(a) + (n2 - 1) * variance(b)) / (n1 + n2 - 2)
    se = math.sqrt(s_pooled_sq * (1 / n1 + 1 / n2))
    t = (mean(a) - mean(b) - d0) / se
    df = n1 + n2 - 2
    return t, df, 2 * float(st.t.sf(abs(t), df))


def welch_t(a: Sequence[float], b: Sequence[float], d0: float = 0.0) -> tuple[float, float, float]:
    """Welch (1947), "The generalisation of Student's problem...", Biometrika 34, 28-35.

    The degrees of freedom are the Welch-Satterthwaite quantity
        (v1 + v2)^2 / (v1^2/(n1-1) + v2^2/(n2-1))     where vi = si^2 / ni
    which is the part everyone gets wrong, and the part a sign flip hides in.
    """
    n1, n2 = len(a), len(b)
    v1, v2 = variance(a) / n1, variance(b) / n2
    se = math.sqrt(v1 + v2)
    t = (mean(a) - mean(b) - d0) / se
    df = (v1 + v2) ** 2 / (v1**2 / (n1 - 1) + v2**2 / (n2 - 1))
    return t, df, 2 * float(st.t.sf(abs(t), df))


# --- variances ---------------------------------------------------------------------------------


def variance_ratio_f(a: Sequence[float], b: Sequence[float]) -> tuple[float, int, int, float]:
    """F = s1^2 / s2^2 on (n1-1, n2-1) df, two-sided p as twice the smaller tail."""
    f = variance(a) / variance(b)
    df1, df2 = len(a) - 1, len(b) - 1
    p = 2 * min(float(st.f.cdf(f, df1, df2)), float(st.f.sf(f, df1, df2)))
    return f, df1, df2, min(p, 1.0)


def bartlett(groups: Sequence[Sequence[float]]) -> tuple[float, int, float]:
    """Bartlett (1937), Proc. R. Soc. A 160, 268-282, including the 1/C correction factor."""
    k = len(groups)
    sizes = [len(g) for g in groups]
    dfs = [n - 1 for n in sizes]
    total_df = sum(dfs)
    pooled = sum(d * variance(g) for d, g in zip(dfs, groups)) / total_df
    numerator = total_df * math.log(pooled) - sum(d * math.log(variance(g)) for d, g in zip(dfs, groups))
    correction = 1 + (sum(1 / d for d in dfs) - 1 / total_df) / (3 * (k - 1))
    statistic = numerator / correction
    return statistic, k - 1, float(st.chi2.sf(statistic, k - 1))


def levene_median(groups: Sequence[Sequence[float]]) -> tuple[float, int, int, float]:
    """Brown & Forsythe (1974), JASA 69, 364-367 — Levene's test centred on the MEDIAN.

    Minitab's "Levene" is this median-centred form, not Levene's original mean-centred one; they
    give visibly different answers on skewed data, which is why the centring is named here.
    """
    deviations = [[abs(float(v) - float(np.median(g))) for v in g] for g in groups]
    return one_way_f(deviations)


# --- ANOVA -------------------------------------------------------------------------------------


def one_way_f(groups: Sequence[Sequence[float]]) -> tuple[float, int, int, float]:
    """One-way ANOVA from the definition: between/within sums of squared deviations."""
    k = len(groups)
    n_total = sum(len(g) for g in groups)
    grand = sum(sum(float(v) for v in g) for g in groups) / n_total
    ss_between = sum(len(g) * (mean(g) - grand) ** 2 for g in groups)
    ss_within = sum(sum((float(v) - mean(g)) ** 2 for v in g) for g in groups)
    df_between, df_within = k - 1, n_total - k
    f = (ss_between / df_between) / (ss_within / df_within)
    return f, df_between, df_within, float(st.f.sf(f, df_between, df_within))


def welch_anova(groups: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """Welch (1951), Biometrika 38, 330-336 — the one-way ANOVA that does not pool variances."""
    weights = [len(g) / variance(g) for g in groups]
    total_weight = sum(weights)
    grand = sum(w * mean(g) for w, g in zip(weights, groups)) / total_weight
    k = len(groups)
    numerator = sum(w * (mean(g) - grand) ** 2 for w, g in zip(weights, groups)) / (k - 1)
    tail = sum((1 - w / total_weight) ** 2 / (len(g) - 1) for w, g in zip(weights, groups))
    denominator = 1 + (2 * (k - 2) / (k**2 - 1)) * tail
    f = numerator / denominator
    df2 = (k**2 - 1) / (3 * tail)
    return f, float(k - 1), df2, float(st.f.sf(f, k - 1, df2))


# --- correlation and regression -------------------------------------------------------------------


def pearson_r(x: Sequence[float], y: Sequence[float]) -> tuple[float, int, float]:
    """r = Sxy / sqrt(Sxx Syy), with the t test on n-2 df."""
    x = [float(v) for v in x]
    y = [float(v) for v in y]
    mx, my = mean(x), mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    r = sxy / math.sqrt(sxx * syy)
    df = len(x) - 2
    t = r * math.sqrt(df / (1 - r**2))
    return r, df, 2 * float(st.t.sf(abs(t), df))


def simple_regression(x: Sequence[float], y: Sequence[float]) -> dict[str, float]:
    """Slope, intercept, their standard errors, R² and the ANOVA split — all from the definitions."""
    x = [float(v) for v in x]
    y = [float(v) for v in y]
    n = len(x)
    mx, my = mean(x), mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    slope = sxy / sxx
    intercept = my - slope * mx
    fitted = [intercept + slope * a for a in x]
    ss_residual = sum((b - f) ** 2 for b, f in zip(y, fitted))
    ss_total = sum((b - my) ** 2 for b in y)
    ss_regression = ss_total - ss_residual
    s_squared = ss_residual / (n - 2)
    return {
        "slope": slope,
        "intercept": intercept,
        "se_slope": math.sqrt(s_squared / sxx),
        "se_intercept": math.sqrt(s_squared * (1 / n + mx**2 / sxx)),
        "s": math.sqrt(s_squared),
        "r_squared": ss_regression / ss_total,
        "ss_regression": ss_regression,
        "ss_residual": ss_residual,
        "ss_total": ss_total,
        "f": (ss_regression / 1) / s_squared,
        "t_slope": slope / math.sqrt(s_squared / sxx),
    }


def vif(columns: Sequence[Sequence[float]]) -> list[float]:
    """VIF_j = 1 / (1 - R²_j) from regressing column j on the others, with an intercept."""
    matrix = np.asarray([[float(v) for v in column] for column in columns], dtype=float).T
    out = []
    for j in range(matrix.shape[1]):
        target = matrix[:, j]
        others = np.delete(matrix, j, axis=1)
        design = np.column_stack([np.ones(len(target)), others])
        beta, *_ = np.linalg.lstsq(design, target, rcond=None)
        residual = target - design @ beta
        r_squared = 1 - float(residual @ residual) / float(((target - target.mean()) ** 2).sum())
        out.append(1 / (1 - r_squared))
    return out


# --- generalised linear models ---------------------------------------------------------------------


def _irls(design: np.ndarray, y: np.ndarray, *, link: str, iterations: int = 100) -> np.ndarray:
    """Iteratively Reweighted Least Squares, the definition GLMs are fitted by.

    McCullagh & Nelder (1989), Generalized Linear Models, 2nd ed., section 2.5. One loop covers both
    families we need: the working response and weight differ, nothing else does.
    """
    beta = np.zeros(design.shape[1])
    for _ in range(iterations):
        eta = design @ beta
        if link == "logit":
            mu = 1 / (1 + np.exp(-eta))
            weight = mu * (1 - mu)
        elif link == "log":
            mu = np.exp(eta)
            weight = mu
        else:  # pragma: no cover - guarded by the callers below
            raise ValueError(link)
        weight = np.clip(weight, 1e-12, None)
        working = eta + (y - mu) / weight
        weighted = design * weight[:, None]
        step = np.linalg.solve(design.T @ weighted, design.T @ (weight * working))
        if np.allclose(step, beta, rtol=1e-13, atol=1e-13):
            return step
        beta = step
    return beta


def logistic_coefficients(predictors: Sequence[Sequence[float]], outcome: Sequence[int]) -> np.ndarray:
    """Binary logistic regression coefficients, intercept first, by longhand IRLS."""
    design = np.column_stack([np.ones(len(outcome))] + [np.asarray(c, dtype=float) for c in predictors])
    return _irls(design, np.asarray(outcome, dtype=float), link="logit")


def logistic_log_likelihood(predictors: Sequence[Sequence[float]], outcome: Sequence[int], beta: np.ndarray) -> float:
    design = np.column_stack([np.ones(len(outcome))] + [np.asarray(c, dtype=float) for c in predictors])
    eta = design @ np.asarray(beta, dtype=float)
    y = np.asarray(outcome, dtype=float)
    return float(np.sum(y * eta - np.log1p(np.exp(eta))))


def poisson_coefficients(predictors: Sequence[Sequence[float]], counts: Sequence[int]) -> np.ndarray:
    """Log-link Poisson regression coefficients, intercept first, by longhand IRLS."""
    design = np.column_stack([np.ones(len(counts))] + [np.asarray(c, dtype=float) for c in predictors])
    return _irls(design, np.asarray(counts, dtype=float), link="log")


# --- categorical ------------------------------------------------------------------------------------


def chi_square_independence(table: Sequence[Sequence[int]]) -> tuple[float, int, float]:
    """Pearson's chi-square on a contingency table: sum (O-E)^2/E with E from the margins."""
    rows = [[int(v) for v in row] for row in table]
    total = sum(sum(row) for row in rows)
    row_totals = [sum(row) for row in rows]
    col_totals = [sum(row[j] for row in rows) for j in range(len(rows[0]))]
    statistic = 0.0
    for i, row in enumerate(rows):
        for j, observed in enumerate(row):
            expected = row_totals[i] * col_totals[j] / total
            statistic += (observed - expected) ** 2 / expected
    df = (len(rows) - 1) * (len(rows[0]) - 1)
    return statistic, df, float(st.chi2.sf(statistic, df))


def chi_square_goodness_of_fit(observed: Sequence[int], expected: Sequence[float]) -> tuple[float, int, float]:
    statistic = sum((o - e) ** 2 / e for o, e in zip(observed, expected))
    df = len(observed) - 1
    return statistic, df, float(st.chi2.sf(statistic, df))


def odds_ratio(a: int, b: int, c: int, d: int) -> float:
    """(a/b) / (c/d) for a 2x2 laid out [[a, b], [c, d]]."""
    return (a * d) / (b * c)


# --- proportions -------------------------------------------------------------------------------------


def clopper_pearson(events: int, trials: int, alpha: float = 0.05) -> tuple[float, float]:
    """Clopper & Pearson (1934) exact interval, as the pair of Beta quantiles they define."""
    low = 0.0 if events == 0 else float(st.beta.ppf(alpha / 2, events, trials - events + 1))
    high = 1.0 if events == trials else float(st.beta.ppf(1 - alpha / 2, events + 1, trials - events))
    return low, high


def exact_binomial_p(events: int, trials: int, p0: float) -> float:
    """Two-sided exact binomial p-value: the total probability of outcomes no more likely than the
    one observed. Computed as an EXACT rational sum when p0 is a simple fraction, so the reference
    value owes nothing to floating point."""
    p = Fraction(p0).limit_denominator(10**6)
    q = 1 - p
    pmf = [math.comb(trials, k) * p**k * q ** (trials - k) for k in range(trials + 1)]
    observed = pmf[events]
    # The standard two-sided rule, with a relative slack for ties that a Fraction makes exact.
    total = sum(value for value in pmf if value <= observed)
    return float(total)


def wald_interval(events: int, trials: int, alpha: float = 0.05) -> tuple[float, float]:
    """The normal-approximation interval: phat +/- z * sqrt(phat (1-phat) / n)."""
    phat = events / trials
    z = float(st.norm.isf(alpha / 2))
    half = z * math.sqrt(phat * (1 - phat) / trials)
    return phat - half, phat + half


# --- outliers -------------------------------------------------------------------------------------


def grubbs(values: Sequence[float]) -> tuple[float, float, int]:
    """Grubbs (1969), Technometrics 11(1), 1-21. G = max|x - xbar| / s, and the two-sided p-value
    from the exact t relationship. Returns (G, p, index of the extreme value)."""
    values = [float(v) for v in values]
    n = len(values)
    centre, spread = mean(values), stdev(values)
    deviations = [abs(v - centre) for v in values]
    index = max(range(n), key=lambda i: deviations[i])
    g = deviations[index] / spread
    # p = n * P(|t| > t_crit) with t_crit derived from G, Bonferroni-corrected over the n candidates
    numerator = n * (n - 2) * g**2
    denominator = (n - 1) ** 2 - n * g**2
    if denominator <= 0:
        return g, 0.0, index
    t = math.sqrt(numerator / denominator)
    p = min(1.0, n * 2 * float(st.t.sf(t, n - 2)))
    return g, p, index


def dixon_q(values: Sequence[float]) -> float:
    """Dixon (1953), Biometrics 9, 74-89 — the r10 ("Q") ratio for the more extreme end, 3 <= n <= 7
    in its strict form but universally quoted as gap/range."""
    ordered = sorted(float(v) for v in values)
    span = ordered[-1] - ordered[0]
    low_gap = ordered[1] - ordered[0]
    high_gap = ordered[-1] - ordered[-2]
    return max(low_gap, high_gap) / span
