// Stat > Regression: opens a form window per procedure, sends it to the one /regression-model route,
// and renders the result. The form building and the standard result layout come from procedureDialog.js
// — shared with Basic Statistics — so all this module adds is the menu, the request, and the two
// things unique to regression output: the Predict panel and the fitted-model window width.

import { apiClient } from './apiClient.js';
import * as wm from './windowManager.js';
import { PROCEDURE_BY_ID, REGRESSION_MENU, buildRequest, describe } from './regressionConfig.js';
import * as dialog from './procedureDialog.js';
import { h, buildDataTable } from './resultView.js';
import * as settings from './settings.js';

let ctx = {
  dataset: () => null,
  addResult: () => {},
  log: () => {},
  onRun: () => {},
};

export function init(options) {
  ctx = { ...ctx, ...options };
}

export function menuConfig() {
  return REGRESSION_MENU;
}

// ---------------------------------------------------------------------------
// the Predict panel
// ---------------------------------------------------------------------------

// Minitab's Predict panel: enter a value for each predictor and get the fit with its confidence and
// prediction intervals. Each prediction is appended, so several settings can be compared side by
// side. The model is refitted server-side per prediction, which keeps this working for a result
// window that outlives any server-side state.
function buildPredictPanel(spec) {
  const wrap = h('div', { class: 'predict-panel' });
  wrap.appendChild(h('p', { class: 'section-label', text: 'Predict' }));
  wrap.appendChild(h('p', { class: 'settings-hint', text: 'Enter a value for each predictor to get the fitted response with its confidence and prediction interval.' }));

  const values = {};
  const grid = h('div', { class: 'predict-grid' });
  for (const name of spec.continuous || []) {
    const input = h('input', { type: 'number', step: 'any' });
    const mean = (spec.means || {})[name];
    if (mean !== undefined && mean !== null) input.value = Number(mean).toFixed(4).replace(/\.?0+$/, '');
    values[name] = input.value;
    input.addEventListener('input', () => {
      values[name] = input.value;
    });
    grid.appendChild(h('div', { class: 'field' }, [h('label', { text: name }), input]));
  }
  for (const name of spec.categorical || []) {
    const levels = (spec.levels || {})[name] || [];
    const select = h('select', {}, levels.map((level) => h('option', { value: level, text: level })));
    values[name] = levels[0] || '';
    select.value = values[name];
    select.addEventListener('change', () => {
      values[name] = select.value;
    });
    grid.appendChild(h('div', { class: 'field' }, [h('label', { text: name }), select]));
  }
  wrap.appendChild(grid);

  const button = h('button', { type: 'button', class: 'btn btn-primary', text: 'Predict' });
  const errorP = h('p', { class: 'error' });
  errorP.hidden = true;
  const output = h('div', { class: 'predict-output' });
  wrap.append(h('div', { class: 'form-actions' }, [button]), errorP, output);

  const rows = [];
  button.addEventListener('click', async () => {
    const dataset = ctx.dataset();
    if (!dataset) {
      errorP.textContent = 'No worksheet is loaded.';
      errorP.hidden = false;
      return;
    }
    button.disabled = true;
    button.textContent = 'Predicting…';
    errorP.hidden = true;
    try {
      const response = await apiClient.regressionModel(dataset.dataset_id, { procedure: 'predict', columns: [], options: { spec, values } });
      const result = response.result;
      rows.push({ ...result.settings, Fit: result.fit, 'SE Fit': result.se_fit, ...predictionIntervals(result) });
      output.innerHTML = '';
      const table = buildDataTable(rows);
      if (table) output.appendChild(table);
      ctx.log(`> Predict: ${result.summary}`);
    } catch (err) {
      errorP.textContent = err.message;
      errorP.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = 'Predict';
    }
  });

  return wrap;
}

function predictionIntervals(result) {
  const pct = `${Math.round((result.confidence_level || 0.95) * 100)}%`;
  const fmt = (pair) => (Array.isArray(pair) && pair.length === 2 ? `(${format(pair[0])}, ${format(pair[1])})` : '');
  return { [`${pct} CI`]: fmt(result.ci), [`${pct} PI`]: fmt(result.pi) };
}

function format(value) {
  if (value === null || value === undefined) return '';
  const decimals = settings.get().decimals;
  return Number.isInteger(value) ? String(value) : Number(value).toFixed(decimals);
}

// ---------------------------------------------------------------------------
// running a procedure
// ---------------------------------------------------------------------------

// Wide enough for the output each procedure produces: the residual panels are a 2×2 grid, and a
// best-subsets table has one column per candidate predictor.
function windowWidth(config, result) {
  if (config.procedure === 'best_subsets') return Math.min(1000, 520 + 70 * (result.candidates || []).length);
  if ((result.graphs || []).some((entry) => entry.renderer === 'fourInOne' || entry.renderer === 'residualPair')) return 860;
  if ((result.graphs || []).length) return 780;
  return 720;
}

function renderResult(container, result, options = {}) {
  dialog.renderStandard(container, result, {
    ...options,
    extras: (target) => {
      if (result.predict_spec) target.appendChild(buildPredictPanel(result.predict_spec));
    },
  });
}

async function runProcedure(config, values) {
  const dataset = ctx.dataset();
  if (!dataset) throw new Error('Load a worksheet first.');
  const request = buildRequest(config, values, dialog.visibleFields(config, values));
  const response = await apiClient.regressionModel(dataset.dataset_id, request);
  const result = response.result;

  ctx.addResult({
    analysisId: `stat_${config.procedure}`,
    label: result.title || describe(config, values),
    data: dialog.reportPayload(result),
    kind: 'result',
    width: windowWidth(config, result),
    values,
    render: (container, opts) => renderResult(container, result, opts || {}),
  });
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
    wm.createWindow({
      id: winId,
      title: config.title,
      kind: 'form',
      content: h('p', { class: 'muted', text: 'No worksheet yet. Open a file from the File menu, or wait for the blank worksheet to finish loading.' }),
    });
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
