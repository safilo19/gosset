"""REST API mirroring the 10 MCP tools, plus the static frontend that talks to it.

Same analysis logic as the MCP server (both import from backend/core/), different interface.
This API has its own in-memory DatasetStore — it does NOT share state with the MCP server.

Run with: uvicorn backend.api:app --reload, then open http://localhost:8000 — the frontend/
directory (plain HTML/CSS/JS, no build step) is served from the same origin as this API,
so there's no CORS and no separate frontend URL to keep track of.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import version
from analytics_mcp.models import (
    AnalysisToInclude,
    ColumnInfo,
    ColumnStats,
    ComputeCorrelationOutput,
    CorrelationPair,
    DatasetSummary,
    DescribeDatasetOutput,
    ExportReportOutput,
    FeatureCoefficient,
    FeatureImportance,
    ForecastPoint,
    ForecastTimeseriesOutput,
    GenerateChartOutput,
    HypothesisTestGroupSummary,
    ListDatasetsOutput,
    LoadDatasetOutput,
    ModelComparisonResult,
    RunAutoMLOutput,
    RunDecisionTreeOutput,
    RunGradientBoostingOutput,
    RunHypothesisTestOutput,
    RunRandomForestOutput,
    RunRegressionOutput,
    RunSegmentationOutput,
    SegmentRowAssignment,
    SegmentSummary,
)
from backend.core import anova as anova_core
from backend.core import basic_stats as basic_stats_core
from backend.core import calc as calc_core
from backend.core import charts as charts_core
from backend.core import data_ops as data_ops_core
from backend.core import datasets as datasets_core
from backend.core import forecasting as forecasting_core
from backend.core import graphs as graphs_core
from backend.core import predictive as predictive_core
from backend.core import procedures as procedures_core
from backend.core import regression as regression_core
from backend.core import regression_models as regression_models_core
from backend.core import reports as reports_core
from backend.core import segmentation as segmentation_core
from backend.core import stats as stats_core
from backend.core import tests as tests_core

# ---------------------------------------------------------------------------
# app + CORS
# ---------------------------------------------------------------------------

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:8000").split(",")
]

app = FastAPI(title="Gosset API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = datasets_core.DatasetStore()

# Serve generated reports (xlsx/markdown/png) so the frontend can offer real download links
# instead of the raw server-side filesystem paths in ExportReportOutput.files.
reports_core.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(reports_core.OUTPUT_DIR)), name="output")


@app.get("/health")
def health() -> dict:
    """Liveness probe. The desktop shell polls this before it shows a window.

    It must not touch the DatasetStore or import anything lazily: the whole point is to answer as
    soon as the app object is serving, so `pid` is what lets the Electron main process confirm the
    process it is talking to is the sidecar it spawned rather than another Gosset already running on
    a recycled port.
    """
    return {"status": "ok", "app": "Gosset", "version": version.VERSION, "pid": os.getpid()}


@app.exception_handler(datasets_core.DatasetNotFoundError)
def _handle_dataset_not_found(request: Request, exc: datasets_core.DatasetNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(datasets_core.ColumnNotFoundError)
def _handle_column_not_found(request: Request, exc: datasets_core.ColumnNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _input_error_body(exc: Exception) -> dict:
    """400 body for an error the person in front of the dialog can fix.

    `swap` rides along when the fix is "you put these two columns the wrong way round" — the dialog
    turns it into a button rather than leaving them to work out which box was wrong. Anything else
    about the error stays in `detail`, which is shown verbatim.
    """
    body: dict = {"detail": str(exc)}
    swap = getattr(exc, "swap", None)
    if swap:
        body["swap"] = list(swap)
    return body


@app.exception_handler(graphs_core.GraphError)
def _handle_graph_error(request: Request, exc: graphs_core.GraphError) -> JSONResponse:
    return JSONResponse(status_code=400, content=_input_error_body(exc))


@app.exception_handler(procedures_core.ProcedureError)
def _handle_procedure_error(request: Request, exc: procedures_core.ProcedureError) -> JSONResponse:
    """Every Stat-menu procedure (basic_stats, regression_models) raises this for input the person in
    front of the dialog can fix, and the message is written to be shown to them verbatim."""
    return JSONResponse(status_code=400, content=_input_error_body(exc))


@app.exception_handler(ValueError)
def _handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# request body models (dataset_id comes from the URL path, not the body)
# ---------------------------------------------------------------------------


class LoadGSheetRequest(BaseModel):
    source: str = Field(..., description="Public Google Sheets share URL.")
    sheet_name: str | None = None


class CorrelationRequest(BaseModel):
    columns: list[str] = Field(..., min_length=2)
    method: Literal["pearson", "spearman"] = "pearson"


class HypothesisTestRequest(BaseModel):
    test_type: Literal["t_test", "chi_square", "anova"]
    columns: list[str] = Field(..., min_length=2, max_length=2)
    alpha: float = Field(0.05, gt=0, lt=1)


class RegressionRequest(BaseModel):
    target: str
    features: list[str] = Field(..., min_length=1)
    model_type: Literal["linear", "logistic"] = "linear"


class ForecastRequest(BaseModel):
    date_column: str
    value_column: str
    periods: int = Field(..., ge=1, le=365)
    method: Literal["exponential_smoothing", "arima", "auto"] = "auto"


class SegmentationRequest(BaseModel):
    columns: list[str] = Field(..., min_length=1)
    method: Literal["kmeans", "rfm", "auto"] = "auto"
    n_clusters: int = Field(3, ge=2, le=10)


class DecisionTreeRequest(BaseModel):
    target: str
    features: list[str] = Field(..., min_length=1)
    task_type: Literal["classification", "regression", "auto"] = "auto"


class RandomForestRequest(BaseModel):
    target: str
    features: list[str] = Field(..., min_length=1)
    task_type: Literal["classification", "regression", "auto"] = "auto"


class GradientBoostingRequest(BaseModel):
    target: str
    features: list[str] = Field(..., min_length=1)
    task_type: Literal["classification", "regression", "auto"] = "auto"


class AutoMLRequest(BaseModel):
    target: str
    features: list[str] = Field(..., min_length=1)
    task_type: Literal["classification", "regression", "auto"] = "auto"


class UpdateCellRequest(BaseModel):
    row_index: int = Field(..., ge=0)
    column: str
    value: Any = Field(..., description="New cell value; validated against the column's existing dtype.")


class UpdateCellOutput(BaseModel):
    dataset_id: str
    row_index: int
    column: str
    value: Any = Field(..., description="The coerced value actually stored, e.g. '3' becomes 3.0 for a numeric column.")


class DatasetRowsOutput(BaseModel):
    dataset_id: str
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]] = Field(..., description="Every row in the dataset, as JSON-safe records — for the Worksheet view.")


class PasteRequest(BaseModel):
    start_row: int = Field(..., ge=0)
    start_column: int = Field(..., ge=0, description="0-based column index, not a column name — paste can extend past existing columns.")
    values: list[list[Any]] = Field(..., min_length=1, description="2D array of pasted values, rows x columns.")


class PasteOutput(BaseModel):
    dataset_id: str
    row_count: int
    column_count: int


class DatasetFullOutput(BaseModel):
    dataset_id: str
    source: str
    source_type: str
    row_count: int
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]] = Field(..., description="Every row, as JSON-safe records — the whole worksheet, for File > Save Project.")


class WorksheetValuesRequest(BaseModel):
    columns: list[str] = Field(..., min_length=1, description="Column names, in worksheet order.")
    rows: list[dict[str, Any]] = Field(..., description="Row records keyed by column name; missing keys become empty cells.")
    source: str = Field("Restored worksheet", description="Label shown in the status bar for the restored worksheet.")


class DeleteRowsRequest(BaseModel):
    row_indices: list[int] = Field(..., min_length=1, description="0-based row indices to delete.")


class DeleteColumnsRequest(BaseModel):
    columns: list[str] = Field(..., min_length=1, description="Names of the columns to delete.")


class DeleteRowsOutput(BaseModel):
    dataset_id: str
    deleted: int
    row_count: int
    column_count: int


class RenameColumnRequest(BaseModel):
    column: str
    new_name: str


class RenameColumnOutput(BaseModel):
    dataset_id: str
    column: str
    new_name: str


class RenameWorksheetRequest(BaseModel):
    name: str = Field(..., description="New display name for the worksheet — what its tab reads.")


class WorksheetRef(BaseModel):
    """A worksheet the frontend should give a tab to — the reply to any Data operation that made one."""

    dataset_id: str
    name: str
    source_type: str
    row_count: int
    columns: list[ColumnInfo]


class DataOpRequest(BaseModel):
    operation: str = Field(..., description=f"One of: {', '.join(data_ops_core.OPERATIONS)}.")
    options: dict[str, Any] = Field(default_factory=dict, description="Everything the dialog collected: by-columns, conditions, mappings, destinations, target worksheet ids.")


class DataOpOutput(BaseModel):
    dataset_id: str
    operation: str
    mode: str = Field(..., description="none | in_place | other_in_place | new | many — what the caller should refresh.")
    result: dict[str, Any] = Field(..., description="Tables, highlights, narrative and (for Display Data) preformatted text.")
    created: list[WorksheetRef] = Field(default_factory=list, description="Worksheets this operation added to the store.")
    modified: list[str] = Field(default_factory=list, description="dataset_ids whose contents changed in place.")


class GraphDataRequest(BaseModel):
    graph_type: str = Field(..., description=f"One of: {', '.join(graphs_core.GRAPH_TYPES)}.")
    columns: list[str] = Field(default_factory=list, description="Columns the graph needs, in the order the graph expects them (e.g. [x, y]).")
    options: dict[str, Any] = Field(default_factory=dict, description="Per-graph settings: bin_width, group_column, distribution parameters, and so on.")


class GraphDataOutput(BaseModel):
    dataset_id: str
    graph_type: str
    data: dict[str, Any] = Field(..., description="Computed series for the requested graph — the frontend only renders this.")


class BasicStatsRequest(BaseModel):
    procedure: str = Field(..., description=f"One of: {', '.join(basic_stats_core.PROCEDURES)}.")
    columns: list[str] = Field(default_factory=list, description="Columns the procedure needs, in the order it expects them (e.g. [value, group] for a 2-sample test with the samples in one column).")
    options: dict[str, Any] = Field(default_factory=dict, description="Everything else the dialog collected: hypothesized values, alternative, confidence level, method, statistic picker, graph toggles.")


class BasicStatsOutput(BaseModel):
    dataset_id: str
    procedure: str
    result: dict[str, Any] = Field(..., description="Tables, highlights, graph series and narrative — the frontend only lays this out.")


class CalcRequest(BaseModel):
    procedure: str = Field(..., description=f"One of: {', '.join(calc_core.PROCEDURES)}.")
    columns: list[str] = Field(default_factory=list, description="Columns the procedure needs, in the order it expects them.")
    options: dict[str, Any] = Field(default_factory=dict, description="Everything else the dialog collected: the formula, the destination, distribution parameters, the Set Base seed, the constants and matrices the operation reads.")


class AnovaRequest(BaseModel):
    procedure: str = Field(..., description=f"One of: {', '.join(anova_core.PROCEDURES)}.")
    columns: list[str] = Field(default_factory=list, description="Columns the procedure needs, in the order it expects them (e.g. [response, *factors, *covariates] — `options.n_factors` says where the split is).")
    options: dict[str, Any] = Field(default_factory=dict, description="Everything else the dialog collected: layout, equal-variance choice, comparison method, explicit terms, random factors, and the stored `model_spec` for the dialogs that work off a fitted model.")


class RegressionModelRequest(BaseModel):
    procedure: str = Field(..., description=f"One of: {', '.join(regression_models_core.PROCEDURES)}.")
    columns: list[str] = Field(default_factory=list, description="[response, *predictors] — `options.n_continuous` says how many of the predictors are continuous.")
    options: dict[str, Any] = Field(default_factory=dict, description="Everything else the dialog collected: model order, interactions, alphas, methods, spec limits, the Predict panel's values.")


class ChartRequest(BaseModel):
    chart_type: Literal["bar", "line", "scatter", "histogram", "heatmap"]
    columns: list[str] = Field(..., min_length=1)


class ReportRequest(BaseModel):
    dataset_id: str
    format: Literal["xlsx", "markdown", "docx", "pdf", "pptx", "both"] = "pdf"
    analyses: list[AnalysisToInclude] = Field(..., min_length=1)
    report_name: str | None = None
    decimals: int = Field(
        reports_core.DEFAULT_DECIMALS,
        ge=0,
        le=8,
        description="Decimal places for fractional numbers, so the report matches what File > Options shows on screen.",
    )
    prepared_by: str | None = Field(
        None,
        max_length=120,
        description=(
            "Name for the cover's byline, from whoever is signed in. Null or empty when nobody is, in "
            "which case the byline is omitted entirely rather than left blank."
        ),
    )


# ---------------------------------------------------------------------------
# POST /datasets  (multipart file upload, or JSON body with a Google Sheets URL)
# ---------------------------------------------------------------------------


@app.post("/datasets", response_model=LoadDatasetOutput)
async def create_dataset(
    request: Request,
    file: UploadFile | None = File(None),
    source_type: str | None = Form(None),
    sheet_name: str | None = Form(None),
) -> LoadDatasetOutput:
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        if file is None or source_type is None:
            raise HTTPException(status_code=400, detail="Multipart upload requires 'file' and 'source_type' form fields.")
        if source_type not in ("csv", "xlsx"):
            raise HTTPException(status_code=400, detail="source_type must be 'csv' or 'xlsx' for file uploads.")
        data = await file.read()
        df = datasets_core.load_dataframe_from_bytes(data, source_type, sheet_name)
        source_label = file.filename or f"uploaded.{source_type}"
    else:
        body = await request.json()
        gsheet = LoadGSheetRequest.model_validate(body)
        df = datasets_core.load_dataframe(gsheet.source, "gsheet", gsheet.sheet_name)
        source_label = gsheet.source
        source_type = "gsheet"

    dataset = store.add(df, source=source_label, source_type=source_type)
    load_summary = datasets_core.summarize_load(dataset)

    return LoadDatasetOutput(
        dataset_id=dataset.dataset_id,
        source=source_label,
        source_type=source_type,
        row_count=load_summary.row_count,
        columns=[ColumnInfo(**c) for c in load_summary.columns],
        preview=load_summary.preview,
    )


@app.post("/datasets/blank", response_model=LoadDatasetOutput)
def create_blank_dataset(name: str | None = Query(None, description="Tab label for the new worksheet, e.g. 'Worksheet 2'.")) -> LoadDatasetOutput:
    """A Minitab-style blank worksheet (C1..C20 x 50 empty rows) — the default view on first load,
    before the user has typed anything or imported a file."""
    df = datasets_core.create_blank_dataframe()
    dataset = store.add(df, source=(name or "").strip() or "Blank worksheet", source_type="blank")
    load_summary = datasets_core.summarize_load(dataset)
    return LoadDatasetOutput(
        dataset_id=dataset.dataset_id,
        source=dataset.source,
        source_type=dataset.source_type,
        row_count=load_summary.row_count,
        columns=[ColumnInfo(**c) for c in load_summary.columns],
        preview=load_summary.preview,
    )


@app.get("/datasets", response_model=ListDatasetsOutput)
def list_datasets() -> ListDatasetsOutput:
    results, _summary = datasets_core.summarize_all(store)
    return ListDatasetsOutput(datasets=[DatasetSummary(**asdict(r)) for r in results])


@app.get("/datasets/{dataset_id}/describe", response_model=DescribeDatasetOutput)
def describe_dataset(dataset_id: str, columns: list[str] | None = Query(None)) -> DescribeDatasetOutput:
    dataset = store.get(dataset_id)
    cols = columns if columns is not None else list(dataset.df.columns)
    store.require_columns(dataset, cols)

    results = stats_core.describe_columns(dataset.df, cols)
    return DescribeDatasetOutput(dataset_id=dataset.dataset_id, stats=[ColumnStats(**asdict(r)) for r in results])


@app.get("/datasets/{dataset_id}/rows", response_model=DatasetRowsOutput)
def get_dataset_rows(dataset_id: str) -> DatasetRowsOutput:
    """Every row of the dataset, for the Worksheet view (describe_dataset only returns a 5-row
    preview, which isn't enough to render an editable grid)."""
    dataset = store.get(dataset_id)
    columns = datasets_core.column_info(dataset.df)
    rows = datasets_core.json_safe_records(dataset.df)
    return DatasetRowsOutput(dataset_id=dataset.dataset_id, columns=[ColumnInfo(**c) for c in columns], rows=rows)


@app.patch("/datasets/{dataset_id}/cell", response_model=UpdateCellOutput)
def update_cell(dataset_id: str, body: UpdateCellRequest) -> UpdateCellOutput:
    dataset = store.get(dataset_id)
    coerced = datasets_core.set_cell_value(dataset, body.row_index, body.column, body.value)
    return UpdateCellOutput(dataset_id=dataset.dataset_id, row_index=body.row_index, column=body.column, value=coerced)


@app.patch("/datasets/{dataset_id}/paste", response_model=PasteOutput)
def paste_into_dataset(dataset_id: str, body: PasteRequest) -> PasteOutput:
    dataset = store.get(dataset_id)
    datasets_core.paste_block(dataset, body.start_row, body.start_column, body.values)
    return PasteOutput(dataset_id=dataset.dataset_id, row_count=len(dataset.df), column_count=len(dataset.df.columns))


@app.patch("/datasets/{dataset_id}/column-name", response_model=RenameColumnOutput)
def rename_dataset_column(dataset_id: str, body: RenameColumnRequest) -> RenameColumnOutput:
    dataset = store.get(dataset_id)
    applied_name = datasets_core.rename_column(dataset, body.column, body.new_name)
    return RenameColumnOutput(dataset_id=dataset.dataset_id, column=body.column, new_name=applied_name)


# ---------------------------------------------------------------------------
# worksheet: whole-contents read/write, row/column deletion
#
# GET /full feeds File > Save Project (which needs every cell, not a preview); the two /values
# routes are its inverse — one creating a dataset from a saved project, one swapping an existing
# worksheet's contents in place so Edit > Undo can restore a delete or a grid-growing paste
# without changing the dataset_id that open result windows already reference.
# ---------------------------------------------------------------------------


@app.get("/datasets/{dataset_id}/full", response_model=DatasetFullOutput)
def get_dataset_full(dataset_id: str) -> DatasetFullOutput:
    dataset = store.get(dataset_id)
    columns = datasets_core.column_info(dataset.df)
    return DatasetFullOutput(
        dataset_id=dataset.dataset_id,
        source=dataset.source,
        source_type=dataset.source_type,
        row_count=len(dataset.df),
        columns=[ColumnInfo(**c) for c in columns],
        rows=datasets_core.json_safe_records(dataset.df),
    )


@app.post("/datasets/values", response_model=LoadDatasetOutput)
def create_dataset_from_values(body: WorksheetValuesRequest) -> LoadDatasetOutput:
    df = datasets_core.dataframe_from_values(body.columns, body.rows)
    dataset = store.add(df, source=body.source, source_type="project")
    load_summary = datasets_core.summarize_load(dataset)
    return LoadDatasetOutput(
        dataset_id=dataset.dataset_id,
        source=dataset.source,
        source_type=dataset.source_type,
        row_count=load_summary.row_count,
        columns=[ColumnInfo(**c) for c in load_summary.columns],
        preview=load_summary.preview,
    )


@app.put("/datasets/{dataset_id}/values", response_model=DatasetRowsOutput)
def replace_dataset_values(dataset_id: str, body: WorksheetValuesRequest) -> DatasetRowsOutput:
    dataset = store.get(dataset_id)
    datasets_core.replace_values(dataset, body.columns, body.rows)
    columns = datasets_core.column_info(dataset.df)
    return DatasetRowsOutput(
        dataset_id=dataset.dataset_id,
        columns=[ColumnInfo(**c) for c in columns],
        rows=datasets_core.json_safe_records(dataset.df),
    )


@app.delete("/datasets/{dataset_id}/rows", response_model=DeleteRowsOutput)
def delete_dataset_rows(dataset_id: str, body: DeleteRowsRequest) -> DeleteRowsOutput:
    dataset = store.get(dataset_id)
    deleted = datasets_core.delete_rows(dataset, body.row_indices)
    return DeleteRowsOutput(dataset_id=dataset.dataset_id, deleted=deleted, row_count=len(dataset.df), column_count=len(dataset.df.columns))


@app.delete("/datasets/{dataset_id}/columns", response_model=DeleteRowsOutput)
def delete_dataset_columns(dataset_id: str, body: DeleteColumnsRequest) -> DeleteRowsOutput:
    dataset = store.get(dataset_id)
    deleted = datasets_core.delete_columns(dataset, body.columns)
    return DeleteRowsOutput(dataset_id=dataset.dataset_id, deleted=deleted, row_count=len(dataset.df), column_count=len(dataset.df.columns))


@app.patch("/datasets/{dataset_id}/name", response_model=WorksheetRef)
def rename_worksheet(dataset_id: str, body: RenameWorksheetRequest) -> WorksheetRef:
    """A worksheet tab's label. Held on the Dataset as its `source`, so the status bar, the
    assistant's "use <name>" matching and a saved project all read the same name."""
    dataset = store.get(dataset_id)
    cleaned = body.name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="A worksheet name cannot be empty.")
    dataset.source = cleaned
    return _worksheet_ref(dataset)


def _worksheet_ref(dataset: datasets_core.Dataset) -> WorksheetRef:
    return WorksheetRef(
        dataset_id=dataset.dataset_id,
        name=dataset.source,
        source_type=dataset.source_type,
        row_count=len(dataset.df),
        columns=[ColumnInfo(**c) for c in datasets_core.column_info(dataset.df)],
    )


@app.post("/datasets/{dataset_id}/data-op", response_model=DataOpOutput)
def run_data_op(dataset_id: str, body: DataOpRequest) -> DataOpOutput:
    """Data menu: every operation behind one route, dispatching on `operation` the same way
    /basic-stats dispatches on `procedure`.

    An operation that reads other open worksheets is handed their frames here (the core module
    knows nothing about the store); one that produces worksheets returns real DataFrames, and the
    decision to replace the active worksheet in place or to add new ones is made here."""
    dataset = store.get(dataset_id)
    others = {ds_id: ds.df for ds_id, ds in store.all().items()}
    names = {ds_id: ds.source for ds_id, ds in store.all().items()}

    outcome = data_ops_core.compute(dataset.df, body.operation, body.options, others=others, names=names)

    created: list[WorksheetRef] = []
    modified: list[str] = []

    if outcome.mode == "in_place":
        dataset.df = outcome.frames[0][1]
        modified.append(dataset.dataset_id)
    elif outcome.mode == "other_in_place":
        target = store.get(outcome.target_id or "")
        target.df = outcome.frames[0][1]
        modified.append(target.dataset_id)
    elif outcome.mode in ("new", "many"):
        for name, frame in outcome.frames:
            made = store.add(frame, source=name or "Worksheet", source_type="derived")
            created.append(_worksheet_ref(made))

    return DataOpOutput(
        dataset_id=dataset.dataset_id,
        operation=body.operation,
        mode=outcome.mode,
        result=outcome.report,
        created=created,
        modified=modified,
    )


@app.post("/datasets/{dataset_id}/graph-data", response_model=GraphDataOutput)
def get_graph_data(dataset_id: str, body: GraphDataRequest) -> GraphDataOutput:
    """Every statistic a plot needs (binning, five-number summaries, quantiles, ECDF steps,
    density curves, interpolated grids) computed here, so the frontend is purely a renderer."""
    dataset = store.get(dataset_id)
    data = graphs_core.compute(dataset.df, body.graph_type, body.columns, body.options)
    return GraphDataOutput(dataset_id=dataset.dataset_id, graph_type=body.graph_type, data=data)


@app.post("/datasets/{dataset_id}/basic-stats", response_model=BasicStatsOutput)
def run_basic_stats(dataset_id: str, body: BasicStatsRequest) -> BasicStatsOutput:
    """Stat > Basic Statistics: all 18 procedures behind one route, dispatching on `procedure` the
    same way /graph-data dispatches on graph_type. Every statistic, interval and plot series is
    computed server-side."""
    dataset = store.get(dataset_id)
    result = basic_stats_core.compute(dataset.df, body.procedure, body.columns, body.options)
    return BasicStatsOutput(dataset_id=dataset.dataset_id, procedure=body.procedure, result=result)


@app.post("/datasets/{dataset_id}/regression-model", response_model=BasicStatsOutput)
def run_regression_model(dataset_id: str, body: RegressionModelRequest) -> BasicStatsOutput:
    """Stat > Regression: the 13 dialogs plus the Predict panel, behind one route dispatching on
    `procedure` — the same shape as /basic-stats, so the frontend renders both identically."""
    dataset = store.get(dataset_id)
    result = regression_models_core.compute(dataset.df, body.procedure, body.columns, body.options)
    return BasicStatsOutput(dataset_id=dataset.dataset_id, procedure=body.procedure, result=result)


@app.post("/datasets/{dataset_id}/calc", response_model=BasicStatsOutput)
def run_calc(dataset_id: str, body: CalcRequest) -> BasicStatsOutput:
    """Calc menu: the Calculator, data generation, random data, probability, resampling and
    matrices — one route dispatching on `procedure`, the same shape as /basic-stats.

    Results that belong in a store the frontend owns come back as `store_columns`,
    `store_constant` or `store_matrix` rather than being written here: the constants and matrix
    stores live in the browser so they can be saved in a .baproj, and a written column goes through
    the ordinary `set_columns` data operation so it lands on the undo stack like any other edit."""
    dataset = store.get(dataset_id)
    result = calc_core.compute(dataset.df, body.procedure, body.columns, body.options)
    return BasicStatsOutput(dataset_id=dataset.dataset_id, procedure=body.procedure, result=result)


@app.post("/datasets/{dataset_id}/anova", response_model=BasicStatsOutput)
def run_anova(dataset_id: str, body: AnovaRequest) -> BasicStatsOutput:
    """Stat > ANOVA: one-way through the general linear model, mixed effects, MANOVA and ANOM —
    all behind one route dispatching on `procedure`, the same shape as /basic-stats.

    The dialogs downstream of a fitted model (Comparisons, Predict, Factorial Plots, Contour,
    Surface, Response Optimizer) send back the `model_spec` the fit returned and the model is
    refitted here. Nothing is cached between calls, so a result window can outlive any server
    state — the same choice the Regression menu's Predict panel makes."""
    dataset = store.get(dataset_id)
    result = anova_core.compute(dataset.df, body.procedure, body.columns, body.options)
    return BasicStatsOutput(dataset_id=dataset.dataset_id, procedure=body.procedure, result=result)


@app.post("/datasets/{dataset_id}/correlation", response_model=ComputeCorrelationOutput)
def compute_correlation(dataset_id: str, body: CorrelationRequest) -> ComputeCorrelationOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, body.columns)

    result = stats_core.compute_correlation(dataset.dataset_id, dataset.df, body.columns, body.method)

    return ComputeCorrelationOutput(
        dataset_id=dataset.dataset_id,
        method=body.method,
        columns=body.columns,
        matrix=result.matrix,
        strongest_pairs=[CorrelationPair(**asdict(p)) for p in result.strongest_pairs],
        interpretation=result.interpretation,
    )


@app.post("/datasets/{dataset_id}/hypothesis-test", response_model=RunHypothesisTestOutput)
def run_hypothesis_test(dataset_id: str, body: HypothesisTestRequest) -> RunHypothesisTestOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, body.columns)

    outcome = tests_core.run_hypothesis_test(dataset.df, body.test_type, body.columns, body.alpha)

    return RunHypothesisTestOutput(
        dataset_id=dataset.dataset_id,
        test_type=body.test_type,
        columns=body.columns,
        alpha=body.alpha,
        statistic=outcome.statistic,
        p_value=outcome.p_value,
        degrees_of_freedom=outcome.degrees_of_freedom,
        df_between=outcome.df_between,
        df_within=outcome.df_within,
        groups=[HypothesisTestGroupSummary(**g) for g in outcome.groups],
        contingency_table=outcome.contingency_table,
        significant=outcome.significant,
        conclusion=outcome.conclusion,
    )


@app.post("/datasets/{dataset_id}/regression", response_model=RunRegressionOutput)
def run_regression(dataset_id: str, body: RegressionRequest) -> RunRegressionOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, [body.target, *body.features])

    outcome = regression_core.run_regression(dataset.df, body.target, body.features, body.model_type)

    return RunRegressionOutput(
        dataset_id=dataset.dataset_id,
        model_type=body.model_type,
        target=body.target,
        features=body.features,
        n_obs=outcome.n_obs,
        r_squared=outcome.r_squared,
        r_squared_label=outcome.r_squared_label,
        intercept=outcome.intercept,
        target_encoding=outcome.target_encoding,
        coefficients=[FeatureCoefficient(**asdict(c)) for c in outcome.coefficients],
        multicollinearity_warnings=outcome.multicollinearity_warnings,
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/forecast", response_model=ForecastTimeseriesOutput)
def forecast_timeseries(dataset_id: str, body: ForecastRequest) -> ForecastTimeseriesOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, [body.date_column, body.value_column])

    outcome = forecasting_core.run_forecast(
        dataset.df, body.date_column, body.value_column, body.periods, body.method, dataset.dataset_id
    )

    return ForecastTimeseriesOutput(
        dataset_id=dataset.dataset_id,
        date_column=body.date_column,
        value_column=body.value_column,
        periods=body.periods,
        method_used=outcome.method_used,
        method_reason=outcome.method_reason,
        inferred_frequency=outcome.inferred_frequency,
        history_length=outcome.history_length,
        confidence_level=outcome.confidence_level,
        forecast=[ForecastPoint(**asdict(p)) for p in outcome.points],
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/segmentation", response_model=RunSegmentationOutput)
def run_segmentation(dataset_id: str, body: SegmentationRequest) -> RunSegmentationOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, body.columns)

    outcome = segmentation_core.run_segmentation(dataset.df, body.columns, body.method, body.n_clusters, dataset.dataset_id)

    return RunSegmentationOutput(
        dataset_id=dataset.dataset_id,
        method_used=outcome.method_used,
        method_reason=outcome.method_reason,
        columns=body.columns,
        n_rows_segmented=outcome.n_rows_used,
        n_rows_excluded=outcome.n_rows_excluded,
        segments=[SegmentSummary(**asdict(g)) for g in outcome.segments],
        row_assignments=[SegmentRowAssignment(**asdict(r)) for r in outcome.row_assignments],
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/decision-tree", response_model=RunDecisionTreeOutput)
def run_decision_tree(dataset_id: str, body: DecisionTreeRequest) -> RunDecisionTreeOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, [body.target, *body.features])

    outcome = predictive_core.fit_decision_tree(dataset.df, body.target, body.features, body.task_type)

    return RunDecisionTreeOutput(
        dataset_id=dataset.dataset_id,
        target=body.target,
        features=body.features,
        task_type_used=outcome.task_type_used,
        method_reason=outcome.method_reason,
        n_obs=outcome.n_obs,
        metric_label=outcome.metric_label,
        metric_value=outcome.metric_value,
        secondary_metric_label=outcome.secondary_metric_label,
        secondary_metric_value=outcome.secondary_metric_value,
        feature_importances=[FeatureImportance(**asdict(f)) for f in outcome.feature_importances],
        tree_summary=outcome.tree_summary,
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/random-forest", response_model=RunRandomForestOutput)
def run_random_forest(dataset_id: str, body: RandomForestRequest) -> RunRandomForestOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, [body.target, *body.features])

    outcome = predictive_core.fit_random_forest(dataset.df, body.target, body.features, body.task_type)

    return RunRandomForestOutput(
        dataset_id=dataset.dataset_id,
        target=body.target,
        features=body.features,
        task_type_used=outcome.task_type_used,
        method_reason=outcome.method_reason,
        n_obs=outcome.n_obs,
        metric_label=outcome.metric_label,
        metric_value=outcome.metric_value,
        secondary_metric_label=outcome.secondary_metric_label,
        secondary_metric_value=outcome.secondary_metric_value,
        feature_importances=[FeatureImportance(**asdict(f)) for f in outcome.feature_importances],
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/gradient-boosting", response_model=RunGradientBoostingOutput)
def run_gradient_boosting(dataset_id: str, body: GradientBoostingRequest) -> RunGradientBoostingOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, [body.target, *body.features])

    outcome = predictive_core.fit_gradient_boosting(dataset.df, body.target, body.features, body.task_type)

    return RunGradientBoostingOutput(
        dataset_id=dataset.dataset_id,
        target=body.target,
        features=body.features,
        task_type_used=outcome.task_type_used,
        method_reason=outcome.method_reason,
        n_obs=outcome.n_obs,
        metric_label=outcome.metric_label,
        metric_value=outcome.metric_value,
        secondary_metric_label=outcome.secondary_metric_label,
        secondary_metric_value=outcome.secondary_metric_value,
        feature_importances=[FeatureImportance(**asdict(f)) for f in outcome.feature_importances],
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/automl", response_model=RunAutoMLOutput)
def run_automl(dataset_id: str, body: AutoMLRequest) -> RunAutoMLOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, [body.target, *body.features])

    outcome = predictive_core.run_automl(dataset.df, body.target, body.features, body.task_type)

    return RunAutoMLOutput(
        dataset_id=dataset.dataset_id,
        target=body.target,
        features=body.features,
        task_type_used=outcome.task_type_used,
        method_reason=outcome.method_reason,
        n_obs=outcome.n_obs,
        metric_label=outcome.metric_label,
        results=[ModelComparisonResult(**asdict(r)) for r in outcome.results],
        best_model=outcome.best_model,
        best_score=outcome.best_score,
        summary=outcome.summary,
    )


@app.post("/datasets/{dataset_id}/chart", response_model=GenerateChartOutput)
def generate_chart(dataset_id: str, body: ChartRequest) -> GenerateChartOutput:
    dataset = store.get(dataset_id)
    store.require_columns(dataset, body.columns)

    result = charts_core.generate_chart(dataset.dataset_id, body.chart_type, body.columns, dataset.df)

    return GenerateChartOutput(
        dataset_id=dataset.dataset_id,
        chart_type=body.chart_type,
        columns=body.columns,
        title=result.title,
        chart_path=result.chart_path,
        image_base64=result.image_base64,
        summary=result.summary,
    )


@app.post("/reports", response_model=ExportReportOutput)
def export_report(body: ReportRequest) -> ExportReportOutput:
    dataset = store.get(body.dataset_id)

    stem = body.report_name or reports_core.default_stem(dataset.dataset_id)
    sections = [
        reports_core.ReportSection(
            title=a.title,
            data=a.data,
            chart_path=a.chart_path,
            chart_image_base64=a.chart_image_base64,
            allow_generated_chart=a.allow_generated_chart,
            full_tables=a.full_tables,
            analysis_id=a.analysis_id,
            note=a.note,
            columns=a.columns,
            timestamp=a.timestamp,
        )
        for a in body.analyses
    ]
    meta = reports_core.ReportMeta(
        dataset_id=dataset.dataset_id,
        source=dataset.source,
        row_count=len(dataset.df),
        column_count=len(dataset.df.columns),
        decimals=body.decimals,
        prepared_by=(body.prepared_by or "").strip(),
    )
    paths = reports_core.build_report(meta, body.format, sections, stem)
    summary_text = reports_core.summarize_export(dataset.dataset_id, [a.title for a in body.analyses], paths)

    return ExportReportOutput(
        dataset_id=dataset.dataset_id,
        format=body.format,
        files=[str(p) for p in paths],
        sections_included=[a.title for a in body.analyses],
        summary=summary_text,
    )


# ---------------------------------------------------------------------------
# static frontend (mounted last so it never shadows the API routes above)
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
