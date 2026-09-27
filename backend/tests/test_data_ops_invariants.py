"""Tier B: invariants for the 25 Data-menu operations, and the `.gsp` project round trip.

Data operations have no reference values — there is nothing to certify about "sort by column B" —
but they have something better: exact invariants. A stack followed by an unstack must give the
original frame back, transposing twice must be the identity, sorting must move whole rows rather
than one column, and a recode's preview must count exactly what applying it changes. Those are
provable statements, and each one is the shape of a bug that has actually happened in this kind of
code.

`OPERATIONS_COVERED` is checked against `data_ops.OPERATIONS` from `test_properties_sweep.py`, so a
new Data operation cannot be added without deciding what invariant holds for it.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.core import data_ops
from backend.core import datasets as datasets_core
from backend.core.datasets import DatasetStore
from backend.core.procedures import ProcedureError
from backend.tests.harness import run_data_op

pytestmark = pytest.mark.properties

# Every operation this module exercises. The sweep test asserts this equals data_ops.OPERATIONS.
OPERATIONS_COVERED = [
    "change_type",
    "concatenate",
    "copy_columns",
    "copy_worksheet",
    "date_extract",
    "date_round",
    "delete_rows",
    "display_data",
    "erase_variables",
    "merge_match",
    "merge_side_by_side",
    "rank",
    "recode",
    "recode_conversion_table",
    "set_columns",
    "sort",
    "split",
    "stack_blocks",
    "stack_columns",
    "stack_rows",
    "stack_worksheets",
    "subset",
    "transpose",
    "unstack_columns",
    "worksheet_info",
]


@pytest.fixture
def wide() -> pd.DataFrame:
    """Three measurement columns and a label, the classic input for Stack / Unstack."""
    return pd.DataFrame(
        {
            "label": ["r1", "r2", "r3", "r4"],
            "before": [10.0, 11.5, 9.25, 12.0],
            "during": [14.0, 13.5, 15.25, 11.0],
            "after": [12.0, 10.5, 13.25, 14.5],
        }
    )


@pytest.fixture
def mixed() -> pd.DataFrame:
    """Deliberately awkward: mixed dtypes, a missing value, an unsorted key, duplicate values."""
    return pd.DataFrame(
        {
            "id": [3, 1, 4, 1, 5],
            "name": ["c", "a", "d", "a", "e"],
            "score": [30.5, 10.5, np.nan, 10.5, 50.0],
            "grade": ["Pass", "Fail", "Pass", "Fail", "Pass"],
        }
    )


def only_frame(result) -> pd.DataFrame:
    assert result.frames, f"expected a frame, got mode={result.mode} with none"
    return result.frames[0][1]


# --- stack / unstack round trip -----------------------------------------------------------------


def test_stack_then_unstack_returns_the_original_values(wide) -> None:
    """The headline invariant. Reshaping is lossless or it is a bug."""
    stacked = only_frame(
        run_data_op(
            wide,
            "stack_columns",
            {
                "columns": ["before", "during", "after"],
                "value_name": "value",
                "subscript_name": "phase",
                "include_subscripts": True,
            },
        )
    )
    assert len(stacked) == 12
    assert set(stacked["phase"].unique()) == {"before", "during", "after"}

    unstacked = only_frame(
        run_data_op(stacked, "unstack_columns", {"columns": ["value"], "subscript_column": "phase"})
    )

    for column in ("before", "during", "after"):
        matching = [c for c in unstacked.columns if column in str(c)]
        assert matching, f"no unstacked column for {column}: {list(unstacked.columns)}"
        recovered = pd.to_numeric(unstacked[matching[0]], errors="coerce").dropna().tolist()
        assert recovered == wide[column].tolist(), f"{column}: {recovered} != {wide[column].tolist()}"


def test_stacking_preserves_every_value_exactly_once(wide) -> None:
    stacked = only_frame(
        run_data_op(
            wide,
            "stack_columns",
            {"columns": ["before", "during", "after"], "value_name": "value", "subscript_name": "phase", "include_subscripts": True},
        )
    )
    assert sorted(stacked["value"].tolist()) == sorted(
        wide["before"].tolist() + wide["during"].tolist() + wide["after"].tolist()
    )


def test_stack_rows_and_stack_blocks_conserve_the_data(wide) -> None:
    rows = only_frame(
        run_data_op(wide, "stack_rows", {"columns": ["before", "during"], "value_name": "value", "subscript_name": "src"})
    )
    assert len(rows) == 8

    blocks = only_frame(
        run_data_op(
            wide,
            "stack_blocks",
            {"blocks": [["before"], ["during"], ["after"]], "subscript_name": "block", "include_subscripts": True},
        )
    )
    assert len(blocks) == 12


# --- transpose ---------------------------------------------------------------------------------------


def test_transposing_twice_returns_the_original(wide) -> None:
    """Rows become columns become rows. Values must survive the trip, whatever the headers do."""
    once = only_frame(run_data_op(wide, "transpose", {"columns": ["before", "during", "after"], "name_column": "label"}))
    twice = only_frame(run_data_op(once, "transpose", {"columns": list(once.columns)[1:], "name_column": list(once.columns)[0]}))

    original = wide[["before", "during", "after"]].to_numpy(dtype=float)
    recovered = twice[[c for c in twice.columns if c != twice.columns[0]]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    assert recovered.shape == original.shape, f"{recovered.shape} != {original.shape}"
    assert np.allclose(recovered, original), f"{recovered}\n!=\n{original}"


def test_transpose_swaps_the_dimensions(wide) -> None:
    once = only_frame(run_data_op(wide, "transpose", {"columns": ["before", "during", "after"], "name_column": "label"}))
    assert len(once) == 3, "three measurement columns become three rows"
    assert len(once.columns) == 5, "four rows plus the name column"


# --- sort keeps rows intact ---------------------------------------------------------------------------


def test_sort_moves_whole_rows_not_one_column(mixed) -> None:
    """The bug this catches destroys data silently: a sorted column beside unsorted neighbours."""
    result = run_data_op(mixed, "sort", {"by": [{"column": "id", "direction": "ascending"}], "destination": "new", "new_name": "Sorted"})
    sorted_frame = only_frame(result)

    assert sorted_frame["id"].tolist() == sorted(mixed["id"].tolist())
    original_pairs = sorted(zip(mixed["id"], mixed["name"]))
    sorted_pairs = sorted(zip(sorted_frame["id"], sorted_frame["name"]))
    assert sorted_pairs == original_pairs, "id/name pairings changed during the sort"

    for _, row in sorted_frame.iterrows():
        matches = mixed[(mixed["id"] == row["id"]) & (mixed["name"] == row["name"])]
        assert len(matches) >= 1, f"row {row.to_dict()} is not in the original"


def test_sort_descending_is_the_reverse_of_ascending(mixed) -> None:
    ascending = only_frame(
        run_data_op(mixed, "sort", {"by": [{"column": "id", "direction": "ascending"}], "destination": "new", "new_name": "A"})
    )
    descending = only_frame(
        run_data_op(mixed, "sort", {"by": [{"column": "id", "direction": "descending"}], "destination": "new", "new_name": "D"})
    )
    assert descending["id"].tolist() == list(reversed(ascending["id"].tolist()))


def test_sort_is_stable_across_a_second_key(mixed) -> None:
    result = only_frame(
        run_data_op(
            mixed,
            "sort",
            {
                "by": [{"column": "grade", "direction": "ascending"}, {"column": "id", "direction": "ascending"}],
                "destination": "new",
                "new_name": "S",
            },
        )
    )
    grades = result["grade"].tolist()
    assert grades == sorted(grades), "the primary key must be in order"
    for grade in set(grades):
        ids = result.loc[result["grade"] == grade, "id"].tolist()
        assert ids == sorted(ids), f"secondary key out of order within {grade}"


def test_rank_ties_share_a_rank_and_the_row_count_is_unchanged(mixed) -> None:
    result = run_data_op(mixed, "rank", {"column": "score", "store_in": "score rank"})
    ranked = only_frame(result) if result.frames else mixed
    assert len(ranked) == len(mixed)
    column = [c for c in ranked.columns if "rank" in str(c).lower()][0]
    ranks = pd.to_numeric(ranked[column], errors="coerce")
    # Two rows share a score of 10.5, so they must share a rank.
    tied = ranks[mixed["score"] == 10.5].dropna().unique()
    assert len(tied) == 1, f"tied scores got different ranks: {tied}"


# --- recode preview matches apply ---------------------------------------------------------------------


def test_recode_preview_counts_match_what_applying_it_changes(mixed) -> None:
    """A preview that overcounts is worse than no preview: it is a promise the apply breaks."""
    options = {
        "columns": ["grade"],
        "to": "text",
        "mappings": [{"from": "Pass", "to": "OK"}, {"from": "Fail", "to": "NO"}],
        "destination": "same",
    }
    result = run_data_op(mixed, "recode", options)
    recoded = only_frame(result) if result.frames else None
    assert recoded is not None

    changed = int((mixed["grade"].astype(str) != recoded["grade"].astype(str)).sum())
    assert changed == len(mixed), "every row's grade was mapped"

    reported = result.report
    counts = [v for v in reported.values() if isinstance(v, int)]
    assert changed in counts or str(changed) in json.dumps(reported), (
        f"the report does not mention the {changed} values it changed: {reported}"
    )


def test_recode_only_touches_the_values_it_names(mixed) -> None:
    result = run_data_op(
        mixed,
        "recode",
        {"columns": ["grade"], "to": "text", "mappings": [{"from": "Pass", "to": "OK"}], "destination": "same", "others": "keep"},
    )
    recoded = only_frame(result)
    assert recoded.loc[mixed["grade"] == "Fail", "grade"].tolist() == ["Fail", "Fail"]
    assert recoded.loc[mixed["grade"] == "Pass", "grade"].tolist() == ["OK", "OK", "OK"]
    assert recoded["score"].fillna(-1).tolist() == mixed["score"].fillna(-1).tolist(), "other columns untouched"


def test_recode_conversion_table_uses_the_other_worksheet(mixed) -> None:
    lookup = pd.DataFrame({"old": ["Pass", "Fail"], "new": ["Y", "N"]})
    result = run_data_op(
        mixed,
        "recode_conversion_table",
        {"columns": ["grade"], "table_worksheet": "w2", "old_column": "old", "new_column": "new"},
        others={"w2": lookup},
        names={"w2": "Lookup"},
    )
    recoded = only_frame(result)
    assert sorted(set(recoded["grade"])) == ["N", "Y"]


# --- subset, split, delete, erase ------------------------------------------------------------------------


def test_subset_and_its_complement_partition_the_rows(mixed) -> None:
    condition = [{"column": "grade", "operator": "=", "value": "Pass"}]
    included = only_frame(run_data_op(mixed, "subset", {"conditions": condition, "action": "include", "new_name": "In"}))
    excluded = only_frame(run_data_op(mixed, "subset", {"conditions": condition, "action": "exclude", "new_name": "Out"}))

    assert len(included) + len(excluded) == len(mixed), "a subset and its complement must cover the frame"
    assert set(included["name"]) & set(excluded["name"]) == set(), "and must not overlap"


def test_split_covers_every_row_exactly_once(mixed) -> None:
    result = run_data_op(mixed, "split", {"by_column": "grade", "base_name": "Grade"})
    assert result.mode == "many"
    total = sum(len(frame) for _, frame in result.frames)
    assert total == len(mixed), f"split produced {total} rows from {len(mixed)}"
    assert len(result.frames) == mixed["grade"].nunique()


def test_delete_rows_removes_exactly_the_rows_named(mixed) -> None:
    result = run_data_op(mixed, "delete_rows", {"rows": "2:3"})
    remaining = only_frame(result)
    assert len(remaining) == len(mixed) - 2
    assert remaining["name"].tolist() == ["c", "a", "e"], remaining["name"].tolist()


def test_erase_variables_blanks_the_contents_and_keeps_the_column(mixed) -> None:
    """Minitab's Erase Variables clears the values and leaves the column in place, which is what
    Gosset does and what its summary says. Asserted in that form so nobody "fixes" it into a drop:
    a worksheet column is positional (C1, C2, ...) and removing one would renumber the rest."""
    result = run_data_op(mixed, "erase_variables", {"columns": ["score"]})
    remaining = only_frame(result)

    assert list(remaining.columns) == list(mixed.columns), "the column itself must remain"
    assert remaining["score"].isna().all(), "its contents must be gone"
    assert len(remaining) == len(mixed), "erasing a column must not drop rows"
    assert remaining["name"].tolist() == mixed["name"].tolist(), "other columns untouched"
    assert "remain" in result.report["summary"], "the summary must say the column stays"


# --- merges and cross-worksheet operations -------------------------------------------------------------


def test_merge_match_keeps_the_left_rows_and_adds_the_right_columns(mixed) -> None:
    lookup = pd.DataFrame({"id": [1, 3, 4, 5], "region": ["N", "S", "E", "W"]})
    result = run_data_op(
        mixed,
        "merge_match",
        {"worksheet": "w2", "how": "left", "keys": [{"left": "id", "right": "id"}], "new_name": "Merged"},
        others={"w2": lookup},
        names={"w2": "Lookup"},
    )
    merged = only_frame(result)
    assert len(merged) == len(mixed), "a left join must not change the row count here"
    assert "region" in merged.columns


def test_merge_side_by_side_pads_to_the_longest(mixed) -> None:
    other = pd.DataFrame({"extra": [1, 2]})
    merged = only_frame(
        run_data_op(mixed, "merge_side_by_side", {"worksheets": ["w2"], "new_name": "Wide"}, others={"w2": other}, names={"w2": "Other"})
    )
    assert len(merged) == max(len(mixed), len(other))
    assert "extra" in merged.columns


def test_stack_worksheets_concatenates_the_rows(mixed) -> None:
    """Two or more OTHER worksheets, named by id — the dialog stacks a chosen list, not "this and
    that one", so a single-worksheet request is refused."""
    stacked = only_frame(
        run_data_op(
            mixed,
            "stack_worksheets",
            {"worksheets": ["w1", "w2"], "new_name": "Stacked", "include_source": True},
            others={"w1": mixed.copy(), "w2": mixed.copy()},
            names={"w1": "First", "w2": "Second"},
        )
    )
    assert len(stacked) == 2 * len(mixed)
    assert "Source" in stacked.columns, "include_source must label where each row came from"
    assert sorted(stacked["Source"].unique()) == ["First", "Second"]

    with pytest.raises(ProcedureError):
        run_data_op(mixed, "stack_worksheets", {"worksheets": ["w1"]}, others={"w1": mixed}, names={"w1": "First"})


def test_copy_columns_and_copy_worksheet_do_not_lose_rows(mixed) -> None:
    copied = run_data_op(mixed, "copy_columns", {"columns": ["id", "name"], "destination": "new", "new_name": "Copy"})
    frame = only_frame(copied)
    assert list(frame.columns) == ["id", "name"] and len(frame) == len(mixed)

    whole = only_frame(run_data_op(mixed, "copy_worksheet", {"columns": list(mixed.columns), "new_name": "Duplicate"}))
    assert whole.shape == mixed.shape


# --- type changes, dates, text -----------------------------------------------------------------------------


def test_change_type_to_text_and_back_preserves_the_numbers() -> None:
    frame = pd.DataFrame({"n": [1.5, -2.25, 0.0, 1000.0]})
    as_text = only_frame(run_data_op(frame, "change_type", {"columns": ["n"], "to": "text"}))
    assert as_text["n"].map(type).eq(str).all()

    back = only_frame(run_data_op(as_text, "change_type", {"columns": ["n"], "to": "numeric"}))
    assert pd.to_numeric(back["n"]).tolist() == frame["n"].tolist()


def test_date_extract_components_agree_with_the_date() -> None:
    frame = pd.DataFrame({"when": ["2026-07-30", "2024-02-29", "1999-12-31"]})
    typed = only_frame(run_data_op(frame, "change_type", {"columns": ["when"], "to": "datetime"}))
    extracted = only_frame(run_data_op(typed, "date_extract", {"column": "when", "components": ["year", "month", "day of month"]}))

    parsed = pd.to_datetime(frame["when"])
    year_col = [c for c in extracted.columns if "year" in str(c).lower()][0]
    assert pd.to_numeric(extracted[year_col]).tolist() == parsed.dt.year.tolist()


def test_date_round_is_idempotent() -> None:
    """Rounding to the month twice must give the same answer as rounding once."""
    frame = pd.DataFrame({"when": pd.to_datetime(["2026-07-30", "2026-07-02", "2026-08-15"])})
    once = only_frame(run_data_op(frame, "date_round", {"column": "when", "unit": "month", "how": "floor", "destination": "same"}))
    twice = only_frame(run_data_op(once, "date_round", {"column": "when", "unit": "month", "how": "floor", "destination": "same"}))
    assert once["when"].astype(str).tolist() == twice["when"].astype(str).tolist()


def test_concatenate_joins_with_the_separator_and_skips_nothing() -> None:
    frame = pd.DataFrame({"a": ["x", "y"], "b": ["1", "2"]})
    joined = only_frame(run_data_op(frame, "concatenate", {"columns": ["a", "b"], "new_column": "ab", "separator": "-"}))
    assert joined["ab"].tolist() == ["x-1", "y-2"]
    assert len(joined) == len(frame)


def test_set_columns_writes_the_values_it_is_given(mixed) -> None:
    result = run_data_op(mixed, "set_columns", {"columns": [{"name": "doubled", "values": [2, 4, 6, 8, 10]}]})
    frame = only_frame(result)
    assert frame["doubled"].tolist() == [2, 4, 6, 8, 10]
    assert len(frame) == len(mixed)


# --- the read-only reports -------------------------------------------------------------------------------


def test_display_data_and_worksheet_info_change_nothing(mixed) -> None:
    for operation, options in (("display_data", {"columns": ["id", "name"]}), ("worksheet_info", {})):
        result = run_data_op(mixed, operation, options)
        assert result.mode == "none", f"{operation} must not modify the worksheet"
        assert result.report, f"{operation} must report something"


def test_worksheet_info_counts_the_columns_and_rows(mixed) -> None:
    report = run_data_op(mixed, "worksheet_info", {}).report
    text = json.dumps(report)
    assert str(len(mixed)) in text and str(len(mixed.columns)) in text


# --- refusals ----------------------------------------------------------------------------------------------


def test_an_unknown_operation_lists_the_known_ones() -> None:
    with pytest.raises(ProcedureError) as caught:
        run_data_op(pd.DataFrame({"a": [1]}), "not_an_operation", {})
    message = str(caught.value)
    assert "sort" in message and "transpose" in message, "the refusal should list what IS available"


def test_sorting_by_nothing_is_refused(mixed) -> None:
    with pytest.raises(ProcedureError):
        run_data_op(mixed, "sort", {"by": []})


# --- the .gsp project round trip --------------------------------------------------------------------------
#
# A `.gsp` is JSON. Saving serialises each worksheet the way GET /datasets/{id}/full does — column
# info plus `rows` as OBJECTS KEYED BY COLUMN NAME — and opening rebuilds the frame through
# `dataframe_from_values`, which is what POST /datasets/values calls. Round-tripping through exactly
# those two functions is therefore the real save/open path, minus the HTTP.


def _save(df: pd.DataFrame) -> dict:
    """What one worksheet looks like inside a saved project file, as JSON text and back."""
    payload = {
        "columns": [c["name"] for c in datasets_core.column_info(df)],
        "rows": datasets_core.json_safe_records(df),
    }
    # Through a string, so anything JSON cannot represent fails here rather than at open time.
    return json.loads(json.dumps(payload, allow_nan=False))


def _open(payload: dict) -> pd.DataFrame:
    return datasets_core.dataframe_from_values(payload["columns"], payload["rows"])


def test_gsp_rows_are_objects_keyed_by_column_name() -> None:
    """The format detail that costs an afternoon: rows are dicts, not arrays.

    A hand-authored fixture with arrays 422s at POST /datasets/values, and until 2026-07-30 it did so
    invisibly. Asserted explicitly so the shape is documented by a test rather than by folklore.
    """
    saved = _save(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    assert isinstance(saved["rows"], list) and saved["rows"]
    assert isinstance(saved["rows"][0], dict), f"rows must be objects, got {type(saved['rows'][0])}"
    assert saved["rows"][0] == {"a": 1, "b": "x"}
    assert saved["columns"] == ["a", "b"]


def test_gsp_round_trip_preserves_values_dtypes_and_missingness() -> None:
    """Round-trip a project and COUNT what comes back — project trap 16 was a deserialiser that
    dropped a field and left everything looking fine."""
    original = pd.DataFrame(
        {
            "n": [1, 2, 3],
            "x": [1.5, -2.25, 0.0],
            "text": ["a", "b", "c"],
            "missing": [1.0, np.nan, 3.0],
            "big": [1e15, 12345.6789, -98765.4321],
        }
    )
    reopened = _open(_save(original))

    assert list(reopened.columns) == list(original.columns), "column order must survive"
    assert len(reopened) == len(original), "row count must survive"
    for column in ("n", "x", "big"):
        assert pd.to_numeric(reopened[column]).tolist() == original[column].tolist(), f"{column} changed"
    assert reopened["text"].tolist() == original["text"].tolist()
    assert reopened["missing"].isna().tolist() == original["missing"].isna().tolist(), "missingness must survive"
    assert pd.api.types.is_numeric_dtype(reopened["n"]), "a numeric column must come back numeric"


# The values above are all comfortably inside the ten decimal places a saved project keeps. The two
# tests below are about what happens outside that, which is a real and currently silent data loss.

SMALL_VALUES = [1e-15, 3.63834187500000e-09, 0.1 + 0.2, 1.234567890123456e-08]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Saving a project rounds every float to TEN DECIMAL PLACES. "
        "`datasets.json_safe_records` serialises with `DataFrame.to_json(orient='records')`, whose "
        "`double_precision` argument defaults to 10 — so 1e-15 is written as -0.0, "
        "3.638341875e-09 becomes 3.6e-09 (two significant digits), and 0.30000000000000004 becomes "
        "0.3. The cut is on decimal places rather than significant figures, so a worksheet of ordinary "
        "measurements is unaffected while a column of p-values or variance components is largely "
        "destroyed, with nothing said. "
        "Passing double_precision=15 helps but does not fix it (3.638342e-09); the real fix is to "
        "serialise floats through repr() rather than pandas' JSON writer."
    ),
)
def test_gsp_round_trip_is_lossless_for_small_magnitudes() -> None:
    original = pd.DataFrame({"tiny": SMALL_VALUES})
    reopened = _open(_save(original))
    assert pd.to_numeric(reopened["tiny"]).tolist() == SMALL_VALUES


def test_gsp_precision_loss_is_exactly_ten_decimal_places() -> None:
    """Pins the boundary of the defect above, so its blast radius is documented rather than guessed.

    The cut is on DECIMAL PLACES, not on magnitude or significant figures. A value needing ten or
    fewer places after the point survives exactly, however large it is; one needing more is rounded
    there, however small it is. So a worksheet of measurements (196.3052, 107.8681568) is safe and a
    column of p-values, variance components or standardised residuals is not — which is the sentence
    that belongs in VALIDATION.md rather than a vague "some precision may be lost".
    """
    within_ten_places = [196.3052, 107.8681568, 1e15, -98765.4321, 0.0001234567]
    reopened = _open(_save(pd.DataFrame({"v": within_ten_places})))
    assert pd.to_numeric(reopened["v"]).tolist() == within_ten_places, "ten places or fewer must be exact"

    beyond = 0.000123456789  # twelve decimal places
    assert _open(_save(pd.DataFrame({"v": [beyond]})))["v"].tolist() == [round(beyond, 10)]

    lost = _open(_save(pd.DataFrame({"v": SMALL_VALUES})))["v"].tolist()
    assert lost != SMALL_VALUES, "if this now passes, the defect is fixed - drop the xfail above"
    assert lost[0] == 0.0, f"1e-15 should currently flush to zero, got {lost[0]}"


def test_gsp_round_trip_preserves_dates_as_worksheet_text() -> None:
    """Dates travel as '2024-01-01', not as a full ISO timestamp — a grid has to be readable."""
    original = pd.DataFrame({"when": pd.to_datetime(["2024-01-01", "2026-07-30"])})
    saved = _save(original)
    assert saved["rows"][0]["when"] == "2024-01-01", saved["rows"][0]

    reopened = _open(saved)
    assert pd.to_datetime(reopened["when"]).tolist() == original["when"].tolist()


def test_gsp_round_trip_survives_a_data_operation(wide) -> None:
    """The realistic path: reshape a worksheet, save, reopen, and get the reshaped frame back."""
    stacked = only_frame(
        run_data_op(
            wide,
            "stack_columns",
            {
                "columns": ["before", "during", "after"],
                "value_name": "value",
                "subscript_name": "phase",
                "include_subscripts": True,
            },
        )
    )
    reopened = _open(_save(stacked))

    assert len(reopened) == 12
    assert sorted(pd.to_numeric(reopened["value"]).tolist()) == sorted(stacked["value"].tolist())
    assert set(reopened["phase"]) == {"before", "during", "after"}


def test_a_reopened_project_can_be_analysed_again(wide) -> None:
    """The point of the round trip: the reopened frame must still work as a worksheet.

    A frame that parses but comes back all-object would run every analysis on text and fail with a
    confusing message about non-numeric columns — long after the save that caused it.
    """
    from backend.tests.harness import run_basic_stats
    from backend.tests.tolerance import assert_close, row_where, table

    reopened = _open(_save(wide))
    before = run_basic_stats(wide, "display_descriptives", ["before"], {})
    after = run_basic_stats(reopened, "display_descriptives", ["before"], {})

    assert_close(
        row_where(table(after, "Statistics"), "Variable", "before")["Mean"],
        row_where(table(before, "Statistics"), "Variable", "before")["Mean"],
        rtol=0,
        what="mean after a save/open cycle",
    )


def test_the_dataset_store_keeps_worksheets_apart() -> None:
    """A project holds several worksheets; the store must not let one leak into another."""
    store = DatasetStore()
    first = store.add(pd.DataFrame({"a": [1, 2]}), source="Sheet 1", source_type="project")
    second = store.add(pd.DataFrame({"b": [3, 4, 5]}), source="Sheet 2", source_type="project")

    assert first.dataset_id != second.dataset_id
    assert list(store.get(first.dataset_id).df.columns) == ["a"]
    assert len(store.get(second.dataset_id).df) == 3
    assert set(store.all()) == {first.dataset_id, second.dataset_id}
