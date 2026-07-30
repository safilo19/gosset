"""The Calculator's expression engine.

Nothing here ever calls eval() or exec(). An expression is parsed with `ast.parse` and then walked
by `_Evaluator`, which handles exactly one node type per method and raises on everything else. A
name that is not a column, a constant or a whitelisted function is an error; an attribute access, a
subscript, a lambda, a comprehension, an import — none of those have a visit method, so they land
in the generic reject. That is the whole security model: a whitelist by construction rather than a
blacklist of things to strip out.

Quoting follows Minitab: 'single quotes' name a COLUMN (which is how a column called `yield (kg)`
is referred to at all), "double quotes" are a text literal. Python's parser throws both away, so
the original source segment is consulted to tell them apart.

Everything is vectorised. A column is a numpy array of length n; a constant or a literal is a
scalar; an aggregate like MEAN() collapses to a scalar. Mixing them works because numpy broadcasts,
so `('yield' - MEAN('yield')) / STDEV('yield')` needs no special handling.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy import stats as st

from backend.core.procedures import ProcedureError

MAX_EXPRESSION_LENGTH = 4000
MAX_NODES = 2000


class ExpressionError(ProcedureError):
    """A problem with the formula itself. `position` is a 0-based offset into the expression, so
    the dialog can put the caret where the trouble is."""

    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


@dataclass
class Context:
    """Everything an expression is allowed to see."""

    columns: dict[str, np.ndarray] = field(default_factory=dict)
    text_columns: dict[str, np.ndarray] = field(default_factory=dict)
    constants: dict[str, Any] = field(default_factory=dict)
    n_rows: int = 0


# ---------------------------------------------------------------------------
# coercion helpers — every function states what it wants and gets it
# ---------------------------------------------------------------------------


def _numeric(value: Any, what: str) -> Any:
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "OUS":
            return pd.to_numeric(pd.Series(value), errors="coerce").to_numpy(dtype=float)
        return value.astype(float)
    if isinstance(value, (bool, np.bool_)):
        return float(value)
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ExpressionError(f"{what} needs a number, but got the text '{value}'.") from None


def _text(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return np.array(["" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v) for v in value], dtype=object)
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _boolean(value: Any, what: str = "A condition") -> Any:
    if isinstance(value, np.ndarray):
        if value.dtype == bool:
            return value
        return _numeric(value, what) != 0
    return bool(value)


def _finite_only(values: np.ndarray) -> np.ndarray:
    """The values an aggregate should see: no NaN, no infinities."""
    numbers = np.asarray(_numeric(values, "This statistic"), dtype=float)
    return numbers[np.isfinite(numbers)]


def _same_length(context: Context, *values: Any) -> int:
    for value in values:
        if isinstance(value, np.ndarray):
            return len(value)
    return context.n_rows or 1


# ---------------------------------------------------------------------------
# the function library
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Function:
    name: str
    category: str
    signature: str
    summary: str
    min_args: int
    max_args: int  # -1 for "any number"
    call: Callable[..., Any]
    aggregate: bool = False


FUNCTIONS: dict[str, Function] = {}


def _register(name: str, category: str, signature: str, summary: str, min_args: int, max_args: int, call, aggregate: bool = False) -> None:
    FUNCTIONS[name] = Function(name, category, signature, summary, min_args, max_args, call, aggregate)


def _elementwise(fn):
    """Wrap a numpy ufunc so it accepts a column or a scalar and never raises on bad input —
    division by zero, the log of a negative number and so on become missing values, which is what
    Minitab's `*` means and what the caller counts afterwards."""

    def run(value):
        with np.errstate(all="ignore"):
            return fn(_numeric(value, "This function"))

    return run


# --- math -------------------------------------------------------------------
_register("ABS", "Math", "ABS(number)", "Absolute value.", 1, 1, _elementwise(np.abs))
_register("SQRT", "Math", "SQRT(number)", "Square root; a negative input gives a missing value.", 1, 1, _elementwise(np.sqrt))
_register("EXP", "Math", "EXP(number)", "e raised to the power of the value.", 1, 1, _elementwise(np.exp))
_register("LN", "Math", "LN(number)", "Natural logarithm.", 1, 1, _elementwise(np.log))
_register("LOG10", "Math", "LOG10(number)", "Base-10 logarithm.", 1, 1, _elementwise(np.log10))
_register("SIGN", "Math", "SIGN(number)", "-1, 0 or 1 according to the sign.", 1, 1, _elementwise(np.sign))
_register("CEIL", "Math", "CEIL(number)", "Round up to a whole number.", 1, 1, _elementwise(np.ceil))
_register("FLOOR", "Math", "FLOOR(number)", "Round down to a whole number.", 1, 1, _elementwise(np.floor))


def _round(value, digits=0):
    with np.errstate(all="ignore"):
        places = int(_numeric(digits, "ROUND's number of digits") if not isinstance(digits, np.ndarray) else digits[0])
        return np.round(_numeric(value, "ROUND"), places)


def _mod(value, divisor):
    with np.errstate(all="ignore"):
        left, right = _numeric(value, "MOD"), _numeric(divisor, "MOD")
        out = np.mod(left, right)
        # numpy leaves x % 0 as nan with a warning; make that explicit and missing.
        return np.where(np.asarray(right) == 0, np.nan, out)


_register("ROUND", "Math", "ROUND(number, digits)", "Round to the given number of decimal places.", 1, 2, _round)
_register("MOD", "Math", "MOD(number, divisor)", "Remainder after division; a zero divisor gives a missing value.", 2, 2, _mod)

# --- statistics (aggregates: they collapse a column to one number) -----------
_register("MEAN", "Statistics", "MEAN(column)", "Arithmetic mean of the non-missing values.", 1, 1, lambda v: float(np.mean(_finite_only(v))) if _finite_only(v).size else float("nan"), aggregate=True)
_register("MEDIAN", "Statistics", "MEDIAN(column)", "Median of the non-missing values.", 1, 1, lambda v: float(np.median(_finite_only(v))) if _finite_only(v).size else float("nan"), aggregate=True)
_register("STDEV", "Statistics", "STDEV(column)", "Sample standard deviation (n − 1).", 1, 1, lambda v: float(np.std(_finite_only(v), ddof=1)) if _finite_only(v).size > 1 else float("nan"), aggregate=True)
_register("VARIANCE", "Statistics", "VARIANCE(column)", "Sample variance (n − 1).", 1, 1, lambda v: float(np.var(_finite_only(v), ddof=1)) if _finite_only(v).size > 1 else float("nan"), aggregate=True)
_register("SUM", "Statistics", "SUM(column)", "Total of the non-missing values.", 1, 1, lambda v: float(np.sum(_finite_only(v))), aggregate=True)
_register("MIN", "Statistics", "MIN(column)", "Smallest non-missing value.", 1, 1, lambda v: float(np.min(_finite_only(v))) if _finite_only(v).size else float("nan"), aggregate=True)
_register("MAX", "Statistics", "MAX(column)", "Largest non-missing value.", 1, 1, lambda v: float(np.max(_finite_only(v))) if _finite_only(v).size else float("nan"), aggregate=True)
_register("RANGE", "Statistics", "RANGE(column)", "Largest minus smallest.", 1, 1, lambda v: (float(np.max(_finite_only(v)) - np.min(_finite_only(v))) if _finite_only(v).size else float("nan")), aggregate=True)
_register("N", "Statistics", "N(column)", "How many values are present.", 1, 1, lambda v: float(_finite_only(v).size), aggregate=True)
_register("COUNT", "Statistics", "COUNT(column)", "How many rows there are, missing values included.", 1, 1, lambda v: float(len(v)) if isinstance(v, np.ndarray) else 1.0, aggregate=True)
_register("NMISS", "Statistics", "NMISS(column)", "How many values are missing.", 1, 1, lambda v: float((len(v) if isinstance(v, np.ndarray) else 1) - _finite_only(v).size), aggregate=True)


def _percentile(values, q):
    clean = _finite_only(values)
    share = float(_numeric(q, "PERCENTILE's percentage") if not isinstance(q, np.ndarray) else q[0])
    if not 0 <= share <= 100:
        raise ExpressionError(f"PERCENTILE's second argument is a percentage between 0 and 100; got {share:g}.")
    return float(np.percentile(clean, share)) if clean.size else float("nan")


_register("PERCENTILE", "Statistics", "PERCENTILE(column, percent)", "The value below which that percentage of the data falls.", 2, 2, _percentile, aggregate=True)
_register("SSQ", "Statistics", "SSQ(column)", "Sum of squares.", 1, 1, lambda v: float(np.sum(_finite_only(v) ** 2)), aggregate=True)

# --- text -------------------------------------------------------------------
_register("LEN", "Text", "LEN(text)", "Number of characters.", 1, 1, lambda v: np.array([len(s) for s in np.atleast_1d(_text(v))], dtype=float) if isinstance(v, np.ndarray) else float(len(_text(v))))
_register("UPPER", "Text", "UPPER(text)", "Convert to upper case.", 1, 1, lambda v: np.array([s.upper() for s in _text(v)], dtype=object) if isinstance(v, np.ndarray) else _text(v).upper())
_register("LOWER", "Text", "LOWER(text)", "Convert to lower case.", 1, 1, lambda v: np.array([s.lower() for s in _text(v)], dtype=object) if isinstance(v, np.ndarray) else _text(v).lower())
_register("TRIM", "Text", "TRIM(text)", "Remove leading and trailing spaces.", 1, 1, lambda v: np.array([s.strip() for s in _text(v)], dtype=object) if isinstance(v, np.ndarray) else _text(v).strip())


def _scalar_int(value, what: str) -> int:
    raw = value[0] if isinstance(value, np.ndarray) and value.size else value
    number = _numeric(raw, what)
    if isinstance(number, np.ndarray):
        number = float(number.flat[0])
    if not np.isfinite(number):
        raise ExpressionError(f"{what} must be a whole number.")
    return int(number)


def _left(value, count):
    n = _scalar_int(count, "LEFT's character count")
    return np.array([s[:n] for s in _text(value)], dtype=object) if isinstance(value, np.ndarray) else _text(value)[:n]


def _right(value, count):
    n = _scalar_int(count, "RIGHT's character count")
    return np.array([s[-n:] if n else "" for s in _text(value)], dtype=object) if isinstance(value, np.ndarray) else (_text(value)[-n:] if n else "")


def _mid(value, start, count):
    begin = _scalar_int(start, "MID's start position") - 1  # 1-based, like a spreadsheet
    n = _scalar_int(count, "MID's character count")
    if begin < 0:
        raise ExpressionError("MID's start position begins at 1.")
    return np.array([s[begin : begin + n] for s in _text(value)], dtype=object) if isinstance(value, np.ndarray) else _text(value)[begin : begin + n]


def _concat(*values):
    length = max((len(v) for v in values if isinstance(v, np.ndarray)), default=0)
    if not length:
        return "".join(_text(v) for v in values)
    parts = [(_text(v) if isinstance(v, np.ndarray) else np.array([_text(v)] * length, dtype=object)) for v in values]
    return np.array(["".join(str(p[i]) for p in parts) for i in range(length)], dtype=object)


_register("LEFT", "Text", "LEFT(text, n)", "The first n characters.", 2, 2, _left)
_register("RIGHT", "Text", "RIGHT(text, n)", "The last n characters.", 2, 2, _right)
_register("MID", "Text", "MID(text, start, n)", "n characters starting at position `start` (1 is the first).", 3, 3, _mid)
_register("CONCAT", "Text", "CONCAT(a, b, …)", "Join text values end to end.", 1, -1, _concat)

# --- logical ----------------------------------------------------------------


def _if(condition, when_true, when_false=None):
    test = _boolean(condition, "IF's first argument")
    if not isinstance(test, np.ndarray):
        return when_true if test else when_false
    length = len(test)
    left = when_true if isinstance(when_true, np.ndarray) else np.array([when_true] * length, dtype=object)
    right = when_false if isinstance(when_false, np.ndarray) else np.array([when_false] * length, dtype=object)
    # object dtype so a numeric branch and a text branch can coexist; the caller narrows it later.
    return np.array([left[i] if test[i] else right[i] for i in range(length)], dtype=object)


def _and(*values):
    out = _boolean(values[0])
    for value in values[1:]:
        out = np.logical_and(out, _boolean(value))
    return out


def _or(*values):
    out = _boolean(values[0])
    for value in values[1:]:
        out = np.logical_or(out, _boolean(value))
    return out


_register("IF", "Logical", "IF(condition, then, else)", "Pick between two values, row by row.", 2, 3, _if)
_register("AND", "Logical", "AND(a, b, …)", "True where every condition holds.", 1, -1, _and)
_register("OR", "Logical", "OR(a, b, …)", "True where any condition holds.", 1, -1, _or)
_register("NOT", "Logical", "NOT(condition)", "Reverses a condition.", 1, 1, lambda v: np.logical_not(_boolean(v)))
_register("ISMISSING", "Logical", "ISMISSING(column)", "True where the value is missing.", 1, 1, lambda v: pd.isna(np.asarray(_numeric(v, "ISMISSING"), dtype=float)) if isinstance(v, np.ndarray) else bool(pd.isna(v)))

# --- date/time --------------------------------------------------------------


def _dates(value):
    series = pd.to_datetime(pd.Series(np.atleast_1d(value)), errors="coerce")
    return series


def _date_part(part):
    def run(value):
        parts = getattr(_dates(value).dt, part)
        out = pd.to_numeric(parts, errors="coerce").to_numpy(dtype=float)
        return out if isinstance(value, np.ndarray) else float(out[0])

    return run


_register("YEAR", "Date/Time", "YEAR(date)", "The year as a number.", 1, 1, _date_part("year"))
_register("MONTH", "Date/Time", "MONTH(date)", "The month as 1–12.", 1, 1, _date_part("month"))
_register("DAY", "Date/Time", "DAY(date)", "The day of the month.", 1, 1, _date_part("day"))
_register("HOUR", "Date/Time", "HOUR(date)", "The hour, 0–23.", 1, 1, _date_part("hour"))
_register("WEEKDAY", "Date/Time", "WEEKDAY(date)", "Day of the week, 1 = Monday.", 1, 1, lambda v: _date_part("dayofweek")(v) + 1)
_register("TODAY", "Date/Time", "TODAY()", "Today's date, as text.", 0, 0, lambda: pd.Timestamp.today().strftime("%Y-%m-%d"))
_register("NOW", "Date/Time", "NOW()", "The current date and time, as text.", 0, 0, lambda: pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))

# --- misc -------------------------------------------------------------------


def _lag(value, periods=1):
    if not isinstance(value, np.ndarray):
        return value
    step = _scalar_int(periods, "LAG's number of rows") if periods is not None else 1
    return pd.Series(value).shift(step).to_numpy()


def _lead(value, periods=1):
    return _lag(value, -_scalar_int(periods, "LEAD's number of rows") if periods is not None else -1)


def _rank(value):
    numbers = pd.Series(_numeric(value, "RANK"))
    return numbers.rank(method="average").to_numpy(dtype=float)


def _sort(value):
    """Sorted values in place of the originals — row i holds the i-th smallest, missing last."""
    if not isinstance(value, np.ndarray):
        return value
    series = pd.Series(_numeric(value, "SORT"))
    return series.sort_values(na_position="last").to_numpy(dtype=float)


def _parsum(value):
    return pd.Series(_numeric(value, "PARSUM")).cumsum().to_numpy(dtype=float)


_register("LAG", "Misc", "LAG(column, n)", "The value n rows earlier; the first n rows become missing.", 1, 2, _lag)
_register("LEAD", "Misc", "LEAD(column, n)", "The value n rows later.", 1, 2, _lead)
_register("RANK", "Misc", "RANK(column)", "Rank of each value; ties share the average rank.", 1, 1, _rank)
_register("SORT", "Misc", "SORT(column)", "The column's values in ascending order.", 1, 1, _sort)
_register("PARSUM", "Misc", "PARSUM(column)", "Running (cumulative) total.", 1, 1, _parsum)
_register("NORMSCORE", "Misc", "NORMSCORE(column)", "Normal score of each value (its expected z under normality).", 1, 1, lambda v: st.norm.ppf((pd.Series(_numeric(v, "NORMSCORE")).rank(method="average") - 0.375) / (len(np.atleast_1d(v)) + 0.25)))

CATEGORY_ORDER = ("Math", "Statistics", "Text", "Logical", "Date/Time", "Misc")


def function_catalogue() -> list[dict[str, Any]]:
    """What the dialog's function browser lists, grouped the way it displays them."""
    out = []
    for category in CATEGORY_ORDER:
        items = [
            {"name": f.name, "signature": f.signature, "summary": f.summary, "aggregate": f.aggregate}
            for f in FUNCTIONS.values()
            if f.category == category
        ]
        out.append({"category": category, "functions": sorted(items, key=lambda i: i["name"])})
    return out


# ---------------------------------------------------------------------------
# the evaluator
# ---------------------------------------------------------------------------

_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
    ast.Mod: _mod,
    ast.FloorDiv: lambda a, b: a // b,
    ast.BitAnd: lambda a, b: np.logical_and(_boolean(a), _boolean(b)),
    ast.BitOr: lambda a, b: np.logical_or(_boolean(a), _boolean(b)),
}

_COMPARE = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


class _Evaluator:
    def __init__(self, source: str, context: Context, mapping: list[int] | None = None):
        # `source` is the REWRITTEN text — quote characters are untouched by normalise(), so
        # reading a node's source segment from it still tells 'column' from "text" correctly.
        self.source = source
        self.mapping = mapping or []
        self.context = context
        self.used_columns: set[str] = set()
        self.used_constants: set[str] = set()

    # -- helpers ------------------------------------------------------------
    def _at(self, node: ast.AST) -> int | None:
        position = getattr(node, "col_offset", None)
        if position is None or not self.mapping:
            return position
        return self.mapping[min(max(position, 0), len(self.mapping) - 1)]

    def _fail(self, node: ast.AST, message: str):
        raise ExpressionError(message, self._at(node))

    def _segment(self, node: ast.AST) -> str:
        try:
            return ast.get_source_segment(self.source, node) or ""
        except Exception:  # noqa: BLE001
            return ""

    def _column(self, name: str, node: ast.AST):
        if name in self.context.columns:
            self.used_columns.add(name)
            return self.context.columns[name]
        if name in self.context.text_columns:
            self.used_columns.add(name)
            return self.context.text_columns[name]
        return None

    # -- dispatch -----------------------------------------------------------
    def visit(self, node: ast.AST):
        method = getattr(self, f"_v_{type(node).__name__}", None)
        if method is None:
            self._fail(node, f"{type(node).__name__} is not allowed in a formula. Use columns, constants, numbers, operators and the functions in the browser.")
        return method(node)

    def _v_Expression(self, node):
        return self.visit(node.body)

    def _v_Constant(self, node):
        value = node.value
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 'single quotes' name a column; "double quotes" are literal text. The parser discards
            # the quote style, so the original source has to be consulted.
            segment = self._segment(node).strip()
            quoted_as_column = segment.startswith("'")
            column = self._column(value, node)
            if quoted_as_column:
                if column is None:
                    known = ", ".join(sorted(self.context.columns) + sorted(self.context.text_columns)) or "(none)"
                    self._fail(node, f"There is no column called '{value}' in this worksheet. Columns: {known}")
                return column
            return value
        if value is None:
            return float("nan")
        self._fail(node, f"{value!r} is not a value a formula can use.")

    def _v_Name(self, node):
        name = node.id
        upper = name.upper()
        column = self._column(name, node)
        if column is not None:
            return column
        if upper in self.context.constants:
            self.used_constants.add(upper)
            return self.context.constants[upper]
        if upper in FUNCTIONS:
            self._fail(node, f"{upper} is a function — it needs brackets, as in {FUNCTIONS[upper].signature}.")
        if upper in ("TRUE", "FALSE"):
            return upper == "TRUE"
        known = ", ".join(sorted(self.context.columns) + sorted(self.context.text_columns)) or "(none)"
        self._fail(
            node,
            f"'{name}' is not a column, a constant or a function. Columns: {known}. "
            "A column name with spaces goes in single quotes.",
        )

    def _v_BinOp(self, node):
        op = _BINARY.get(type(node.op))
        if op is None:
            self._fail(node, f"The {type(node.op).__name__} operator is not allowed in a formula.")
        left, right = self.visit(node.left), self.visit(node.right)
        if type(node.op) in (ast.BitAnd, ast.BitOr):
            return op(left, right)
        with np.errstate(all="ignore"):
            return op(_numeric(left, "This operator"), _numeric(right, "This operator"))

    def _v_UnaryOp(self, node):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -_numeric(operand, "Negation")
        if isinstance(node.op, ast.UAdd):
            return _numeric(operand, "This operator")
        if isinstance(node.op, (ast.Not, ast.Invert)):
            return np.logical_not(_boolean(operand))
        self._fail(node, f"The {type(node.op).__name__} operator is not allowed in a formula.")

    def _v_BoolOp(self, node):
        # `and` / `or` short-circuit in Python and cannot be applied to a whole column, so they are
        # evaluated as element-wise logic instead — which is what a formula means by them.
        values = [self.visit(v) for v in node.values]
        combine = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
        out = _boolean(values[0])
        for value in values[1:]:
            out = combine(out, _boolean(value))
        return out

    def _v_Compare(self, node):
        if len(node.ops) != 1:
            self._fail(node, "Chained comparisons like a < b < c are not supported; write AND(a < b, b < c).")
        op = _COMPARE.get(type(node.ops[0]))
        if op is None:
            self._fail(node, f"The {type(node.ops[0]).__name__} comparison is not allowed in a formula.")
        left, right = self.visit(node.left), self.visit(node.comparators[0])
        # Text compares as text; anything else compares as a number.
        text_side = isinstance(left, str) or isinstance(right, str) or (isinstance(left, np.ndarray) and left.dtype.kind in "OUS") or (isinstance(right, np.ndarray) and right.dtype.kind in "OUS")
        with np.errstate(all="ignore"):
            if text_side and type(node.ops[0]) in (ast.Eq, ast.NotEq):
                return op(_text(left), _text(right))
            return op(_numeric(left, "This comparison"), _numeric(right, "This comparison"))

    def _v_Call(self, node):
        if not isinstance(node.func, ast.Name):
            self._fail(node, "Only the functions in the browser can be called.")
        name = node.func.id.upper()
        function = FUNCTIONS.get(name)
        if function is None:
            self._fail(node.func, f"There is no function called {node.func.id}. Open the function browser to see what is available.")
        if node.keywords:
            self._fail(node, f"{name} takes its arguments in order, not by name.")
        args = [self.visit(a) for a in node.args]
        if len(args) < function.min_args or (function.max_args >= 0 and len(args) > function.max_args):
            expected = f"{function.min_args}" if function.min_args == function.max_args else (f"at least {function.min_args}" if function.max_args < 0 else f"{function.min_args} to {function.max_args}")
            self._fail(node, f"{name} takes {expected} argument(s); {len(args)} given. Signature: {function.signature}")
        try:
            return function.call(*args)
        except ExpressionError:
            raise
        except ProcedureError as err:
            raise ExpressionError(str(err), self._at(node)) from err
        except Exception as err:  # noqa: BLE001 - a library failure becomes a message about the formula
            raise ExpressionError(f"{name} could not be computed: {err}", self._at(node)) from err

    def _v_IfExp(self, node):
        return _if(self.visit(node.test), self.visit(node.body), self.visit(node.orelse))


_WORD_OPERATORS = {"AND": "and", "OR": "or", "NOT": "not"}
_WORD_RE = re.compile(r"\b(AND|OR|NOT)\b(\s*)(\()?", re.IGNORECASE)


def normalise(source: str) -> tuple[str, list[int]]:
    """Rewrite Minitab's spellings into ones Python's parser accepts.

    `A AND B` is how a formula is written; Python needs `A and B` (`AND(a, b)`, the function form,
    is left alone). `=` means equality; Python needs `==`. `<>` means "not equal".

    Returns the rewritten text AND a map from each of its offsets back to the original, because
    `=` → `==` shifts everything after it. Without that map every caret position the dialog shows
    would drift one character right for each `=` earlier in the formula.
    """
    out: list[str] = []
    mapping: list[int] = []
    quote: str | None = None
    i = 0
    while i < len(source):
        ch = source[i]
        if quote:
            out.append(ch)
            mapping.append(i)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            mapping.append(i)
            i += 1
            continue
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if ch == "<" and nxt == ">":
            out.extend("!=")
            mapping.extend([i, i + 1])
            i += 2
            continue
        if ch in "!<>=" and nxt == "=":  # already a two-character comparison
            out.extend([ch, nxt])
            mapping.extend([i, i + 1])
            i += 2
            continue
        if ch == "=":  # a lone '=' is Minitab's equality test
            out.extend("==")
            mapping.extend([i, i])
            i += 1
            continue
        out.append(ch)
        mapping.append(i)
        i += 1

    text = "".join(out)
    result = list(text)
    for match in _WORD_RE.finditer(text):
        if match.group(3):
            continue  # the function-call form, AND(...)
        start = match.start()
        # Inside a string literal? Count unescaped quotes before this point.
        prefix = text[:start]
        if (prefix.count("'") - prefix.count("\\'")) % 2 or (prefix.count('"') - prefix.count('\\"')) % 2:
            continue
        for offset, character in enumerate(_WORD_OPERATORS[match.group(1).upper()]):
            result[start + offset] = character
    return "".join(result), mapping


def _guard(source: str) -> tuple[ast.Expression, str, list[int]]:
    if not source or not source.strip():
        raise ExpressionError("Enter a formula.", 0)
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"The formula is too long ({len(source)} characters; the limit is {MAX_EXPRESSION_LENGTH}).", 0)
    text, mapping = normalise(source)

    def back(position: int) -> int:
        """A position in the rewritten text, mapped to the character the user actually typed."""
        if not mapping:
            return 0
        return mapping[min(max(position, 0), len(mapping) - 1)]

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as err:
        # SyntaxError's offset is 1-based and can point one past the end.
        raise ExpressionError(f"The formula could not be read: {err.msg}.", back((err.offset or 1) - 1)) from None
    count = sum(1 for _ in ast.walk(tree))
    if count > MAX_NODES:
        raise ExpressionError(f"The formula is too complex ({count} parts; the limit is {MAX_NODES}).", 0)
    return tree, text, mapping


@dataclass
class Result:
    value: Any
    is_scalar: bool
    used_columns: list[str]
    used_constants: list[str]
    kind: str  # 'numeric' | 'text' | 'logical'


def evaluate(source: str, context: Context) -> Result:
    """Parse and run one expression. Raises ExpressionError with a caret position on any problem."""
    tree, text, mapping = _guard(source)
    evaluator = _Evaluator(text, context, mapping)
    value = evaluator.visit(tree)

    is_scalar = not isinstance(value, np.ndarray)
    if isinstance(value, np.ndarray) and value.dtype == bool:
        kind = "logical"
    elif isinstance(value, np.ndarray) and value.dtype.kind in "OUS":
        # An object array from IF() may still be entirely numeric — narrow it if so.
        numbers = pd.to_numeric(pd.Series(value), errors="coerce")
        original_filled = pd.Series(value).notna().sum()
        kind = "numeric" if numbers.notna().sum() == original_filled and original_filled > 0 else "text"
        if kind == "numeric":
            value = numbers.to_numpy(dtype=float)
    elif isinstance(value, np.ndarray):
        kind = "numeric"
    elif isinstance(value, (bool, np.bool_)):
        kind = "logical"
    elif isinstance(value, str):
        kind = "text"
    else:
        kind = "numeric"

    return Result(value, is_scalar, sorted(evaluator.used_columns), sorted(evaluator.used_constants), kind)


def check(source: str, context: Context) -> dict[str, Any]:
    """Validate without computing anything expensive — the live check under the formula box.

    It runs the real evaluator against one-row stand-ins for the columns, so a wrong function name,
    a wrong argument count and an unknown column are all caught by exactly the code that would
    catch them at run time, rather than by a second half-parser that could disagree with it.
    """
    probe = Context(
        columns={name: values[:1] if len(values) else np.zeros(1) for name, values in context.columns.items()},
        text_columns={name: values[:1] if len(values) else np.array([""], dtype=object) for name, values in context.text_columns.items()},
        constants=dict(context.constants),
        n_rows=1,
    )
    try:
        result = evaluate(source, probe)
    except ExpressionError as err:
        return {"ok": False, "error": str(err), "position": err.position}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err), "position": None}
    return {"ok": True, "error": None, "position": None, "kind": result.kind, "scalar": result.is_scalar, "columns": result.used_columns, "constants": result.used_constants}
