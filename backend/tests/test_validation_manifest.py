"""VALIDATION.md must match what the registry says — and must keep saying the unflattering parts.

A coverage manifest is only worth reading if it cannot drift. Two failure modes matter and both are
covered here: the file falling behind the registry, and the file quietly losing the rows nobody
enjoys publishing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.tests import coverage
from backend.tests.generate_validation import TARGET, render

pytestmark = pytest.mark.properties

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def validation() -> str:
    assert TARGET.exists(), "VALIDATION.md is missing — run `python -m backend.tests.generate_validation`"
    return TARGET.read_text(encoding="utf-8")


def test_validation_md_is_up_to_date(validation: str) -> None:
    assert validation == render(), (
        "VALIDATION.md has drifted from backend/tests/coverage.py. Regenerate it with "
        "`python -m backend.tests.generate_validation` and commit the result."
    )


def test_every_procedure_appears_in_the_manifest(validation: str) -> None:
    missing = [entry.key for entry in coverage.REGISTRY if f"`{entry.key}`" not in validation]
    assert not missing, f"not listed in VALIDATION.md: {missing}"


def test_unvalidated_procedures_are_named_not_summarised(validation: str) -> None:
    """The honesty clause. Anything at tier `none` must be listed by name under NOT YET VALIDATED."""
    unvalidated = [entry for entry in coverage.REGISTRY if entry.tier == "none"]
    if not unvalidated:
        assert "NOT YET VALIDATED" in validation, "the tier must stay documented even when empty"
        return
    section = validation.split("### NOT YET VALIDATED")[1]
    for entry in unvalidated:
        assert f"`{entry.key}`" in section, f"{entry.key} is unvalidated but not in that section"


def test_the_known_issues_are_all_still_listed(validation: str) -> None:
    """Each is pinned by a strict xfail in the suite; the manifest must describe all four."""
    for fragment in (
        "Filip is not fitted correctly",
        "R-squared reported on two different scales",
        "Saving a project rounds every float",
        "Hypergeometric CDF is blank at a non-integer",
    ):
        assert fragment in validation, f"VALIDATION.md no longer mentions: {fragment}"


def test_the_gaps_are_all_still_listed(validation: str) -> None:
    for fragment in ("NoInt1", "lag-1 autocorrelation", "Mendel"):
        assert fragment in validation, f"VALIDATION.md no longer mentions the gap: {fragment}"


def test_every_cited_source_is_a_real_reference_file(validation: str) -> None:
    """A citation in the manifest must come from a committed file, not from memory."""
    from backend.tests.refdata import PUBLISHED_ROOT, load

    for path in PUBLISHED_ROOT.glob("*.toml"):
        assert path.name in validation, f"{path.name} exists but is not listed"
        assert load(path.stem)["meta"]["citation"] in validation


def test_reference_files_carry_their_provenance_header() -> None:
    """SOURCE, what it certifies and the retrieval date, in the file itself — not in a README."""
    from backend.tests.refdata import PUBLISHED_ROOT

    for path in sorted(PUBLISHED_ROOT.glob("*.toml")):
        header = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#"))
        assert "SOURCE:" in header, f"{path.name} has no SOURCE line"
        assert "CERTIFIES:" in header, f"{path.name} does not say what it certifies"
        assert re.search(r"RETRIEVED: \d{4}-\d{2}-\d{2}", header), f"{path.name} has no retrieval date"
        assert len(header) > 200, f"{path.name}'s header is too thin to be provenance"


# --- the credibility surface -----------------------------------------------------------------------


def test_the_readme_links_to_the_manifest_and_says_what_it_claims() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "VALIDATION.md" in readme, "the README must link to the coverage manifest"
    assert "NIST" in readme, "the README must say what the engine is validated against"
    assert "tests.yml/badge.svg" in readme or "workflow/status" in readme, "the README needs a tests badge"


def test_the_about_window_states_the_validation_claim() -> None:
    """One line in the About dialog, so the claim travels with the app and not only the repository."""
    brand = (REPO_ROOT / "frontend" / "brand" / "brand.js").read_text(encoding="utf-8")
    assert "NIST" in brand, "About should name what the statistical engine is validated against"
    assert "VALIDATION.md" in brand, "About should point at the manifest"


def test_the_test_workflow_runs_the_whole_suite() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "pytest" in workflow
    assert "push" in workflow and "pull_request" in workflow, "the suite must run on both"


def test_the_release_workflow_is_blocked_by_the_suite() -> None:
    """The rule with no exceptions: a release cannot ship with a failing statistical test.

    Asserted structurally — the build job must DEPEND on the test job, so a red suite stops the
    installer rather than merely printing a warning beside it.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    # The suite is reused rather than copied, so the release runs exactly the job the Tests workflow
    # runs and the two cannot drift apart.
    assert "uses: ./.github/workflows/tests.yml" in workflow, (
        "the release workflow must call the Tests workflow rather than a copy of it"
    )
    assert re.search(r"needs:\s*\[?\s*test", workflow), (
        "the build job must be `needs: test`, or a failing suite would not stop the release"
    )
    assert "continue-on-error" not in workflow, "the suite must be able to fail the release"

    # And the called workflow has to actually run the tests.
    called = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "workflow_call" in called, "tests.yml must be callable for the gate above to work"
    assert "pytest" in called
