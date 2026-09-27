"""Golden snapshots for the procedures that have no reference value to check against.

A bootstrap interval, a randomization p-value, a k-means labelling and an AutoML leaderboard cannot
be validated against a published number, because nobody publishes one. What CAN be pinned is that a
fixed seed and a committed input produce a fixed output, so a refactor that changes the arithmetic
has to be explained rather than merely noticed.

The contract is deliberately blunt: **a failing snapshot means "say what changed, or fix the
regression"**. It is not a reason to regenerate. Regeneration is a separate, explicit act:

    GOSSET_UPDATE_GOLDEN=1 pytest backend/tests/test_golden_stochastic.py

and the resulting diff is what the reviewer reads. The stored files are JSON with every number at
full repr precision, because a snapshot rounded for readability is a snapshot that stops detecting
things.

Comparison is by relative tolerance, not equality: these values come out of BLAS and libm, and a
different machine will differ in the last bits without anything having changed. `SNAPSHOT_RTOL` is
deliberately looser than the suite's estimate tolerance for that reason, and tight enough that a
changed resampling scheme moves a p-value well past it.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

GOLDEN_ROOT = Path(__file__).resolve().parent / "reference_data" / "golden"

# Loose enough to survive a different BLAS, tight enough that a changed algorithm cannot hide.
SNAPSHOT_RTOL = 1e-9
SNAPSHOT_ATOL = 1e-12


def updating() -> bool:
    return os.environ.get("GOSSET_UPDATE_GOLDEN", "") not in ("", "0", "false", "False")


def _normalise(value: Any) -> Any:
    """Strip what is not part of the answer: numpy scalars, and NaN/inf which JSON cannot hold."""
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if hasattr(value, "item"):  # numpy scalar
        return _normalise(value.item())
    return str(value)


def _compare(actual: Any, stored: Any, path: str, problems: list[str]) -> None:
    if isinstance(stored, dict):
        if not isinstance(actual, dict):
            problems.append(f"{path}: expected an object, got {type(actual).__name__}")
            return
        for key in sorted(set(stored) | set(actual)):
            if key not in stored:
                problems.append(f"{path}.{key}: new key {actual[key]!r}")
            elif key not in actual:
                problems.append(f"{path}.{key}: key disappeared (was {stored[key]!r})")
            else:
                _compare(actual[key], stored[key], f"{path}.{key}", problems)
        return

    if isinstance(stored, list):
        if not isinstance(actual, list):
            problems.append(f"{path}: expected a list, got {type(actual).__name__}")
            return
        if len(actual) != len(stored):
            problems.append(f"{path}: length {len(actual)}, snapshot has {len(stored)}")
            return
        for index, (a, s) in enumerate(zip(actual, stored)):
            _compare(a, s, f"{path}[{index}]", problems)
        return

    if isinstance(stored, (int, float)) and not isinstance(stored, bool) and isinstance(actual, (int, float)):
        if abs(float(actual) - float(stored)) > SNAPSHOT_RTOL * abs(float(stored)) + SNAPSHOT_ATOL:
            problems.append(f"{path}: {actual!r} != {stored!r} (snapshot)")
        return

    if actual != stored:
        problems.append(f"{path}: {actual!r} != {stored!r} (snapshot)")


def check(name: str, payload: Any, *, description: str) -> None:
    """Compare `payload` with the committed snapshot `name`, or write it when regenerating."""
    path = GOLDEN_ROOT / f"{name}.json"
    normalised = _normalise(payload)

    if updating() or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "_snapshot": name,
                    "_what": description,
                    "_contract": (
                        "A fixed seed and a committed input must give this output. If this file "
                        "needs to change, say why in the commit message - a diff here is a change "
                        "in what the software computes."
                    ),
                    "value": normalised,
                },
                indent=1,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if not updating():
            raise AssertionError(
                f"snapshot {name}.json did not exist and has been created; review and commit it, "
                "then re-run"
            )
        return

    stored = json.loads(path.read_text(encoding="utf-8"))["value"]
    problems: list[str] = []
    _compare(normalised, stored, name, problems)
    if problems:
        raise AssertionError(
            f"{len(problems)} difference(s) from the committed snapshot {path.name} "
            f"({description}).\n  "
            + "\n  ".join(problems[:20])
            + ("\n  ..." if len(problems) > 20 else "")
            + "\n\nEither this is a regression, or the change is intended — in which case regenerate "
            "with GOSSET_UPDATE_GOLDEN=1 and explain the diff in the commit message."
        )
