"""Loader for the cited reference files under `reference_data/published/`.

Each file is TOML with a `#` header comment carrying SOURCE, DATA, CERTIFIES and RETRIEVED, then
`[meta]`, `[data]` and `[expected]` tables. TOML is used rather than JSON precisely because it takes
comments: the provenance has to travel WITH the numbers, not in a README that drifts away from them.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

PUBLISHED_ROOT = Path(__file__).resolve().parent / "reference_data" / "published"


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    path = PUBLISHED_ROOT / f"{name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"no reference file {name}.toml in {PUBLISHED_ROOT}")
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    payload["_header"] = "\n".join(
        line[1:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    )
    payload["_path"] = path
    return payload


def frame(name: str, columns: dict[str, str] | None = None) -> pd.DataFrame:
    """The `[data]` table as a worksheet.

    `columns` renames on the way out, so a test can say `frame("sleep_cushny_peebles",
    {"drug1": "Drug 1"})` and exercise the real-world case of a column name with a space in it.
    """
    data = load(name)["data"]
    lengths = {key: len(value) for key, value in data.items() if isinstance(value, list)}
    if not lengths:
        raise ValueError(f"{name} has no list-valued columns in [data]")
    size = max(lengths.values())
    built = {key: value for key, value in data.items() if isinstance(value, list) and len(value) == size}
    out = pd.DataFrame(built)
    return out.rename(columns=columns) if columns else out


def expected(name: str) -> dict[str, Any]:
    return load(name)["expected"]


def citation(name: str) -> str:
    return str(load(name)["meta"]["citation"])


def all_names() -> list[str]:
    return sorted(path.stem for path in PUBLISHED_ROOT.glob("*.toml"))
