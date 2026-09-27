"""Provenance for the committed NIST files, enforced rather than asserted in prose.

The `.dat` files are byte-exact copies of what NIST publishes, deliberately WITHOUT a provenance
header pasted on top: leaving them pristine is what lets anyone diff a committed file against its
URL and confirm no certified value was edited on the way in. The provenance the suite is supposed to
carry — exact citation/URL, what is certified, retrieval date — therefore lives in `manifest.json`,
and these tests make it load-bearing:

* every committed file is listed, with its URL, retrieval date and what it certifies;
* every listed file still hashes to the SHA-256 recorded when it was fetched;
* nothing has been added to the directory that the manifest does not describe.

A hash mismatch means someone edited a reference dataset, which is the one change in this repository
that would make every "validated" claim meaningless.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from backend.tests.nist.strd import DATA_ROOT

pytestmark = pytest.mark.nist

MANIFEST_PATH = DATA_ROOT / "manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ENTRIES = MANIFEST["datasets"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_cites_its_source() -> None:
    assert "Statistical Reference Datasets" in MANIFEST["citation"]
    assert "itl.nist.gov" in MANIFEST["citation"]
    assert re.search(r"\d{4}-\d{2}-\d{2}", MANIFEST["citation"]), "the citation must carry an access date"


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["name"] for e in ENTRIES])
def test_every_entry_is_fully_described(entry: dict) -> None:
    assert entry["url"].startswith("https://www.itl.nist.gov/div898/strd/")
    assert entry["url"].endswith(f"{entry['name']}.dat")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["retrieved"]), "retrieval date must be ISO yyyy-mm-dd"
    assert len(entry["certifies"]) > 20, "say what the file certifies, not just that it certifies something"
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["name"] for e in ENTRIES])
def test_file_still_matches_its_recorded_hash(entry: dict) -> None:
    path = DATA_ROOT / entry["path"]
    assert path.exists(), f"{entry['path']} is listed in the manifest but missing from the repository"
    assert _sha256(path) == entry["sha256"], (
        f"{entry['path']} no longer matches the SHA-256 recorded when it was downloaded from "
        f"{entry['url']}. A certified reference dataset must never be edited; re-fetch it with "
        "`python backend/tests/reference_data/nist/fetch_nist.py --write` if NIST itself changed it."
    )


def test_no_undocumented_reference_files() -> None:
    """A `.dat` that nobody can trace is not reference data."""
    listed = {(DATA_ROOT / entry["path"]).resolve() for entry in ENTRIES}
    found = {path.resolve() for path in DATA_ROOT.rglob("*.dat")}
    assert found == listed, f"undocumented files: {sorted(str(p.name) for p in found - listed)}"


def test_all_three_collections_are_present() -> None:
    counts: dict[str, int] = {}
    for entry in ENTRIES:
        counts[entry["path"].split("/")[0]] = counts.get(entry["path"].split("/")[0], 0) + 1
    assert counts == {"univariate": 9, "lls": 11, "anova": 11}
