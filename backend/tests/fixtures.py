"""Worksheets the coverage sweep runs procedures against.

All of them are either a committed reference file under `reference_data/published/` or one of the
repository's own sample CSVs, so the sweep never depends on a random draw and never needs a network.
Loaded lazily and cached, because the sweep touches every procedure and would otherwise re-read the
same 150-row frame a hundred times.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from backend.tests.refdata import frame

REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=None)
def iris() -> pd.DataFrame:
    return frame("iris_fisher")


@lru_cache(maxsize=None)
def sleep() -> pd.DataFrame:
    return frame("sleep_cushny_peebles")


@lru_cache(maxsize=None)
def spector() -> pd.DataFrame:
    return frame("spector_grades")


@lru_cache(maxsize=None)
def cpunish() -> pd.DataFrame:
    return frame("cpunish_executions")


@lru_cache(maxsize=None)
def anscombe() -> pd.DataFrame:
    return frame("anscombe_quartet")


@lru_cache(maxsize=None)
def horse_kicks() -> pd.DataFrame:
    return frame("horse_kicks_bortkiewicz")


@lru_cache(maxsize=None)
def nile() -> pd.DataFrame:
    data = frame("nile_flow")
    return pd.DataFrame(
        {"date": pd.to_datetime(data["year"].astype(int).astype(str) + "-01-01"), "volume": data["volume"]}
    )


@lru_cache(maxsize=None)
def factorial() -> pd.DataFrame:
    """The repository's balanced 3x4x2 design with two covariates and two responses."""
    return pd.read_csv(REPO_ROOT / "sample_factorial.csv")


@lru_cache(maxsize=None)
def nested() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "sample_nested.csv")


@lru_cache(maxsize=None)
def grid() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "sample_grid.csv")


@lru_cache(maxsize=None)
def stability() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "sample_stability.csv")


@lru_cache(maxsize=None)
def timeseries() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "sample_timeseries.csv")


@lru_cache(maxsize=None)
def customers() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "sample_customers.csv")


@lru_cache(maxsize=None)
def sales() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "sample_data.csv")


@lru_cache(maxsize=None)
def blank() -> pd.DataFrame:
    """For the procedures that take summarised input or matrices and read no column at all."""
    return pd.DataFrame({"unused": [0.0]})


@lru_cache(maxsize=None)
def counts() -> pd.DataFrame:
    """Small integer counts with an obvious group split, for the count-based procedures."""
    return pd.DataFrame(
        {
            "defects": [3, 5, 2, 7, 4, 6, 1, 8, 5, 3, 4, 2],
            "line": ["A"] * 6 + ["B"] * 6,
            "exposure": [10.0] * 12,
        }
    )


@lru_cache(maxsize=None)
def ordinal() -> pd.DataFrame:
    """An ordered response with two predictors, for the ordinal and nominal logistic dialogs."""
    rng = np.random.default_rng(4)
    n = 120
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    latent = 1.2 * x1 - 0.8 * x2 + rng.normal(0, 1, n)
    grades = pd.cut(latent, bins=[-np.inf, -0.6, 0.6, np.inf], labels=["low", "medium", "high"])
    return pd.DataFrame({"x1": x1, "x2": x2, "grade": grades.astype(str)})
