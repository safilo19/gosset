"""run_segmentation logic (RFM / K-means, auto-selection). Plain Python — no MCP or web-framework code."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# shared result types
# ---------------------------------------------------------------------------


@dataclass
class SegmentRow:
    row_index: int
    segment: str


@dataclass
class SegmentGroup:
    segment: str
    size: int
    mean_values: dict[str, float]
    profile: str


@dataclass
class SegmentationResult:
    rows: list[SegmentRow]
    groups: list[SegmentGroup]
    n_rows_used: int
    n_rows_excluded: int


# ---------------------------------------------------------------------------
# auto method detection
# ---------------------------------------------------------------------------

_RECENCY_KEYWORDS = ("recency", "last_purchase", "last purchase", "last_order", "last order", "last_visit", "date")
_FREQUENCY_KEYWORDS = ("frequency", "freq", "order_count", "orders", "count", "visits", "purchases", "transactions")
_MONETARY_KEYWORDS = ("monetary", "spend", "spent", "amount", "revenue", "value", "price", "sales", "total")


def _matches(name: str, keywords: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(kw in lowered for kw in keywords)


def _looks_like_dates(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return False
    parsed = pd.to_datetime(series, errors="coerce")
    non_null = series.notna().sum()
    return non_null > 0 and parsed.notna().sum() / non_null > 0.9


def detect_rfm_roles(df: pd.DataFrame, columns: list[str]) -> dict[str, str] | None:
    """Best-effort match of the 3 given columns to recency/frequency/monetary roles.

    Returns {"recency": col, "frequency": col, "monetary": col} if exactly one column
    confidently matches each role, else None (caller should fall back to kmeans).
    """
    if len(columns) != 3:
        return None

    recency_candidates = [c for c in columns if _matches(c, _RECENCY_KEYWORDS) and _looks_like_dates(df[c])]
    frequency_candidates = [
        c for c in columns if _matches(c, _FREQUENCY_KEYWORDS) and pd.api.types.is_numeric_dtype(df[c])
    ]
    monetary_candidates = [
        c for c in columns if _matches(c, _MONETARY_KEYWORDS) and pd.api.types.is_numeric_dtype(df[c])
    ]

    # A column can only fill one role; require a unique, non-overlapping assignment.
    if len(recency_candidates) != 1 or len(frequency_candidates) != 1 or len(monetary_candidates) != 1:
        return None
    roles = {"recency": recency_candidates[0], "frequency": frequency_candidates[0], "monetary": monetary_candidates[0]}
    if len({roles["recency"], roles["frequency"], roles["monetary"]}) != 3:
        return None
    return roles


# ---------------------------------------------------------------------------
# RFM segmentation
# ---------------------------------------------------------------------------

_RFM_PROFILES = {
    "Champions": "Recent, frequent, high-spending customers — your best customers.",
    "Loyal Customers": "Buy regularly and recently, with solid spend — reliable repeat customers.",
    "Potential Loyalists": "High frequency/spend but haven't purchased as recently — worth re-engaging.",
    "New/Promising": "Purchased recently but haven't built up frequency or spend yet.",
    "At Risk": "Used to buy often and spend a lot, but haven't purchased in a while — winnable back.",
    "Needs Attention": "Middling on recency, frequency, and spend — neither strong nor lost.",
    "Lost": "Long time since last purchase, low frequency and spend — likely churned.",
}


def _quartile_score(series: pd.Series, smaller_is_better: bool) -> pd.Series:
    ranks = series.rank(method="first", ascending=not smaller_is_better)
    n_bins = min(4, series.nunique())
    if n_bins < 2:
        return pd.Series(1, index=series.index)
    return pd.qcut(ranks, n_bins, labels=list(range(1, n_bins + 1))).astype(int)


def _rfm_segment_name(r_norm: float, fm_norm: float) -> str:
    r_high, r_low = r_norm >= 0.66, r_norm <= 0.33
    fm_high, fm_low = fm_norm >= 0.66, fm_norm <= 0.33

    if r_high and fm_high:
        return "Champions"
    if r_high and fm_low:
        return "New/Promising"
    if r_high:
        return "Loyal Customers"
    if r_low and fm_high:
        return "At Risk"
    if r_low and fm_low:
        return "Lost"
    if fm_high:
        return "Potential Loyalists"
    return "Needs Attention"


def run_rfm(df: pd.DataFrame, roles: dict[str, str]) -> SegmentationResult:
    recency_col, frequency_col, monetary_col = roles["recency"], roles["frequency"], roles["monetary"]

    sub = df[[recency_col, frequency_col, monetary_col]].copy()
    sub[recency_col] = pd.to_datetime(sub[recency_col], errors="coerce")
    valid_mask = sub.notna().all(axis=1)
    used = sub[valid_mask]
    excluded = int((~valid_mask).sum())

    if len(used) < 4:
        raise ValueError(
            f"Not enough complete rows for RFM segmentation: {len(used)} row(s) have all of "
            f"{recency_col}/{frequency_col}/{monetary_col} present, need at least 4."
        )

    snapshot_date = used[recency_col].max() + pd.Timedelta(days=1)
    recency_days = (snapshot_date - used[recency_col]).dt.days

    r_score = _quartile_score(recency_days, smaller_is_better=True)
    f_score = _quartile_score(used[frequency_col], smaller_is_better=False)
    m_score = _quartile_score(used[monetary_col], smaller_is_better=False)

    r_max = r_score.max()
    fm_score = (f_score + m_score) / 2
    fm_max = fm_score.max()

    r_norm = (r_score - 1) / (r_max - 1) if r_max > 1 else pd.Series(1.0, index=used.index)
    fm_norm = (fm_score - 1) / (fm_max - 1) if fm_max > 1 else pd.Series(1.0, index=used.index)

    segment_labels = pd.Series(
        [_rfm_segment_name(r, fm) for r, fm in zip(r_norm, fm_norm)],
        index=used.index,
    )

    rows = [SegmentRow(row_index=int(idx), segment=label) for idx, label in segment_labels.items()]

    groups = []
    for segment_name in segment_labels.unique():
        members = used[segment_labels == segment_name]
        groups.append(
            SegmentGroup(
                segment=segment_name,
                size=len(members),
                mean_values={
                    "recency_days": float(recency_days[segment_labels == segment_name].mean()),
                    frequency_col: float(members[frequency_col].mean()),
                    monetary_col: float(members[monetary_col].mean()),
                },
                profile=_RFM_PROFILES.get(segment_name, ""),
            )
        )
    groups.sort(key=lambda g: g.size, reverse=True)

    return SegmentationResult(rows=rows, groups=groups, n_rows_used=len(used), n_rows_excluded=excluded)


# ---------------------------------------------------------------------------
# K-means segmentation
# ---------------------------------------------------------------------------


def run_kmeans(df: pd.DataFrame, columns: list[str], n_clusters: int) -> SegmentationResult:
    non_numeric = [c for c in columns if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        raise ValueError(
            f"Column(s) {', '.join(non_numeric)} are not numeric. kmeans requires numeric feature columns "
            f"— encode categorical columns first, or choose different columns."
        )

    sub = df[columns]
    valid_mask = sub.notna().all(axis=1)
    used = sub[valid_mask]
    excluded = int((~valid_mask).sum())

    if len(used) < n_clusters * 2:
        raise ValueError(
            f"Not enough complete rows for {n_clusters} clusters: {len(used)} row(s) with no missing values "
            f"across {columns}, need at least {n_clusters * 2}."
        )

    scaled = StandardScaler().fit_transform(used.to_numpy())
    model = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit(scaled)
    labels = model.labels_

    overall_mean = used.mean()
    overall_std = used.std().replace(0, np.nan)

    rows = [SegmentRow(row_index=int(idx), segment=f"Cluster {label}") for idx, label in zip(used.index, labels)]

    groups = []
    for cluster_id in sorted(set(labels)):
        members = used[labels == cluster_id]
        mean_values = members.mean()

        tags = []
        for col in columns:
            std = overall_std[col]
            z = 0.0 if pd.isna(std) else (mean_values[col] - overall_mean[col]) / std
            if z > 0.5:
                tags.append(f"above-average {col}")
            elif z < -0.5:
                tags.append(f"below-average {col}")
            else:
                tags.append(f"typical {col}")
        profile = ", ".join(tags) + "."

        groups.append(
            SegmentGroup(
                segment=f"Cluster {cluster_id}",
                size=int(len(members)),
                mean_values={col: float(mean_values[col]) for col in columns},
                profile=profile,
            )
        )
    groups.sort(key=lambda g: g.size, reverse=True)

    return SegmentationResult(rows=rows, groups=groups, n_rows_used=len(used), n_rows_excluded=excluded)


# ---------------------------------------------------------------------------
# auto/rfm/kmeans orchestration
# ---------------------------------------------------------------------------


@dataclass
class SegmentationOutcome:
    method_used: str
    method_reason: str
    n_rows_used: int
    n_rows_excluded: int
    segments: list[SegmentGroup]
    row_assignments: list[SegmentRow]
    summary: str = field(default="")


def run_segmentation(
    df: pd.DataFrame, columns: list[str], method: str, n_clusters: int, dataset_id: str
) -> SegmentationOutcome:
    if method in ("auto", "rfm"):
        roles = detect_rfm_roles(df, columns)
        if roles:
            if method == "auto":
                reason = (
                    f"Detected RFM-style columns: '{roles['recency']}' looks like a recency date, "
                    f"'{roles['frequency']}' looks like a frequency count, and '{roles['monetary']}' looks like "
                    f"a monetary amount, so running RFM segmentation."
                )
            else:
                reason = (
                    f"Running RFM segmentation using recency='{roles['recency']}', "
                    f"frequency='{roles['frequency']}', monetary='{roles['monetary']}'."
                )
            result = run_rfm(df, roles)
            method_used = "rfm"
        elif method == "rfm":
            raise ValueError(
                f"rfm requires exactly 3 columns matching recency (date-like), frequency (count-like), and "
                f"monetary (spend-like) roles; couldn't confidently match {columns} to those roles. "
                f"Try column names like 'last_purchase_date', 'order_count', 'total_spent', or use method='kmeans'."
            )
        else:
            reason = (
                f"Could not confidently detect recency/frequency/monetary columns among {columns}; "
                f"defaulting to kmeans (n_clusters={n_clusters})."
            )
            result = run_kmeans(df, columns, n_clusters)
            method_used = "kmeans"
    else:
        reason = f"Using the requested method (kmeans, n_clusters={n_clusters})."
        result = run_kmeans(df, columns, n_clusters)
        method_used = "kmeans"

    lines = [
        f"Segmented dataset '{dataset_id}' using {method_used} "
        f"({result.n_rows_used} rows used, {result.n_rows_excluded} excluded for missing values).",
        reason,
    ]
    lines += [f"- {g.segment} (n={g.size}): {g.profile}" for g in result.groups]

    return SegmentationOutcome(
        method_used=method_used,
        method_reason=reason,
        n_rows_used=result.n_rows_used,
        n_rows_excluded=result.n_rows_excluded,
        segments=result.groups,
        row_assignments=result.rows,
        summary="\n".join(lines),
    )
