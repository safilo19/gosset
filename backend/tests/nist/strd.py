"""Readers for the three NIST StRD file layouts.

Each `.dat` file carries its own documentation, its certified values and its data in one plain-text
block, so the parsers here work off content markers ("Certified Values", "Data:") rather than the
line numbers the headers quote. Line numbers would be the obvious thing to use and are a trap: the
univariate files count them from 1 including the header, the LLS files quote ranges that are off by
a line in a couple of sets, and any of it would break if NIST ever reflowed a file.

Certified numbers are written in Fortran-ish exponent form (`0.334910077722432E-01`), sometimes with
a trailing annotation (`10000002 (exact)`), which `_number` handles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA_ROOT = Path(__file__).resolve().parent.parent / "reference_data" / "nist"

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?")


def _number(text: str) -> float:
    """First number in `text`, tolerating Fortran D exponents and '(exact)' annotations."""
    match = _NUMBER.search(text)
    if match is None:
        raise ValueError(f"no number in {text!r}")
    return float(match.group(0).replace("D", "E").replace("d", "e"))


def _numbers(text: str) -> list[float]:
    return [float(m.replace("D", "E").replace("d", "e")) for m in _NUMBER.findall(text)]


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


# --- Univariate Summary Statistics -------------------------------------------------------------


@dataclass(frozen=True)
class UnivariateSet:
    name: str
    values: np.ndarray
    mean: float
    stdev: float
    autocorrelation: float
    exact: bool  # the constructed NumAcc sets certify exact values rather than 15-digit ones

    @property
    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"y": self.values})


@lru_cache(maxsize=None)
def univariate(name: str) -> UnivariateSet:
    lines = _lines(DATA_ROOT / "univariate" / f"{name}.dat")

    mean = stdev = autocorrelation = None
    exact = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Sample Mean"):
            mean = _number(stripped.split(":", 1)[1])
            exact = exact or "(exact)" in stripped
        elif stripped.startswith("Sample Standard Deviation"):
            stdev = _number(stripped.split(":", 1)[1])
        elif stripped.startswith("Sample Autocorrelation"):
            autocorrelation = _number(stripped.split(":", 1)[1])
    if mean is None or stdev is None or autocorrelation is None:
        raise ValueError(f"{name}: could not find all three certified values")

    # Data runs from the "Data: Y" marker (followed by a dashed rule) to the end of the file. The
    # marker has to be that exact line: the header carries a "Data:  Constructed Variable" line too.
    start = next(i for i, line in enumerate(lines) if re.match(r"^Data:\s*Y\s*$", line, flags=re.IGNORECASE))
    values = [
        _number(line)
        for line in lines[start + 1 :]
        if line.strip() and not set(line.strip()) <= {"-"}
    ]
    return UnivariateSet(name, np.asarray(values, dtype=float), mean, stdev, autocorrelation, exact)


UNIVARIATE_SETS = (
    # (name, difficulty) — NIST's own grading, quoted in each file's header.
    ("PiDigits", "Lower"),
    ("Lottery", "Lower"),
    ("Lew", "Lower"),
    ("Mavro", "Lower"),
    ("Michelso", "Lower"),
    ("NumAcc1", "Lower"),
    ("NumAcc2", "Average"),
    ("NumAcc3", "Average"),
    ("NumAcc4", "Higher"),
)


# --- Linear Least Squares ----------------------------------------------------------------------


@dataclass(frozen=True)
class RegressionSet:
    name: str
    y: np.ndarray
    x: np.ndarray  # (n, k) predictors as published, before any polynomial expansion
    n_parameters: int
    has_intercept: bool
    polynomial: bool  # "Polynomial Class" with one x column means x, x^2, ... x^(k-1)
    coefficients: list[float]
    coefficient_sds: list[float]
    residual_sd: float
    r_squared: float
    regression_df: int
    regression_ss: float
    regression_ms: float
    f_statistic: float
    residual_df: int
    residual_ss: float
    residual_ms: float

    @property
    def predictor_names(self) -> list[str]:
        if self.polynomial:
            return [f"x^{p}" if p > 1 else "x" for p in range(1, self.n_parameters)]
        return [f"x{i + 1}" for i in range(self.x.shape[1])]

    @property
    def frame(self) -> pd.DataFrame:
        """The worksheet a user would build: y, then one column per model term.

        For the polynomial sets that means the powers of x that Calc > Calculator would produce —
        Gosset's Fit Regression Model takes columns, not a formula, so the expansion happens here
        exactly as it would in the app.
        """
        data: dict[str, np.ndarray] = {"y": self.y}
        if self.polynomial:
            base = self.x[:, 0]
            for power in range(1, self.n_parameters):
                data["x" if power == 1 else f"x^{power}"] = base**power
        else:
            for index in range(self.x.shape[1]):
                data[f"x{index + 1}"] = self.x[:, index]
        return pd.DataFrame(data)


@lru_cache(maxsize=None)
def regression(name: str) -> RegressionSet:
    lines = _lines(DATA_ROOT / "lls" / f"{name}.dat")
    text = "\n".join(lines)

    # "2 Parameters (B0,B1)", and NoInt1/NoInt2's singular "1 Parameter (B1)".
    n_parameters = int(re.search(r"(\d+)\s+Parameters?\s*\(", text).group(1))
    # NIST calls Pontius "Quadratic Class" and the rest "Polynomial Class"; both mean the same
    # thing here — one published x column that the model raises to successive powers. Longley is
    # labelled Polynomial too but ships six real predictors, hence the column-count guard below.
    polynomial = "Polynomial Class" in text or "Quadratic Class" in text
    # NoInt1/NoInt2 model y = B1*x with no constant term; every other set has B0.
    has_intercept = bool(re.search(r"^\s*B0\s", text, flags=re.MULTILINE))

    coefficients: list[float] = []
    coefficient_sds: list[float] = []
    for line in lines:
        match = re.match(r"\s*B(\d+)\s+(.*)$", line)
        if match:
            pair = _numbers(match.group(2))
            if len(pair) >= 2:
                coefficients.append(pair[0])
                coefficient_sds.append(pair[1])

    # The only "Standard Deviation" line carrying a number is the residual one: the column heading
    # above the coefficient block ("Standard Deviation / of Estimate") has no number on it.
    residual_sd = next(
        _number(line.split("Deviation")[-1])
        for line in lines
        if "Standard Deviation" in line and _NUMBER.search(line.split("Deviation")[-1])
    )
    r_squared = next(_number(line.split("R-Squared")[-1]) for line in lines if "R-Squared" in line)

    regression_row = next(line for line in lines if re.match(r"\s*Regression\s+\d", line))
    residual_row = next(line for line in lines if re.match(r"\s*Residual\s+\d", line))
    reg = _numbers(regression_row)
    res = _numbers(residual_row)
    # Wampler1 and Wampler2 fit their polynomial exactly: residual SS is 0 and NIST prints the F
    # statistic as the word "Infinity" rather than a number.
    f_statistic = reg[3] if len(reg) > 3 else float("inf")

    start = next(i for i, line in enumerate(lines) if re.match(r"^Data:\s+y\s", line))
    rows = [_numbers(line) for line in lines[start + 1 :] if line.strip()]
    matrix = np.asarray([row for row in rows if row], dtype=float)
    return RegressionSet(
        name=name,
        y=matrix[:, 0],
        x=matrix[:, 1:],
        n_parameters=n_parameters,
        has_intercept=has_intercept,
        polynomial=polynomial and matrix.shape[1] == 2,
        coefficients=coefficients,
        coefficient_sds=coefficient_sds,
        residual_sd=residual_sd,
        r_squared=r_squared,
        regression_df=int(reg[0]),
        regression_ss=reg[1],
        regression_ms=reg[2],
        f_statistic=f_statistic,
        residual_df=int(res[0]),
        residual_ss=res[1],
        residual_ms=res[2],
    )


REGRESSION_SETS = (
    ("Norris", "Lower"),
    ("Pontius", "Lower"),
    ("NoInt1", "Average"),
    ("NoInt2", "Average"),
    ("Filip", "Higher"),
    ("Longley", "Higher"),
    ("Wampler1", "Higher"),
    ("Wampler2", "Higher"),
    ("Wampler3", "Higher"),
    ("Wampler4", "Higher"),
    ("Wampler5", "Higher"),
)


# --- Analysis of Variance ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnovaSet:
    name: str
    factor: np.ndarray
    response: np.ndarray
    between_df: int
    between_ss: float
    between_ms: float
    f_statistic: float
    within_df: int
    within_ss: float
    within_ms: float
    r_squared: float
    residual_sd: float

    @property
    def frame(self) -> pd.DataFrame:
        # The factor is a label, not a number: One-Way ANOVA groups by distinct value, and an
        # integer column would still group correctly but reads as a measurement in the UI.
        return pd.DataFrame(
            {"treatment": [f"L{int(v)}" for v in self.factor], "response": self.response}
        )


@lru_cache(maxsize=None)
def anova(name: str) -> AnovaSet:
    lines = _lines(DATA_ROOT / "anova" / f"{name}.dat")

    between = next(line for line in lines if re.match(r"\s*Between\s+\w+\s+\d", line))
    within = next(line for line in lines if re.match(r"\s*Within\s+\w+\s+\d", line))
    b = _numbers(between)
    w = _numbers(within)
    r_squared = next(_number(line.split("R-Squared")[-1]) for line in lines if "Certified R-Squared" in line)
    residual_sd = next(
        _number(line.split("Deviation")[-1]) for line in lines if "Standard Deviation" in line and _NUMBER.search(line.split("Deviation")[-1])
    )

    start = next(i for i, line in enumerate(lines) if re.match(r"^Data:\s+[A-Za-z]", line))
    rows = [_numbers(line) for line in lines[start + 1 :] if line.strip()]
    matrix = np.asarray([row for row in rows if len(row) == 2], dtype=float)
    return AnovaSet(
        name=name,
        factor=matrix[:, 0],
        response=matrix[:, 1],
        between_df=int(b[0]),
        between_ss=b[1],
        between_ms=b[2],
        f_statistic=b[3],
        within_df=int(w[0]),
        within_ss=w[1],
        within_ms=w[2],
        r_squared=r_squared,
        residual_sd=residual_sd,
    )


@lru_cache(maxsize=None)
def anova_exact(name: str) -> tuple[tuple[str, ...], tuple[Fraction, ...]]:
    """The same ANOVA data as EXACT rationals, straight from the decimals in the file.

    Used to separate two different losses that look identical from the outside: what a decimal costs
    when it becomes a float64, and what the arithmetic costs afterwards. Computing the certified sums
    of squares in `Fraction` reproduces NIST exactly, which both validates the parser and fixes the
    ceiling any float64 implementation could reach.
    """
    lines = _lines(DATA_ROOT / "anova" / f"{name}.dat")
    start = next(i for i, line in enumerate(lines) if re.match(r"^Data:\s+[A-Za-z]", line))
    labels: list[str] = []
    values: list[Fraction] = []
    for line in lines[start + 1 :]:
        parts = line.split()
        if len(parts) == 2:
            labels.append(parts[0])
            values.append(Fraction(parts[1]))
    return tuple(labels), tuple(values)


ANOVA_SETS = (
    ("SiRstv", "Lower"),
    ("SmLs01", "Lower"),
    ("SmLs02", "Lower"),
    ("SmLs03", "Lower"),
    ("SmLs04", "Average"),
    ("SmLs05", "Average"),
    ("SmLs06", "Average"),
    ("SmLs07", "Higher"),
    ("SmLs08", "Higher"),
    ("SmLs09", "Higher"),
    ("AtmWtAg", "Average"),
)
