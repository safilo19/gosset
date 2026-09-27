"""Calc > Matrices, against the identities that define the operations.

Matrix arithmetic has the pleasant property that almost everything is checkable without a reference
table: A·A⁻¹ is the identity, (Aᵀ)ᵀ is A, det(AB) is det(A)det(B), and an eigenvector satisfies
Av = λv by construction. Where a numeric answer IS needed the matrices are chosen so the answer is
known in closed form — a 2×2 inverse from the adjugate formula, the eigenvalues of a diagonal or
triangular matrix, the eigenvalues of a symmetric matrix whose characteristic polynomial factors.

The results all travel as `store_matrix` payloads, because the matrix store lives in the browser and
not on the server (see the architecture rule): the backend takes operands in the request and hands
back rows for the client to keep.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.core.procedures import ProcedureError
from backend.tests.harness import run_calc
from backend.tests.tolerance import RTOL_ESTIMATE, assert_close, table

pytestmark = pytest.mark.published

BLANK = pd.DataFrame({"unused": [0.0]})

# A 2x2 whose inverse is exact in binary floating point, a symmetric matrix with integer
# eigenvalues, and a general 3x3 with a clean determinant.
SIMPLE = [[4.0, 7.0], [2.0, 6.0]]
SYMMETRIC = [[2.0, 1.0], [1.0, 2.0]]  # eigenvalues 3 and 1, eigenvectors (1,1)/sqrt2 and (1,-1)/sqrt2
GENERAL = [[2.0, 0.0, 1.0], [1.0, 3.0, 2.0], [1.0, 1.0, 4.0]]  # determinant 18, comfortably invertible
DIAGONAL = [[5.0, 0.0, 0.0], [0.0, -2.0, 0.0], [0.0, 0.0, 0.5]]


def matrix_out(result: dict) -> np.ndarray:
    payload = result["store_matrix"]
    return np.asarray(payload["rows"], dtype=float)


def run_matrix(procedure: str, options: dict) -> dict:
    return run_calc(BLANK, procedure, [], options)


# --- inverse ---------------------------------------------------------------------------------------


def test_inverse_times_the_original_is_the_identity() -> None:
    result = run_matrix("matrix_invert", {"matrix": SIMPLE, "store_in": "M2"})
    inverse = matrix_out(result)
    product = np.asarray(SIMPLE) @ inverse
    assert np.allclose(product, np.eye(2), atol=1e-12), product


def test_two_by_two_inverse_matches_the_adjugate_formula() -> None:
    """1/(ad-bc) * [[d, -b], [-c, a]] — the closed form, so this is a real reference value."""
    a, b = SIMPLE[0]
    c, d = SIMPLE[1]
    determinant = a * d - b * c
    expected = np.asarray([[d, -b], [-c, a]]) / determinant

    inverse = matrix_out(run_matrix("matrix_invert", {"matrix": SIMPLE, "store_in": "M2"}))
    assert np.allclose(inverse, expected, rtol=1e-14), f"{inverse} != {expected}"

    checks = table(run_matrix("matrix_invert", {"matrix": SIMPLE, "store_in": "M2"}), "Checks")[0]
    assert_close(checks["Determinant"], determinant, rtol=RTOL_ESTIMATE, what="determinant")
    assert checks["Max |M·M⁻¹ − I|"] < 1e-12


def test_inverse_of_the_inverse_is_the_original() -> None:
    once = matrix_out(run_matrix("matrix_invert", {"matrix": GENERAL, "store_in": "M2"}))
    twice = matrix_out(run_matrix("matrix_invert", {"matrix": once.tolist(), "store_in": "M3"}))
    assert np.allclose(twice, np.asarray(GENERAL), atol=1e-10), twice


def test_a_singular_matrix_is_refused_with_an_explanation() -> None:
    """The second row is twice the first, so there is no inverse — and the message must say why."""
    with pytest.raises(ProcedureError) as caught:
        run_matrix("matrix_invert", {"matrix": [[1.0, 2.0], [2.0, 4.0]], "store_in": "M2"})
    message = str(caught.value)
    assert "singular" in message.lower()
    assert "multiples" in message.lower(), f"the refusal should explain the cause: {message!r}"


def test_a_non_square_matrix_cannot_be_inverted() -> None:
    with pytest.raises(ProcedureError) as caught:
        run_matrix("matrix_invert", {"matrix": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], "store_in": "M2"})
    assert "square" in str(caught.value).lower()


# --- transpose -------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", [SIMPLE, GENERAL, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]])
def test_transposing_twice_returns_the_original(source: list[list[float]]) -> None:
    once = matrix_out(run_matrix("matrix_transpose", {"matrix": source, "store_in": "M2"}))
    twice = matrix_out(run_matrix("matrix_transpose", {"matrix": once.tolist(), "store_in": "M3"}))
    assert np.array_equal(twice, np.asarray(source)), f"{twice} != {source}"
    assert once.shape == (len(source[0]), len(source))


def test_transpose_of_a_product_reverses_the_order() -> None:
    """(AB)ᵀ = BᵀAᵀ — the identity most likely to expose a row/column mix-up."""
    a, b = np.asarray(GENERAL), np.asarray(GENERAL).T @ np.asarray(GENERAL)
    product = matrix_out(
        run_matrix("matrix_arithmetic", {"operation": "multiply", "left": a.tolist(), "right": b.tolist(), "store_in": "M4"})
    )
    left = matrix_out(run_matrix("matrix_transpose", {"matrix": product.tolist(), "store_in": "M5"}))

    bt = matrix_out(run_matrix("matrix_transpose", {"matrix": b.tolist(), "store_in": "M6"}))
    at = matrix_out(run_matrix("matrix_transpose", {"matrix": a.tolist(), "store_in": "M7"}))
    right = matrix_out(
        run_matrix("matrix_arithmetic", {"operation": "multiply", "left": bt.tolist(), "right": at.tolist(), "store_in": "M8"})
    )
    assert np.allclose(left, right, atol=1e-12)


def test_a_symmetric_matrix_is_its_own_transpose() -> None:
    once = matrix_out(run_matrix("matrix_transpose", {"matrix": SYMMETRIC, "store_in": "M2"}))
    assert np.array_equal(once, np.asarray(SYMMETRIC))


# --- eigen analysis ---------------------------------------------------------------------------------


def test_eigenvalues_of_a_diagonal_matrix_are_its_diagonal() -> None:
    """Sorted largest first, as the dialog documents."""
    result = run_matrix("matrix_eigen", {"matrix": DIAGONAL, "store_values_in": "K1", "store_vectors_in": "M2"})
    values = [row["Eigenvalue"] for row in table(result, "Eigenvalues (largest first)")]
    assert values == sorted(values, reverse=True)
    assert np.allclose(sorted(values), sorted([5.0, -2.0, 0.5]), atol=1e-12)


def test_eigenvalues_of_a_known_symmetric_matrix() -> None:
    """[[2,1],[1,2]] has eigenvalues 3 and 1, with eigenvectors along (1,1) and (1,-1)."""
    result = run_matrix("matrix_eigen", {"matrix": SYMMETRIC, "store_values_in": "K1", "store_vectors_in": "M2"})
    values = [row["Eigenvalue"] for row in table(result, "Eigenvalues (largest first)")]
    assert_close(values[0], 3.0, rtol=1e-14, what="largest eigenvalue")
    assert_close(values[1], 1.0, rtol=1e-14, what="smallest eigenvalue")

    vectors = matrix_out(result)
    for index, expected_direction in enumerate(([1, 1], [1, -1])):
        column = vectors[:, index]
        direction = np.asarray(expected_direction, dtype=float)
        cosine = abs(float(column @ direction) / (np.linalg.norm(column) * np.linalg.norm(direction)))
        assert_close(cosine, 1.0, rtol=1e-12, what=f"eigenvector {index} direction")
        assert_close(float(np.linalg.norm(column)), 1.0, rtol=1e-12, what=f"eigenvector {index} is unit length")


@pytest.mark.parametrize("source", [SYMMETRIC, DIAGONAL, GENERAL])
def test_every_eigenpair_satisfies_a_v_equals_lambda_v(source: list[list[float]]) -> None:
    """The definition. Independent of any library, and the strongest check available here."""
    result = run_matrix("matrix_eigen", {"matrix": source, "store_values_in": "K1", "store_vectors_in": "M2"})
    values = [row["Eigenvalue"] for row in table(result, "Eigenvalues (largest first)")]
    vectors = matrix_out(result)
    a = np.asarray(source)

    for index, eigenvalue in enumerate(values):
        v = vectors[:, index]
        assert np.allclose(a @ v, eigenvalue * v, atol=1e-10), (
            f"Av != lambda v for eigenvalue {eigenvalue}: {a @ v} vs {eigenvalue * v}"
        )


@pytest.mark.parametrize("source", [SYMMETRIC, DIAGONAL, GENERAL])
def test_eigenvalues_sum_to_the_trace_and_multiply_to_the_determinant(source: list[list[float]]) -> None:
    """Two identities that hold for any square matrix, and that a sorting bug cannot break but a
    dropped or duplicated eigenvalue can."""
    result = run_matrix("matrix_eigen", {"matrix": source, "store_values_in": "K1"})
    values = [row["Eigenvalue"] for row in table(result, "Eigenvalues (largest first)")]
    a = np.asarray(source)

    assert len(values) == a.shape[0]
    assert_close(sum(values), float(np.trace(a)), rtol=1e-10, what="sum of eigenvalues = trace")
    assert_close(math.prod(values), float(np.linalg.det(a)), rtol=1e-9, what="product of eigenvalues = det")


def test_eigen_analysis_needs_somewhere_to_put_the_answer() -> None:
    with pytest.raises(ProcedureError) as caught:
        run_matrix("matrix_eigen", {"matrix": SYMMETRIC})
    assert "eigenvalues" in str(caught.value).lower()


def test_a_non_symmetric_matrix_with_complex_eigenvalues_is_labelled() -> None:
    """A rotation has no real eigenvalues; storing only the real parts must be said out loud."""
    rotation = [[0.0, -1.0], [1.0, 0.0]]
    result = run_matrix("matrix_eigen", {"matrix": rotation, "store_values_in": "K1"})
    assert result["note"], "complex eigenvalues must be flagged, not silently truncated"
    assert "complex" in result["note"].lower()


# --- arithmetic ---------------------------------------------------------------------------------------


def test_multiplication_is_the_matrix_product() -> None:
    a, b = np.asarray(GENERAL), np.asarray(SYMMETRIC + [[3.0, 4.0]])  # 3x2 on the right
    result = run_matrix(
        "matrix_arithmetic", {"operation": "multiply", "left": a.tolist(), "right": b.tolist(), "store_in": "M4"}
    )
    assert np.allclose(matrix_out(result), a @ b, atol=1e-12)


def test_multiplying_by_the_identity_changes_nothing() -> None:
    identity = np.eye(3).tolist()
    result = run_matrix(
        "matrix_arithmetic", {"operation": "multiply", "left": GENERAL, "right": identity, "store_in": "M4"}
    )
    assert np.allclose(matrix_out(result), np.asarray(GENERAL), atol=1e-14)


def test_determinant_of_a_product_is_the_product_of_determinants() -> None:
    """det(AB) = det(A)det(B). Read out of the inverse dialog's Checks table, so it exercises the
    determinant Gosset actually shows rather than one computed here."""
    a, b = np.asarray(GENERAL), np.asarray(GENERAL).T + np.eye(3)
    product = matrix_out(
        run_matrix("matrix_arithmetic", {"operation": "multiply", "left": a.tolist(), "right": b.tolist(), "store_in": "M4"})
    )

    def determinant(source) -> float:
        checks = table(run_matrix("matrix_invert", {"matrix": np.asarray(source).tolist(), "store_in": "Mx"}), "Checks")
        return float(checks[0]["Determinant"])

    assert_close(determinant(product), determinant(a) * determinant(b), rtol=1e-10, what="det(AB)")


def test_addition_and_subtraction_are_element_by_element() -> None:
    a, b = np.asarray(SIMPLE), np.asarray([[1.0, 1.0], [1.0, 1.0]])
    added = matrix_out(run_matrix("matrix_arithmetic", {"operation": "add", "left": a.tolist(), "right": b.tolist(), "store_in": "M3"}))
    subtracted = matrix_out(
        run_matrix("matrix_arithmetic", {"operation": "subtract", "left": added.tolist(), "right": b.tolist(), "store_in": "M4"})
    )
    assert np.array_equal(added, a + b)
    assert np.array_equal(subtracted, a), "add then subtract must return the original exactly"


def test_scalar_multiplication_scales_every_element() -> None:
    result = run_matrix("matrix_arithmetic", {"operation": "scalar", "left": SIMPLE, "scalar": -2.5, "store_in": "M2"})
    assert np.array_equal(matrix_out(result), np.asarray(SIMPLE) * -2.5)


def test_elementwise_product_is_not_the_matrix_product() -> None:
    """Two different operations that a wrong dispatch would confuse; on these operands they differ."""
    a, b = np.asarray(SIMPLE), np.asarray(SYMMETRIC)
    hadamard = matrix_out(
        run_matrix("matrix_arithmetic", {"operation": "elementwise", "left": a.tolist(), "right": b.tolist(), "store_in": "M3"})
    )
    product = matrix_out(
        run_matrix("matrix_arithmetic", {"operation": "multiply", "left": a.tolist(), "right": b.tolist(), "store_in": "M4"})
    )
    assert np.array_equal(hadamard, a * b)
    assert not np.allclose(hadamard, product)


def test_incompatible_shapes_are_refused_with_the_numbers_named() -> None:
    with pytest.raises(ProcedureError) as caught:
        run_matrix(
            "matrix_arithmetic",
            {"operation": "multiply", "left": [[1.0, 2.0]], "right": [[1.0, 2.0]], "store_in": "M3"},
        )
    message = str(caught.value)
    assert "column count" in message and "row count" in message, message


def test_a_matrix_with_a_missing_value_is_refused() -> None:
    with pytest.raises(ProcedureError) as caught:
        run_matrix("matrix_transpose", {"matrix": [[1.0, float("nan")], [3.0, 4.0]], "store_in": "M2"})
    assert "missing or infinite" in str(caught.value)


# --- round trip through the worksheet -----------------------------------------------------------------


def test_columns_to_matrix_and_back_is_the_identity() -> None:
    """Data > Copy moves values between the worksheet and the matrix store; the trip must be lossless."""
    frame = pd.DataFrame({"a": [1.5, 2.5, 3.5], "b": [-1.0, 0.0, 4.25]})
    to_matrix = run_calc(frame, "matrix_from_columns", ["a", "b"], {"store_in": "M1"})
    rows = to_matrix["store_matrix"]["rows"]
    assert np.array_equal(np.asarray(rows), frame.to_numpy(dtype=float))

    back = run_calc(frame, "matrix_to_columns", [], {"matrix": rows, "store_prefix": "C"})
    stored = back.get("store_columns")
    assert stored, f"matrix_to_columns should write columns; got {list(back)}"
    assert np.allclose(np.column_stack([column["values"] for column in stored]), frame.to_numpy(dtype=float))


def test_diagonal_extraction_returns_the_diagonal() -> None:
    result = run_calc(BLANK, "matrix_diagonal", [], {"direction": "extract", "matrix": GENERAL, "store_in": "C1"})
    stored = result["store_columns"][0]["values"]
    assert list(stored) == [GENERAL[i][i] for i in range(3)] == [2.0, 3.0, 4.0]
