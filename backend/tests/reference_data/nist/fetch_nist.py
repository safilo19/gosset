"""Re-download the NIST StRD reference datasets that live beside this script.

The committed `.dat` files are byte-exact copies of what NIST publishes — deliberately NOT
annotated with a provenance header, so anyone can diff a committed file against the live NIST
URL and confirm no certified value was edited on the way in. Provenance therefore lives in
`manifest.json` (URL, retrieval date, what is certified, SHA-256) and is enforced by
`backend/tests/nist/test_nist_manifest.py`, which re-hashes every file on every run.

Run from the repo root:

    python backend/tests/reference_data/nist/fetch_nist.py            # verify only
    python backend/tests/reference_data/nist/fetch_nist.py --write    # re-download + rewrite manifest

Re-downloading is not part of the test suite: the tests read the committed copies, so the suite
stays offline and deterministic.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"

# NIST serves 403 to the default urllib agent.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; gosset-validation-suite/1.0)"}

UNIVARIATE_BASE = "https://www.itl.nist.gov/div898/strd/univ/data/"
LLS_BASE = "https://www.itl.nist.gov/div898/strd/lls/data/LINKS/DATA/"
ANOVA_BASE = "https://www.itl.nist.gov/div898/strd/anova/"

# (subdirectory, filename stem, base url, what the file certifies)
DATASETS: list[tuple[str, str, str, str]] = []

_UNIVARIATE_CERTIFIES = "sample mean, sample standard deviation, lag-1 autocorrelation"
for _name in (
    "PiDigits",
    "Lottery",
    "Lew",
    "Mavro",
    "Michelso",
    "NumAcc1",
    "NumAcc2",
    "NumAcc3",
    "NumAcc4",
):
    DATASETS.append(("univariate", _name, UNIVARIATE_BASE, _UNIVARIATE_CERTIFIES))

_LLS_CERTIFIES = (
    "regression coefficients and their standard deviations, residual standard deviation, "
    "R-squared, and the ANOVA table (df, SS, MS, F)"
)
for _name in (
    "Norris",
    "Pontius",
    "NoInt1",
    "NoInt2",
    "Filip",
    "Longley",
    "Wampler1",
    "Wampler2",
    "Wampler3",
    "Wampler4",
    "Wampler5",
):
    DATASETS.append(("lls", _name, LLS_BASE, _LLS_CERTIFIES))

_ANOVA_CERTIFIES = (
    "between/within degrees of freedom, sums of squares, mean squares, the F statistic, "
    "R-squared, and the residual standard deviation"
)
for _name in (
    "SiRstv",
    "SmLs01",
    "SmLs02",
    "SmLs03",
    "SmLs04",
    "SmLs05",
    "SmLs06",
    "SmLs07",
    "SmLs08",
    "SmLs09",
    "AtmWtAg",
):
    DATASETS.append(("anova", _name, ANOVA_BASE, _ANOVA_CERTIFIES))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https host
        return response.read()


def write() -> int:
    today = _dt.date.today().isoformat()
    entries = []
    for subdir, stem, base, certifies in DATASETS:
        url = f"{base}{stem}.dat"
        target = HERE / subdir / f"{stem}.dat"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _download(url)
        # The three StRD collections open differently: lls/anova lead with "NIST/ITL StRD",
        # the univariate files with "File Name:". Both name the file on line 1 or 2.
        if b"Certified Values" not in payload[:2000] or stem.encode() not in payload[:400]:
            print(f"  !! {stem}: response does not look like a StRD file", file=sys.stderr)
            return 1
        # Normalise CRLF so the committed copy is stable across platforms and git autocrlf
        # settings; the numbers, which are all that is certified, are untouched.
        target.write_bytes(payload.replace(b"\r\n", b"\n"))
        entries.append(
            {
                "name": stem,
                "path": f"{subdir}/{stem}.dat",
                "url": url,
                "retrieved": today,
                "certifies": certifies,
                "sha256": _sha256(target),
            }
        )
        print(f"  ok {subdir}/{stem}.dat")

    MANIFEST.write_text(
        json.dumps(
            {
                "source": "NIST/ITL Statistical Reference Datasets (StRD)",
                "citation": (
                    "National Institute of Standards and Technology, Information Technology "
                    "Laboratory. Statistical Reference Datasets. "
                    "https://www.itl.nist.gov/div898/strd/ (accessed " + today + ")."
                ),
                "note": (
                    "Files are byte-exact copies of the NIST originals apart from CRLF->LF line "
                    "endings, so each can be diffed against its URL. Provenance is here rather "
                    "than in a header comment inside the data files for exactly that reason."
                ),
                "datasets": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST}")
    return 0


def verify() -> int:
    if not MANIFEST.exists():
        print("no manifest.json - run with --write", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = 0
    for entry in manifest["datasets"]:
        path = HERE / entry["path"]
        if not path.exists():
            print(f"  MISSING {entry['path']}", file=sys.stderr)
            bad += 1
        elif _sha256(path) != entry["sha256"]:
            print(f"  CHANGED {entry['path']}", file=sys.stderr)
            bad += 1
    print(f"{len(manifest['datasets']) - bad}/{len(manifest['datasets'])} files verified")
    return 1 if bad else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="re-download and rewrite the manifest")
    args = parser.parse_args()
    raise SystemExit(write() if args.write else verify())
