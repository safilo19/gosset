"""Pydantic input/output models for the Phase 1 tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# load_dataset
# ---------------------------------------------------------------------------


class LoadDatasetInput(BaseModel):
    source: str = Field(
        ...,
        description=(
            "Path to a local CSV or .xlsx file, or a public Google Sheets share URL "
            "(the sheet must be shared as 'Anyone with the link can view')."
        ),
        examples=[
            "C:/data/sample_data.csv",
            "https://docs.google.com/spreadsheets/d/1AbCDeFGhijKLmnoPQRstuv/edit#gid=0",
        ],
    )
    source_type: Literal["csv", "xlsx", "gsheet"] = Field(
        ...,
        description="Type of the data source: 'csv', 'xlsx' (Excel), or 'gsheet' (public Google Sheets link).",
        examples=["csv"],
    )
    sheet_name: str | None = Field(
        None,
        description="Optional sheet name to read from an Excel workbook. Ignored for csv/gsheet. Defaults to the first sheet.",
        examples=["Sheet1"],
    )

    @field_validator("source", "sheet_name")
    @classmethod
    def _strip_whitespace(cls, value: str | None) -> str | None:
        # Guards against stray leading/trailing spaces (incl. non-breaking spaces from copy-paste).
        return value.strip() if value is not None else value


class ColumnInfo(BaseModel):
    name: str
    dtype: str


class LoadDatasetOutput(BaseModel):
    dataset_id: str = Field(..., description="Generated ID to reference this dataset in later tool calls, e.g. 'ds_1'.")
    source: str
    source_type: str
    row_count: int
    columns: list[ColumnInfo]
    preview: list[dict[str, Any]] = Field(..., description="Up to the first 5 rows, as JSON-safe records.")


# ---------------------------------------------------------------------------
# list_datasets
# ---------------------------------------------------------------------------


class DatasetSummary(BaseModel):
    dataset_id: str
    source: str
    source_type: str
    row_count: int
    column_count: int
    columns: list[str]


class ListDatasetsOutput(BaseModel):
    datasets: list[DatasetSummary]


# ---------------------------------------------------------------------------
# describe_dataset
# ---------------------------------------------------------------------------


class DescribeDatasetInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    columns: list[str] | None = Field(
        None,
        description="Optional subset of column names to describe. Defaults to all columns.",
        examples=[["units", "revenue"]],
    )


class ColumnStats(BaseModel):
    column: str
    dtype: str
    count: int = Field(..., description="Number of non-missing values.")
    missing: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | str | None = None
    max: float | str | None = None


class DescribeDatasetOutput(BaseModel):
    dataset_id: str
    stats: list[ColumnStats]


# ---------------------------------------------------------------------------
# compute_correlation
# ---------------------------------------------------------------------------


class ComputeCorrelationInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    columns: list[str] = Field(
        ...,
        min_length=2,
        description="At least two numeric column names to correlate.",
        examples=[["units", "revenue"]],
    )
    method: Literal["pearson", "spearman"] = Field(
        "pearson",
        description="Correlation method: 'pearson' for linear relationships, 'spearman' for monotonic/rank relationships.",
    )


class CorrelationPair(BaseModel):
    column_a: str
    column_b: str
    correlation: float
    strength: str = Field(..., description="Plain-language strength label, e.g. 'strong positive'.")


class ComputeCorrelationOutput(BaseModel):
    dataset_id: str
    method: str
    columns: list[str]
    matrix: dict[str, dict[str, float | None]]
    strongest_pairs: list[CorrelationPair]
    interpretation: str = Field(..., description="Plain-language note on the strongest relationships found.")


# ---------------------------------------------------------------------------
# run_hypothesis_test (Phase 2)
# ---------------------------------------------------------------------------


class RunHypothesisTestInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    test_type: Literal["t_test", "chi_square", "anova"] = Field(
        ...,
        description=(
            "Which test to run: 't_test' (two-sample, numeric vs. a 2-group column), "
            "'anova' (one-way, numeric vs. a 3+-group column), or "
            "'chi_square' (independence between two categorical columns)."
        ),
    )
    columns: list[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description=(
            "Exactly two columns. For t_test/anova: [numeric value column, categorical group column]. "
            "For chi_square: [categorical column A, categorical column B]."
        ),
        examples=[["revenue", "region"]],
    )
    alpha: float = Field(0.05, gt=0, lt=1, description="Significance threshold used for the conclusion. Default 0.05.")


class HypothesisTestGroupSummary(BaseModel):
    group: str
    count: int
    mean: float | None = None


class RunHypothesisTestOutput(BaseModel):
    dataset_id: str
    test_type: str
    columns: list[str]
    alpha: float
    statistic: float
    p_value: float
    degrees_of_freedom: float | None = Field(None, description="Single dof value; used for t_test and chi_square.")
    df_between: int | None = Field(None, description="ANOVA between-groups degrees of freedom.")
    df_within: int | None = Field(None, description="ANOVA within-groups degrees of freedom.")
    groups: list[HypothesisTestGroupSummary] = Field(default_factory=list, description="Per-group count/mean; used for t_test and anova.")
    contingency_table: dict[str, dict[str, int]] | None = Field(None, description="Cross-tab of counts; used for chi_square.")
    significant: bool
    conclusion: str = Field(..., description="Plain-language conclusion, e.g. 'statistically significant at α=0.05'.")


# ---------------------------------------------------------------------------
# run_regression (Phase 2)
# ---------------------------------------------------------------------------


class RunRegressionInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    target: str = Field(..., description="Numeric target column for linear regression, or binary column for logistic.")
    features: list[str] = Field(..., min_length=1, description="Numeric predictor columns.", examples=[["units", "discount"]])
    model_type: Literal["linear", "logistic"] = Field(
        "linear",
        description="'linear' for a continuous numeric target (OLS), 'logistic' for a binary target (Logit).",
    )


class FeatureCoefficient(BaseModel):
    feature: str
    coefficient: float
    std_err: float
    p_value: float
    significant: bool = Field(..., description="True if p_value < 0.05.")
    vif: float | None = Field(None, description="Variance inflation factor; None if fewer than 2 features.")
    multicollinearity_flag: str | None = Field(None, description="'moderate concern' (VIF>5), 'high concern' (VIF>10), or None.")


class RunRegressionOutput(BaseModel):
    dataset_id: str
    model_type: str
    target: str
    features: list[str]
    n_obs: int
    r_squared: float
    r_squared_label: str = Field(..., description="'R²' for linear, 'Pseudo R² (McFadden)' for logistic.")
    intercept: float
    target_encoding: dict[str, int] | None = Field(None, description="How a non-numeric logistic target was mapped to 0/1.")
    coefficients: list[FeatureCoefficient]
    multicollinearity_warnings: list[str]
    summary: str = Field(..., description="Plain-language read of which features matter and any multicollinearity concerns.")


# ---------------------------------------------------------------------------
# forecast_timeseries (Phase 2)
# ---------------------------------------------------------------------------


class ForecastTimeseriesInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    date_column: str = Field(..., description="Column containing dates/timestamps (parseable by pandas).", examples=["month"])
    value_column: str = Field(..., description="Numeric column to forecast.", examples=["revenue"])
    periods: int = Field(..., ge=1, le=365, description="Number of future periods to forecast.")
    method: Literal["exponential_smoothing", "arima", "auto"] = Field(
        "auto",
        description="Forecasting method. 'auto' inspects the series (length/trend/seasonality) and picks one.",
    )


class ForecastPoint(BaseModel):
    period: str = Field(..., description="Label for the forecasted period (ISO date or timestamp).")
    forecast: float
    lower_ci: float | None = None
    upper_ci: float | None = None


class ForecastTimeseriesOutput(BaseModel):
    dataset_id: str
    date_column: str
    value_column: str
    periods: int
    method_used: Literal["exponential_smoothing", "arima"]
    method_reason: str = Field(..., description="Plain-language reason auto-selection (or the requested method) was used.")
    inferred_frequency: str | None
    history_length: int
    confidence_level: float
    forecast: list[ForecastPoint]
    summary: str


# ---------------------------------------------------------------------------
# run_segmentation (Phase 3)
# ---------------------------------------------------------------------------


class RunSegmentationInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    columns: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Columns to segment on. For RFM: exactly 3 columns representing recency (a date-like column), "
            "frequency (a count-like column), and monetary (a spend-like column) — roles are auto-detected from "
            "column names/dtypes. For kmeans: any number of numeric feature columns."
        ),
        examples=[["last_purchase_date", "order_count", "total_spent"]],
    )
    method: Literal["kmeans", "rfm", "auto"] = Field(
        "auto",
        description="'auto' detects RFM-style columns and picks rfm or kmeans accordingly; or force one explicitly.",
    )
    n_clusters: int = Field(3, ge=2, le=10, description="Number of clusters for kmeans. Ignored for rfm.")


class SegmentSummary(BaseModel):
    segment: str
    size: int
    mean_values: dict[str, float]
    profile: str = Field(..., description="Plain-language description of this segment.")


class SegmentRowAssignment(BaseModel):
    row_index: int
    segment: str


class RunSegmentationOutput(BaseModel):
    dataset_id: str
    method_used: Literal["kmeans", "rfm"]
    method_reason: str = Field(..., description="Plain-language reason auto-selection (or the requested method) was used.")
    columns: list[str]
    n_rows_segmented: int
    n_rows_excluded: int = Field(..., description="Rows dropped for missing values in the segmentation columns.")
    segments: list[SegmentSummary]
    row_assignments: list[SegmentRowAssignment]
    summary: str


# ---------------------------------------------------------------------------
# generate_chart (Phase 3)
# ---------------------------------------------------------------------------


class GenerateChartInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    chart_type: Literal["bar", "line", "scatter", "histogram", "heatmap"] = Field(
        ..., description="Kind of chart to generate."
    )
    columns: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Columns to plot. 'histogram' needs 1 numeric column. 'bar'/'line'/'scatter' need exactly 2 "
            "columns [x, y]. 'heatmap' needs 2+ numeric columns for a correlation matrix."
        ),
        examples=[["units", "revenue"]],
    )


class GenerateChartOutput(BaseModel):
    dataset_id: str
    chart_type: str
    columns: list[str]
    title: str
    chart_path: str = Field(..., description="Absolute path to the saved PNG file; reusable by export_report.")
    image_base64: str = Field(..., description="Base64-encoded PNG image data (no data URI prefix).")
    summary: str


# ---------------------------------------------------------------------------
# export_report (Phase 3)
# ---------------------------------------------------------------------------


class AnalysisToInclude(BaseModel):
    title: str = Field(
        ..., description="Section heading for this analysis in the report (also used as the xlsx sheet name).",
        examples=["Revenue vs Units Correlation"],
    )
    data: dict[str, Any] = Field(
        ...,
        description=(
            "The structuredContent JSON previously returned by another tool call this session "
            "(e.g. compute_correlation's or run_regression's output)."
        ),
    )
    allow_generated_chart: bool = Field(
        True,
        description=(
            "Whether the report may render a chart from `data` when no chart image is supplied. "
            "Set False when this section is a single output block, so a table exports as a table only."
        ),
    )
    full_tables: bool = Field(
        False,
        description=(
            "Whether a long table in this section exports in full. Off by default: a document truncates "
            "past ~25 rows and notes how many were left out, so one long table cannot bury the findings "
            "after it across several pages. Set True to include every row deliberately."
        ),
    )
    chart_path: str | None = Field(
        None, description="Optional chart_path from a prior generate_chart call, to embed alongside this section."
    )
    chart_image_base64: str | None = Field(
        None,
        description=(
            "Optional PNG (data URL or bare base64) of the chart as it was rendered on screen. Takes precedence "
            "over chart_path, and lets any chart type appear in a report without a server-side renderer."
        ),
    )
    analysis_id: str = Field(
        "",
        description=(
            "Which analysis produced this section (e.g. 'normality', 'fit_model'). The report engine uses it to "
            "decide a verdict badge's polarity: a significant NORMALITY test is bad news, a significant t-test is "
            "a finding, and the same p-value cannot say both without knowing the test."
        ),
    )
    note: str = Field(
        "",
        description=(
            "Commentary written by the user in the Report pane rather than produced by an analysis. A section with "
            "a note renders as prose between the result cards and gets no heading, badge or table."
        ),
    )
    columns: str = Field("", description="The input columns, for the card's metadata line (e.g. 'yield_kg, machine').")
    timestamp: str = Field("", description="When the analysis was run, already formatted for display.")


class ExportReportInput(BaseModel):
    dataset_id: str = Field(..., description="ID of the dataset these analyses relate to (used for labeling only).", examples=["ds_1"])
    format: Literal["xlsx", "markdown", "docx", "pdf", "both"] = Field(
        "both", description="Output format to generate: a single format, or 'both' for markdown + xlsx."
    )
    analyses: list[AnalysisToInclude] = Field(..., min_length=1, description="Prior analysis results to include, in order.")
    report_name: str | None = Field(
        None, description="Optional base filename (without extension). Defaults to an auto-generated name."
    )
    decimals: int = Field(3, ge=0, le=8, description="Decimal places used for fractional numbers in tables.")


class ExportReportOutput(BaseModel):
    dataset_id: str
    format: str
    files: list[str] = Field(..., description="Absolute paths to the generated report file(s), under the project's output/ folder.")
    sections_included: list[str]
    summary: str


# ---------------------------------------------------------------------------
# get_graph_data
# ---------------------------------------------------------------------------


class GetGraphDataInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a loaded dataset.", examples=["ds_1"])
    graph_type: str = Field(
        ...,
        description=(
            "Which graph's data to compute: scatter, bubble, line, area, bar, pie, time_series, histogram, boxplot, "
            "heatmap, correlogram, binned_scatter, dotplot, individual_value, interval, ecdf, probability, "
            "distribution, stem_leaf, matrix_plot, marginal, parallel_coords, contour, surface, scatter3d."
        ),
        examples=["histogram"],
    )
    columns: list[str] = Field(default_factory=list, description="Columns the graph needs, in the order it expects them (e.g. [x, y]).")
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-graph settings, e.g. {'bin_width': 100} for histogram, {'group_column': 'region'} for boxplot, or distribution parameters.",
    )


class GetGraphDataOutput(BaseModel):
    dataset_id: str
    graph_type: str
    data: dict[str, Any] = Field(..., description="The computed series for that graph (binning, five-number stats, quantiles, grids, ...).")
    summary: str


# ---------------------------------------------------------------------------
# run_decision_tree (Phase 6 — Predictive Analytics)
# ---------------------------------------------------------------------------


class RunDecisionTreeInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    target: str = Field(..., description="Column to predict.", examples=["revenue"])
    features: list[str] = Field(..., min_length=1, description="Numeric predictor columns.", examples=[["units", "discount_pct"]])
    task_type: Literal["classification", "regression", "auto"] = Field(
        "auto", description="'auto' inspects the target's dtype/cardinality and picks classification or regression."
    )


class FeatureImportance(BaseModel):
    feature: str
    importance: float


class RunDecisionTreeOutput(BaseModel):
    dataset_id: str
    target: str
    features: list[str]
    task_type_used: Literal["classification", "regression"]
    method_reason: str = Field(..., description="Plain-language reason auto-selection (or the requested task_type) was used.")
    n_obs: int
    metric_label: str = Field(..., description="'Accuracy' for classification, 'R²' for regression.")
    metric_value: float
    secondary_metric_label: str = Field(..., description="'F1 (weighted)' for classification, 'RMSE' for regression.")
    secondary_metric_value: float
    feature_importances: list[FeatureImportance]
    tree_summary: str | None = Field(None, description="Plain-text view of the top 2 levels of splits (sklearn's export_text).")
    summary: str


# ---------------------------------------------------------------------------
# run_random_forest (Phase 6 — Predictive Analytics)
# ---------------------------------------------------------------------------


class RunRandomForestInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    target: str = Field(..., description="Column to predict.", examples=["revenue"])
    features: list[str] = Field(..., min_length=1, description="Numeric predictor columns.", examples=[["units", "discount_pct"]])
    task_type: Literal["classification", "regression", "auto"] = Field(
        "auto", description="'auto' inspects the target's dtype/cardinality and picks classification or regression."
    )


class RunRandomForestOutput(BaseModel):
    dataset_id: str
    target: str
    features: list[str]
    task_type_used: Literal["classification", "regression"]
    method_reason: str = Field(..., description="Plain-language reason auto-selection (or the requested task_type) was used.")
    n_obs: int
    metric_label: str = Field(..., description="'Accuracy' for classification, 'R²' for regression.")
    metric_value: float
    secondary_metric_label: str = Field(..., description="'F1 (weighted)' for classification, 'RMSE' for regression.")
    secondary_metric_value: float
    feature_importances: list[FeatureImportance]
    summary: str


# ---------------------------------------------------------------------------
# run_gradient_boosting (Phase 6 — Predictive Analytics)
# ---------------------------------------------------------------------------


class RunGradientBoostingInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    target: str = Field(..., description="Column to predict.", examples=["revenue"])
    features: list[str] = Field(..., min_length=1, description="Numeric predictor columns.", examples=[["units", "discount_pct"]])
    task_type: Literal["classification", "regression", "auto"] = Field(
        "auto", description="'auto' inspects the target's dtype/cardinality and picks classification or regression."
    )


class RunGradientBoostingOutput(BaseModel):
    dataset_id: str
    target: str
    features: list[str]
    task_type_used: Literal["classification", "regression"]
    method_reason: str = Field(..., description="Plain-language reason auto-selection (or the requested task_type) was used.")
    n_obs: int
    metric_label: str = Field(..., description="'Accuracy' for classification, 'R²' for regression.")
    metric_value: float
    secondary_metric_label: str = Field(..., description="'F1 (weighted)' for classification, 'RMSE' for regression.")
    secondary_metric_value: float
    feature_importances: list[FeatureImportance]
    summary: str


# ---------------------------------------------------------------------------
# run_automl (Phase 6 — Predictive Analytics)
# ---------------------------------------------------------------------------


class RunAutoMLInput(BaseModel):
    dataset_id: str = Field(..., description="ID of a previously loaded dataset, e.g. 'ds_1'.", examples=["ds_1"])
    target: str = Field(..., description="Column to predict.", examples=["revenue"])
    features: list[str] = Field(..., min_length=1, description="Numeric predictor columns.", examples=[["units", "discount_pct"]])
    task_type: Literal["classification", "regression", "auto"] = Field(
        "auto", description="'auto' inspects the target's dtype/cardinality and picks classification or regression."
    )


class ModelComparisonResult(BaseModel):
    model: str
    score: float


class RunAutoMLOutput(BaseModel):
    dataset_id: str
    target: str
    features: list[str]
    task_type_used: Literal["classification", "regression"]
    method_reason: str = Field(..., description="Plain-language reason auto-selection (or the requested task_type) was used.")
    n_obs: int
    metric_label: str = Field(..., description="'Accuracy' for classification, 'R²' for regression — same metric for every model tried.")
    results: list[ModelComparisonResult] = Field(..., description="Every applicable model tried, ranked best-first by cross-validated score.")
    best_model: str
    best_score: float
    summary: str = Field(..., description="Plain-language recommendation of the best model and why.")
