"""MCP tool wrappers for all 3 phases.

Each function here only: parses the MCP Pydantic input, calls the relevant backend.core
function for the actual analysis, and formats the result as an MCP CallToolResult. All
analysis logic lives in backend/core/ and is shared with the REST API (backend/api.py).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from backend.core import charts as charts_core
from backend.core import datasets as datasets_core
from backend.core import forecasting as forecasting_core
from backend.core import graphs as graphs_core
from backend.core import predictive as predictive_core
from backend.core import regression as regression_core
from backend.core import reports as reports_core
from backend.core import segmentation as segmentation_core
from backend.core import stats as stats_core
from backend.core import tests as tests_core

from .app import mcp
from .models import (
    ColumnInfo,
    ColumnStats,
    ComputeCorrelationInput,
    ComputeCorrelationOutput,
    CorrelationPair,
    DatasetSummary,
    DescribeDatasetInput,
    DescribeDatasetOutput,
    ExportReportInput,
    GetGraphDataInput,
    GetGraphDataOutput,
    ExportReportOutput,
    FeatureCoefficient,
    FeatureImportance,
    ForecastPoint,
    ForecastTimeseriesInput,
    ForecastTimeseriesOutput,
    GenerateChartInput,
    GenerateChartOutput,
    HypothesisTestGroupSummary,
    ListDatasetsOutput,
    LoadDatasetInput,
    LoadDatasetOutput,
    ModelComparisonResult,
    RunAutoMLInput,
    RunAutoMLOutput,
    RunDecisionTreeInput,
    RunDecisionTreeOutput,
    RunGradientBoostingInput,
    RunGradientBoostingOutput,
    RunHypothesisTestInput,
    RunHypothesisTestOutput,
    RunRandomForestInput,
    RunRandomForestOutput,
    RunRegressionInput,
    RunRegressionOutput,
    RunSegmentationInput,
    RunSegmentationOutput,
    SegmentRowAssignment,
    SegmentSummary,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True)
WRITES_FILES = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

store = datasets_core.DatasetStore()


def _text(*lines: str) -> list[TextContent]:
    return [TextContent(type="text", text="\n".join(lines))]


@mcp.tool(annotations=READ_ONLY)
def load_dataset(input: LoadDatasetInput) -> Annotated[CallToolResult, LoadDatasetOutput]:
    """Load a CSV, .xlsx, or public Google Sheets link into an in-memory DataFrame and cache it under a new dataset_id."""
    df = datasets_core.load_dataframe(input.source, input.source_type, input.sheet_name)
    dataset = store.add(df, source=input.source, source_type=input.source_type)
    load_summary = datasets_core.summarize_load(dataset)

    output = LoadDatasetOutput(
        dataset_id=dataset.dataset_id,
        source=input.source,
        source_type=input.source_type,
        row_count=load_summary.row_count,
        columns=[ColumnInfo(**c) for c in load_summary.columns],
        preview=load_summary.preview,
    )

    col_list = ", ".join(c.name for c in output.columns)
    content_text = _text(
        f"Loaded dataset '{dataset.dataset_id}' from {input.source} ({input.source_type}).",
        f"{output.row_count} rows, {len(output.columns)} columns: {col_list}.",
        f"Preview of the first {len(output.preview)} row(s) is in structuredContent.",
    )
    return CallToolResult(content=content_text, structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def list_datasets() -> Annotated[CallToolResult, ListDatasetsOutput]:
    """List all datasets currently cached in memory, with basic row/column metadata."""
    results, summary_text = datasets_core.summarize_all(store)
    output = ListDatasetsOutput(datasets=[DatasetSummary(**asdict(r)) for r in results])
    return CallToolResult(content=_text(summary_text), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def describe_dataset(input: DescribeDatasetInput) -> Annotated[CallToolResult, DescribeDatasetOutput]:
    """Return per-column summary statistics (mean/median/std/min/max/missing-count/dtype) for a loaded dataset."""
    dataset = store.get(input.dataset_id)
    columns = input.columns if input.columns is not None else list(dataset.df.columns)
    store.require_columns(dataset, columns)

    results = stats_core.describe_columns(dataset.df, columns)
    summary_text = stats_core.describe_summary(dataset.dataset_id, results)

    output = DescribeDatasetOutput(dataset_id=dataset.dataset_id, stats=[ColumnStats(**asdict(r)) for r in results])
    return CallToolResult(content=_text(summary_text), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def compute_correlation(input: ComputeCorrelationInput) -> Annotated[CallToolResult, ComputeCorrelationOutput]:
    """Compute a pearson/spearman correlation matrix across numeric columns and summarize the strongest relationships."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, input.columns)

    result = stats_core.compute_correlation(dataset.dataset_id, dataset.df, input.columns, input.method)

    output = ComputeCorrelationOutput(
        dataset_id=dataset.dataset_id,
        method=input.method,
        columns=input.columns,
        matrix=result.matrix,
        strongest_pairs=[CorrelationPair(**asdict(p)) for p in result.strongest_pairs],
        interpretation=result.interpretation,
    )
    return CallToolResult(content=_text(result.summary), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_hypothesis_test(input: RunHypothesisTestInput) -> Annotated[CallToolResult, RunHypothesisTestOutput]:
    """Run a t-test, one-way ANOVA, or chi-square test of independence and report significance in plain language."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, input.columns)

    outcome = tests_core.run_hypothesis_test(dataset.df, input.test_type, input.columns, input.alpha)

    output = RunHypothesisTestOutput(
        dataset_id=dataset.dataset_id,
        test_type=input.test_type,
        columns=input.columns,
        alpha=input.alpha,
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

    content_text = _text(
        f"Ran {input.test_type} on dataset '{dataset.dataset_id}' (columns: {', '.join(input.columns)}).",
        f"statistic={outcome.statistic:.4g}, p={outcome.p_value:.4g}.",
        outcome.conclusion,
    )
    return CallToolResult(content=content_text, structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_regression(input: RunRegressionInput) -> Annotated[CallToolResult, RunRegressionOutput]:
    """Fit a linear (OLS) or logistic regression, with per-feature p-values and VIF-based multicollinearity checks."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, [input.target, *input.features])

    outcome = regression_core.run_regression(dataset.df, input.target, input.features, input.model_type)

    output = RunRegressionOutput(
        dataset_id=dataset.dataset_id,
        model_type=input.model_type,
        target=input.target,
        features=input.features,
        n_obs=outcome.n_obs,
        r_squared=outcome.r_squared,
        r_squared_label=outcome.r_squared_label,
        intercept=outcome.intercept,
        target_encoding=outcome.target_encoding,
        coefficients=[FeatureCoefficient(**asdict(c)) for c in outcome.coefficients],
        multicollinearity_warnings=outcome.multicollinearity_warnings,
        summary=outcome.summary,
    )
    return CallToolResult(content=_text(*outcome.content_lines), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def forecast_timeseries(input: ForecastTimeseriesInput) -> Annotated[CallToolResult, ForecastTimeseriesOutput]:
    """Forecast future values of a time series using exponential smoothing or ARIMA (or auto-select between them)."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, [input.date_column, input.value_column])

    outcome = forecasting_core.run_forecast(
        dataset.df, input.date_column, input.value_column, input.periods, input.method, dataset.dataset_id
    )

    output = ForecastTimeseriesOutput(
        dataset_id=dataset.dataset_id,
        date_column=input.date_column,
        value_column=input.value_column,
        periods=input.periods,
        method_used=outcome.method_used,
        method_reason=outcome.method_reason,
        inferred_frequency=outcome.inferred_frequency,
        history_length=outcome.history_length,
        confidence_level=outcome.confidence_level,
        forecast=[ForecastPoint(**asdict(p)) for p in outcome.points],
        summary=outcome.summary,
    )
    return CallToolResult(content=_text(*outcome.content_lines), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_segmentation(input: RunSegmentationInput) -> Annotated[CallToolResult, RunSegmentationOutput]:
    """Segment rows via RFM (recency/frequency/monetary) or K-means clustering, with a plain-language profile per segment."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, input.columns)

    outcome = segmentation_core.run_segmentation(
        dataset.df, input.columns, input.method, input.n_clusters, dataset.dataset_id
    )

    output = RunSegmentationOutput(
        dataset_id=dataset.dataset_id,
        method_used=outcome.method_used,
        method_reason=outcome.method_reason,
        columns=input.columns,
        n_rows_segmented=outcome.n_rows_used,
        n_rows_excluded=outcome.n_rows_excluded,
        segments=[SegmentSummary(**asdict(g)) for g in outcome.segments],
        row_assignments=[SegmentRowAssignment(**asdict(r)) for r in outcome.row_assignments],
        summary=outcome.summary,
    )
    return CallToolResult(content=_text(outcome.summary), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_decision_tree(input: RunDecisionTreeInput) -> Annotated[CallToolResult, RunDecisionTreeOutput]:
    """Fit a decision tree (classifier or regressor, auto-detected from the target) with cross-validated
    accuracy/F1 or R²/RMSE, ranked feature importances, and the top splits as plain text."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, [input.target, *input.features])

    outcome = predictive_core.fit_decision_tree(dataset.df, input.target, input.features, input.task_type)

    output = RunDecisionTreeOutput(
        dataset_id=dataset.dataset_id,
        target=input.target,
        features=input.features,
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
    return CallToolResult(content=_text(*outcome.content_lines), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_random_forest(input: RunRandomForestInput) -> Annotated[CallToolResult, RunRandomForestOutput]:
    """Fit a random forest (classifier or regressor, auto-detected from the target) with cross-validated
    accuracy/F1 or R²/RMSE and ranked feature importances."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, [input.target, *input.features])

    outcome = predictive_core.fit_random_forest(dataset.df, input.target, input.features, input.task_type)

    output = RunRandomForestOutput(
        dataset_id=dataset.dataset_id,
        target=input.target,
        features=input.features,
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
    return CallToolResult(content=_text(*outcome.content_lines), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_gradient_boosting(input: RunGradientBoostingInput) -> Annotated[CallToolResult, RunGradientBoostingOutput]:
    """Fit a gradient boosting model (classifier or regressor, auto-detected from the target) with cross-validated
    accuracy/F1 or R²/RMSE and ranked feature importances."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, [input.target, *input.features])

    outcome = predictive_core.fit_gradient_boosting(dataset.df, input.target, input.features, input.task_type)

    output = RunGradientBoostingOutput(
        dataset_id=dataset.dataset_id,
        target=input.target,
        features=input.features,
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
    return CallToolResult(content=_text(*outcome.content_lines), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def run_automl(input: RunAutoMLInput) -> Annotated[CallToolResult, RunAutoMLOutput]:
    """Cross-validate every applicable model for the task (linear/logistic regression, decision tree, random
    forest, gradient boosting), rank them by mean score, and recommend the best one with a plain-language reason."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, [input.target, *input.features])

    outcome = predictive_core.run_automl(dataset.df, input.target, input.features, input.task_type)

    output = RunAutoMLOutput(
        dataset_id=dataset.dataset_id,
        target=input.target,
        features=input.features,
        task_type_used=outcome.task_type_used,
        method_reason=outcome.method_reason,
        n_obs=outcome.n_obs,
        metric_label=outcome.metric_label,
        results=[ModelComparisonResult(**asdict(r)) for r in outcome.results],
        best_model=outcome.best_model,
        best_score=outcome.best_score,
        summary=outcome.summary,
    )
    return CallToolResult(content=_text(*outcome.content_lines), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def generate_chart(input: GenerateChartInput) -> Annotated[CallToolResult, GenerateChartOutput]:
    """Generate a bar/line/scatter/histogram/heatmap chart (matplotlib) as a base64 PNG, saved to a temp file for reuse by export_report."""
    dataset = store.get(input.dataset_id)
    store.require_columns(dataset, input.columns)

    result = charts_core.generate_chart(dataset.dataset_id, input.chart_type, input.columns, dataset.df)

    output = GenerateChartOutput(
        dataset_id=dataset.dataset_id,
        chart_type=input.chart_type,
        columns=input.columns,
        title=result.title,
        chart_path=result.chart_path,
        image_base64=result.image_base64,
        summary=result.summary,
    )

    content = [
        TextContent(type="text", text=result.summary),
        ImageContent(type="image", data=result.image_base64, mimeType="image/png"),
    ]
    return CallToolResult(content=content, structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=READ_ONLY)
def get_graph_data(input: GetGraphDataInput) -> Annotated[CallToolResult, GetGraphDataOutput]:
    """Compute the series behind any of the app's graph types — histogram bins, boxplot five-number
    summaries, ECDF steps, normal-probability quantiles, distribution curves, correlation matrices,
    interpolated 3D grids, and so on. Read-only: it computes from a loaded dataset and returns
    numbers, drawing nothing itself."""
    dataset = store.get(input.dataset_id)
    data = graphs_core.compute(dataset.df, input.graph_type, input.columns, input.options)
    summary_text = (
        f"Computed {input.graph_type} data for dataset '{dataset.dataset_id}'"
        + (f" on {', '.join(input.columns)}" if input.columns else "")
        + f". Keys returned: {', '.join(sorted(data.keys()))}."
    )
    output = GetGraphDataOutput(dataset_id=dataset.dataset_id, graph_type=input.graph_type, data=data, summary=summary_text)
    return CallToolResult(content=_text(summary_text), structuredContent=output.model_dump(mode="json"))


@mcp.tool(annotations=WRITES_FILES)
def export_report(input: ExportReportInput) -> Annotated[CallToolResult, ExportReportOutput]:
    """Format prior analysis results (structuredContent from earlier tool calls) into a report under output/ —
    a formatted PDF, a Word .docx, an xlsx workbook, Markdown, or 'both' for markdown + xlsx. PDF and Word get
    a title block, real heading styles, shaded tables and an embedded chart per section. Writes files, so this
    is NOT read-only — but it's non-destructive: it only creates new report files and never modifies or deletes
    existing data."""
    dataset = store.get(input.dataset_id)

    stem = input.report_name or reports_core.default_stem(dataset.dataset_id)
    sections = [
        reports_core.ReportSection(
            title=a.title,
            data=a.data,
            chart_path=a.chart_path,
            chart_image_base64=a.chart_image_base64,
            analysis_id=a.analysis_id,
            note=a.note,
            columns=a.columns,
            timestamp=a.timestamp,
        )
        for a in input.analyses
    ]
    meta = reports_core.ReportMeta(
        dataset_id=dataset.dataset_id,
        source=dataset.source,
        row_count=len(dataset.df),
        column_count=len(dataset.df.columns),
        decimals=input.decimals,
    )
    paths = reports_core.build_report(meta, input.format, sections, stem)
    summary_text = reports_core.summarize_export(dataset.dataset_id, [a.title for a in input.analyses], paths)

    output = ExportReportOutput(
        dataset_id=dataset.dataset_id,
        format=input.format,
        files=[str(p) for p in paths],
        sections_included=[a.title for a in input.analyses],
        summary=summary_text,
    )
    return CallToolResult(content=_text(summary_text), structuredContent=output.model_dump(mode="json"))
