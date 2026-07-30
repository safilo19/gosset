// The Calc menu's behaviour layer. Most items are ordinary registry entries driven by
// procedureDialog's form builder; three are bespoke because a form cannot describe them:
//
//   Calculator   — a column list, a function browser and live validation around a formula box
//   Set Base     — one number that seeds every later random draw
//   Matrices     — the store's own window (matrices.js)
//
// A Calc result can write to three different places, and this module is what routes them:
// `store_columns` goes through the ordinary `set_columns` data operation so it lands on the undo
// stack, `store_constant` goes to constants.js, `store_matrix` goes to matrices.js. All three
// stores live in the browser, which is what lets a project file carry them.

import { apiClient } from './apiClient.js';
import * as wm from './windowManager.js';
import * as dialogs from './dialogs.js';
import * as dialog from './procedureDialog.js';
import * as constants from './constants.js';
import * as matrices from './matrices.js';
import { PROCEDURE_BY_ID, PROCEDURES, buildRequest, calcMenuConfig, describe, distributionConfig } from './calcConfig.js';
import { h } from './resultView.js';

let ctx = {
  dataset: () => null,
  gridValues: () => [],
  log: () => {},
  logBlock: () => {},
  addResult: () => {},
  onRun: () => {},
  applyDataOp: async () => {},
  snapshot: () => null,
  commitEdit: async () => {},
  onSeedChange: () => {},
};

// The Set Base seed, and the generated distribution dialogs (built once the catalogue arrives).
let seed = null;
let distributionList = [];
const generated = new Map();

export function init(options) {
  ctx = { ...ctx, ...options };
}

export function currentSeed() {
  return seed;
}

export function restoreSeed(value) {
  seed = value === null || value === undefined || value === '' ? null : Number(value);
}

/** Every config this menu can open, generated ones included. */
function configFor(id) {
  return PROCEDURE_BY_ID[id] || generated.get(id) || null;
}

export function menuConfig() {
  return calcMenuConfig(distributionList);
}

/** The distribution catalogue is served by the backend, so the two never drift apart. Until it
 *  arrives the Calc menu still builds — just without the two generated submenus. */
export async function loadCatalogue(datasetId) {
  const response = await apiClient.calc(datasetId, { procedure: 'catalogue', columns: [], options: {} });
  distributionList = response.result.distributions || [];
  functionCatalogue = response.result.functions || [];
  generated.clear();
  for (const distribution of distributionList) {
    generated.set(`random_${distribution.id}`, distributionConfig('random', distribution));
    if (distribution.id !== 'multivariate_normal') generated.set(`probability_${distribution.id}`, distributionConfig('probability', distribution));
  }
  return { distributions: distributionList.length, functions: functionCatalogue.length };
}

let functionCatalogue = [];

// ---------------------------------------------------------------------------
// applying a result's three kinds of output
// ---------------------------------------------------------------------------

async function applyStores(result, label) {
  const dataset = ctx.dataset();
  const written = [];

  if ((result.store_columns || []).length) {
    if (!dataset) throw new Error('Open a worksheet first.');
    const before = ctx.snapshot();
    const response = await apiClient.dataOp(dataset.dataset_id, { operation: 'set_columns', options: { columns: result.store_columns } });
    await ctx.commitEdit(label, before);
    await ctx.applyDataOp(response, { label });
    written.push(`${result.store_columns.length} column(s)`);
  }
  if (result.store_constant && result.store_constant.name) {
    const { name, value } = result.store_constant;
    const existing = constants.get(name);
    if (existing) constants.set(constants.list().map((c) => (c.key === existing.key ? { ...c, value } : c)));
    else constants.store_values([value], { keys: [name], namePrefix: '' });
    written.push(`constant ${name}`);
  }
  if (result.store_matrix && result.store_matrix.name) {
    matrices.put(result.store_matrix.name, result.store_matrix.rows);
    written.push(`matrix ${result.store_matrix.name}`);
  }
  return written;
}

function renderResult(container, result, options = {}) {
  if (result.text) container.appendChild(h('pre', { class: 'session-block-pre' }, [result.text]));
  dialog.renderStandard(container, result, options);
}

function windowWidth(result) {
  if ((result.graphs || []).length) return 760;
  if ((result.tables || []).length > 2) return 700;
  return 620;
}

function report(config, values, result) {
  const hasOutput = (result.tables || []).length || (result.highlights || []).length || (result.graphs || []).length;
  if (!hasOutput) {
    ctx.log(`> ${result.summary}`);
    return;
  }
  ctx.addResult({
    analysisId: `calc_${result.procedure || config.procedure}`,
    label: result.title || describe(config, values),
    data: dialog.reportPayload(result),
    kind: 'result',
    width: windowWidth(result),
    values,
    render: (container, opts) => renderResult(container, result, opts || {}),
  });
}

/** Everything a Calc request needs to know about the browser-side stores. */
function storeOptions() {
  const payload = { constants: {} };
  for (const constant of constants.list()) {
    payload.constants[constant.key] = constant.value;
    if (constant.name) payload.constants[constant.name.toUpperCase()] = constant.value;
  }
  if (seed !== null) payload.seed = seed;
  return payload;
}

/** A matrix field holds the matrix's KEY; the backend has no store, so send the numbers. */
function resolveMatrices(request) {
  for (const key of ['matrix', 'left', 'right', 'covariance']) {
    const value = request.options[key];
    if (typeof value === 'string' && value) {
      const rows = matrices.rowsOf(value);
      if (!rows) throw new Error(`Matrix ${value} is no longer in the store.`);
      request.options[key] = rows;
      if (key === 'matrix') request.options.source_name = value;
    }
  }
  return request;
}

async function runProcedure(config, values, extra = {}) {
  const dataset = ctx.dataset();
  if (!dataset) throw new Error('Load a worksheet first.');
  const request = buildRequest(config, values, dialog.visibleFields(config, values));
  request.options = { ...request.options, ...storeOptions(), ...extra };
  resolveMatrices(request);

  const response = await apiClient.calc(dataset.dataset_id, request);
  const result = response.result;
  const label = result.title || describe(config, values);

  const written = await applyStores(result, label);
  if (result.text) ctx.logBlock(result.title || label, result.text);
  report(config, values, result);
  if (written.length && !(result.tables || []).length) ctx.log(`> ${label}: wrote ${written.join(', ')}.`);
  return result;
}

// ---------------------------------------------------------------------------
// the Calculator — a bespoke window
// ---------------------------------------------------------------------------

const VALIDATE_DELAY = 300;

function buildCalculatorWindow(initialValues) {
  const dataset = ctx.dataset();
  const columns = (dataset && dataset.columns) || [];

  const destination = h('input', { type: 'text', placeholder: 'a column name, or K1 for a constant' });
  destination.value = (initialValues && initialValues.store_in) || '';

  const expression = h('textarea', { class: 'calc-expression mono-input', rows: '4', spellcheck: 'false', placeholder: "IF('yield_kg' > 50, 1, 0)" });
  expression.value = (initialValues && initialValues.expression) || '';

  const status = h('p', { class: 'calc-status settings-hint' });
  const caret = h('pre', { class: 'calc-caret' });
  caret.hidden = true;
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', text: 'Store result' });
  submit.disabled = true;

  // Insert at the caret rather than appending: double-clicking a column halfway through writing a
  // formula has to put it where the cursor is, which is the whole point of the list.
  const insert = (text) => {
    const start = expression.selectionStart ?? expression.value.length;
    const end = expression.selectionEnd ?? start;
    expression.value = expression.value.slice(0, start) + text + expression.value.slice(end);
    const cursor = start + text.length;
    expression.focus();
    expression.setSelectionRange(cursor, cursor);
    validateSoon();
  };

  // A name with anything other than letters, digits and underscores must be quoted to parse.
  const columnToken = (name) => (/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) ? `'${name}'` : `'${name.replace(/'/g, "\\'")}'`);

  const columnList = h('div', { class: 'calc-list' });
  if (!columns.length) columnList.appendChild(h('p', { class: 'muted', text: 'This worksheet has no columns yet.' }));
  for (const column of columns) {
    columnList.appendChild(
      h('button', {
        type: 'button',
        class: 'calc-list-item',
        text: column.name,
        title: `${column.name} (${column.dtype}) — double-click to insert`,
        onDblclick: () => insert(columnToken(column.name)),
        onClick: (e) => {
          if (e.detail === 0) insert(columnToken(column.name)); // keyboard activation
        },
      }),
    );
  }

  const constantList = constants.list();
  if (constantList.length) {
    columnList.appendChild(h('p', { class: 'calc-list-heading', text: 'Constants' }));
    for (const constant of constantList) {
      columnList.appendChild(
        h('button', {
          type: 'button',
          class: 'calc-list-item',
          text: constants.label(constant),
          title: 'Double-click to insert',
          onDblclick: () => insert(constant.key),
        }),
      );
    }
  }

  // The function browser, grouped by category. Clicking inserts the signature with its argument
  // names still in place and selects the first one, so the next keystroke replaces it.
  const functionBox = h('div', { class: 'calc-list' });
  const categorySelect = h('select', {}, functionCatalogue.map((group) => h('option', { value: group.category, text: group.category })));
  const describeBox = h('p', { class: 'settings-hint calc-function-help', text: 'Pick a category, then click a function to insert it.' });

  const fillFunctions = () => {
    const group = functionCatalogue.find((entry) => entry.category === categorySelect.value) || functionCatalogue[0];
    functionBox.innerHTML = '';
    for (const fn of (group && group.functions) || []) {
      functionBox.appendChild(
        h('button', {
          type: 'button',
          class: 'calc-list-item',
          text: fn.name,
          title: `${fn.signature} — ${fn.summary}`,
          onMouseenter: () => {
            describeBox.textContent = `${fn.signature} — ${fn.summary}`;
          },
          onClick: () => {
            const open = fn.signature.indexOf('(');
            const args = fn.signature.slice(open + 1, fn.signature.lastIndexOf(')'));
            insert(fn.signature.slice(0, open) + '(' + args + ')');
            if (args) {
              // Select the first placeholder argument so typing replaces it.
              const start = expression.value.lastIndexOf(args);
              const firstArg = args.split(',')[0];
              expression.setSelectionRange(start, start + firstArg.length);
            }
          },
        }),
      );
    }
  };
  categorySelect.addEventListener('change', fillFunctions);
  fillFunctions();

  let timer = null;
  let lastChecked = null;
  const validateNow = async () => {
    const source = expression.value;
    lastChecked = source;
    if (!source.trim()) {
      status.textContent = 'Type a formula, or build one from the lists.';
      status.classList.remove('calc-status-error', 'calc-status-ok');
      caret.hidden = true;
      submit.disabled = true;
      return;
    }
    try {
      const response = await apiClient.calc(ctx.dataset().dataset_id, { procedure: 'validate_expression', columns: [], options: { expression: source, ...storeOptions() } });
      if (expression.value !== lastChecked) return; // a newer keystroke has already superseded this
      const outcome = response.result;
      if (outcome.ok) {
        status.textContent = `Valid — gives ${outcome.scalar ? 'a single value' : 'one value per row'}${outcome.kind ? ` (${outcome.kind})` : ''}.`;
        status.classList.add('calc-status-ok');
        status.classList.remove('calc-status-error');
        caret.hidden = true;
        submit.disabled = false;
      } else {
        status.textContent = outcome.error || 'The formula could not be read.';
        status.classList.add('calc-status-error');
        status.classList.remove('calc-status-ok');
        if (typeof outcome.position === 'number') {
          // A caret line under the formula, in the same monospace grid, pointing at the offset.
          caret.textContent = `${' '.repeat(Math.max(0, outcome.position))}^`;
          caret.hidden = false;
        } else {
          caret.hidden = true;
        }
        submit.disabled = true;
      }
    } catch (err) {
      status.textContent = err.message;
      status.classList.add('calc-status-error');
      submit.disabled = true;
    }
  };
  const validateSoon = () => {
    clearTimeout(timer);
    timer = setTimeout(validateNow, VALIDATE_DELAY);
  };
  expression.addEventListener('input', validateSoon);

  const errorP = h('p', { class: 'error' });
  errorP.hidden = true;

  const form = h('form', { class: 'tool-form calc-form', novalidate: 'novalidate' }, [
    h('div', { class: 'field' }, [h('label', { text: 'Store result in' }), destination, h('p', { class: 'settings-hint', text: 'A column name writes one value per row. A constant (K1, K2…) needs a formula that gives a single value, such as MEAN(…).' })]),
    h('div', { class: 'calc-panes' }, [
      h('div', { class: 'calc-pane' }, [h('p', { class: 'section-label', text: 'Columns and constants' }), columnList]),
      h('div', { class: 'calc-pane' }, [h('p', { class: 'section-label', text: 'Functions' }), categorySelect, functionBox, describeBox]),
    ]),
    h('div', { class: 'field' }, [h('label', { text: 'Expression' }), expression, caret, status]),
    h('div', { class: 'form-actions' }, [submit]),
    errorP,
  ]);

  if (expression.value) validateNow();
  else status.textContent = 'Type a formula, or build one from the lists.';

  return { form, destination, expression, submit, errorP };
}

function openCalculator(initialValues) {
  const winId = 'calc-form-calculator';
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  if (!ctx.dataset()) {
    wm.createWindow({ id: winId, title: 'Calculator', kind: 'form', content: h('p', { class: 'muted', text: 'No worksheet yet. Open a file from the File menu, or wait for the blank worksheet to finish loading.' }) });
    return;
  }

  const { form, destination, expression, submit, errorP } = buildCalculatorWindow(initialValues);
  const win = wm.createWindow({ id: winId, title: 'Calculator', kind: 'form', content: form, width: 620 });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = { store_in: destination.value.trim(), expression: expression.value };
    if (!values.store_in) {
      errorP.textContent = 'Enter a column name or a constant (K1) to store the result in.';
      errorP.hidden = false;
      return;
    }
    errorP.hidden = true;
    submit.disabled = true;
    const idle = submit.textContent;
    submit.textContent = 'Working…';
    try {
      ctx.onRun('calculator', values);
      const asConstant = /^K\d+$/i.test(values.store_in) || !!constants.get(values.store_in);
      await runProcedure({ id: 'calculator', procedure: 'calculator', fields: [], title: 'Calculator' }, values, {
        expression: values.expression,
        store_in: values.store_in,
        as_constant: asConstant,
      });
      win.close();
    } catch (err) {
      errorP.textContent = err.message;
      errorP.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = idle;
    }
  });
}

// ---------------------------------------------------------------------------
// Set Base
// ---------------------------------------------------------------------------

function openSetBase() {
  dialogs.panel({
    title: 'Set Base',
    width: 460,
    render: (close) => {
      const input = h('input', { type: 'number', step: 1, min: 0, placeholder: '12345' });
      input.value = seed === null ? '' : String(seed);
      const form = h('form', { class: 'dialog' }, [
        h('p', { class: 'dialog-message', text: 'Set the base for the random number generator.' }),
        h('p', { class: 'dialog-detail', text: 'Every later Random Data and Resampling run starts from this base, so the same base gives the same numbers again. Leave it blank for a different sample every time.' }),
        h('div', { class: 'field' }, [h('label', { text: 'Base' }), input]),
        h('div', { class: 'dialog-actions' }, [
          h('button', { type: 'submit', class: 'btn btn-primary', text: 'Set base' }),
          h('button', {
            type: 'button',
            class: 'btn',
            text: 'Clear base',
            onClick: () => {
              seed = null;
              ctx.onSeedChange(null);
              ctx.log('> Base cleared — random data will differ on every run.');
              close();
            },
          }),
          h('button', { type: 'button', class: 'btn', text: 'Cancel', onClick: close }),
        ]),
      ]);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        const raw = input.value.trim();
        if (raw === '') {
          seed = null;
          ctx.log('> Base cleared — random data will differ on every run.');
        } else {
          const value = Number(raw);
          if (!Number.isInteger(value) || value < 0) return;
          seed = value;
          ctx.log(`> Base set to ${value}. Random Data and Resampling will now repeat exactly with this base.`);
        }
        ctx.onSeedChange(seed);
        close();
      });
      return form;
    },
  });
}

// ---------------------------------------------------------------------------
// opening a dialog
// ---------------------------------------------------------------------------

export function open(calcId, initialValues) {
  if (calcId === 'calculator') return openCalculator(initialValues);
  if (calcId === 'set_base') return openSetBase();
  if (calcId === 'matrices_window') return matrices.openWindow();

  const config = configFor(calcId);
  if (!config) return;

  const winId = `calc-form-${config.id}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  if (!ctx.dataset()) {
    wm.createWindow({ id: winId, title: config.title, kind: 'form', content: h('p', { class: 'muted', text: 'No worksheet yet. Open a file from the File menu, or wait for the blank worksheet to finish loading.' }) });
    return;
  }

  let win;
  const formConfig = { ...config, fields: (config.fields || []).filter((f) => !f.omitFromForm) };
  const content = dialog.buildForm(formConfig, initialValues, {
    onSubmit: async (values) => {
      ctx.onRun(config.id, values);
      await runProcedure(config, values);
      if (win) win.close();
    },
  });
  win = wm.createWindow({ id: winId, title: config.title, kind: 'form', content, width: config.width || 520 });
}

export { PROCEDURE_BY_ID };

/** Whether this menu owns the id — app.js routes a data-calc click through here. */
export function owns(id) {
  return !!configFor(id) || id === 'calculator' || id === 'set_base' || id === 'matrices_window';
}
