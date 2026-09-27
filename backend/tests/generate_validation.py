"""Render VALIDATION.md from the coverage registry and the reference-data manifests.

Generated, never hand-edited. The point of generating it is that the honest rows come out whether
anyone wants them to or not: a procedure at tier `none` appears as NOT YET VALIDATED because the
registry says so, and `test_validation_manifest.py` fails if the committed file has drifted from
what this script produces.

    python -m backend.tests.generate_validation           # write VALIDATION.md
    python -m backend.tests.generate_validation --check   # exit 1 if it is out of date
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from backend.tests import coverage
from backend.tests.nist.strd import DATA_ROOT as NIST_ROOT
from backend.tests.refdata import PUBLISHED_ROOT, load

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "VALIDATION.md"

TIER_ORDER = ["nist", "published", "reference", "snapshot", "properties", "none"]

TIER_BLURB = {
    "nist": (
        "Checked against a **NIST StRD certified value** — a dataset published by the National "
        "Institute of Standards and Technology together with results computed in multiple-precision "
        "arithmetic, for exactly this purpose."
    ),
    "published": (
        "Checked against a **number published in a cited source** — a textbook, a journal paper, or "
        "the documented output of the reference implementation that source describes."
    ),
    "reference": (
        "Checked against a **textbook formula coded independently** in "
        "`backend/tests/reference_impl.py` — written out from the definition rather than by calling "
        "the same library function the app calls, which would prove only that the arguments were "
        "spelled right."
    ),
    "snapshot": (
        "**Fixed-seed golden snapshot plus seed-independent properties.** These procedures resample, "
        "cluster or cross-validate, so there is no reference value to aim at. The snapshot detects "
        "change; the properties (a bootstrap interval contains its estimate, a permutation p-value "
        "matches an exactly enumerable case, clusters partition every row) are the correctness part."
    ),
    "properties": (
        "**Properties only.** Exercised by the coverage sweep and checked against the universal "
        "invariants — p-values in [0, 1], standard errors non-negative, R-squared at most 1, "
        "confidence intervals ordered, no NaN or Infinity reaching the payload — but not compared "
        "with a number anyone else computed."
    ),
    "none": "**NOT YET VALIDATED.** No reference value, no snapshot, and not reached by the sweep.",
}

KNOWN_ISSUES = """\
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
"""


def _table(entries: list[coverage.Entry]) -> list[str]:
    lines = ["| Procedure | Where | Reference |", "| --- | --- | --- |"]
    for entry in sorted(entries, key=lambda e: e.menu):
        sources = "<br>".join(entry.sources) if entry.sources else ""
        if entry.note:
            sources = (sources + "<br>" if sources else "") + f"_{entry.note}_"
        lines.append(f"| `{entry.key}` | {entry.menu} | {sources or '—'} |")
    return lines


def render() -> str:
    by_tier: dict[str, list[coverage.Entry]] = defaultdict(list)
    for entry in coverage.REGISTRY:
        by_tier[entry.tier].append(entry)

    nist_manifest = json.loads((NIST_ROOT / "manifest.json").read_text(encoding="utf-8"))
    published = sorted(PUBLISHED_ROOT.glob("*.toml"))
    total = len(coverage.REGISTRY)
    counts = coverage.counts_by_tier()

    out: list[str] = []
    out.append("# Validation")
    out.append("")
    out.append(
        "This file is **generated** from `backend/tests/coverage.py` by "
        "`python -m backend.tests.generate_validation`, and `test_validation_manifest.py` fails if "
        "it drifts. It is generated rather than written so the unflattering rows cannot be quietly "
        "dropped: a procedure with no validation appears below because the registry says it has "
        "none."
    )
    out.append("")
    out.append(
        f"**{total} procedures.** "
        + ", ".join(f"{counts[tier]} {coverage.TIER_LABEL[tier]}" for tier in TIER_ORDER if counts[tier])
        + "."
    )
    out.append("")
    external = counts["nist"] + counts["published"] + counts["reference"]
    out.append(
        f"**Read that carefully.** {external} of {total} procedures ({external / total * 100:.0f}%) are "
        f"checked against a value someone else computed. The other {total - external} are exercised "
        "and checked for internal consistency, and that is not the same thing: *Properties only* "
        "means nobody has confirmed the number is right, just that it is not obviously wrong. "
        "Those rows are a to-do list, not a clean bill of health."
    )
    out.append("")

    out.append("## Summary")
    out.append("")
    out.append("| Tier | Procedures | Share |")
    out.append("| --- | --- | --- |")
    for tier in TIER_ORDER:
        if not counts[tier]:
            continue
        out.append(f"| {coverage.TIER_LABEL[tier]} | {counts[tier]} | {counts[tier] / total * 100:.0f}% |")
    out.append("")

    out.append("## Reference data")
    out.append("")
    out.append(
        f"**NIST StRD** — {len(nist_manifest['datasets'])} certified datasets committed under "
        "`backend/tests/reference_data/nist/`, byte-exact copies of the published files so each can "
        "be diffed against its URL. Provenance (exact URL, retrieval date, what is certified, "
        "SHA-256) is in `manifest.json` and re-checked on every test run."
    )
    out.append("")
    out.append(f"> {nist_manifest['citation']}")
    out.append("")
    out.append(
        f"**Published examples** — {len(published)} reference files under "
        "`backend/tests/reference_data/published/`, each a TOML file whose header comment carries "
        "the exact citation, what it certifies and the retrieval date:"
    )
    out.append("")
    out.append("| File | Source |")
    out.append("| --- | --- |")
    for path in published:
        payload = load(path.stem)
        out.append(f"| `{path.name}` | {payload['meta']['citation']} |")
    out.append("")

    out.append("## Numerical limits")
    out.append("")
    out.append(
        "NIST grades its regression and ANOVA sets by difficulty on purpose, and the hard ones are "
        "where a package's arithmetic runs out. Measured on this build (Python 3.11, numpy 2.4, "
        "statsmodels 0.14, scipy 1.17), worst agreement in significant digits:"
    )
    out.append("")
    out.append("| Set | Difficulty | Digits | Note |")
    out.append("| --- | --- | --- | --- |")
    for name, difficulty, digits, note in [
        ("Norris", "Lower", "13.0", "full double precision"),
        ("Pontius", "Lower", "6.2", "uncentred quadratic in x ~ 1e6; a QR solve of the same matrix reaches 12.2"),
        ("Longley", "Higher", "10.9", "the classic near-collinear case"),
        ("Wampler1-3", "Higher", "9.4-10.2", ""),
        ("Wampler4", "Higher", "8.0", "signal swamped by 1e4 noise by construction"),
        ("Wampler5", "Higher", "6.0", "signal swamped by 1e6 noise by construction"),
        ("Filip", "Higher", "**0**", "not fitted correctly — see Known issues"),
        ("SmLs01-03", "Lower", "14.4-14.8", "one constant leading digit"),
        ("SmLs04-06", "Average", "8.7-9.3", "seven constant leading digits"),
        (
            "SmLs07-09",
            "Higher",
            "2.7-3.3",
            "thirteen constant leading digits. Converting those decimals to float64 costs ~4.0 "
            "digits before any statistic is computed, and the accumulation costs ~1.3 more; the "
            "budget is measured exactly in `test_smls07_precision_budget`",
        ),
        ("AtmWtAg", "Average", "8.5", "between-group sum of squares of 3.6e-9"),
        ("NumAcc4", "Higher", "8.3", "univariate standard deviation of 0.1 on values of ~1e7"),
    ]:
        out.append(f"| {name} | {difficulty} | {digits} | {note} |")
    out.append("")

    out.append(KNOWN_ISSUES)

    out.append("## Coverage by tier")
    out.append("")
    for tier in TIER_ORDER:
        entries = by_tier.get(tier) or []
        if not entries:
            # An empty tier is still stated, so "no NOT YET VALIDATED section" can never be mistaken
            # for "someone removed it".
            out.append(f"### {coverage.TIER_LABEL[tier]} (0)")
            out.append("")
            out.append(TIER_BLURB[tier])
            out.append("")
            out.append(
                "None. Every procedure the app dispatches is at least reached by the coverage sweep "
                "— which is a low bar, and the *Properties only* section above is where the real "
                "gaps are."
            )
            out.append("")
            continue
        out.append(f"### {coverage.TIER_LABEL[tier]} ({len(entries)})")
        out.append("")
        out.append(TIER_BLURB[tier])
        out.append("")
        out.extend(_table(entries))
        out.append("")

    out.append("## Running the suite")
    out.append("")
    out.append("```")
    out.append("pip install -r requirements.txt -r requirements-dev.txt")
    out.append("pytest                                   # the whole suite, offline")
    out.append("pytest -m nist                           # only the NIST-certified checks")
    out.append("pytest -m published                      # only the cited worked examples")
    out.append("GOSSET_UPDATE_GOLDEN=1 pytest -m snapshot # regenerate the golden snapshots")
    out.append("```")
    out.append("")
    out.append(
        "The suite is offline and deterministic: every reference dataset is committed. "
        "`backend/tests/reference_data/nist/fetch_nist.py --write` re-downloads the NIST files and "
        "rewrites their manifest, and is deliberately not part of the test run."
    )
    out.append("")
    out.append(
        "A release cannot ship with a failing statistical test: `.github/workflows/release.yml` "
        "runs this suite before it builds an installer and stops if anything is red."
    )
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if VALIDATION.md is out of date")
    args = parser.parse_args()

    content = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            print("VALIDATION.md is out of date — run `python -m backend.tests.generate_validation`", file=sys.stderr)
            raise SystemExit(1)
        print("VALIDATION.md is up to date")
        raise SystemExit(0)

    TARGET.write_text(content, encoding="utf-8")
    print(f"wrote {TARGET} ({len(content.splitlines())} lines)")
