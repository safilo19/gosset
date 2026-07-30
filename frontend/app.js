// Plain DOM app. The worksheet is the base document layer (worksheet.js); every tool form and
// every analysis result opens as a floating window above it (windowManager.js). This file owns
// the menu bar, the global shortcuts, results, the assistant, and project save/open.

import { apiClient } from './apiClient.js';
import { ANALYSES, STAT_MENU, defaultValues, validateValues, buildParams, summarizeParams } from './analysisConfig.js';
import { GENERIC_HELP, buildHelpText, buildWelcome, columnListReply, datasetLabel, matchDataset, parseCommand } from './chatParser.js';
import * as wm from './windowManager.js';
import * as ws from './worksheet.js';
import * as dialogs from './dialogs.js';
import * as settings from './settings.js';
import * as themeMode from './themeMode.js';
import * as theme from './charts/theme.js';
import { applyThemeIn as applyPlotlyTheme, applyInteractivityToAll as applyPlotlyInteractivity, hasTrackedPlot } from './charts/plotly.js';
import * as graphs from './graphs.js';
import * as basicStats from './basicStats.js';
import * as regression from './regression.js';
import * as anova from './anova.js';
import * as calc from './calc.js';
import * as matrices from './matrices.js';
import * as dataMenu from './dataMenu.js';
import * as procedureDialog from './procedureDialog.js';
import * as menus from './menu.js';
import * as tabs from './worksheetTabs.js';
import * as constants from './constants.js';
import * as conditionalFormat from './conditionalFormat.js';
import * as iconGallery from './icons/gallery.js';
import * as menuHelp from './menuHelp.js';
import * as brand from './brand/brand.js';
import * as desktop from './desktopBridge.js';
import * as blockMenu from './blockMenu.js';
import * as blockCapture from './blockCapture.js';
import * as reportPane from './reportPane.js';
// The pieces of a result window that app.js and basicStats.js must render identically.
import { h, block, buildDataTable, buildStatGrid, buildTableBlock, buildTextBlock, countUp, formatCell, renderNumberInto } from './resultView.js';

const ANALYSIS_BY_ID = Object.fromEntries(ANALYSES.map((a) => [a.id, a]));
const ANALYSIS_LABEL_BY_ID = Object.fromEntries(ANALYSES.map((a) => [a.id, a.label]));

// The project extension. `.gsp` ("Gosset project") is what the desktop installer registers with
// Windows and what every new save uses; `.baproj` was the name before the app was called Gosset and
// is still ACCEPTED on the way in, so nobody's saved work becomes unopenable over a rename. The file
// format itself never changed — only the extension — so a legacy file needs no conversion.
const PROJECT_EXT = '.gsp';
const LEGACY_PROJECT_EXT = '.baproj';

// Mirrors reports.TABLE_ROW_LIMIT in the backend: the row count past which a document
// truncates a table. Only used to decide whether to OFFER the full-table staging — the backend
// remains the authority on what actually gets cut.
const REPORT_TABLE_ROW_LIMIT = 25;
const PROJECT_MARKER = 'personal-analytics-bi-project';
// v1 saved one worksheet; v2 added every open worksheet, which one was active, the stored constants
// and the conditional-formatting rules; v3 adds the Report pane's staged blocks (with their PNGs).
// An older file still opens — every reader below tolerates a missing key (see restoreProject).
const PROJECT_VERSION = 3;

// Chart styling lives in charts/theme.js — analysis-result charts and every Graph menu item share
// those defaults and that palette, so old and new charts read as one product. Those tokens are
// always read through the `theme.` namespace, never destructured into local constants: a copy
// taken at import time would keep painting light-theme colors after a switch to dark.
theme.applyDefaults();

const noMotion = () => settings.motionDisabled();

// Programmatically "clicks" a download link so the file saves immediately, instead of making
// the user find and click a link themselves. Whether the browser prompts for a save location
// or saves straight to the Downloads folder is a browser setting this page has no control over.
function triggerDownload(href, filename) {
  const a = h('a', { href, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function downloadTextFile(filename, text, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  triggerDownload(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function safeFileName(name) {
  return (name || 'project').trim().replace(/[^A-Za-z0-9._ -]+/g, '_').replace(/\s+/g, '_') || 'project';
}

// ---------------------------------------------------------------------------
// analysis dispatch
// ---------------------------------------------------------------------------

function runAnalysis(analysisId, datasetId, params) {
  switch (analysisId) {
    case 'describe':
      return apiClient.describe(datasetId, params.columns);
    case 'correlation':
      return apiClient.correlation(datasetId, params);
    case 'hypothesis':
      return apiClient.hypothesisTest(datasetId, params);
    case 'regression':
      return apiClient.regression(datasetId, params);
    case 'forecast':
      return apiClient.forecast(datasetId, params);
    case 'segmentation':
      return apiClient.segmentation(datasetId, params);
    case 'chart':
      return apiClient.chart(datasetId, params);
    case 'decision_tree':
      return apiClient.decisionTree(datasetId, params);
    case 'random_forest':
      return apiClient.randomForest(datasetId, params);
    case 'gradient_boosting':
      return apiClient.gradientBoosting(datasetId, params);
    case 'automl':
      return apiClient.automl(datasetId, params);
    default:
      throw new Error(`Unknown analysis: ${analysisId}`);
  }
}

// ---------------------------------------------------------------------------
// result rendering
// ---------------------------------------------------------------------------

const TABLE_KEYS_PRIORITY = [
  'coefficients',
  'forecast',
  'segments',
  'strongest_pairs',
  'stats',
  'groups',
  'datasets',
  'preview',
  'row_assignments',
  'feature_importances',
  'results',
];
const NARRATIVE_KEYS = ['conclusion', 'interpretation', 'summary', 'method_reason'];
const HIDE_SCALAR_KEYS = new Set(['image_base64', 'chart_path', ...NARRATIVE_KEYS]);

function extractTable(analysisId, data) {
  // Segmentation's mean_values is a nested dict per segment; flatten it so each mean shows
  // as its own column instead of one opaque JSON blob.
  if (analysisId === 'segmentation' && Array.isArray(data.segments) && data.segments.length) {
    const rows = data.segments.map((s) => ({ segment: s.segment, size: s.size, profile: s.profile, ...s.mean_values }));
    return { key: 'segments', rows };
  }
  for (const key of TABLE_KEYS_PRIORITY) {
    const value = data[key];
    if (Array.isArray(value) && value.length && value.every((v) => v && typeof v === 'object')) {
      return { key, rows: value };
    }
  }
  if (data.matrix && typeof data.matrix === 'object' && Object.keys(data.matrix).length) {
    const rows = Object.entries(data.matrix).map(([k, v]) => ({ column: k, ...v }));
    return { key: 'matrix', rows };
  }
  if (data.contingency_table && typeof data.contingency_table === 'object' && Object.keys(data.contingency_table).length) {
    const rows = Object.entries(data.contingency_table).map(([k, v]) => ({ '(row)': k, ...v }));
    return { key: 'contingency_table', rows };
  }
  return { key: null, rows: [] };
}

function buildHighlights(analysisId, data) {
  const d = settings.get().decimals;
  switch (analysisId) {
    case 'correlation': {
      const highlights = [];
      const top = data.strongest_pairs && data.strongest_pairs[0];
      if (top) {
        highlights.push({
          label: `${top.column_a} × ${top.column_b}`,
          value: top.correlation,
          decimals: d,
          tone: top.correlation >= 0 ? 'positive' : 'negative',
        });
      }
      if (Array.isArray(data.strongest_pairs)) {
        highlights.push({ label: 'Pairs compared', value: data.strongest_pairs.length, decimals: 0 });
      }
      return highlights;
    }
    case 'hypothesis': {
      const highlights = [
        { label: 'Test statistic', value: data.statistic, decimals: d },
        { label: 'P-value', value: data.p_value, decimals: d, tone: data.significant ? 'positive' : undefined },
      ];
      const dof = data.degrees_of_freedom ?? data.df_between;
      if (dof != null) highlights.push({ label: 'Degrees of freedom', value: dof, decimals: 0 });
      return highlights;
    }
    case 'regression':
      return [
        { label: data.r_squared_label || 'R²', value: data.r_squared, decimals: d },
        { label: 'Observations', value: data.n_obs, decimals: 0 },
        { label: 'Intercept', value: data.intercept, decimals: d },
      ];
    case 'forecast':
      return [
        { label: 'Periods forecasted', value: data.periods, decimals: 0 },
        { label: 'History length', value: data.history_length, decimals: 0 },
        { label: 'Confidence level', value: data.confidence_level * 100, decimals: 0, suffix: '%' },
      ];
    case 'segmentation':
      return [
        { label: 'Rows segmented', value: data.n_rows_segmented, decimals: 0 },
        { label: 'Rows excluded', value: data.n_rows_excluded, decimals: 0 },
        { label: 'Segments found', value: (data.segments || []).length, decimals: 0 },
      ];
    case 'decision_tree':
    case 'random_forest':
    case 'gradient_boosting':
      return [
        { label: data.metric_label || 'Score', value: data.metric_value, decimals: d, tone: 'positive' },
        { label: data.secondary_metric_label || 'Secondary', value: data.secondary_metric_value, decimals: d },
        { label: 'Observations', value: data.n_obs, decimals: 0 },
      ];
    case 'automl':
      return [
        { label: `Best: ${data.best_model}`, value: data.best_score, decimals: d, tone: 'positive' },
        { label: 'Models compared', value: (data.results || []).length, decimals: 0 },
        { label: 'Observations', value: data.n_obs, decimals: 0 },
      ];
    default:
      return [];
  }
}

function baseChartOptions() {
  return theme.baseOptions({});
}

function buildChartConfig(analysisId, data) {
  if (typeof Chart === 'undefined') return null;

  if (analysisId === 'correlation' && Array.isArray(data.strongest_pairs) && data.strongest_pairs.length) {
    const labels = data.strongest_pairs.map((p) => `${p.column_a} × ${p.column_b}`);
    const values = data.strongest_pairs.map((p) => p.correlation);
    const opts = baseChartOptions();
    opts.scales.y = { ...opts.scales.y, min: -1, max: 1 };
    return {
      type: 'bar',
      data: { labels, datasets: [{ data: values, backgroundColor: values.map((v) => (v >= 0 ? theme.SUCCESS : theme.DANGER)), maxBarThickness: 40 }] },
      options: opts,
    };
  }

  if (analysisId === 'hypothesis' && Array.isArray(data.groups) && data.groups.length) {
    const labels = data.groups.map((g) => g.group);
    const values = data.groups.map((g) => g.mean ?? 0);
    return {
      type: 'bar',
      data: { labels, datasets: [{ data: values, backgroundColor: theme.ACCENT, maxBarThickness: 48 }] },
      options: baseChartOptions(),
    };
  }

  if (analysisId === 'regression' && Array.isArray(data.coefficients) && data.coefficients.length) {
    const labels = data.coefficients.map((c) => c.feature);
    const values = data.coefficients.map((c) => c.coefficient);
    // Non-significant coefficients are drawn washed out — the reader should see at a glance
    // which effects the model actually supports.
    const colors = data.coefficients.map((c) => {
      const base = c.coefficient >= 0 ? theme.SUCCESS : theme.DANGER;
      return c.significant === false ? theme.alpha(base, 0.35) : base;
    });
    return {
      type: 'bar',
      data: { labels, datasets: [{ data: values, backgroundColor: colors, maxBarThickness: 40 }] },
      options: baseChartOptions(),
    };
  }

  if (analysisId === 'forecast' && Array.isArray(data.forecast) && data.forecast.length) {
    const labels = data.forecast.map((p) => p.period);
    const hasCI = data.forecast.every((p) => p.lower_ci != null && p.upper_ci != null);
    const datasets = [];
    if (hasCI) {
      datasets.push({
        label: 'Upper bound',
        data: data.forecast.map((p) => p.upper_ci),
        borderColor: theme.alpha(theme.ACCENT, 0.25),
        backgroundColor: theme.alpha(theme.ACCENT, 0.1),
        pointRadius: 0,
        borderWidth: 1,
        fill: '+1',
        tension: 0.3,
      });
      datasets.push({
        label: 'Lower bound',
        data: data.forecast.map((p) => p.lower_ci),
        borderColor: theme.alpha(theme.ACCENT, 0.25),
        pointRadius: 0,
        borderWidth: 1,
        fill: false,
        tension: 0.3,
      });
    }
    datasets.push({
      label: 'Forecast',
      data: data.forecast.map((p) => p.forecast),
      borderColor: theme.ACCENT,
      backgroundColor: theme.alpha(theme.ACCENT, 0.12),
      pointBackgroundColor: theme.ACCENT,
      pointRadius: 2.5,
      borderWidth: 2,
      tension: 0.3,
      fill: hasCI ? false : 'origin',
    });
    const opts = baseChartOptions();
    opts.plugins.legend = { display: true, labels: { color: theme.MUTED, boxWidth: 10, filter: (item) => item.text === 'Forecast' } };
    return { type: 'line', data: { labels, datasets }, options: opts };
  }

  if (analysisId === 'segmentation' && Array.isArray(data.segments) && data.segments.length) {
    const labels = data.segments.map((s) => s.segment);
    const values = data.segments.map((s) => s.size);
    return {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: labels.map((_, i) => theme.color(i)), borderColor: theme.SURFACE, borderWidth: 2 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: noMotion() ? 0 : 600, easing: 'easeOutQuart' },
        plugins: {
          legend: { position: 'right', labels: { color: theme.MUTED, boxWidth: 10 } },
          tooltip: baseChartOptions().plugins.tooltip,
        },
      },
    };
  }

  if (['decision_tree', 'random_forest', 'gradient_boosting'].includes(analysisId) && Array.isArray(data.feature_importances) && data.feature_importances.length) {
    const sorted = [...data.feature_importances].sort((a, b) => b.importance - a.importance);
    return {
      type: 'bar',
      data: { labels: sorted.map((f) => f.feature), datasets: [{ data: sorted.map((f) => f.importance), backgroundColor: theme.ACCENT, maxBarThickness: 40 }] },
      options: baseChartOptions(),
    };
  }

  if (analysisId === 'automl' && Array.isArray(data.results) && data.results.length) {
    const sorted = [...data.results].sort((a, b) => b.score - a.score);
    return {
      type: 'bar',
      data: {
        labels: sorted.map((r) => r.model),
        datasets: [{ data: sorted.map((r) => r.score), backgroundColor: sorted.map((r) => (r.model === data.best_model ? theme.SUCCESS : theme.ACCENT)), maxBarThickness: 48 }],
      },
      options: baseChartOptions(),
    };
  }

  return null;
}

function mountChart(container, config, compact, onCapture) {
  if (!config) return;
  const height = config.type === 'doughnut' ? 230 : 250;
  theme.mountChart(container, config, { compact, height, onCapture });
}

function renderResultBody(container, analysisId, data, { hideNarrative = false, compact = false, onCapture } = {}) {
  if (!data) return;

  if (data.files) {
    const summaryBlock = hideNarrative ? null : buildTextBlock(data.summary, { name: 'Export summary' });
    if (summaryBlock) container.appendChild(summaryBlock);
    container.appendChild(
      block(
        { kind: 'text', name: 'Files', text: data.files.join('\n') },
        h(
          'ul',
          { class: 'download-list' },
          data.files.map((f) => h('li', {}, [h('a', { href: apiClient.downloadUrl(f), target: '_blank', rel: 'noreferrer', download: '', text: f.split(/[\\/]/).pop() })])),
        ),
      ),
    );
    return;
  }

  const narrative = hideNarrative ? null : NARRATIVE_KEYS.map((k) => data[k]).find(Boolean);
  const narrativeBlock = buildTextBlock(narrative);
  if (narrativeBlock) container.appendChild(narrativeBlock);

  if (data.tree_summary) {
    const tree = h('div');
    tree.append(h('p', { class: 'section-label', text: 'Top splits' }), h('pre', { class: 'tree-summary' }, [data.tree_summary.trim()]));
    container.appendChild(block({ kind: 'text', name: 'Top splits', text: data.tree_summary.trim() }, tree));
  }

  if (data.image_base64) {
    // A server-rendered PNG is a chart block: Copy as Picture reads the <img> rather than a canvas.
    container.appendChild(
      block(
        { kind: 'chart', name: data.title || 'Chart' },
        h('img', { class: 'result-image', src: `data:image/png;base64,${data.image_base64}`, alt: data.title || 'chart' }),
      ),
    );
  }

  // A Basic Statistics result carries its own tiles and its own output blocks. This path runs when
  // the record has no live renderer — a project reopened from a .baproj file.
  const ownTables = Array.isArray(data.tables) ? data.tables : null;

  const grid = buildStatGrid(ownTables ? data.highlights : buildHighlights(analysisId, data));
  if (grid) container.appendChild(grid);

  if (!ownTables) {
    const config = buildChartConfig(analysisId, data);
    if (config) {
      // Same ordering rule as drawGraph: the wrapper is attached BEFORE the chart mounts, because a
      // Chart.js chart built in a detached element paints nothing.
      const host = h('div');
      // printDraw rebuilds the same config into an export-sized host (see resultView.block).
      container.appendChild(
        block(
          {
            kind: 'chart',
            name: data.title || 'Chart',
            printDraw: (printHost) => {
              const cfg = buildChartConfig(analysisId, data);
              if (cfg) mountChart(printHost, cfg, false, null);
            },
          },
          host,
        ),
      );
      mountChart(host, config, compact, onCapture);
    }
  }

  const { key: tableKey, rows } = ownTables ? { key: null, rows: [] } : extractTable(analysisId, data);
  const scalars = Object.entries(data).filter(([k, v]) => k !== tableKey && !HIDE_SCALAR_KEYS.has(k) && (typeof v !== 'object' || v === null));

  // Main table first, then the loose scalars — those are run metadata (dataset id, method,
  // alpha), which belongs under the findings, not above them.
  for (const table of ownTables || []) {
    const tableBlock = buildTableBlock(table.title, table.rows);
    if (tableBlock) container.appendChild(tableBlock);
  }

  if (rows.length > 0) {
    const dt = buildDataTable(rows, analysisId === 'automl' && tableKey === 'results' ? data.best_model : null);
    if (dt) container.appendChild(block({ kind: 'table', name: tableKey ? prettyKey(tableKey) : 'Results', rows }, dt));
  }

  if (scalars.length > 0) {
    const tbody = h('tbody');
    for (const [k, v] of scalars) {
      const td = h('td');
      if (typeof v === 'number' && Number.isFinite(v)) renderNumberInto(td, v);
      else td.textContent = formatCell(v);
      tbody.appendChild(h('tr', {}, [h('th', { text: k }), td]));
    }
    container.appendChild(
      block(
        { kind: 'table', name: 'Run details', rows: scalars.map(([k, v]) => ({ Setting: k, Value: formatCell(v) })) },
        h('div', { class: 'table-scroll' }, [h('table', { class: 'scalar-table' }, [tbody])]),
      ),
    );
  }
}

/** 'strongest_pairs' -> 'Strongest pairs', for naming a block after the key its rows came from. */
function prettyKey(key) {
  const words = String(key).replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// ---------------------------------------------------------------------------
// app state
// ---------------------------------------------------------------------------

const state = {
  dataset: null, // the ACTIVE dataset — always read through activeDataset(), never captured
  datasets: [], // every dataset loaded this session, in load order (all still live on the backend)
  results: [], // {id, analysisId, label, data, values, windowId, win}
  nextResultId: 1,
  sessionLines: [], // {text, className, resultId} — mirrored so a project can save/restore the log
  project: { name: '', description: '' },
  lastDialog: null, // {analysisId, values} for Edit > Edit Last Dialog
};

// ---------------------------------------------------------------------------
// the active dataset: one shared source of truth
// ---------------------------------------------------------------------------
// Loading a file replaces the worksheet, but the dataset it replaced is still loaded on the
// backend — so the app keeps a registry of them all plus one pointer to the active one. Every
// consumer (worksheet, tool forms, graphs, the assistant) resolves the id through activeDataset()
// at the moment it acts rather than holding one, which is what keeps them from drifting onto
// different data. Listeners let the UI react to a switch instead of polling.

const datasetListeners = [];

function activeDataset() {
  return state.dataset;
}

function worksheetName(record) {
  return record ? record.name || record.source : '';
}

function otherDatasetNames() {
  return state.datasets.filter((r) => r !== state.dataset).map(worksheetName);
}

function onActiveDatasetChange(fn) {
  datasetListeners.push(fn);
}

// A tab label that is not already taken. A blank sheet is numbered ("Worksheet 3"); anything else
// keeps the name it arrived with — a file name, or the name the Data operation chose for it.
function uniqueWorksheetName(base) {
  const taken = new Set(state.datasets.map(worksheetName));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base} (${n})`)) n += 1;
  return `${base} (${n})`;
}

function nextBlankNumber() {
  let n = 1;
  const taken = new Set(state.datasets.map(worksheetName));
  while (taken.has(`Worksheet ${n}`)) n += 1;
  return n;
}

function registerDataset(record) {
  const existing = state.datasets.find((r) => r.dataset_id === record.dataset_id);
  if (existing) {
    Object.assign(existing, record, { name: existing.name });
    renderTabs();
    return existing;
  }
  // A blank worksheet nobody typed into isn't data the user "has", so an imported file or a
  // derived worksheet takes its place rather than leaving an empty tab behind. Asking for a blank
  // worksheet explicitly (the + tab, File > New) is exempt — that one was wanted.
  if (record.source_type !== 'blank') {
    const discarded = state.datasets.filter((r) => r.source_type === 'blank' && !r.touched);
    state.datasets = state.datasets.filter((r) => !discarded.includes(r));
    for (const gone of discarded) ws.dropHistory(gone.dataset_id);
  }

  record.name = uniqueWorksheetName(record.name || record.source);
  // The tab label and the record's `source` are kept identical on purpose: the assistant matches
  // "use <name>" against source (chatParser.matchDataset), and it must answer to what the tab says.
  record.source = record.name;
  state.datasets.push(record);
  renderTabs();
  return record;
}

function findWorksheet(datasetId) {
  return state.datasets.find((r) => r.dataset_id === datasetId) || null;
}

// Re-points the whole app — worksheet included — at an already-loaded dataset.
function switchToDataset(record) {
  if (!record || record === state.dataset) return;
  setDataset(record, { quiet: true });
  logSessionLine(`> Switched to ${worksheetName(record)} — ${record.row_count} rows × ${record.columns.length} columns.`, 'session-line session-line-muted');
}

// ---------------------------------------------------------------------------
// the worksheet tab strip
// ---------------------------------------------------------------------------

function renderTabs() {
  tabs.render(state.datasets, state.dataset ? state.dataset.dataset_id : null);
}

async function addBlankWorksheet() {
  const data = await apiClient.createBlankDataset(`Worksheet ${nextBlankNumber()}`);
  setDataset(data, { quiet: true });
  logSessionLine(`> New worksheet '${worksheetName(state.dataset)}' created.`);
  return state.dataset;
}

async function renameWorksheet(datasetId, name) {
  const record = findWorksheet(datasetId);
  if (!record) return;
  const previous = worksheetName(record);
  const applied = uniqueWorksheetName(name.trim());
  try {
    await apiClient.renameWorksheet(datasetId, applied);
  } catch (err) {
    // The label is the frontend's to own; a backend hiccup must not lose the rename the user just
    // typed, so it is applied locally either way and the failure is only reported.
    ws.showError(`The worksheet was renamed locally, but the server could not be told: ${err.message}`);
  }
  record.name = applied;
  record.source = applied;
  renderTabs();
  renderStatus();
  if (chatWin && record === state.dataset) chatWin.setSubtitle(applied);
  logSessionLine(`> Renamed worksheet '${previous}' to '${applied}'.`, 'session-line session-line-muted');
}

async function closeWorksheet(datasetId) {
  const record = findWorksheet(datasetId);
  if (!record) return;
  if (state.datasets.length <= 1) {
    ws.showError('This is the only worksheet — a project always has one. Use File > New > New Worksheet to start a fresh one first.');
    return;
  }
  const isActive = record === state.dataset;
  const hasData = isActive ? ws.hasData() : record.row_count > 0 && record.source_type !== 'blank';
  if (hasData) {
    const ok = await dialogs.confirm({
      title: 'Close Worksheet',
      message: `Close '${worksheetName(record)}'?`,
      detail: 'Its data is discarded unless the project has been saved. Result windows and the session log are kept.',
      confirmLabel: 'Close worksheet',
      danger: true,
    });
    if (!ok) return;
  }
  const index = state.datasets.indexOf(record);
  state.datasets = state.datasets.filter((r) => r !== record);
  ws.dropHistory(datasetId);
  conditionalFormat.clearWorksheet(datasetId);
  logSessionLine(`> Closed worksheet '${worksheetName(record)}'.`, 'session-line session-line-muted');
  if (isActive) setDataset(state.datasets[Math.max(0, index - 1)], { quiet: true });
  else renderTabs();
}

tabs.init({
  onSwitch: (datasetId) => switchToDataset(findWorksheet(datasetId)),
  onRename: (datasetId, name) => renameWorksheet(datasetId, name),
  onClose: (datasetId) => closeWorksheet(datasetId),
  onNew: () => addBlankWorksheet().catch((err) => ws.showError(`Could not create a worksheet: ${err.message}`)),
});

// ---------------------------------------------------------------------------
// session window
// ---------------------------------------------------------------------------

const sessionWindow = document.getElementById('session-window');
const sessionWindowBody = document.getElementById('session-window-body');
const sessionCollapseBtn = document.getElementById('session-collapse-btn');
const sessionResizeHandle = document.getElementById('session-resize-handle');

function appendSessionNode(entry) {
  // Data > Display Data prints a whole block of values, not a line — Minitab's Session Window is
  // as much a printout as a log, so the block keeps its own preformatted node.
  const node = entry.block
    ? h('div', { class: 'session-block' }, [entry.text ? h('div', { class: 'session-block-title', text: entry.text }) : null, h('pre', { class: 'session-block-pre' }, [entry.block])])
    : entry.resultId
      ? h('button', {
          type: 'button',
          class: 'session-line-link',
          text: entry.text,
          title: 'Show this result window',
          onClick: () => showResult(entry.resultId),
        })
      : h('div', { class: entry.className || 'session-line', text: entry.text });
  sessionWindowBody.appendChild(node);
  sessionWindowBody.scrollTop = sessionWindowBody.scrollHeight;
}

function logSessionLine(text, className = 'session-line') {
  const entry = { text, className, resultId: null };
  state.sessionLines.push(entry);
  appendSessionNode(entry);
}

function logSessionBlock(title, text) {
  const entry = { text: `> ${title}`, className: 'session-line', resultId: null, block: text };
  state.sessionLines.push(entry);
  appendSessionNode(entry);
}

function logSessionResult(result) {
  const narrative = NARRATIVE_KEYS.map((k) => result.data && result.data[k]).find(Boolean) || 'Done.';
  const entry = { text: `> ${result.label} — ${narrative}`, className: 'session-line', resultId: result.id };
  state.sessionLines.push(entry);
  appendSessionNode(entry);
}

function clearSessionLog() {
  state.sessionLines = [];
  sessionWindowBody.innerHTML = '';
}

sessionCollapseBtn.addEventListener('click', () => {
  const collapsed = sessionWindow.classList.toggle('collapsed');
  sessionCollapseBtn.textContent = collapsed ? 'Expand' : 'Collapse';
});

(function wireSessionResize() {
  let startY = 0;
  let startHeight = 0;
  let dragging = false;

  function onMove(e) {
    if (!dragging) return;
    const delta = startY - e.clientY;
    sessionWindow.style.height = `${Math.min(Math.max(startHeight + delta, 60), window.innerHeight * 0.7)}px`;
  }
  function onUp() {
    dragging = false;
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
  }
  sessionResizeHandle.addEventListener('pointerdown', (e) => {
    if (sessionWindow.classList.contains('collapsed')) return;
    dragging = true;
    startY = e.clientY;
    startHeight = sessionWindow.getBoundingClientRect().height;
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    e.preventDefault();
  });
})();

// ---------------------------------------------------------------------------
// result windows
// ---------------------------------------------------------------------------

function resultWindowKind(analysisId, data) {
  if (analysisId === 'chart' || (data && data.image_base64)) return 'chart';
  return 'result';
}

function renderResultInto(result, body) {
  // Clearing the body detaches every canvas in it. Any chart still animating would keep ticking
  // against a canvas that has left the document and throw `this._fn is not a function` from inside
  // Chart.js every frame — which is exactly what a theme switch does to a window whose charts are
  // still drawing. Stop them first; they are about to be rebuilt from the same record anyway.
  stopChartsIn(body);
  body.innerHTML = '';
  // body is already attached here (it belongs to an open window)
  if (result.render) result.render(body, { onCapture: captureFor(result) });
  else renderResultBody(body, result.analysisId, result.data, { hideNarrative: false, compact: false, onCapture: captureFor(result) });
}

// Whatever a result draws, the PNG of it is kept on the record so File > Export Report can put
// the very same picture in the PDF/Word/Excel/Markdown output.
function captureFor(result) {
  return (dataUrl) => {
    result.capture = dataUrl;
  };
}

/**
 * A result's chart PNG rendered for PRINT: light palette, 2x, whatever theme the app is in.
 *
 * The result is re-rendered into an offscreen host rather than re-photographed from its window,
 * because the on-screen chart's colours were baked in when it was built. The host must be ATTACHED —
 * a Chart.js chart in a detached element paints nothing — so it is parked far off-screen instead of
 * hidden, since a zero-size or `display:none` host measures zero and gets no pixels either.
 *
 * `index` selects among a result that draws several charts, so a staged block gets its own figure and
 * not its neighbour's. Resolves to null when the result draws no chart at all.
 */
function printCapture(result, index = 0) {
  if (!result) return Promise.resolve(null);
  // theme.renderForExport owns the geometry, the light palette, print-sized type, the settle and the
  // composition; this only says WHAT to draw and WHICH figure of it to take. `scope` picks the index-th
  // chart block, because a result may draw several figures and a section wants its own — not all of
  // them merged, and not a guess based on the order asynchronous captures happened to arrive in.
  return theme
    .renderForExport(
      (host) => {
        if (result.render) result.render(host, {});
        else renderResultBody(host, result.analysisId, result.data, { hideNarrative: false, compact: false });
      },
      {
        scope: (host) => {
          const charts = [...host.querySelectorAll('.out-block-chart')];
          return charts[index] || charts[0] || null;
        },
      },
    )
    .catch(() => null);
}

function openResultWindow(result) {
  const body = h('div');
  if (result.render) result.render(body, { onCapture: captureFor(result) });
  else renderResultBody(body, result.analysisId, result.data, { hideNarrative: false, compact: false, onCapture: captureFor(result) });
  const win = wm.createWindow({
    id: `result-${result.id}`,
    title: result.label,
    kind: result.kind || resultWindowKind(result.analysisId, result.data),
    width: result.width || undefined,
    content: body,
  });
  result.windowId = win.id;
  result.win = win;
  return win;
}

// Clicking a Session Window entry: focus the result's window if it's still open (restoring it
// if minimized), otherwise render it fresh.
function showResult(resultId) {
  const result = state.results.find((r) => r.id === resultId);
  if (!result) return;
  if (result.windowId && wm.has(result.windowId)) wm.focus(result.windowId);
  else openResultWindow(result);
}

function addResult(analysisId, label, data, { open = true, values = null, render = null, kind = null, width = null } = {}) {
  // `at` is stamped once, here, because a report card's metadata line says when the analysis RAN —
  // not when it was exported, which is what reading the clock later would give.
  const result = { id: state.nextResultId++, analysisId, label, data, values, render, kind, width, at: runStamp(), capture: null, windowId: null, win: null };
  state.results.push(result);
  if (open) openResultWindow(result);
  logSessionResult(result);
  refreshMenuState();
  return result;
}

// ---------------------------------------------------------------------------
// tool windows (forms)
// ---------------------------------------------------------------------------

function buildToolForm(config, columns, { onDone, initialValues } = {}) {
  const values = defaultValues(config);
  // A saved/last-run set of inputs may name columns that no longer exist (deleted since) —
  // keep only what still applies rather than submitting a stale column name.
  if (initialValues) {
    for (const f of config.fields) {
      const v = initialValues[f.name];
      if (v === undefined) continue;
      if (f.type === 'columns') values[f.name] = (Array.isArray(v) ? v : []).filter((c) => columns.includes(c));
      else if (f.type === 'column') values[f.name] = columns.includes(v) ? v : '';
      else values[f.name] = v;
    }
  } else {
    // File > Options' default significance level prefills any alpha field.
    for (const f of config.fields) if (f.name === 'alpha') values[f.name] = settings.get().alpha;
  }

  const form = h('form', { class: 'tool-form' });
  const errorP = h('p', { class: 'error' });
  errorP.hidden = true;
  const submitBtn = h('button', { type: 'submit', class: 'btn btn-primary', text: config.submitLabel || `Run ${config.label.toLowerCase()}` });

  for (const f of config.fields) {
    const fieldWrap = h('div', { class: 'field' }, [h('label', { text: f.label })]);

    if (f.type === 'column') {
      const select = h('select', {}, [h('option', { value: '', text: '— choose a column —' }), ...columns.map((c) => h('option', { value: c, text: c }))]);
      select.value = values[f.name];
      select.addEventListener('change', () => {
        values[f.name] = select.value;
      });
      fieldWrap.appendChild(select);
    } else if (f.type === 'columns') {
      const list = h('div', { class: 'checkbox-list' });
      for (const c of columns) {
        const checkbox = h('input', { type: 'checkbox' });
        checkbox.checked = (values[f.name] || []).includes(c);
        checkbox.addEventListener('change', () => {
          const arr = values[f.name] || [];
          if (checkbox.checked) {
            if (!arr.includes(c)) arr.push(c);
          } else {
            values[f.name] = arr.filter((x) => x !== c);
          }
        });
        list.appendChild(h('label', { class: 'checkbox-item' }, [checkbox, c]));
      }
      fieldWrap.appendChild(list);
    } else if (f.type === 'select') {
      const select = h('select', {}, f.options.map((o) => h('option', { value: o, text: o })));
      select.value = values[f.name];
      select.addEventListener('change', () => {
        values[f.name] = select.value;
      });
      fieldWrap.appendChild(select);
    } else if (f.type === 'number') {
      const input = h('input', { type: 'number', step: f.step || 1, min: f.min, max: f.max });
      input.value = values[f.name];
      input.addEventListener('input', () => {
        values[f.name] = input.value;
      });
      fieldWrap.appendChild(input);
    }

    form.appendChild(fieldWrap);
  }

  form.appendChild(h('div', { class: 'form-actions' }, [submitBtn]));
  form.appendChild(errorP);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const validationError = validateValues(config, values);
    if (validationError) {
      errorP.textContent = validationError;
      errorP.hidden = false;
      return;
    }
    errorP.hidden = true;
    submitBtn.disabled = true;
    const idleLabel = submitBtn.textContent;
    submitBtn.textContent = 'Running…';
    try {
      const params = buildParams(config, values);
      const data = await runAnalysis(config.id, state.dataset.dataset_id, params);
      // Remember the inputs so Edit > Edit Last Dialog (Ctrl+E) can reopen this form prefilled.
      state.lastDialog = { analysisId: config.id, values: JSON.parse(JSON.stringify(values)) };
      // The form window gives way to its result window — results are never appended to a
      // page-long scroll, they are windows the user can arrange side by side.
      if (onDone) onDone();
      addResult(config.id, summarizeParams(config, values), data, { values: state.lastDialog.values });
    } catch (err) {
      errorP.textContent = err.message;
      errorP.hidden = false;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = idleLabel;
    }
  });

  return form;
}

// ---------------------------------------------------------------------------
// Export Report — the readable deliverable, kept deliberately distinct from
// Save Project (the working session). Someone after a PDF should never end up
// with a .baproj, which is what the old "Save Current Output As…" label caused.
// ---------------------------------------------------------------------------

const EXPORT_FORMATS = [
  { value: 'pdf', name: 'PDF', ext: '.pdf', note: 'Formatted report for sharing or printing.', button: 'Export PDF' },
  { value: 'docx', name: 'Word', ext: '.docx', note: 'Editable document with real heading styles.', button: 'Export Word document' },
  { value: 'xlsx', name: 'Excel', ext: '.xlsx', note: 'One worksheet per analysis, numbers intact.', button: 'Export Excel workbook' },
  { value: 'markdown', name: 'Markdown', ext: '.md', note: 'Plain text for wikis, docs or git.', button: 'Export Markdown' },
  { value: 'pptx', name: 'PowerPoint', ext: '.pptx', note: 'One slide per section, chart or table centred.', button: 'Export PowerPoint deck' },
];

function datasetStem() {
  const base = state.project.name || (state.dataset && state.dataset.source) || `${brand.name} Project`;
  return `${safeFileName(base.replace(/\.[^.]+$/, ''))}-report`;
}

// `scope` is 'session' (every analysis, in the order it was run) or 'report' (the Report pane's
// curated blocks, in the order they were arranged). The Report pane opens the dialog on 'report';
// File > Export Report opens it on 'session'. Either way both choices stay switchable in the dialog.
function openExportDialog({ scope: initialScope = 'session' } = {}) {
  if (wm.has('export-report')) {
    wm.focus('export-report');
    return;
  }
  const exportable = state.results.filter((r) => r.analysisId !== 'export');

  dialogs.panel({
    title: 'Export Report',
    width: 560,
    render: (close) => {
      if (exportable.length === 0 && reportPane.count() === 0) {
        return h('div', { class: 'dialog' }, [
          h('p', { class: 'dialog-message', text: 'There is nothing to put in a report yet.' }),
          h('p', { class: 'dialog-detail', text: 'Run an analysis from the Stat or Graph menu first — every result from this session can then be included here, or you can stage individual blocks in the Report pane.' }),
          h('div', { class: 'dialog-actions' }, [h('button', { type: 'button', class: 'btn btn-primary', text: 'Close', onClick: close })]),
        ]);
      }

      let scope = reportPane.count() === 0 ? 'session' : initialScope;
      let format = EXPORT_FORMATS[0];
      const selected = new Set(exportable.map((r) => r.id)); // everything included by default

      const grid = h('div', { class: 'format-grid' });
      const cards = [];
      const submitBtn = h('button', { type: 'submit', class: 'btn btn-primary', text: format.button });

      for (const option of EXPORT_FORMATS) {
        const radio = h('input', { type: 'radio', name: 'export-format', value: option.value });
        radio.checked = option.value === format.value;
        const card = h('label', { class: `format-card${radio.checked ? ' selected' : ''}` }, [
          radio,
          h('span', { class: 'format-card-body' }, [
            h('span', { class: 'format-card-name' }, [option.name, h('span', { class: 'format-card-ext', text: option.ext })]),
            h('span', { class: 'format-card-note', text: option.note }),
          ]),
        ]);
        radio.addEventListener('change', () => {
          if (!radio.checked) return;
          format = option;
          for (const c of cards) c.classList.toggle('selected', c === card);
          submitBtn.textContent = option.button; // the button says exactly what it will produce
        });
        cards.push(card);
        grid.appendChild(card);
      }

      const list = h('div', { class: 'checkbox-list' });
      for (const r of exportable) {
        const checkbox = h('input', { type: 'checkbox' });
        checkbox.checked = true;
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) selected.add(r.id);
          else selected.delete(r.id);
        });
        list.appendChild(h('label', { class: 'checkbox-item' }, [checkbox, r.label]));
      }

      // The staged list is ordered and curated, so it is shown as a numbered running order rather
      // than as checkboxes — unchecking one here would contradict the pane it came from.
      const stagedList = h('ol', { class: 'export-staged' });
      for (const item of reportPane.serialize()) {
        stagedList.appendChild(
          h('li', {}, [item.kind === 'note' ? h('em', { text: item.text ? `Note: ${item.text.slice(0, 60)}` : 'Note (empty)' }) : `${item.source ? `${item.source} — ` : ''}${item.name}`]),
        );
      }

      const sessionField = h('div', { class: 'field' }, [h('label', { text: `Analyses to include (${exportable.length})` }), list]);
      const reportField = h('div', { class: 'field' }, [h('label', { text: `Staged blocks (${reportPane.count()})` }), stagedList]);

      const scopeTabs = h('div', { class: 'scope-tabs', role: 'tablist' });
      const scopeButtons = [];
      for (const option of [
        { value: 'session', label: 'Everything from this session', note: `${exportable.length} analysis result(s), in the order they were run` },
        { value: 'report', label: 'Report pane contents', note: reportPane.count() ? `${reportPane.count()} staged block(s), in your order` : 'Nothing staged yet' },
      ]) {
        const btn = h('button', { type: 'button', class: 'scope-tab', role: 'tab' }, [
          h('span', { class: 'scope-tab-label', text: option.label }),
          h('span', { class: 'scope-tab-note', text: option.note }),
        ]);
        if (option.value === 'report' && reportPane.count() === 0) {
          btn.classList.add('scope-tab-disabled');
          btn.setAttribute('aria-disabled', 'true');
          btn.title = 'Send blocks to the report from a block’s chevron menu first.';
        } else {
          btn.addEventListener('click', () => {
            scope = option.value;
            applyScope();
          });
        }
        scopeButtons.push([option.value, btn]);
        scopeTabs.appendChild(btn);
      }

      function applyScope() {
        for (const [value, btn] of scopeButtons) {
          const on = value === scope;
          btn.classList.toggle('scope-tab-active', on);
          btn.setAttribute('aria-selected', String(on));
        }
        sessionField.hidden = scope !== 'session';
        reportField.hidden = scope !== 'report';
      }

      const nameInput = h('input', { type: 'text', placeholder: 'report' });
      nameInput.value = datasetStem();

      const errorP = h('p', { class: 'error' });
      errorP.hidden = true;

      const form = h('form', { class: 'dialog' }, [
        h('div', { class: 'field' }, [h('label', { text: 'What to export' }), scopeTabs]),
        h('div', { class: 'field' }, [h('label', { text: 'Format' }), grid]),
        sessionField,
        reportField,
        h('div', { class: 'field' }, [h('label', { text: 'File name' }), nameInput]),
        h('div', { class: 'dialog-actions' }, [submitBtn, h('button', { type: 'button', class: 'btn', text: 'Cancel', onClick: close })]),
        errorP,
      ]);
      applyScope();

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (scope === 'session' && selected.size === 0) {
          errorP.textContent = 'Select at least one analysis to include.';
          errorP.hidden = false;
          return;
        }
        if (scope === 'report' && reportPane.count() === 0) {
          errorP.textContent = 'Nothing is staged in the report pane yet.';
          errorP.hidden = false;
          return;
        }
        errorP.hidden = true;
        const idleLabel = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Exporting…';
        try {
          const analyses = await withPrintCharts(
            scope === 'report'
              ? reportPane.sections()
              : exportable
                  .filter((r) => selected.has(r.id))
                  .map((r) => ({
                    title: r.label,
                    data: r.data,
                    chart_path: r.data?.chart_path || null,
                    chart_image_base64: r.capture || null,
                    ...resultCardFields(r),
                  })),
          );
          const data = await apiClient.exportReport({
            dataset_id: state.dataset.dataset_id,
            format: format.value,
            analyses,
            report_name: safeFileName(nameInput.value) || null,
            decimals: settings.get().decimals,
          });
          close();
          addResult('export', `${format.name} report (${analyses.length} section${analyses.length === 1 ? '' : 's'})`, data);
          // Don't make the user hunt for a download link — save each file immediately. Staggered
          // slightly since browsers can block near-simultaneous downloads.
          (data.files || []).forEach((f, i) => {
            setTimeout(() => triggerDownload(apiClient.downloadUrl(f), f.split(/[\\/]/).pop()), i * 400);
          });
        } catch (err) {
          errorP.textContent = err.message;
          errorP.hidden = false;
        } finally {
          submitBtn.disabled = false;
          submitBtn.textContent = idleLabel;
        }
      });

      return form;
    },
  });
}

// Both Stat-menu procedure modules use data-stat; whichever registry owns the id opens it.
function openStatDialog(statId, initialValues) {
  if (basicStats.PROCEDURE_BY_ID[statId]) basicStats.open(statId, initialValues);
  else if (regression.PROCEDURE_BY_ID[statId]) regression.open(statId, initialValues);
  else if (anova.PROCEDURE_BY_ID[statId]) anova.open(statId, initialValues);
}

// Edit > Edit Last Dialog reopens whichever kind of dialog ran last — a Stat procedure or one of
// the generic analysis forms — with the same inputs prefilled.
function reopenLastDialog() {
  const last = state.lastDialog;
  if (!last) return;
  if (last.statId) openStatDialog(last.statId, last.values);
  else if (last.dataId) dataMenu.open(last.dataId, last.values);
  else if (last.calcId) calc.open(last.calcId, last.values);
  else openToolWindow(last.analysisId, last.values);
}

function openToolWindow(analysisId, initialValues) {
  const config = ANALYSIS_BY_ID[analysisId];
  if (!config) return;
  if (config.special) {
    // 'export' isn't an analysis form — it's the Export Report dialog.
    openExportDialog();
    return;
  }
  const winId = `form-${analysisId}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  if (!state.dataset) {
    wm.createWindow({
      id: winId,
      title: config.label,
      kind: 'form',
      content: h('p', { class: 'muted', text: 'No worksheet yet. Open a file from the File menu, or wait for the blank worksheet to finish loading.' }),
    });
    return;
  }

  const columns = state.dataset.columns.map((c) => c.name);
  // The content is built before the window so the window can size itself to the form's real
  // height on its first paint; `win` is only dereferenced later, from the submit handler.
  let win;
  const onDone = () => win && win.close();
  const content = buildToolForm(config, columns, { onDone, initialValues });
  win = wm.createWindow({ id: winId, title: config.label, kind: 'form', content });
}

// ---------------------------------------------------------------------------
// dataset status + summary window
// ---------------------------------------------------------------------------

function renderStatus() {
  const d = state.dataset;
  const wrap = document.getElementById('menubar-status');
  if (!d) {
    document.title = brand.name;
    wrap.hidden = true;
    return;
  }
  const nameEl = document.getElementById('status-source');
  const sheet = worksheetName(d);
  const label = state.project.name ? `${state.project.name} — ${sheet}` : sheet;
  // The browser tab carries the app name plus whatever is open, so several windows are tellable
  // apart. Set here because this is already the one place that knows the active worksheet's label.
  document.title = `${brand.name} — ${label}`;
  // The desktop window's title bar is chrome the document cannot reach, so it is asked for. Given
  // the project name alone: a title bar that changed every time the user clicked a worksheet tab
  // would be noise, and the worksheet is already named in the app's own status line.
  desktop.setTitle(state.project.name);
  nameEl.textContent = label;
  nameEl.title = label;
  const sheets = state.datasets.length > 1 ? ` · ${state.datasets.length} worksheets` : '';
  document.getElementById('status-meta').textContent = `${d.row_count} rows · ${d.columns.length} cols${sheets}`;
  wrap.hidden = false;
  // The worksheet pane says which of the several worksheets is on screen.
  const title = document.getElementById('worksheet-head-title');
  if (title) title.textContent = sheet || 'Worksheet';
}

function openSummaryWindow() {
  if (wm.has('summary')) {
    wm.focus('summary');
    return;
  }
  const d = state.dataset;
  const content = h('div');
  if (!d) {
    content.appendChild(h('p', { class: 'muted', text: 'No worksheet loaded yet.' }));
  } else {
    const schemaTable = h('table', {}, [
      h('thead', {}, [h('tr', {}, [h('th', { text: 'Column' }), h('th', { text: 'Type' })])]),
      h('tbody', {}, d.columns.map((c) => h('tr', {}, [h('td', { text: c.name }), h('td', { text: c.dtype })]))),
    ]);
    const previewRows = (d.preview || []).length ? d.preview : ws.contents().rows.slice(0, 5);
    const previewTable = h('table', {}, [
      h('thead', {}, [h('tr', {}, d.columns.map((c) => h('th', { text: c.name })))]),
      h(
        'tbody',
        {},
        previewRows.map((row) =>
          h(
            'tr',
            {},
            d.columns.map((c) => {
              const v = row[c.name];
              const td = h('td');
              if (typeof v === 'number' && Number.isFinite(v)) {
                td.classList.add('num');
                td.textContent = formatCell(v);
              } else {
                td.textContent = v === null || v === undefined ? '' : String(v);
              }
              return td;
            }),
          ),
        ),
      ),
    ]);
    content.append(
      h('p', { class: 'muted' }, [`${worksheetName(d)} · ${d.row_count} rows · ${d.columns.length} columns · `, h('code', { text: d.dataset_id })]),
      h('p', { class: 'section-label', text: 'Columns' }),
      h('div', { class: 'table-scroll' }, [schemaTable]),
      h('p', { class: 'section-label', text: 'First rows' }),
      h('div', { class: 'table-scroll' }, [previewTable]),
    );
  }
  wm.createWindow({ id: 'summary', title: 'Dataset summary', kind: 'summary', content });
}

// ---------------------------------------------------------------------------
// open / import window — files, Google Sheets links, and .baproj project files
// ---------------------------------------------------------------------------

function openImportWindow(initialError) {
  if (wm.has('import')) {
    wm.focus('import');
    return;
  }

  const statusP = h('p', { class: 'status', text: 'Loading…' });
  statusP.hidden = true;
  const errorP = h('p', { class: 'error' });
  errorP.hidden = !initialError;
  if (initialError) errorP.textContent = initialError;

  const fileInput = h('input', { type: 'file', accept: `.csv,.xlsx,${PROJECT_EXT},${LEGACY_PROJECT_EXT},.json`, hidden: 'hidden' });
  const dropzone = h('div', { class: 'dropzone' }, [
    (() => {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'dropzone-icon');
      svg.setAttribute('width', '22');
      svg.setAttribute('height', '22');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '1.5');
      const p1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p1.setAttribute('d', 'M12 16V4M12 4L7 9M12 4l5 5');
      const p2 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p2.setAttribute('d', 'M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3');
      svg.append(p1, p2);
      return svg;
    })(),
    h('span', { text: `Drop a CSV, .xlsx or ${PROJECT_EXT} file here, or click to choose one` }),
    fileInput,
  ]);

  const gsheetInput = h('input', { type: 'text', placeholder: 'Public Google Sheets link' });
  const gsheetBtn = h('button', { type: 'submit', class: 'btn btn-primary', text: 'Load sheet' });
  const gsheetForm = h('form', { class: 'gsheet-form' }, [gsheetInput, gsheetBtn]);

  const content = h('div', { class: 'import-panel' }, [
    h('p', { class: 'muted', text: `Data files replace the current worksheet. A ${PROJECT_EXT} file restores a whole saved project.` }),
    dropzone,
    h('div', { class: 'field' }, [h('label', { text: 'Google Sheets' }), gsheetForm]),
    statusP,
    errorP,
  ]);

  const win = wm.createWindow({ id: 'import', title: 'Open', kind: 'import', content });

  const setBusy = (busy) => {
    statusP.hidden = !busy;
  };
  const setError = (msg) => {
    errorP.hidden = !msg;
    if (msg) errorP.textContent = msg;
  };

  async function loadFile(file) {
    setBusy(true);
    setError(null);
    try {
      const lower = file.name.toLowerCase();
      if (lower.endsWith(PROJECT_EXT) || lower.endsWith(LEGACY_PROJECT_EXT) || lower.endsWith('.json')) {
        await openProjectFile(file);
      } else {
        const ext = lower.split('.').pop();
        const data = await apiClient.uploadFile(file, ext === 'xlsx' ? 'xlsx' : 'csv');
        setDataset(data, { resetProject: true });
        settings.addRecent({ kind: 'file', name: file.name });
        buildRecentSubmenu();
      }
      win.close();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    const file = e.dataTransfer.files?.[0];
    if (file) loadFile(file);
  });
  fileInput.addEventListener('change', (e) => {
    if (e.target.files?.[0]) loadFile(e.target.files[0]);
  });

  gsheetForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = gsheetInput.value.trim();
    if (!url) return;
    setBusy(true);
    setError(null);
    try {
      await loadGSheet(url);
      win.close();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  });
}

async function loadGSheet(url) {
  const data = await apiClient.loadGSheet(url);
  setDataset(data, { resetProject: true });
  settings.addRecent({ kind: 'gsheet', name: url, url });
  buildRecentSubmenu();
}

function setDataset(loadResponse, { resetProject = false, quiet = false } = {}) {
  if (!loadResponse) return;
  const changed = !state.dataset || state.dataset.dataset_id !== loadResponse.dataset_id;
  // registerDataset returns the record already in the registry when there is one, so switching
  // back to a worksheet keeps the tab label it was given rather than reverting to its source.
  const record = registerDataset(loadResponse);
  state.dataset = record;
  if (resetProject) state.project = { name: '', description: '' };
  ws.setDataset(record);
  // Undo history is kept per worksheet inside worksheet.js, so switching tabs must NOT clear it.
  ws.showError(null);
  renderTabs();
  renderStatus();
  ws.render();
  if (wm.has('summary')) {
    wm.close('summary');
    openSummaryWindow();
  }
  conditionalFormat.refreshManageWindow();
  if (!quiet) {
    logSessionLine(`> Worksheet loaded from ${worksheetName(record)} — ${record.row_count} rows × ${record.columns.length} columns.`, 'session-line session-line-muted');
  }
  if (changed) for (const fn of datasetListeners) fn(record);
  refreshMenuState();
}

// ---------------------------------------------------------------------------
// what a Data-menu operation did: new worksheets get tabs, a rewritten worksheet gets a redraw
// ---------------------------------------------------------------------------

async function applyDataOp(response) {
  for (const made of response.created || []) {
    registerDataset({
      dataset_id: made.dataset_id,
      source: made.name,
      name: made.name,
      source_type: made.source_type,
      row_count: made.row_count,
      columns: made.columns,
      preview: [],
      touched: true,
    });
  }
  // Every operation that makes worksheets makes the first one active, so the result of what was
  // just asked for is what is on screen — the same way Minitab lands you in the new worksheet.
  const first = (response.created || [])[0];
  if (first) {
    switchToDataset(findWorksheet(first.dataset_id));
    if ((response.created || []).length > 1) {
      logSessionLine(`> Created ${response.created.length} worksheets: ${response.created.map((w) => w.name).join(', ')}.`, 'session-line session-line-muted');
    }
    return;
  }

  for (const datasetId of response.modified || []) {
    const record = findWorksheet(datasetId);
    if (!record) continue;
    record.touched = true;
    if (record === state.dataset) {
      // ws.render() is the one path that repaints the grid AND refreshes the record's schema,
      // so the column pickers in every open dialog see the new columns immediately.
      await ws.render();
      continue;
    }
    const rows = await apiClient.getRows(datasetId);
    record.columns = rows.columns;
    record.row_count = rows.rows.length;
    logSessionLine(`> Worksheet '${worksheetName(record)}' now has ${record.row_count} rows × ${record.columns.length} columns.`, 'session-line session-line-muted');
  }
  renderTabs();
  renderStatus();
}

// ---------------------------------------------------------------------------
// File menu: new / project save / open / print / options
// ---------------------------------------------------------------------------

// A project holds as many worksheets as you like, so this ADDS one and switches to it rather than
// replacing what is there — the same thing the + button on the tab strip does.
async function newWorksheet() {
  await addBlankWorksheet();
}

async function newProject() {
  const ok = await dialogs.confirm({
    title: 'New Project',
    message: 'Start a new project?',
    detail: 'The worksheet, every open window, all results and the session log will be cleared.',
    confirmLabel: 'New project',
    danger: true,
  });
  if (!ok) return;
  wm.closeAll();
  state.results = [];
  state.nextResultId = 1;
  state.lastDialog = null;
  state.project = { name: '', description: '' };
  state.datasets = []; // a new project starts with no worksheets to switch back to
  state.dataset = null;
  constants.clear();
  matrices.clear();
  calc.restoreSeed(null);
  anova.restoreModels(null);
  conditionalFormat.setRules([]);
  reportPane.clear();
  clearSessionLog();
  const data = await apiClient.createBlankDataset('Worksheet 1');
  setDataset(data, { quiet: true });
  logSessionLine('> New project.');
}

async function exitToBlank() {
  const ok = await dialogs.confirm({
    title: 'Exit',
    message: 'Close everything and return to a blank worksheet?',
    detail: 'Open windows and results are discarded. The session log is kept — this is a local tool, there is nothing to sign out of.',
    confirmLabel: 'Exit',
    danger: true,
  });
  if (!ok) return;
  wm.closeAll();
  state.results = [];
  state.lastDialog = null;
  state.project = { name: '', description: '' };
  state.datasets = [];
  state.dataset = null;
  const data = await apiClient.createBlankDataset('Worksheet 1');
  setDataset(data, { quiet: true });
  logSessionLine('> Exited to a blank worksheet.');
}

// The project file: everything needed to pick the session back up — EVERY worksheet (each pulled
// from GET /datasets/{id}/full, the authoritative copy) and which one was active, the stored
// constants, the conditional-formatting rules, the session log, and every analysis run with its
// inputs and its results.
//
// Rules point at worksheets by index, not by dataset_id: the ids are minted fresh by the server
// every time a project is opened, so an id saved in a file means nothing on the way back in.
async function buildProjectPayload() {
  const worksheets = [];
  for (const record of state.datasets) {
    const full = await apiClient.getFull(record.dataset_id);
    worksheets.push({
      name: worksheetName(record),
      source: full.source,
      source_type: record.source_type,
      columns: full.columns,
      rows: full.rows,
    });
  }
  const activeIndex = Math.max(0, state.datasets.findIndex((r) => r === state.dataset));
  const indexById = new Map(state.datasets.map((r, i) => [r.dataset_id, i]));

  return {
    app: PROJECT_MARKER,
    version: PROJECT_VERSION,
    saved_at: new Date().toISOString(),
    project: { name: state.project.name, description: state.project.description },
    worksheets,
    active_worksheet: activeIndex,
    // Kept so a v2 file still opens in a build that only knows v1.
    worksheet: worksheets[activeIndex] || null,
    constants: constants.list(),
    models: anova.storedModels(),
    matrices: matrices.list(),
    seed: calc.currentSeed(),
    formatting: conditionalFormat.all().map((rule) => {
      const { worksheet, ...rest } = rule;
      return { ...rest, worksheetIndex: indexById.has(worksheet) ? indexById.get(worksheet) : 0 };
    }),
    // The curated report: block payloads and their captured PNGs, in the staged order.
    report: reportPane.serialize(),
    session: state.sessionLines,
    results: state.results.map((r) => ({ id: r.id, analysisId: r.analysisId, label: r.label, values: r.values || null, data: r.data, at: r.at || '', capture: r.capture || null })),
    last_dialog: state.lastDialog,
  };
}

async function saveProject({ promptForName = false } = {}) {
  if (!state.dataset) return;
  let name = state.project.name;
  if (promptForName || !name) {
    const entered = await dialogs.prompt({
      title: promptForName ? 'Save Project As' : 'Save Project',
      // In the desktop app the next step is a native save dialog, so promising "your downloads"
      // there would be a lie — the user picks the folder themselves.
      message: desktop.available()
        ? `The project is written to a single ${PROJECT_EXT} file. You choose where next.`
        : `The project is written to a single ${PROJECT_EXT} file in your downloads.`,
      label: 'Project name',
      value: name || `${brand.name} Project`,
      confirmLabel: 'Save',
      hint: 'Saves your session to reopen later. To create a PDF/Word/Excel report, use File > Export Report.',
    });
    if (!entered) return;
    name = entered;
    state.project.name = entered;
    renderStatus();
  }
  try {
    const payload = await buildProjectPayload();
    const fileName = `${safeFileName(name)}${PROJECT_EXT}`;
    const text = JSON.stringify(payload, null, 2);

    // Two real save paths. The desktop shell writes the file where the user says, which is what
    // makes "save it to the Desktop and double-click it" possible at all; a browser can only hand
    // the blob to the download manager.
    let savedAs = fileName;
    if (desktop.available()) {
      const chosen = await desktop.saveProjectDialog(fileName, text);
      if (!chosen) return; // cancelled in the native dialog — not an error, and nothing was written
      savedAs = chosen.name || fileName;
    } else {
      downloadTextFile(fileName, text, 'application/json');
    }

    const rows = payload.worksheets.reduce((total, w) => total + w.rows.length, 0);
    logSessionLine(
      `> Saved project '${name}' — ${payload.worksheets.length} worksheet(s), ${rows} row(s), ${payload.results.length} result(s), ` +
        `${payload.constants.length} constant(s), ${payload.matrices.length} matri${payload.matrices.length === 1 ? 'x' : 'ces'}, ` +
        `${payload.formatting.length} formatting rule(s), ${payload.report.length} staged block(s).`,
    );
    settings.addRecent({ kind: 'project', name: savedAs });
    buildRecentSubmenu();
    refreshMenuState();
  } catch (err) {
    ws.showError(`Could not save the project: ${err.message}`);
  }
}

/**
 * Open a project handed over by the OS — a .gsp double-clicked in Explorer.
 *
 * Separate from openProjectFile() because there is no File object: the shell has already read the
 * text off disk. Both funnel into the same validation and restoreProject(), so a project opened this
 * way and one dragged into the import window cannot diverge.
 */
async function openProjectText(text, fileName) {
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`${fileName} is not valid JSON, so it isn't a project file.`);
  }
  if (!payload || payload.app !== PROJECT_MARKER || !(payload.worksheets || payload.worksheet)) {
    throw new Error(`${fileName} is not a ${PROJECT_EXT} project file saved by this app.`);
  }
  await restoreProject(payload, fileName);
}

function readFileText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsText(file);
  });
}

/**
 * File > Open. The native dialog in the desktop app, the import window in a browser.
 *
 * The import window is not dead in the desktop app — it still owns the Google Sheets field and the
 * drop target, and Data > Import still opens it. This only changes what File > Open does, because a
 * desktop app whose Open command shows an in-page drop zone instead of the OS file picker reads as
 * a web page in a frame.
 */
async function openViaNativeDialog() {
  if (!desktop.available()) {
    openImportWindow();
    return;
  }
  let picked;
  try {
    picked = await desktop.openFileDialog();
  } catch (err) {
    openImportWindow(`Could not open the file dialog: ${err.message}`);
    return;
  }
  if (!picked) return; // cancelled

  const lower = (picked.name || '').toLowerCase();
  try {
    if (picked.text != null || lower.endsWith(PROJECT_EXT) || lower.endsWith(LEGACY_PROJECT_EXT)) {
      await openProjectText(picked.text, picked.name);
    } else {
      // A data file arrives as base64 because it crossed an IPC boundary; rebuild the File the
      // upload endpoint expects so this shares one code path with a dropped file.
      const bytes = Uint8Array.from(atob(picked.base64), (c) => c.charCodeAt(0));
      const ext = lower.endsWith('.xlsx') ? 'xlsx' : 'csv';
      const file = new File([bytes], picked.name, { type: 'application/octet-stream' });
      const data = await apiClient.uploadFile(file, ext);
      setDataset(data, { resetProject: true });
      settings.addRecent({ kind: 'file', name: picked.name });
      buildRecentSubmenu();
    }
  } catch (err) {
    ws.showError(`Could not open ${picked.name}: ${err.message}`);
  }
}

async function openProjectFile(file) {
  const text = await readFileText(file);
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`${file.name} is not valid JSON, so it isn't a project file.`);
  }
  if (!payload || payload.app !== PROJECT_MARKER || !(payload.worksheets || payload.worksheet)) {
    throw new Error(`${file.name} is not a ${PROJECT_EXT} project file saved by this app.`);
  }
  await restoreProject(payload, file.name);
}

async function restoreProject(payload, fileName) {
  // v1 saved a single `worksheet`; v2 saves the whole list. Both open.
  const saved = payload.worksheets && payload.worksheets.length ? payload.worksheets : [payload.worksheet];

  wm.closeAll();
  clearSessionLog();
  state.results = [];
  state.datasets = []; // opening a project replaces the session, worksheets included
  state.dataset = null;
  state.project = { name: (payload.project && payload.project.name) || fileName.replace(/\.[^.]+$/, ''), description: (payload.project && payload.project.description) || '' };
  state.lastDialog = payload.last_dialog || null;
  constants.set(payload.constants || []);
  anova.restoreModels(payload.models);
  matrices.set(payload.matrices || []);
  calc.restoreSeed(payload.seed);
  reportPane.restore(payload.report);

  const idByIndex = [];
  let rowTotal = 0;
  for (let i = 0; i < saved.length; i += 1) {
    const sheet = saved[i] || {};
    const columns = (sheet.columns || []).map((c) => (typeof c === 'string' ? c : c.name));
    const rows = sheet.rows || [];
    rowTotal += rows.length;
    const name = sheet.name || sheet.source || `Worksheet ${i + 1}`;
    const created = await apiClient.createFromValues(columns, rows, name);
    created.name = name;
    created.touched = true;
    registerDataset(created);
    idByIndex.push(created.dataset_id);
  }

  // Rules were saved against worksheet indices; give them the ids this session just minted.
  conditionalFormat.setRules(payload.formatting || []);
  conditionalFormat.remapWorksheets(idByIndex);

  const activeIndex = Math.min(Math.max(0, payload.active_worksheet || 0), state.datasets.length - 1);
  setDataset(state.datasets[activeIndex], { quiet: true });

  // Restore results first so the log's clickable entries have something to point at.
  const restored = (payload.results || []).map((r) => ({
    id: r.id,
    analysisId: r.analysisId,
    label: r.label,
    values: r.values || null,
    data: r.data,
    // A reopened project keeps each result's original run time; a v2 file has none, and an empty
    // stamp simply leaves that half of the card's metadata line out rather than lying about it.
    at: r.at || '',
    capture: r.capture || null,
    windowId: null,
    win: null,
  }));
  state.results = restored;
  state.nextResultId = restored.reduce((max, r) => Math.max(max, r.id), 0) + 1;

  for (const entry of payload.session || []) {
    const line = { text: entry.text, className: entry.className || 'session-line', resultId: entry.resultId || null, block: entry.block || null };
    if (line.resultId && !restored.some((r) => r.id === line.resultId)) line.resultId = null;
    state.sessionLines.push(line);
    appendSessionNode(line);
  }

  for (const result of restored) openResultWindow(result);

  logSessionLine(
    `> Opened project '${state.project.name}' from ${fileName} — ${state.datasets.length} worksheet(s), ${rowTotal} row(s), ` +
      `${restored.length} result(s), ${constants.count()} constant(s), ${matrices.count()} matri${matrices.count() === 1 ? 'x' : 'ces'}, ` +
      `${conditionalFormat.all().length} formatting rule(s) restored.`,
  );
  settings.addRecent({ kind: 'project', name: fileName });
  buildRecentSubmenu();
  refreshMenuState();
}

const PRINTABLE_KINDS = new Set(['result', 'chart', 'summary']);

function printFocusedWindow() {
  const target = wm.focused();
  if (!target || !PRINTABLE_KINDS.has(target.kind)) return;
  target.el.classList.add('print-target');
  const cleanup = () => {
    target.el.classList.remove('print-target');
    window.removeEventListener('afterprint', cleanup);
  };
  window.addEventListener('afterprint', cleanup);
  try {
    window.print();
  } finally {
    // Some browsers never fire afterprint (or fire it before the dialog closes); a short
    // fallback makes sure the app never gets stuck in its print-only layout.
    setTimeout(cleanup, 1000);
  }
  logSessionLine(`> Printed '${target.title}'.`, 'session-line session-line-muted');
}

function openProjectDescriptionDialog() {
  dialogs.panel({
    title: 'Project Description',
    width: 460,
    render: (close) => {
      const nameInput = h('input', { type: 'text', placeholder: 'analysis-project' });
      nameInput.value = state.project.name;
      const descInput = h('textarea', { placeholder: 'What this project is for, where the data came from, what to look at next…' });
      descInput.value = state.project.description;
      const form = h('form', { class: 'dialog' }, [
        h('p', { class: 'settings-hint', text: `Saved inside the ${PROJECT_EXT} project file.` }),
        h('div', { class: 'field' }, [h('label', { text: 'Title' }), nameInput]),
        h('div', { class: 'field' }, [h('label', { text: 'Description' }), descInput]),
        h('div', { class: 'dialog-actions' }, [
          h('button', { type: 'submit', class: 'btn btn-primary', text: 'Save description' }),
          h('button', { type: 'button', class: 'btn', text: 'Cancel', onClick: close }),
        ]),
      ]);
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        state.project = { name: nameInput.value.trim(), description: descInput.value.trim() };
        renderStatus();
        refreshMenuState();
        logSessionLine('> Project description updated.', 'session-line session-line-muted');
        close();
      });
      return form;
    },
  });
}

function openOptionsDialog() {
  dialogs.panel({
    title: 'Options',
    width: 440,
    render: (close) => {
      const current = settings.get();
      const decimals = h('input', { type: 'number', min: 0, max: 8, step: 1 });
      decimals.value = current.decimals;
      const alpha = h('input', { type: 'number', min: 0.001, max: 0.5, step: 0.001 });
      alpha.value = current.alpha;
      const animations = h('input', { type: 'checkbox' });
      animations.checked = current.animations;
      const menuHelpToggle = h('input', { type: 'checkbox' });
      menuHelpToggle.checked = current.menuHelp;
      const interactiveCharts = h('input', { type: 'checkbox' });
      interactiveCharts.checked = current.interactiveCharts;
      // The menu-bar switch only ever writes an explicit light/dark; "System" is reachable here,
      // and it is what a first visit starts on.
      const themeSelect = h('select', {}, [
        h('option', { value: 'light', text: 'Light' }),
        h('option', { value: 'dark', text: 'Dark' }),
        h('option', { value: 'system', text: 'System' }),
      ]);
      themeSelect.value = current.theme;

      const form = h('form', { class: 'dialog' }, [
        h('div', { class: 'field' }, [
          h('label', { text: 'Theme' }),
          h('div', { class: 'field-inline' }, [
            themeSelect,
            h('span', {
              class: 'settings-hint',
              text: `System follows your OS setting, which is currently ${themeMode.systemPrefersDark() ? 'dark' : 'light'}.`,
            }),
          ]),
        ]),
        h('div', { class: 'field' }, [
          h('label', { text: 'Decimal places in results' }),
          h('div', { class: 'field-inline' }, [decimals, h('span', { class: 'settings-hint', text: 'Values smaller than this show in exponential form.' })]),
        ]),
        h('div', { class: 'field' }, [
          h('label', { text: 'Default significance level (alpha)' }),
          h('div', { class: 'field-inline' }, [alpha, h('span', { class: 'settings-hint', text: 'Prefilled into test forms.' })]),
        ]),
        h('div', { class: 'field' }, [
          h('label', { text: 'Help' }),
          h('label', { class: 'checkbox-item' }, [menuHelpToggle, 'Show menu help on hover']),
          h('p', { class: 'settings-hint', text: 'A short card explaining a menu item, after the pointer rests on it for a moment.' }),
        ]),
        h('div', { class: 'field' }, [
          h('label', { text: 'Charts' }),
          h('label', { class: 'checkbox-item' }, [interactiveCharts, 'Interactive charts']),
          h('p', {
            class: 'settings-hint',
            text: 'On: zoom, pan, hover details, and clickable legends on every chart. Off: plain static charts.',
          }),
        ]),
        h('div', { class: 'field' }, [
          h('label', { text: 'Motion' }),
          h('label', { class: 'checkbox-item' }, [animations, 'Animate windows, charts and counters']),
          settings.prefersReducedMotion
            ? h('p', { class: 'settings-hint', text: 'Your system asks for reduced motion, so animation stays off regardless of this setting.' })
            : null,
        ]),
        h('div', { class: 'dialog-actions' }, [
          h('button', { type: 'submit', class: 'btn btn-primary', text: 'Apply' }),
          h('button', { type: 'button', class: 'btn', text: 'Cancel', onClick: close }),
        ]),
      ]);

      form.addEventListener('submit', (e) => {
        e.preventDefault();
        settings.update({
          decimals: decimals.value,
          alpha: alpha.value,
          animations: animations.checked,
          menuHelp: menuHelpToggle.checked,
          interactiveCharts: interactiveCharts.checked,
          theme: themeSelect.value,
        });
        close();
      });
      return form;
    },
  });
}

// ---------------------------------------------------------------------------
// Help > About
// ---------------------------------------------------------------------------

// The one place the mark appears in accent rather than inheriting the surrounding ink — the same
// treatment the loading state uses. `.brand-mark-accent` sets `color`, so the SVG's currentColor
// resolves to the accent without the asset itself naming a colour.
function openAboutWindow() {
  if (wm.has('about')) {
    wm.focus('about');
    return;
  }
  const markHost = h('div', { class: 'brand-mark-accent about-mark' });
  brand.mountMark(markHost, 56);
  const content = h('div', { class: 'about' }, [
    markHost,
    h('p', { class: 'about-name', text: brand.name }),
    h('p', { class: 'about-version', text: `Version ${brand.version}` }),
    h('p', { class: 'about-namesake', text: brand.namesake }),
    h('p', { class: 'about-credits', text: `Built on ${brand.credits}` }),
  ]);
  wm.createWindow({ id: 'about', title: `About ${brand.name}`, kind: 'result', width: 380, height: 320, content });
  // The mark is fetched, so the panel's real height is only known a tick later; without this the
  // credits line lands under the fold behind a scrollbar.
  requestAnimationFrame(() => wm.fitToContent('about'));
}

let appliedDecimals = settings.get().decimals;
let appliedInteractiveCharts = settings.get().interactiveCharts;

function applySettings(next) {
  document.documentElement.classList.toggle('motion-off', !next.animations);
  // Chart.js needs no CSS for plain mode — charts/theme.js registers no listeners at all in it —
  // but Plotly's modebar is DOM chrome behind a config value that no relayout can reach, so the
  // stylesheet hides it from `:root.charts-plain`. Set here too on first load, before any chart.
  document.documentElement.classList.toggle('charts-plain', !next.interactiveCharts);

  const chartsChanged = next.interactiveCharts !== appliedInteractiveCharts;
  const decimalsChanged = next.decimals !== appliedDecimals;
  appliedInteractiveCharts = next.interactiveCharts;
  appliedDecimals = next.decimals;

  // A chart bakes its interaction options in at construction just as it bakes in its colours, so
  // switching modes means drawing every open one again — the same path, and the same registry, a
  // theme switch uses. That covers result windows, the Assistant's bubbles and, since the Graph
  // Builder preview renders through the same mountChart, its previews too. The extra Plotly call
  // reaches tracked plots whose window is not a result window; reThemeOpenWindows handles the rest
  // in place, because rebuilding a 3D plot would throw away the camera angle.
  if (chartsChanged) {
    applyPlotlyInteractivity();
    reThemeOpenWindows();
    return; // a re-render already picked up any decimals change
  }
  // Re-render open result windows so a decimals change shows up in output already on screen.
  // Guarded on decimals specifically: a theme change lands here too, and the theme handler below
  // already rebuilds every window — without this the toggle would render each one twice.
  if (decimalsChanged) {
    for (const result of state.results) {
      if (result.win && result.windowId && wm.has(result.windowId)) renderResultInto(result, result.win.body);
    }
  }
}

settings.onChange((next) => {
  applySettings(next);
  logSessionLine(
    `> Options applied: ${next.decimals} decimal places, alpha ${next.alpha}, animation ${next.animations ? 'on' : 'off'}, menu help ${next.menuHelp ? 'on' : 'off'}, ${next.interactiveCharts ? 'interactive' : 'plain'} charts, theme ${next.theme}.`,
    'session-line session-line-muted',
  );
});

// ---------------------------------------------------------------------------
// output block actions (the chevron menu on each block of a result window)
// ---------------------------------------------------------------------------

/**
 * The analysis a block belongs to. Matched on the window handle's BODY containing the block — the
 * handle windowManager hands back exposes `body`, not its outer element, so comparing against
 * el.closest('.window') silently never matches and every block ends up labelled "Result".
 */
/** "29 Jul 2026 15:40" — the wording the report cards use, formatted once at run time. */
function runStamp(date = new Date()) {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(date.getDate())} ${months[date.getMonth()]} ${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * The input columns of a result, for a report card's metadata line.
 *
 * Read back out of the dialog's collected `values` rather than recorded separately: every dialog
 * already stores what the user picked, and each config names its column fields differently
 * (`column`, `columns`, `response`, `factors`…). Matching against the worksheet's real column names
 * is what makes one rule work for all 78 dialogs without a per-dialog list to keep in step.
 */
function resultColumns(result) {
  const dataset = activeDataset();
  const known = new Set((dataset?.columns || []).map((c) => (typeof c === 'string' ? c : c.name)));
  const found = [];
  const take = (v) => {
    if (typeof v === 'string' && known.has(v) && !found.includes(v)) found.push(v);
  };
  for (const value of Object.values(result?.values || {})) {
    if (Array.isArray(value)) value.forEach(take);
    else take(value);
  }
  return found.join(', ');
}

/**
 * The report-card fields every export path sends alongside a result's title and data.
 *
 * `result_id` is not part of the API: withPrintCharts uses it to find the live result and re-render its
 * chart for print, then strips it from the payload.
 */
function resultCardFields(result) {
  return {
    analysis_id: result?.analysisId || '',
    columns: resultColumns(result),
    timestamp: result?.at || '',
    result_id: result?.id ?? null,
  };
}

function resultForBlock(el) {
  return state.results.find((r) => r.win && r.win.body && r.win.body.contains(el)) || null;
}

function blockSourceLabel(el) {
  const result = resultForBlock(el);
  return result ? result.label : 'Result';
}

/**
 * This block's position among the CHART blocks of its result window, or 0.
 *
 * Counted over chart blocks only, because that is the order the renderers report their captures in —
 * counting all blocks would index past the end for any result with a table above its figure.
 */
function chartBlockIndex(el) {
  const result = resultForBlock(el);
  if (!result || !result.win || !result.win.body) return 0;
  const charts = [...result.win.body.querySelectorAll('.out-block-chart')];
  const at = charts.indexOf(el);
  return at < 0 ? 0 : at;
}

/**
 * Swap every section's on-screen chart PNG for a print-quality one, where the result is still live.
 *
 * Done at export time rather than at capture time so ordinary interaction never pays for it, and so a
 * section exported from dark mode gets light-themed art without the app having been in light mode. A
 * section whose result has since been closed, or that came out of a reopened project, keeps the PNG it
 * already has — a slightly dark figure beats no figure.
 */
async function withPrintCharts(sections) {
  const out = [];
  for (const section of sections) {
    const result = section.result_id ? state.results.find((r) => r.id === section.result_id) : null;
    const upgraded = result ? await printCapture(result, section.chart_index || 0) : null;
    // result_id / chart_index are ours, not the API's; strip them before the request.
    const { result_id: _id, chart_index: _index, ...payload } = section;
    out.push(upgraded ? { ...payload, chart_image_base64: upgraded } : payload);
  }
  return out;
}

/** One export section describing a single block, in the shape /reports already takes. */
async function blockSection(el, info) {
  const source = blockSourceLabel(el);
  const section = {
    title: `${source} — ${info.name}`.replace(/ — $/, ''),
    data: {},
    chart_path: null,
    chart_image_base64: null,
    // A block exports as the one thing it is. Without this the server's last-resort branch renders a
    // chart out of a table block's own rows and the document gets both.
    allow_generated_chart: false,
    ...resultCardFields(resultForBlock(el)),
  };
  if (info.kind === 'chart') {
    // The chart travels as the picture the user is looking at, which is the same contract the
    // whole-session export uses.
    section.chart_image_base64 = await blockCapture.blockToDataUrl(el, info).catch(() => null);
  } else if (info.rows && info.rows.length) {
    section.data = { tables: [{ title: info.name, rows: info.rows }] };
  } else if (info.text) {
    section.data = { conclusion: info.text };
  }
  return section;
}

/** Ship one block to the server as its own document, and download it. */
async function exportBlock(el, info, format, label) {
  if (!state.dataset) throw new Error('Open a worksheet first.');
  const section = await blockSection(el, info);
  const data = await apiClient.exportReport({
    dataset_id: state.dataset.dataset_id,
    format,
    analyses: [section],
    report_name: safeFileName(`${section.title}`) || null,
    decimals: settings.get().decimals,
  });
  // triggerDownload already exists for the project/report files — reuse it rather than a second copy.
  for (const file of data.files || []) triggerDownload(apiClient.downloadUrl(file), file.split(/[\/]/).pop());
  logSessionLine(`> Sent '${info.name}' to ${label}.`, 'session-line session-line-muted');
  blockMenu.flash(el);
}

/** Tab-separated text, so a pasted table lands in Excel/Sheets as cells — the same convention the
 *  worksheet's own clipboard uses. */
function rowsToTsv(rows) {
  const headers = [];
  for (const row of rows) for (const key of Object.keys(row)) if (!headers.includes(key)) headers.push(key);
  const lines = [headers.join('\t')];
  for (const row of rows) lines.push(headers.map((hd) => formatCell(row[hd])).join('\t'));
  return lines.join('\n');
}

async function copyBlock(el, info) {
  if (info.kind === 'chart') {
    await copyImageToClipboard(await blockCapture.blockToBlob(el, info));
    logSessionLine(`> Copied '${info.name}' as a picture.`, 'session-line session-line-muted');
    blockMenu.flash(el);
    return;
  }
  const text = info.rows && info.rows.length ? rowsToTsv(info.rows) : info.text || (info.body ? info.body.innerText : '');
  if (!text) throw new Error('There is nothing in this block to copy.');
  await navigator.clipboard.writeText(text);
  logSessionLine(`> Copied '${info.name}'.`, 'session-line session-line-muted');
  blockMenu.flash(el);
}

async function copyImageToClipboard(blob) {
  if (!navigator.clipboard || typeof ClipboardItem === 'undefined' || !navigator.clipboard.write) {
    throw new Error('This browser cannot put an image on the clipboard. Use Send to Word instead.');
  }
  await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
}

async function copyBlockAsPicture(el, info) {
  await copyImageToClipboard(await blockCapture.blockToBlob(el, info));
  logSessionLine(`> Copied '${info.name}' as a picture.`, 'session-line session-line-muted');
  blockMenu.flash(el);
}

/** Print one block, reusing the print stylesheet's single-target mechanism. */
function printBlock(el, info) {
  el.classList.add('block-print-target');
  document.documentElement.classList.add('printing-block');
  const cleanup = () => {
    el.classList.remove('block-print-target');
    document.documentElement.classList.remove('printing-block');
    window.removeEventListener('afterprint', cleanup);
  };
  window.addEventListener('afterprint', cleanup);
  try {
    window.print();
  } finally {
    // Same belt-and-braces as printFocusedWindow: some browsers never fire afterprint, and the app
    // must not be left in its print-only layout.
    setTimeout(cleanup, 1000);
  }
  logSessionLine(`> Printed '${info.name}'.`, 'session-line session-line-muted');
}

async function sendBlockToReport(el, info, { fullTable = false } = {}) {
  // A chart's capture IS its export image, so it is kept full size. Everything else exports from its
  // rows or its text, so it only needs a thumbnail — which keeps the .baproj from carrying a
  // megabyte of table pictures nothing renders at that size.
  const capture = await (info.kind === 'chart' ? blockCapture.blockToDataUrl(el, info) : blockCapture.blockToThumbDataUrl(el, 240, info)).catch(() => null);
  const staged = {
    kind: info.kind,
    name: info.name,
    source: blockSourceLabel(el),
    capture,
    // Staged deliberately as a FULL table: the report keeps every row instead of cutting it at
    // REPORT_TABLE_ROW_LIMIT. Travels in the .baproj with the rest of the staged block.
    fullTable: !!fullTable,
    text: info.text || '',
    data: info.rows && info.rows.length ? { tables: [{ title: info.name, rows: info.rows }] } : info.text ? { conclusion: info.text } : {},
    // Captured now, not at export time: the result window this block came from may be closed by then,
    // and a staged block outlives it — it is saved in the project.
    card: {
      ...resultCardFields(resultForBlock(el)),
      // Which of the result's charts this block is, so the export re-renders THIS figure for print
      // and not the first one in a result that draws several.
      chart_index: chartBlockIndex(el),
    },
  };
  reportPane.add(staged);
  reportPane.reveal();
  blockMenu.flash(el);
  logSessionLine(`> Added '${info.name}' to report.`, 'session-line session-line-muted');
}

/**
 * Halt any Chart.js animation inside a block that is about to be detached. Without this, deleting a
 * chart block mid-animation throws `this._fn is not a function` from inside Chart.js's animation
 * tick, every frame, because the animator keeps running against a canvas that is no longer in the
 * document. `stop()` rather than `destroy()`: the canvas keeps its last painted frame, so Undo can
 * re-insert the very same node and the chart is still there.
 */
function stopChartsIn(el) {
  if (typeof Chart === 'undefined' || !Chart.getChart) return;
  for (const canvas of el.querySelectorAll('canvas')) {
    const chart = Chart.getChart(canvas);
    if (!chart) continue;
    try {
      chart.stop();
    } catch {
      // Chart.js's own stop() walks its pending animations to cancel them, so a chart animating a
      // property it cannot interpolate throws from in here too. A cleanup helper must never be the
      // thing that fails an action — the canvas is about to be discarded either way.
    }
  }
}

/** Remove a block from its window, recoverably. Removing the last one closes the window. */
function removeBlock(el, info) {
  const parent = el.parentElement;
  const next = el.nextSibling;
  const win = el.closest('.window');
  const result = resultForBlock(el);
  stopChartsIn(el);
  el.remove();
  const remaining = win ? win.querySelectorAll('.out-block').length : 1;
  const closed = remaining === 0 && result && result.windowId && wm.has(result.windowId);
  if (closed) wm.close(result.windowId);
  blockMenu.offerUndo(`Removed '${info.name}'.`, () => {
    if (closed) {
      // The window is gone, so put the block back by re-rendering the result from its record.
      openResultWindow(result);
      return;
    }
    if (next) parent.insertBefore(el, next);
    else parent.appendChild(el);
  });
  logSessionLine(`> Removed '${info.name}' from '${result ? result.label : 'result'}'.`, 'session-line session-line-muted');
}

blockMenu.init({
  sendToWord: (el, info) => exportBlock(el, info, 'docx', 'Word'),
  sendToPowerPoint: (el, info) => exportBlock(el, info, 'pptx', 'PowerPoint'),
  sendToReport: sendBlockToReport,
  copy: copyBlock,
  copyAsPicture: copyBlockAsPicture,
  print: printBlock,
  remove: removeBlock,
  notify: (message) => logSessionLine(`> ${message}`, 'session-line session-line-error'),
  // Everything applies to every block except exporting one with no worksheet behind it.
  disabledReason: (id, info) => {
    if ((id === 'word' || id === 'pptx') && !state.dataset) return 'Open a worksheet first — an export is written against a dataset.';
    if (id === 'copy' && info.kind === 'tiles' && !(info.rows || []).length) return 'This block has no values to copy.';
    // The full-table staging is only on offer when there is a long table to include; the ordinary
    // Send to Report already carries everything shorter than the truncation threshold.
    if (id === 'report-full' && (info.rows || []).length <= REPORT_TABLE_ROW_LIMIT) {
      return `A table is only shortened in a report past ${REPORT_TABLE_ROW_LIMIT} rows — this one exports in full already.`;
    }
    return null;
  },
});

reportPane.init({
  openExport: () => openExportDialog({ scope: 'report' }),
  confirm: (message) => dialogs.ask({ title: 'Report', message, buttons: [{ label: 'Remove all', value: true, primary: true }, { label: 'Cancel', value: false }] }),
});

// ---------------------------------------------------------------------------
// theme switching
// ---------------------------------------------------------------------------

// Everything made of DOM re-themes itself through the CSS variables. Canvases do not: Chart.js
// copies the axis, grid and tooltip colours into each chart's own options object when the chart is
// built, so no amount of .update() will refresh an existing one — it has to be drawn again. Every
// result window still holds the data and render function it came from, so "draw again" is just a
// re-render of the same record, through the same path a decimals change uses.
//
// Plotly is the exception: rebuilding a 3D plot would discard the camera angle the user rotated
// to, so tracked plots are re-layouted in place instead (charts/plotly.js).
function reThemeOpenWindows() {
  theme.refresh();

  let rebuilt = 0;
  for (const result of state.results) {
    if (!result.win || !result.windowId || !wm.has(result.windowId)) continue;
    if (hasTrackedPlot(result.win.body)) applyPlotlyTheme(result.win.body);
    else renderResultInto(result, result.win.body);
    rebuilt += 1;
  }
  rebuilt += reThemeChatBubbles();
  return rebuilt;
}

themeMode.onChange((next) => {
  const rebuilt = reThemeOpenWindows();
  logSessionLine(`> Theme: ${next}${rebuilt ? ` — ${rebuilt} open window(s) redrawn` : ''}.`, 'session-line session-line-muted');
});

themeMode.mountToggle(document.getElementById('theme-toggle'));

// ---------------------------------------------------------------------------
// assistant window — the chat panel keeps its history across close/reopen by
// reusing the same DOM node.
// ---------------------------------------------------------------------------
// The assistant holds NO dataset of its own. Every message resolves activeDataset() as it is
// submitted, so loading a file, creating a blank worksheet or opening a project is reflected in
// the very next answer, and the examples it offers are written in the active dataset's real
// column names.

let chatPanel = null;
let chatHistory = null;
let chatInput = null;
let chatSend = null;
let chatWin = null; // window handle while the Assistant window is open (for its title-bar context)
let chatBusy = false;

// A chart in the transcript belongs to no result window, so it has no record to re-render from on
// a theme switch. The bubbles that carry one are remembered here for exactly that.
const chatResultBubbles = [];

// Redraws the answer part of every tracked bubble, leaving the assistant's own text alone.
function reThemeChatBubbles() {
  let redrawn = 0;
  for (let i = chatResultBubbles.length - 1; i >= 0; i -= 1) {
    const rec = chatResultBubbles[i];
    if (!rec.bubble.isConnected) {
      chatResultBubbles.splice(i, 1); // the transcript was cleared — drop the record
      continue;
    }
    for (const node of [...rec.bubble.children]) {
      if (!node.classList.contains('chat-text')) node.remove();
    }
    renderResultBody(rec.bubble, rec.analysisId, rec.data, { hideNarrative: true, compact: true });
    redrawn += 1;
  }
  return redrawn;
}

function addChatMessage(role, text, data, analysisId) {
  const bubble = h('div', { class: 'chat-bubble' });
  if (text) bubble.appendChild(h('p', { class: 'chat-text', text }));
  if (data) {
    renderResultBody(bubble, analysisId, data, { hideNarrative: true, compact: true });
    chatResultBubbles.push({ bubble, analysisId, data });
  }
  const msg = h('div', { class: `chat-message chat-message-${role}` }, [bubble]);
  chatHistory.appendChild(msg);
  requestAnimationFrame(() => chatHistory.scrollTo({ top: chatHistory.scrollHeight, behavior: noMotion() ? 'auto' : 'smooth' }));
  return msg;
}

// A context line rather than a bubble: it is the app telling you what the assistant is looking
// at, not the assistant answering something.
function addChatNote(text) {
  if (!chatHistory) return;
  chatHistory.appendChild(h('div', { class: 'chat-note', text }));
  requestAnimationFrame(() => chatHistory.scrollTo({ top: chatHistory.scrollHeight, behavior: noMotion() ? 'auto' : 'smooth' }));
}

function datasetListReply() {
  if (!state.datasets.length) return GENERIC_HELP;
  const lines = state.datasets.map((r) => `- ${r.source} — ${r.row_count} rows × ${r.columns.length} cols${r === state.dataset ? '  (active)' : ''}`);
  const head = state.datasets.length === 1 ? 'One dataset is loaded in this session:' : `${state.datasets.length} datasets are loaded in this session:`;
  const tail = state.datasets.length > 1 ? '\nSay "use <name>" to switch — the worksheet follows.' : '';
  return `${head}\n${lines.join('\n')}${tail}`;
}

function handleSwitchRequest(name) {
  const hit = matchDataset(name, state.datasets);
  if (hit.dataset) {
    if (hit.dataset === state.dataset) {
      addChatMessage('bot', `Already working with ${datasetLabel(hit.dataset)}.`);
      return;
    }
    // The dataset-change listener posts the confirmation, so a switch made from the menu or the
    // File dialog announces itself exactly the same way.
    switchToDataset(hit.dataset);
    return;
  }
  if (hit.ambiguous) {
    addChatMessage('bot', `"${name.trim()}" matches ${hit.ambiguous.map((r) => r.source).join(' and ')}. Which one did you mean?`);
    return;
  }
  addChatMessage('bot', `I don't have a dataset called "${name.trim()}" loaded.\n${datasetListReply()}`);
}

function buildChatPanel() {
  chatHistory = h('div', { class: 'chat-history' });
  chatInput = h('input', { type: 'text', placeholder: 'Ask about the data…', 'aria-label': 'Ask about the data' });
  chatSend = h('button', { type: 'submit', class: 'btn btn-primary', text: 'Send' });
  const form = h('form', { class: 'chat-input-row' }, [chatInput, chatSend]);
  chatPanel = h('div', { class: 'chat-panel' }, [chatHistory, form]);

  // The Assistant says what it is, once, when its panel is first built. Everything after this is a
  // reply to something the user actually asked.
  addChatMessage(
    'bot',
    `${brand.name}'s assistant. Ask about the worksheet in plain language — "describe the data", ` +
      `"correlation between two columns", "forecast the last column" — or use the Stat and Graph menus for the full set of procedures.`,
  );

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text || chatBusy) return;
    chatInput.value = '';
    addChatMessage('user', text);

    // Resolved per message, never cached: this is the whole reason the assistant follows the
    // worksheet instead of answering about whatever was loaded first.
    const active = activeDataset();
    const parsed = parseCommand(text, active);

    switch (parsed.action) {
      case 'no-dataset':
        addChatMessage('bot', 'I have no worksheet yet — the blank one may still be loading, or you can open a file from the File menu. Ask me again once it is there.');
        return;
      case 'help':
        addChatMessage('bot', buildWelcome(active, otherDatasetNames()));
        return;
      case 'columns':
        addChatMessage('bot', active ? columnListReply(active) : GENERIC_HELP);
        return;
      case 'list-datasets':
        addChatMessage('bot', datasetListReply());
        return;
      case 'switch-dataset':
        handleSwitchRequest(parsed.params.name);
        return;
      case 'error':
        addChatMessage('bot', parsed.message);
        return;
      case 'unknown':
        addChatMessage('bot', buildHelpText(active, otherDatasetNames()));
        return;
      default:
        break;
    }

    chatBusy = true;
    chatSend.disabled = true;
    const busyMessage = addChatMessage('bot', 'Working…');
    busyMessage.querySelector('.chat-text').classList.add('pulse-text', 'status');
    try {
      const data = await runAnalysis(parsed.action, active.dataset_id, parsed.params);
      const narrative = data.conclusion || data.interpretation || data.summary || 'Done — see the result below.';
      busyMessage.remove();
      // If a different dataset became active while this ran, say which data the answer is about
      // rather than letting it read as an answer about the new worksheet.
      const stale = activeDataset() !== active;
      addChatMessage('bot', stale ? `From ${active.source}: ${narrative}` : narrative, data, parsed.action);
      // Chat results are logged and kept in state like any other run, so they can be exported
      // and reopened as their own window from the Session Window.
      addResult(parsed.action, `${ANALYSIS_LABEL_BY_ID[parsed.action] || parsed.action} (assistant)`, data, { open: false });
    } catch (err) {
      busyMessage.remove();
      addChatMessage('bot', `Error: ${err.message}`);
    } finally {
      chatBusy = false;
      chatSend.disabled = false;
    }
  });

  // Built from the dataset that is active right now — not a hardcoded example dataset.
  addChatMessage('bot', buildWelcome(activeDataset(), otherDatasetNames()));
  return chatPanel;
}

function openChatWindow() {
  if (wm.has('chat')) {
    wm.focus('chat');
    return;
  }
  if (!chatPanel) buildChatPanel();
  chatWin = wm.createWindow({
    id: 'chat',
    title: 'Assistant',
    kind: 'chat',
    content: chatPanel,
    onClose: () => {
      chatWin = null;
    },
  });
  chatWin.body.classList.add('win-body-flush');
  // The one honest signal of context that is visible without scrolling the history.
  chatWin.setSubtitle(activeDataset() ? activeDataset().source : 'no worksheet');
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

// Anything that changes the active dataset — a file load, a blank worksheet, opening a project,
// or "use <name>" — lands here, so the assistant's context is announced the same way every time.
onActiveDatasetChange((dataset) => {
  if (chatWin) chatWin.setSubtitle(dataset ? dataset.source : 'no worksheet');
  if (chatPanel && dataset) addChatNote(`Now working with ${datasetLabel(dataset)}.`);
});

// ---------------------------------------------------------------------------
// menu bar
// ---------------------------------------------------------------------------

const menubar = document.getElementById('menubar');
const menuEls = Array.from(document.querySelectorAll('.menu'));

function anyMenuOpen() {
  return menuEls.some((m) => m.classList.contains('open'));
}

function closeAllMenus() {
  menus.closeFlyouts();
  for (const m of menuEls) m.classList.remove('open');
  menuHelp.hide(); // a card positioned against a panel that no longer exists must not linger
}

function item(action) {
  return menubar.querySelector(`.menu-item[data-action="${action}"]`);
}

function setEnabled(action, enabled) {
  const el = item(action);
  if (!el) return;
  el.disabled = !enabled;
  el.setAttribute('aria-disabled', String(!enabled));
}

// Menus reflect what is actually possible right now, the way a desktop menu does.
function refreshMenuState() {
  const hasDataset = !!state.dataset;
  const range = ws.selection();
  const focusedWin = wm.focused();

  setEnabled('undo', ws.canUndo());
  setEnabled('redo', ws.canRedo());
  setEnabled('clear', !!range);
  setEnabled('delete', !!range);
  setEnabled('copy', !!range);
  setEnabled('cut', !!range);
  setEnabled('paste', !!range);
  setEnabled('select-all', hasDataset);
  setEnabled('edit-last-dialog', !!state.lastDialog);

  setEnabled('save-project', hasDataset);
  setEnabled('save-project-as', hasDataset);
  setEnabled('export-report', state.results.some((r) => r.analysisId !== 'export'));
  setEnabled('print', !!focusedWin && PRINTABLE_KINDS.has(focusedWin.kind));

  // Project Description reads as unset until there is something in it.
  item('project-description').classList.toggle('menu-item-muted', !state.project.description && !state.project.name);

  // Stat > ANOVA's General Linear Model / Mixed Effects submenus grey out everything downstream of
  // a fit until there is one to work from.
  anova.refreshMenuState();
}

function buildRecentSubmenu() {
  const host = document.getElementById('recent-submenu');
  host.innerHTML = '';
  const entries = settings.recent();
  if (!entries.length) {
    host.appendChild(h('div', { class: 'submenu-empty', text: 'Nothing opened yet' }));
    return;
  }
  for (const entry of entries) {
    const isLink = entry.kind === 'gsheet';
    const btn = h('button', {
      type: 'button',
      class: 'menu-item',
      title: isLink
        ? entry.url
        : 'Browsers cannot reopen a local file without you choosing it again — this opens the file chooser.',
      onClick: async () => {
        closeAllMenus();
        if (isLink) {
          try {
            await loadGSheet(entry.url);
          } catch (err) {
            openImportWindow(err.message);
          }
        } else {
          openImportWindow(`Choose "${entry.name}" again to reopen it — a browser cannot read a local path on its own.`);
        }
      },
    });
    btn.dataset.icon = 'recent-file';
    btn.dataset.help = isLink
      ? 'Reloads this Google Sheet, replacing the active worksheet with what the sheet holds now.'
      : 'Reopens a file used earlier. A browser cannot read a saved path on its own, so this opens the file chooser at this file.';
    btn.append(h('span', { class: 'mi-label', text: entry.name }), h('span', { class: 'mi-key', text: entry.kind === 'project' ? 'project' : entry.kind === 'gsheet' ? 'sheet' : 'file' }));
    host.appendChild(btn);
  }
  // Built by hand rather than from a config, so it needs the icon slot put in explicitly.
  menus.hydrateIcons(host);
}

// Tracks whether the currently open menu was opened by sliding across the bar rather than by a
// click. Without it, clicking a second menu's trigger would read as "click the already-open
// menu" — because the pointer entering the trigger has already switched to it — and close
// everything instead of leaving the new menu open.
let openedByHover = false;

function openMenu(menu) {
  closeAllMenus();
  refreshMenuState();
  menu.classList.add('open');
  menus.placeDropdown(menu); // never let a dropdown run off the bottom of the viewport
}

for (const menu of menuEls) {
  const trigger = menu.querySelector('.menu-trigger');
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const shouldClose = menu.classList.contains('open') && !openedByHover;
    openedByHover = false;
    if (shouldClose) closeAllMenus();
    else openMenu(menu);
  });
  // Once a menu is open, hovering across the bar switches menus — standard menu-bar behavior.
  trigger.addEventListener('mouseenter', () => {
    if (anyMenuOpen() && !menu.classList.contains('open')) {
      openMenu(menu);
      openedByHover = true;
    }
  });
}

document.addEventListener('click', () => {
  openedByHover = false;
});

document.addEventListener('click', closeAllMenus);

const sessionToggleItem = document.querySelector('[data-action="toggle-session"]');

const ACTIONS = {
  // File
  'new-worksheet': newWorksheet,
  'new-project': newProject,
  open: () => openViaNativeDialog(),
  'save-project': () => saveProject(),
  'save-project-as': () => saveProject({ promptForName: true }),
  'export-report': openExportDialog,
  print: printFocusedWindow,
  'project-description': openProjectDescriptionDialog,
  options: openOptionsDialog,
  exit: exitToBlank,
  // Edit
  undo: () => ws.undo().then(refreshMenuState),
  redo: () => ws.redo().then(refreshMenuState),
  clear: () => ws.clearSelection().then(refreshMenuState),
  delete: () => ws.deleteSelection().then(refreshMenuState),
  copy: () => ws.copySelection(),
  cut: () => ws.cutSelection().then(refreshMenuState),
  paste: () => ws.pasteFromClipboard().then(refreshMenuState),
  'select-all': () => {
    ws.selectAll();
    refreshMenuState();
  },
  'edit-last-dialog': reopenLastDialog,
  // Window > Icon Gallery — the dev view of icons/registry.js, for checking the set in both themes
  'icon-gallery': () => iconGallery.open(),
  report: () => reportPane.open(),
  // Help
  about: openAboutWindow,
  // Data
  import: () => openImportWindow(),
  summary: openSummaryWindow,
  'reload-worksheet': () => ws.render(),
  constants: () => constants.openWindow(),
  // Data > Conditional Formatting — one entry per rule kind, plus manage/clear
  ...Object.fromEntries(conditionalFormat.RULE_KINDS.map((kind) => [`cf-${kind.kind}`, () => conditionalFormat.openRuleDialog(kind.kind)])),
  'cf-manage': () => conditionalFormat.openManageWindow(),
  'cf-clear-column': () => {
    const column = ws.selectedColumnName();
    if (!column) {
      ws.showError('Click a cell in the column whose rules you want to clear, then try again.');
      return;
    }
    const removed = conditionalFormat.clearColumn(state.dataset.dataset_id, column);
    logSessionLine(removed ? `> Cleared ${removed} formatting rule(s) on '${column}'.` : `> '${column}' had no formatting rules.`, 'session-line session-line-muted');
  },
  'cf-clear-all': async () => {
    const count = conditionalFormat.forWorksheet(state.dataset.dataset_id).length;
    if (!count) {
      logSessionLine('> This worksheet has no formatting rules.', 'session-line session-line-muted');
      return;
    }
    const ok = await dialogs.confirm({
      title: 'Clear Rules',
      message: `Remove all ${count} conditional formatting rule(s) on this worksheet?`,
      confirmLabel: 'Clear rules',
      danger: true,
    });
    if (!ok) return;
    conditionalFormat.clearWorksheet(state.dataset.dataset_id);
    logSessionLine(`> Cleared ${count} conditional formatting rule(s).`);
  },
  // Window
  chat: openChatWindow,
  cascade: () => wm.cascade(),
  'close-all': () => wm.closeAll(),
  'toggle-session': () => {
    const hidden = sessionWindow.hidden;
    sessionWindow.hidden = !hidden;
    const label = sessionToggleItem.querySelector('.mi-label') || sessionToggleItem;
    label.textContent = hidden ? 'Hide Session Window' : 'Show Session Window';
  },
};

menubar.addEventListener('click', (e) => {
  const el = e.target.closest('.menu-item');
  if (!el) return;
  // Inert items swallow the click without closing the menu. A truly disabled button gets that for
  // free (it dispatches no click at all); an aria-disabled one — kept clickable so its "why not"
  // tooltip can appear — has to be stopped here before the document-level closer sees it.
  if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
    e.stopPropagation();
    return;
  }
  if (el.classList.contains('menu-item-submenu')) return; // a category, handled by menu.js
  const action = el.dataset.action;
  if (action && ACTIONS[action]) ACTIONS[action]();
  else if (el.dataset.graph) graphs.openGraph(el.dataset.graph);
  else if (el.dataset.stat) openStatDialog(el.dataset.stat);
  else if (el.dataset.data) dataMenu.open(el.dataset.data);
  else if (el.dataset.calc) calc.open(el.dataset.calc);
  else if (el.dataset.analysis) openToolWindow(el.dataset.analysis);
  closeAllMenus();
});

document.getElementById('worksheet-import-btn').addEventListener('click', () => openImportWindow());

// ---------------------------------------------------------------------------
// global keyboard shortcuts
//
// File-level shortcuts fire from anywhere: Chrome's own Ctrl+S / Ctrl+P / Ctrl+O dialogs are
// never what someone wants in a data tool, so those are always intercepted. The editing
// shortcuts (Ctrl+A/C/X/V/Z/Y, Delete) only act on the worksheet — inside a form field or the
// assistant's input they are left to the browser, so normal text editing keeps working.
// ---------------------------------------------------------------------------

function isWorksheetCell(el) {
  return !!el && el.classList && el.classList.contains('worksheet-cell-input') && !el.classList.contains('worksheet-header-input');
}

function isTextEntry(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'TEXTAREA' || tag === 'SELECT' || (tag === 'INPUT' && !['checkbox', 'radio', 'button', 'file'].includes(el.type));
}

document.addEventListener('keydown', async (e) => {
  if (e.key === 'Escape') {
    if (anyMenuOpen()) {
      closeAllMenus();
      return;
    }
    wm.closeFocused();
    refreshMenuState();
    return;
  }

  const active = document.activeElement;
  const inCell = isWorksheetCell(active);
  const inOtherTextEntry = !inCell && isTextEntry(active);
  const ctrl = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();

  if (ctrl) {
    // always-on, whatever has focus
    if (key === 'n') {
      e.preventDefault();
      if (e.shiftKey) newProject();
      else newWorksheet();
      return;
    }
    if (key === 'o') {
      e.preventDefault();
      openImportWindow();
      return;
    }
    if (key === 's') {
      e.preventDefault();
      saveProject();
      return;
    }
    if (key === 'p') {
      e.preventDefault();
      printFocusedWindow();
      return;
    }
    if (key === 'e') {
      e.preventDefault();
      reopenLastDialog();
      return;
    }

    // worksheet-only editing shortcuts
    if (inOtherTextEntry) return;
    if (key === 'z') {
      e.preventDefault();
      await ws.undo();
      refreshMenuState();
      return;
    }
    if (key === 'y') {
      e.preventDefault();
      await ws.redo();
      refreshMenuState();
      return;
    }
    if (key === 'a') {
      e.preventDefault();
      ws.selectAll();
      refreshMenuState();
      return;
    }
    if (key === 'c' || key === 'x') {
      // With a single cell in play, let the browser copy the text inside it; a real range
      // means the user wants the block as tab-separated values.
      if (inCell && ws.selectionSize() <= 1) return;
      e.preventDefault();
      if (key === 'c') await ws.copySelection();
      else await ws.cutSelection();
      refreshMenuState();
      return;
    }
    if (key === 'v') {
      // Inside a cell the browser fires a native paste event that the grid already handles —
      // intercepting here too would paste twice.
      if (inCell) return;
      e.preventDefault();
      await ws.pasteFromClipboard();
      refreshMenuState();
      return;
    }
    return;
  }

  if ((e.key === 'Delete' || e.key === 'Backspace') && !inOtherTextEntry) {
    // A single cell being edited keeps normal text editing; a selected range clears.
    if (ws.selectionSize() > 1) {
      e.preventDefault();
      await ws.clearSelection();
      refreshMenuState();
    }
  }
});

// Keep Edit-menu enablement in step with the selection made by mouse or keyboard.
document.getElementById('worksheet-layer').addEventListener('pointerup', () => refreshMenuState());
document.getElementById('window-layer').addEventListener('pointerup', () => refreshMenuState());

// ---------------------------------------------------------------------------
// startup — the worksheet is the default document, so create a blank one
// immediately, the way Minitab always has a worksheet ready before you have
// typed anything or imported a file.
// ---------------------------------------------------------------------------

ws.init({
  log: (text) => logSessionLine(text),
  // Conditional formatting is computed by conditionalFormat.js and painted by the grid: the grid
  // asks for a colour per cell, and knows nothing about what a rule is.
  formatting: {
    prepare: (worksheetId, grid) => conditionalFormat.prepare(worksheetId, grid),
    colorFor: (column, rowIndex) => conditionalFormat.colorFor(column, rowIndex),
  },
  onGridChanged: ({ columns, rows }) => {
    if (state.dataset) {
      // The registry holds this same object, so the active dataset's schema stays current
      // everywhere — including in the assistant's column matching — as the grid is edited.
      state.dataset.columns = columns;
      state.dataset.row_count = rows.length;
      // Once there is data in it, a blank worksheet is real work and stays in the registry.
      if (!state.dataset.touched && ws.hasData()) state.dataset.touched = true;
      renderStatus();
      renderTabs();
    }
    refreshMenuState();
  },
});

conditionalFormat.init({
  log: (text) => logSessionLine(text),
  dataset: () => state.dataset,
  gridValues: () => ws.contents().rows,
  // Any change to the rules redraws the grid (which recomputes them) and the Manage window.
  repaint: () => {
    if (state.dataset) ws.render();
    conditionalFormat.refreshManageWindow();
  },
});

constants.init({
  log: (text) => logSessionLine(text),
  onChange: () => refreshMenuState(),
});

matrices.init({
  log: (text) => logSessionLine(text),
  onChange: () => refreshMenuState(),
});

// The column pickers in every dialog read the schema and the categories out of the live grid; the
// Data menu's cross-worksheet dialogs also need the other open worksheets and the constants store.
procedureDialog.init({
  dataset: () => state.dataset,
  gridValues: () => ws.contents().rows,
  worksheets: () => state.datasets,
  constants: () => constants.list().map((c) => ({ key: c.key, label: constants.label(c) })),
  storedModel: () => anova.activeModelSpec(),
  matrices: () => matrices.options(),
});

// A Stat procedure result is an ordinary result record with its own renderer, so it gets a window, a
// clickable Session Window entry, and a place in exports like every other analysis.
const statContext = {
  dataset: () => state.dataset,
  log: (text) => logSessionLine(text),
  onRun: (statId, values) => {
    state.lastDialog = { statId, values: JSON.parse(JSON.stringify(values)) };
    refreshMenuState();
  },
  addResult: ({ analysisId, label, data, kind, values, render, width }) => addResult(analysisId, label, data, { values, render, kind, width }),
};

basicStats.init({
  ...statContext,
  gridValues: () => ws.contents().rows,
  // Store Descriptive Statistics writes real worksheet columns, as one undoable step
  storeColumns: (specs) => ws.storeColumns(specs),
});
regression.init(statContext);

anova.init({
  ...statContext,
  // A fitted model is part of the session, so it is saved with the project and restored with it.
  onModelStored: () => refreshMenuState(),
});

calc.init({
  dataset: () => state.dataset,
  gridValues: () => ws.contents().rows,
  log: (text) => logSessionLine(text),
  logBlock: (title, text) => logSessionBlock(title, text),
  addResult: ({ analysisId, label, data, kind, values, render, width }) => addResult(analysisId, label, data, { values, render, kind, width }),
  onRun: (calcId, values) => {
    state.lastDialog = { calcId, values: JSON.parse(JSON.stringify(values)) };
    refreshMenuState();
  },
  applyDataOp: (response, meta) => applyDataOp(response, meta),
  snapshot: () => ws.snapshotNow(),
  commitEdit: (label, before) => ws.commitExternalEdit(label, before),
  onSeedChange: () => refreshMenuState(),
});

dataMenu.init({
  dataset: () => state.dataset,
  worksheets: () => state.datasets,
  gridValues: () => ws.contents().rows,
  selectedRows: () => ws.selectedRowIndices(),
  log: (text) => logSessionLine(text),
  logBlock: (title, text) => logSessionBlock(title, text),
  addResult: ({ analysisId, label, data, kind, values, render, width }) => addResult(analysisId, label, data, { values, render, kind, width }),
  onRun: (dataId, values) => {
    state.lastDialog = { dataId, values: JSON.parse(JSON.stringify(values)) };
    refreshMenuState();
  },
  applyDataOp: (response, meta) => applyDataOp(response, meta),
  snapshot: () => ws.snapshotNow(),
  commitEdit: (label, before) => ws.commitExternalEdit(label, before),
});

// Data, Stat and Graph are all generated from nested configs and share menu.js's flyout behaviour.
// The Data menu mirrors Minitab's own structure and order; Basic Statistics and Regression lead
// the Stat menu, each listing Minitab's items in its own grouping and order.
menus.buildDropdown('data', dataMenu.menuConfig());
menus.buildDropdown('calc', calc.menuConfig());
menus.buildDropdown('stat', [
  { label: 'Basic Statistics', items: basicStats.menuConfig() },
  { label: 'Regression', items: regression.menuConfig() },
  { label: 'ANOVA', items: anova.menuConfig() },
  ...STAT_MENU,
]);
// File, Edit and Window are static markup rather than configs, so their icon slots are put in from
// their data-icon attributes. Runs after the generated menus so one pass covers the whole bar.
menus.hydrateIcons();
menus.initMenus();
menuHelp.init(); // the hover/focus help card; reads data-help / data-needs off the items above

graphs.init({
  dataset: () => state.dataset,
  log: (text) => logSessionLine(text),
  // A graph result is an ordinary result record with its own renderer, so it gets a window, a
  // clickable Session Window entry, and a place in exports like every other analysis.
  addGraphResult: ({ analysisId, label, data, kind, values, render }) => addResult(analysisId, label, data, { values, render, kind }),
});

applySettings(settings.get());
brand.mountLogo(document.getElementById('app-logo')); // the app name at the left of the menu bar
iconGallery.initHashRoute(); // #icons opens the gallery without going through the menu
buildRecentSubmenu();
refreshMenuState();
logSessionLine('> Session started.', 'session-line session-line-muted');

apiClient
  .createBlankDataset('Worksheet 1')
  .then(async (data) => {
    setDataset(data, { quiet: true });
    // The Calc menu's Random Data and Probability Distributions submenus are generated from the
    // backend's own catalogue, so the two can never list different distributions. The menu is
    // already built without them; this fills those two flyouts in once the list arrives.
    try {
      const loaded = await calc.loadCatalogue(data.dataset_id);
      menus.buildDropdown('calc', calc.menuConfig());
      logSessionLine(`> Calc ready: ${loaded.functions} function categories, ${loaded.distributions} distributions.`, 'session-line session-line-muted');
    } catch (err) {
      logSessionLine(`> The Calc distribution catalogue could not be loaded (${err.message}). The Calculator and the other Calc dialogs still work.`, 'session-line session-line-muted');
    }
  })
  .catch((err) => {
    ws.showError(`Could not create a blank worksheet: ${err.message}`);
    openImportWindow(`Could not create a blank worksheet (${err.message}). You can still open a file here.`);
  })
  .finally(() => {
    // Registered LAST, and in `finally` so a failed blank worksheet does not cost us the handler.
    //
    // The desktop shell holds a .gsp that arrived on the command line until this call tells it the
    // renderer can take one, so this is what makes a cold double-click work. It has to come after
    // the blank-worksheet promise settles: restoreProject() replaces state.datasets wholesale, and
    // if the default worksheet were still in flight it would arrive afterwards and appear as a
    // stray second tab in the project the user just opened.
    desktop.onOpenProject(async ({ name, text }) => {
      try {
        await openProjectText(text, name);
      } catch (err) {
        ws.showError(`Could not open ${name}: ${err.message}`);
      }
    });
  });
