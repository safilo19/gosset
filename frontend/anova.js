// Stat > ANOVA: opens a form window per procedure, sends it to the one /anova route, and renders
// the result. The form builder and the standard result layout come from procedureDialog.js —
// shared with Basic Statistics and Regression — so what this module adds is the menu, the request,
// and the one thing unique to this area: the stored model.
//
// The stored model is a `model_spec` the GLM and Mixed dialogs return. It lives here, in the
// frontend, and every downstream dialog (Comparisons, Predict, Factorial Plots, Contour, Surface,
// Response Optimizer) posts it back so the backend can refit. Nothing is cached server-side, which
// is the same choice the Regression menu's Predict panel makes and for the same reason: a result
// window outlives any server state. It also means the stored model travels in a saved project.

import { apiClient } from './apiClient.js';
import * as wm from './windowManager.js';
import { MODEL_DEPENDENT, PROCEDURE_BY_ID, anovaMenuConfig, buildRequest, describe } from './anovaConfig.js';
import * as dialog from './procedureDialog.js';
import { h, buildDataTable } from './resultView.js';
import * as settings from './settings.js';

let ctx = {
  dataset: () => null,
  addResult: () => {},
  log: () => {},
  onRun: () => {},
  onModelStored: () => {},
};

// One slot per model kind. `active` is set immediately before a form is built, so the model-*
// field types know which model's factors and covariates to offer.
const models = { glm: null, mixed: null };
let active = 'glm';

export function init(options) {
  ctx = { ...ctx, ...options };
}

export function menuConfig() {
  return anovaMenuConfig();
}

export { PROCEDURE_BY_ID };

/** The spec the model-* dialog fields read; also what File > Save Project persists. */
export function activeModelSpec() {
  return models[active];
}

export function storedModels() {
  return { glm: models.glm, mixed: models.mixed };
}

export function restoreModels(stored) {
  models.glm = (stored && stored.glm) || null;
  models.mixed = (stored && stored.mixed) || null;
  refreshMenuState();
}

const MODEL_LABEL = { glm: 'General Linear Model', mixed: 'Mixed Effects Model' };

/** Items that work off a fitted model stay inert, with a tooltip saying so, until there is one. */
export function refreshMenuState() {
  for (const { id, kind } of MODEL_DEPENDENT) {
    const el = document.querySelector(`.menu[data-menu="stat"] [data-stat="${id}"]`);
    if (!el) continue;
    const ready = !!models[kind];
    el.classList.toggle('menu-item-disabled', !ready);
    if (ready) {
      el.removeAttribute('aria-disabled');
      el.title = `Uses the ${MODEL_LABEL[kind]} fitted for ${models[kind].response}.`;
    } else {
      el.setAttribute('aria-disabled', 'true');
      el.title = `Run Stat > ANOVA > ${MODEL_LABEL[kind]} > Fit ${MODEL_LABEL[kind]} first — this works from that fitted model.`;
    }
  }
}

// ---------------------------------------------------------------------------
// the Predict panel
// ---------------------------------------------------------------------------

// Same panel as the Regression menu's, pointed at the stored ANOVA model: a value per covariate, a
// level per factor, and each prediction appended so several settings can be compared side by side.
function buildPredictPanel(spec, procedure) {
  const wrap = h('div', { class: 'predict-panel' });
  wrap.appendChild(h('p', { class: 'section-label', text: 'Predict' }));
  wrap.appendChild(h('p', { class: 'settings-hint', text: 'Enter a value for each predictor to get the fitted response with its confidence and prediction interval.' }));

  const values = {};
  const grid = h('div', { class: 'predict-grid' });
  for (const name of spec.covariates || []) {
    const input = h('input', { type: 'number', step: 'any' });
    const mean = (spec.means || {})[name];
    if (mean !== undefined && mean !== null) input.value = Number(mean).toFixed(4).replace(/\.?0+$/, '');
    values[name] = input.value;
    input.addEventListener('input', () => {
      values[name] = input.value;
    });
    grid.appendChild(h('div', { class: 'field' }, [h('label', { text: name }), input]));
  }
  for (const name of spec.factors || []) {
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
      const response = await apiClient.anova(dataset.dataset_id, { procedure, columns: [], options: { model_spec: spec, values } });
      const result = response.result;
      rows.push({ ...result.settings, Fit: result.fit, 'SE Fit': result.se_fit, ...intervals(result) });
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

function intervals(result) {
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

// Wide enough for what the procedure draws: the factorial/optimiser panels are a 2-column grid,
// a four-in-one is 2×2, and a comparison table can be long but is not wide.
function windowWidth(result) {
  const renderers = (result.graphs || []).map((entry) => entry.renderer);
  if (renderers.some((r) => ['mainEffects', 'interactionPlot', 'desirabilityProfile', 'fourInOne'].includes(r))) return 880;
  if (renderers.some((r) => ['contour', 'surface'].includes(r))) return 820;
  if ((result.graphs || []).length) return 780;
  return 720;
}

function renderResult(container, result, options = {}) {
  dialog.renderStandard(container, result, {
    ...options,
    extras: (target) => {
      // A fit that stored a model offers its Predict panel straight away, so the common case never
      // needs the separate Predict dialog.
      if (result.model_spec) target.appendChild(buildPredictPanel(result.model_spec, result.procedure === 'mixed_model' ? 'mixed_predict' : 'glm_predict'));
    },
  });
}

async function runProcedure(config, values) {
  const dataset = ctx.dataset();
  if (!dataset) throw new Error('Load a worksheet first.');

  const request = buildRequest(config, values, dialog.visibleFields(config, values));
  if (config.needsModel) {
    const spec = models[config.needsModel];
    if (!spec) throw new Error(`Fit a ${MODEL_LABEL[config.needsModel]} first — this works from that fitted model.`);
    request.options = { ...request.options, model_spec: spec };
  }

  const response = await apiClient.anova(dataset.dataset_id, request);
  const result = response.result;

  if (config.storesModel && result.model_spec) {
    models[config.storesModel] = result.model_spec;
    refreshMenuState();
    ctx.onModelStored(config.storesModel, result.model_spec);
    ctx.log(`> Stored the ${MODEL_LABEL[config.storesModel]} of ${result.model_spec.response} — the rest of that submenu now works from it.`);
  }

  ctx.addResult({
    analysisId: `stat_${config.procedure}`,
    label: result.title || describe(config, values),
    data: dialog.reportPayload(result),
    kind: 'result',
    width: windowWidth(result),
    values,
    render: (container, opts) => renderResult(container, result, opts || {}),
  });
}

// ---------------------------------------------------------------------------
// opening a dialog
// ---------------------------------------------------------------------------

/** Predict has no settings of its own — it IS the panel, so it opens as one. */
function openPredictWindow(config) {
  const spec = models[config.needsModel];
  const winId = `stat-form-${config.id}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  const body = h('div');
  body.appendChild(h('p', { class: 'muted', text: `From the stored ${MODEL_LABEL[config.needsModel]} of ${spec.response}.` }));
  body.appendChild(buildPredictPanel(spec, config.procedure));
  wm.createWindow({ id: winId, title: config.title, kind: 'form', content: body, width: 460 });
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

  // Set before the form is built: the model-factor / model-covariate / model-holds fields read
  // whichever model this dialog belongs to.
  if (config.needsModel) active = config.needsModel;
  else if (config.storesModel) active = config.storesModel;

  if (config.needsModel && !models[config.needsModel]) {
    wm.createWindow({
      id: winId,
      title: config.title,
      kind: 'form',
      content: h('p', { class: 'muted', text: `No ${MODEL_LABEL[config.needsModel]} has been fitted yet. Run Stat > ANOVA > ${MODEL_LABEL[config.needsModel]} > Fit ${MODEL_LABEL[config.needsModel]} — this dialog works from that fitted model.` }),
    });
    return;
  }
  if (config.panelOnly) {
    openPredictWindow(config);
    return;
  }

  let win;
  const content = dialog.buildForm(config, initialValues, {
    // File > Options' significance level decides the prefilled confidence level.
    prefill: (values) => {
      if ('confidence' in values) values.confidence = Number((1 - settings.get().alpha).toFixed(4));
      if ('alpha' in values) values.alpha = settings.get().alpha;
    },
    onSubmit: async (values) => {
      ctx.onRun(config.id, values);
      await runProcedure(config, values);
      if (win) win.close();
    },
  });
  win = wm.createWindow({ id: winId, title: config.title, kind: 'form', content, width: config.width || 520 });
}
