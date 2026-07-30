// The Data menu's behaviour layer — the thin half of the config/behaviour split. The registry in
// dataMenuConfig.js says what each dialog collects and which backend operation it runs; this file
// opens the forms, sends the request, and decides what the reply means for the app: refresh the
// grid in place, open a new worksheet tab, print into the Session Window, or show a result window.
//
// Three items never reach the backend at all — the constants copies. A constant is a client-side
// scratch value (see constants.js), so Column to Constants reads the live grid and Constants to
// Constants is pure bookkeeping. Constants to Column is the one that writes, and it goes through
// the ordinary `set_columns` operation so it is undoable like every other worksheet edit.

import { apiClient } from './apiClient.js';
import * as wm from './windowManager.js';
import * as dialog from './procedureDialog.js';
import * as constants from './constants.js';
import * as matrices from './matrices.js';
import { PROCEDURE_BY_ID, buildRequest, dataMenuConfig, describe, formFields } from './dataMenuConfig.js';
import { h } from './resultView.js';

let ctx = {
  dataset: () => null,
  worksheets: () => [],
  gridValues: () => [],
  selectedRows: () => [],
  log: () => {},
  logBlock: () => {},
  addResult: () => {},
  onRun: () => {},
  // app.js owns the worksheet registry, so it is the one that turns `created`/`modified` into
  // tabs, a re-render and (for a new worksheet) a switch.
  applyDataOp: async () => {},
  // ws.snapshotNow() / ws.commitExternalEdit() — one undo step around a server-side edit.
  snapshot: () => null,
  commitEdit: async () => {},
};

export function init(options) {
  ctx = { ...ctx, ...options };
}

export function menuConfig() {
  return dataMenuConfig();
}

export { PROCEDURE_BY_ID };

function activeName() {
  const dataset = ctx.dataset();
  return dataset ? dataset.name || dataset.source : 'this worksheet';
}

// ---------------------------------------------------------------------------
// results
// ---------------------------------------------------------------------------

function renderReport(container, result, options = {}) {
  if (result.text) {
    container.appendChild(h('pre', { class: 'session-block-pre' }, [result.text]));
    return;
  }
  dialog.renderStandard(container, result, options);
}

function reportResult(config, values, result) {
  const hasOutput = (result.tables || []).length || (result.highlights || []).length || result.text;
  if (!hasOutput) {
    ctx.log(`> ${result.summary}`);
    return;
  }
  ctx.addResult({
    analysisId: `data_${config.operation || config.id}`,
    label: result.title || describe(config, values),
    data: dialog.reportPayload(result),
    kind: 'result',
    width: (result.tables || []).length ? 720 : null,
    values,
    render: (container, opts) => renderReport(container, result, opts || {}),
  });
}

// ---------------------------------------------------------------------------
// running an operation
// ---------------------------------------------------------------------------

async function runOperation(config, values, { extra = {}, previewOnly = false } = {}) {
  const dataset = ctx.dataset();
  if (!dataset) throw new Error('Open a worksheet first.');

  // "Rows selected in the worksheet" is resolved here, where the grid's selection lives, and sent
  // as an ordinary row list — the backend never needs to know what a selection is.
  const merged = { ...extra };
  if (values.by === 'selection') {
    const rows = ctx.selectedRows();
    if (!rows.length) throw new Error('Select the rows in the worksheet first, then reopen this dialog.');
    merged.by = 'rows';
    merged.rows = rows.map((r) => r + 1).join(' ');
  }

  const request = buildRequest(config, values, { worksheetName: activeName(), extra: merged });
  const label = describe(config, values);
  const before = config.undoable && !previewOnly ? ctx.snapshot() : null;

  const response = await apiClient.dataOp(dataset.dataset_id, request);
  const result = response.result || {};

  // in_place is the only mode that both changes the worksheet we are looking at AND leaves us on
  // it, so it is the only one with an undo step to record. new/many switch to a fresh worksheet
  // (nothing to undo yet); other_in_place rewrites a worksheet we are not looking at.
  if (response.mode === 'in_place' && before) await ctx.commitEdit(label, before);

  await ctx.applyDataOp(response, { label, config });

  if (result.text) ctx.logBlock(result.title || label, result.text);
  // reportResult either opens a result window (which logs its own clickable Session entry) or,
  // when the operation produced no output to show, logs the summary itself. Either way the run is
  // in the log exactly once.
  reportResult(config, values, result);
  return response;
}

// ---------------------------------------------------------------------------
// the three constants operations (client-side)
// ---------------------------------------------------------------------------

function parseRowSpec(spec, rowCount) {
  const text = String(spec || '').trim();
  if (!text) return null;
  const picked = new Set();
  for (const token of text.split(/[\s,;]+/).filter(Boolean)) {
    const range = token.match(/^(\d+)\s*[:-]\s*(\d+)$/);
    if (range) {
      let [, a, b] = range;
      let start = Number(a);
      let end = Number(b);
      if (start > end) [start, end] = [end, start];
      for (let r = start; r <= end; r += 1) if (r >= 1 && r <= rowCount) picked.add(r - 1);
    } else if (/^\d+$/.test(token)) {
      const r = Number(token);
      if (r >= 1 && r <= rowCount) picked.add(r - 1);
    } else {
      throw new Error(`'${token}' is not a row number or range. Rows are written like '1:5 12 20:25'.`);
    }
  }
  return [...picked].sort((a, b) => a - b);
}

const LOCAL_OPERATIONS = {
  columnToConstants(config, values) {
    const rows = ctx.gridValues();
    const picked = parseRowSpec(values.rows, rows.length);
    const source = picked ? picked.map((i) => rows[i]) : rows;
    const taken = source.map((row) => (row ? row[values.column] : null)).filter((v) => v !== null && v !== undefined && v !== '');
    if (!taken.length) throw new Error(`'${values.column}' holds no values in those rows.`);
    const stored = constants.store_values(taken, { namePrefix: values.name_prefix || values.column });
    ctx.log(`> Copied ${stored.length} value(s) from '${values.column}' into constants ${stored.map((c) => c.key).join(', ')}.`);
    constants.openWindow();
  },

  constantsToConstants(config, values) {
    const source = (values.source_constants || []).map((key) => constants.get(key)).filter(Boolean);
    if (!source.length) throw new Error('Choose at least one constant to copy.');
    const made = source.map((c) => constants.add(c.value, c.name));
    ctx.log(`> Copied ${made.length} constant(s) into ${made.map((c) => c.key).join(', ')}.`);
    constants.openWindow();
  },

  matricesToMatrices(config, values) {
    const source = (values.source_matrices || []).map((key) => matrices.get(key)).filter(Boolean);
    if (!source.length) throw new Error('Choose at least one matrix to copy.');
    const made = source.map((m) => matrices.put('', m.rows, m.name));
    ctx.log(`> Copied ${made.length} matri${made.length === 1 ? 'x' : 'ces'} into ${made.map((m) => m.key).join(', ')}.`);
    matrices.openWindow();
  },

  async constantsToColumn(config, values) {
    const source = (values.source_constants || []).map((key) => constants.get(key)).filter(Boolean);
    if (!source.length) throw new Error('Choose at least one constant to copy.');
    const spec = { name: values.store_in, values: source.map((c) => c.value), overwrite: !!values.overwrite };
    const before = ctx.snapshot();
    const dataset = ctx.dataset();
    const response = await apiClient.dataOp(dataset.dataset_id, { operation: 'set_columns', options: { columns: [spec] } });
    await ctx.commitEdit(`copy ${source.length} constant(s) into ${values.store_in}`, before);
    await ctx.applyDataOp(response, { label: 'Constants to Column' });
    ctx.log(`> ${response.result.summary}`);
  },
};

// ---------------------------------------------------------------------------
// opening a dialog
// ---------------------------------------------------------------------------

export function open(dataId, initialValues) {
  const config = PROCEDURE_BY_ID[dataId];
  if (!config) return;

  const winId = `data-form-${config.id}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  if (!ctx.dataset()) {
    wm.createWindow({ id: winId, title: config.title, kind: 'form', content: h('p', { class: 'muted', text: 'No worksheet yet. Open a file from the File menu, or wait for the blank worksheet to finish loading.' }) });
    return;
  }

  // An item with nothing to ask (Worksheet Information) just runs.
  if (config.immediate && !config.fields.length) {
    ctx.onRun(config.id, {});
    runOperation(config, {}).catch((err) => ctx.log(`> ${config.title} failed: ${err.message}`));
    return;
  }

  let win;
  const formConfig = { ...config, fields: formFields(config) };
  const content = dialog.buildForm(formConfig, initialValues, {
    onSubmit: async (values) => {
      ctx.onRun(config.id, values);
      if (config.local) await LOCAL_OPERATIONS[config.local](config, values);
      else await runOperation(config, values);
      if (win) win.close();
    },
    // Change Data Type asks the same question with preview:true and shows the answer without
    // touching the worksheet — the dialog stays open so the choice can be changed.
    secondary: config.previewLabel
      ? {
          label: config.previewLabel,
          run: (values) => runOperation(config, values, { extra: { preview: true }, previewOnly: true }),
        }
      : null,
  });
  win = wm.createWindow({ id: winId, title: config.title, kind: 'form', content, width: config.width || 520 });
}
