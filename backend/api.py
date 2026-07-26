"""REST API mirroring the 10 MCP tools, for the upcoming React frontend.

Same analysis logic as the MCP server (both import from backend/core/), different interface.
This API has its own in-memory DatasetStore — it does NOT share state with the MCP server.

Run with: uvicorn backend.api:app --reload
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
    ForecastPoint,
    ForecastTimeseriesOutput,
    GenerateChartOutput,
    HypothesisTestGroupSummary,
    ListDatasetsOutput,
    LoadDatasetOutput,
    RunHypothesisTestOutput,
    RunRegressionOutput,
    RunSegmentationOutput,
    SegmentRowAssignment,
    SegmentSummary,
)
from backend.core import charts as charts_core
from backend.core import datasets as datasets_core
from backend.core import forecasting as forecasting_core
from backend.core import regression as regression_core
from backend.core import reports as reports_core
from backend.core import segmentation as segmentation_core
from backend.core import stats as stats_core
from backend.core import tests as tests_core

# ---------------------------------------------------------------------------
# app + CORS
# ---------------------------------------------------------------------------

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
]

app = FastAPI(title="Personal Data Analysis & BI Toolkit API")

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


@app.exception_handler(datasets_core.DatasetNotFoundError)
def _handle_dataset_not_found(request: Request, exc: datasets_core.DatasetNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(datasets_core.ColumnNotFoundError)
def _handle_column_not_found(request: Request, exc: datasets_core.ColumnNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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


class ChartRequest(BaseModel):
    chart_type: Literal["bar", "line", "scatter", "histogram", "heatmap"]
    columns: list[str] = Field(..., min_length=1)


class ReportRequest(BaseModel):
    dataset_id: str
    format: Literal["xlsx", "markdown", "both"] = "both"
    analyses: list[AnalysisToInclude] = Field(..., min_length=1)
    report_name: str | None = None


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
    sections = [reports_core.ReportSection(title=a.title, data=a.data, chart_path=a.chart_path) for a in body.analyses]
    paths = reports_core.build_report(dataset.dataset_id, body.format, sections, stem)
    summary_text = reports_core.summarize_export(dataset.dataset_id, [a.title for a in body.analyses], paths)

    return ExportReportOutput(
        dataset_id=dataset.dataset_id,
        format=body.format,
        files=[str(p) for p in paths],
        sections_included=[a.title for a in body.analyses],
        summary=summary_text,
    )
