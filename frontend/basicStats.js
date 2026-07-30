// Stat > Basic Statistics: the 18 Minitab procedures. The form builder and the standard result
// layout come from procedureDialog.js (shared with regression.js); what is specific to this menu is
// the registry, the Graphical Summary one-pager, and Store Descriptive Statistics writing its
// results into the worksheet.

import { apiClient } from './apiClient.js';
import * as wm from './windowManager.js';
import { PROCEDURE_BY_ID, BASIC_STATS_MENU, buildRequest, describe } from './basicStatsConfig.js';
import * as dialog from './procedureDialog.js';
import { h, buildStatGrid, buildTableBlock } from './resultView.js';
import * as settings from './settings.js';

let ctx = {
  dataset: () => null,
  gridValues: () => [],
  storeColumns: async () => [],
  addResult: () => {},
  log: () => {},
  onRun: () => {},
};

export function init(options) {
  ctx = { ...ctx, ...options };
}

export function menuConfig() {
  return BASIC_STATS_MENU;
}

// ---------------------------------------------------------------------------
// rendering: the shared layout, plus Minitab's Graphical Summary one-pager
// ---------------------------------------------------------------------------

// Minitab's one-pager: histogram with the fitted normal curve, boxplot and the two interval plots
// down the left, the statistics table and the normality verdict down the right.
function renderGraphicalSummary(container, result, { onCapture } = {}) {
  const panel = result.panels[0];
  if (result.conclusion) container.appendChild(h('p', { class: 'narrative', text: result.conclusion }));
  const grid = buildStatGrid(result.highlights);
  if (grid) container.appendChild(grid);

  const layout = h('div', { class: 'gsummary' });
  const charts = h('div', { class: 'gsummary-charts' });
  const side = h('div', { class: 'gsummary-side' });
  layout.append(charts, side);
  container.appendChild(layout);

  dialog.drawGraph(charts, { renderer: 'histogram', title: `Histogram of ${panel.variable} with fitted normal curve`, data: panel.histogram });
  dialog.drawGraph(charts, { renderer: 'boxplot', title: `Boxplot of ${panel.variable}`, data: panel.boxplot });
  dialog.drawGraph(charts, {
    renderer: 'ciIntervals',
    title: `${Math.round(panel.confidence * 100)}% confidence intervals for the mean and the median`,
    data: { rows: panel.intervals, confidence: panel.confidence, value_label: panel.variable },
  });

  const statTable = buildTableBlock('Statistics', panel.stat_rows);
  if (statTable) side.appendChild(statTable);
  const intervalTable = buildTableBlock(`${Math.round(panel.confidence * 100)}% confidence intervals`, panel.all_intervals);
  if (intervalTable) side.appendChild(intervalTable);
  side.appendChild(
    h('p', { class: 'chart-note', text: panel.normal ? 'The Anderson-Darling test does not reject normality at α = 0.05.' : 'The Anderson-Darling test rejects normality at α = 0.05 — treat normal-theory intervals with care.' }),
  );

  const details = dialog.buildDetails(result);
  if (details) container.appendChild(details);
  dialog.captureStack(container, onCapture);
}

function renderResult(container, result, options = {}) {
  if (result.procedure === 'graphical_summary' && (result.panels || []).length) renderGraphicalSummary(container, result, options);
  else dialog.renderStandard(container, result, options);
}

// ---------------------------------------------------------------------------
// running a procedure
// ---------------------------------------------------------------------------

// A window wide enough for what the procedure draws: the graphical summary is a two-column
// one-pager, a correlation matrix is as wide as the number of variables.
function windowWidth(config, result) {
  if (config.procedure === 'graphical_summary') return 900;
  if (config.procedure === 'correlation' || config.procedure === 'covariance') return Math.min(980, 420 + 110 * (result.variables || []).length);
  if ((result.graphs || []).length) return 760;
  return null;
}

function addStatResult(config, result, values, { label, data, render }) {
  ctx.addResult({
    analysisId: `stat_${config.procedure}`,
    label: label || result.title || describe(config, values),
    data: data || dialog.reportPayload(result),
    kind: 'result',
    width: windowWidth(config, result),
    values,
    render: (container, opts) => render(container, opts || {}),
  });
}

async function runProcedure(config, values) {
  const dataset = ctx.dataset();
  if (!dataset) throw new Error('Load a worksheet first.');
  const request = buildRequest(config, values);
  const response = await apiClient.basicStats(dataset.dataset_id, request);
  const result = response.result;

  if (config.storesColumns) {
    const specs = result.store_columns || [];
    const written = await ctx.storeColumns(specs);
    const stored = { ...result, stored_columns: written.join(', '), tables: result.tables };
    ctx.log(`> Stored ${written.length} column(s) in the worksheet: ${written.join(', ')}.`);
    addStatResult(config, stored, values, {
      label: `${result.title} → ${written.length} column(s)`,
      data: dialog.reportPayload(stored),
      render: (container, opts) => dialog.renderStandard(container, stored, opts),
    });
    return;
  }

  // A graphical summary is one window per variable — the one-pager only makes sense per variable.
  if (config.procedure === 'graphical_summary' && (result.panels || []).length) {
    for (const panel of result.panels) {
      const single = {
        ...result,
        title: `Graphical Summary: ${panel.variable}`,
        panels: [panel],
        tables: result.tables.filter((t) => t.title.endsWith(panel.variable)),
        highlights: [
          { label: `Mean (${panel.variable})`, value: (panel.stat_rows.find((r) => r.Statistic === 'Mean') || {}).Value },
          { label: 'Anderson-Darling A²', value: panel.anderson_darling },
          { label: 'A² p-value', value: panel.anderson_darling_p, tone: panel.normal ? 'positive' : 'negative' },
        ],
        conclusion: `Graphical summary of ${panel.variable}: A² = ${panel.anderson_darling.toFixed(4)}, p = ${panel.anderson_darling_p < 0.001 ? panel.anderson_darling_p.toExponential(2) : panel.anderson_darling_p.toFixed(4)} — ${panel.normal ? 'consistent with a normal distribution' : 'not consistent with a normal distribution'}.`,
      };
      addStatResult(config, single, values, {
        label: single.title,
        data: dialog.reportPayload(single),
        render: (container, opts) => renderGraphicalSummary(container, single, opts),
      });
    }
    return;
  }

  addStatResult(config, result, values, { render: (container, opts) => renderResult(container, result, opts) });
}

export function open(statId, initialValues) {
  const config = PROCEDURE_BY_ID[statId];
  if (!config) return;

  const winId = `stat-form-${config.id}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  if (!ctx.dataset()) {
    wm.createWindow({ id: winId, title: config.title, kind: 'form', content: h('p', { class: 'muted', text: 'No worksheet yet. Open a file from the File menu, or wait for the blank worksheet to finish loading.' }) });
    return;
  }

  let win;
  const content = dialog.buildForm(config, initialValues, {
    // File > Options' significance level decides the prefilled confidence level.
    prefill: (values) => {
      if ('confidence' in values) values.confidence = Number((1 - settings.get().alpha).toFixed(4));
    },
    onSubmit: async (values) => {
      ctx.onRun(config.id, values);
      await runProcedure(config, values);
      if (win) win.close();
    },
  });
  win = wm.createWindow({ id: winId, title: config.title, kind: 'form', content });
}

export { PROCEDURE_BY_ID };
