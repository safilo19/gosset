"""Derive a badge's three structured fields from an analysis result.

The engine renders `{verdict_label, verdict_polarity, key_stat}` and nothing else. An analysis that
already supplies them wins; for everything that does not, they are computed HERE, from the numbers on
the result — never by reading its prose.

Why that matters: the conclusions are written for humans and get reworded. A regex over "significant"
would flip a badge from red to green the day someone writes "not statistically significant" with a
line break in the middle of it. Numbers do not have that problem.

Polarity is about ATTENTION, not about good news: `positive` (green) means "this test found
something", `negative` (red) means "the model or the assumption is in trouble", `neutral` means
"nothing to flag". A significant normality test is a red badge, because it says the assumption failed.
"""

from __future__ import annotations

import re
from typing import Any

# Keys an analysis may already carry. Checked first, so an analysis can always override.
EXPLICIT_KEYS = ("verdict_label", "verdict_polarity", "key_stat")

# Results whose significant p-value means "the assumption you needed has failed", so green/red flip.
# Matched against a NORMALISED id (see _normalise), which is why they are written with underscores:
# both the internal id `equal_variances` and the menu label "Test for Equal Variances" reduce to a
# string containing `equal_variances`, so a caller can pass whichever it has.
_INVERTED = {
    "normality",
    "poisson_goodness",
    "poisson_gof",
    "equal_variances",
    "outlier",
    "goodness_of_fit",
    "autocorrelation",
}


def _normalise(text: str) -> str:
    """Lowercase, non-alphanumerics collapsed to single underscores.

    Lets one token list serve both the internal analysis ids and the human menu labels, which is what
    the frontend and the MCP tool respectively tend to have to hand.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _first(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def _format_p(p: float) -> str:
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"


def derive(data: dict[str, Any], analysis_id: str = "", alpha: float = 0.05) -> dict[str, str] | None:
    """The three badge fields, or None when this result has no verdict worth a badge.

    A card without a badge is normal and fine — a descriptive-statistics table is not a finding.
    """
    if not isinstance(data, dict):
        return None

    explicit = {key: data[key] for key in EXPLICIT_KEYS if data.get(key)}
    if explicit.get("verdict_label"):
        return {
            "verdict_label": str(explicit["verdict_label"]),
            "verdict_polarity": str(explicit.get("verdict_polarity") or "neutral"),
            "key_stat": str(explicit.get("key_stat") or ""),
        }

    p = _num(_first(data, "p_value", "p", "pvalue", "anderson_darling_p", "a2_p_value"))
    if p is not None:
        significant = p < alpha
        subject = _normalise(analysis_id)
        inverted = any(token in subject for token in _INVERTED)
        if inverted:
            label = "Assumption not met" if significant else "Assumption holds"
            polarity = "negative" if significant else "positive"
        else:
            label = "Significant" if significant else "Not significant"
            polarity = "positive" if significant else "neutral"
        return {"verdict_label": label, "verdict_polarity": polarity, "key_stat": _format_p(p)}

    # A model with no p-value still has a headline: how much it explains.
    r2 = _num(_first(data, "r_squared", "r2", "adj_r_squared"))
    if r2 is not None:
        if r2 >= 0.7:
            label, polarity = "Strong fit", "positive"
        elif r2 >= 0.3:
            label, polarity = "Moderate fit", "neutral"
        else:
            label, polarity = "Weak fit", "negative"
        return {"verdict_label": label, "verdict_polarity": polarity, "key_stat": f"R² = {r2:.3f}"}

    accuracy = _num(_first(data, "accuracy", "metric_value", "best_score"))
    if accuracy is not None:
        return {
            "verdict_label": "Model scored",
            "verdict_polarity": "neutral",
            "key_stat": f"{_first(data, 'metric_label') or 'score'} = {accuracy:.3f}",
        }

    segments = _first(data, "segments")
    if isinstance(segments, list) and segments:
        return {"verdict_label": "Segments found", "verdict_polarity": "positive", "key_stat": f"k = {len(segments)}"}

    return None


def line(fields: dict[str, str] | None) -> str:
    """The badge as plain text, for the Markdown and Excel exports — same words, no colour."""
    if not fields:
        return ""
    dot = {"positive": "●", "negative": "●", "neutral": "○"}.get(fields.get("verdict_polarity", ""), "○")
    parts = [dot, fields.get("verdict_label", "")]
    if fields.get("key_stat"):
        parts.append(f"— {fields['key_stat']}")
    return " ".join(p for p in parts if p)
