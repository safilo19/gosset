// The dialog engine shared by the Stat menu's procedure modules (basicStats.js, regression.js).
//
// Both menus work the same way: a declarative registry describes a form, the form is sent to one
// backend route, and the result comes back in one shape (tables / highlights / graphs / narrative)
// that one renderer lays out. That form builder and that renderer live here so the two menus cannot
// drift apart — a Regression dialog has to look and behave exactly like a Basic Statistics one.
//
// Field types: column, columns, value (levels of another column), select, radio, checkbox, number,
// text, checkbox-grid. A field marked `advanced: true` goes inside a collapsed "Options" section,
// which is what keeps a form with fifteen settings looking like a form with four.

import * as theme from './charts/theme.js';
import { renderers } from './charts/renderers.js';
import { modelRenderers } from './charts/modelRenderers.js';
import { h, block, buildStatGrid, buildTableBlock, buildTextBlock, formatCell } from './resultView.js';
// The Data menu's composite field types (condition builder, sort keys, mapping tables, worksheet
// pickers). They call back into this module for the column lists, which is why they live in their
// own file: this one stays the small engine, that one holds the widgets.
import { ARRAY_FIELDS, EXTRA_FIELDS } from './dialogFields.js';
import * as wm from './windowManager.js';

let ctx = {
  dataset: () => null,
  gridValues: () => [],
  // Every worksheet open right now, for the cross-worksheet Data operations.
  worksheets: () => [],
  constants: () => [],
  // The model the ANOVA menu last fitted, for the dialogs that work off it rather than off columns.
  storedModel: () => null,
  // The Calc menu's matrix store, for the matrix pickers.
  matrices: () => [],
};

export function init(options) {
  ctx = { ...ctx, ...options };
}

// ---------------------------------------------------------------------------
// column and value pickers
// ---------------------------------------------------------------------------

export function columnsFor(filter) {
  const dataset = ctx.dataset();
  const all = (dataset && dataset.columns) || [];
  if (filter === 'numeric') return all.filter((c) => /int|float|number/i.test(c.dtype)).map((c) => c.name);
  return all.map((c) => c.name);
}

/** Every open worksheet as {id, label}; `includeActive` decides whether the current one is offered
 *  (Stack Worksheets wants it, Merge with another worksheet does not). */
export function worksheetOptions(includeActive = false) {
  const active = ctx.dataset();
  return (ctx.worksheets() || [])
    .filter((w) => includeActive || !active || w.dataset_id !== active.dataset_id)
    .map((w) => ({
      id: w.dataset_id,
      label: `${w.name || w.source} (${w.row_count} × ${(w.columns || []).length})`,
    }));
}

/** The column names of any open worksheet, by dataset id. */
export function columnsOf(datasetId) {
  const worksheet = (ctx.worksheets() || []).find((w) => w.dataset_id === datasetId);
  return worksheet ? (worksheet.columns || []).map((c) => c.name) : [];
}

/** The stored constants as {key, label} — Copy ▸ Constants to Column picks from these. */
export function constantOptions() {
  return ctx.constants() || [];
}

/** The ANOVA menu's stored model spec ({response, factors, covariates, levels, means, …}) or null. */
export function storedModel() {
  return ctx.storedModel();
}

/** The stored matrices as {key, label} — the matrix pickers on the Calc menu choose from these. */
export function matrixOptions() {
  return ctx.matrices() || [];
}

// The distinct values of a column, for the "which level" pickers.
export function distinctValues(columnName) {
  if (!columnName) return [];
  const seen = [];
  for (const row of ctx.gridValues()) {
    const value = row[columnName];
    if (value === null || value === undefined || value === '') continue;
    const text = String(value);
    if (!seen.includes(text)) seen.push(text);
    if (seen.length > 60) break;
  }
  return seen.sort();
}

// ---------------------------------------------------------------------------
// values: defaults, visibility, validation
// ---------------------------------------------------------------------------

export function visibleFields(config, values) {
  return config.fields.filter((f) => !f.showIf || f.showIf(values));
}

const isArrayField = (field) => field.type === 'columns' || field.type === 'checkbox-grid' || field.type === 'levels' || ARRAY_FIELDS.has(field.type);

// A composite field's rows are objects, so a shared default array would be edited in place by
// every dialog that opened afterwards — each form gets its own deep copy.
function cloneDefault(value) {
  return JSON.parse(JSON.stringify(value));
}

export function defaultValues(config) {
  const values = {};
  for (const field of config.fields) {
    if (isArrayField(field)) values[field.name] = cloneDefault(field.default || []);
    else if (field.type === 'checkbox') values[field.name] = !!field.default;
    else values[field.name] = field.default ?? '';
  }
  return values;
}

// A composite row counts as filled in once its defining part is chosen — a sort key needs a
// column, a mapping needs an old value. Half-finished rows are dropped rather than rejected.
const ROW_IS_LIVE = {
  'sort-by': (row) => !!row.column,
  conditions: (row) => !!row.column,
  'map-rows': (row) => String(row.from ?? '').trim() !== '',
  'range-rows': (row) => String(row.low ?? '').trim() !== '' || String(row.high ?? '').trim() !== '',
  pairs: (row) => !!row.left && !!row.right,
  'column-blocks': (row) => Array.isArray(row) && row.length > 0,
};

export function liveRows(field, value) {
  const test = ROW_IS_LIVE[field.type];
  const rows = Array.isArray(value) ? value : [];
  return test ? rows.filter((row) => row && test(row)) : rows;
}

export function validate(config, values) {
  for (const field of visibleFields(config, values)) {
    const value = values[field.name];
    if (isArrayField(field)) {
      const count = liveRows(field, value).length;
      if (field.required && count === 0) return `${field.label} is required.`;
      if (field.minSelect && count < field.minSelect) return `${field.label} needs at least ${field.minSelect}.`;
      if (field.maxSelect && count > field.maxSelect) return `${field.label} allows at most ${field.maxSelect}.`;
    } else if (field.required && (value === '' || value === undefined || value === null)) {
      return `${field.label} is required.`;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// the form
// ---------------------------------------------------------------------------

function optionList(field) {
  return (field.options || []).map((o) => (typeof o === 'string' ? { value: o, label: o } : o));
}

function checkboxGrid(field, values, onChange) {
  const wrap = h('div', { class: 'stats-picker' });
  const list = h('div', { class: 'stats-picker-list' });
  const boxes = [];
  for (const item of field.items || []) {
    const box = h('input', { type: 'checkbox' });
    box.checked = (values[field.name] || []).includes(item.key);
    box.addEventListener('change', () => {
      const current = values[field.name] || [];
      values[field.name] = box.checked ? [...current, item.key] : current.filter((k) => k !== item.key);
      onChange();
    });
    boxes.push(box);
    list.appendChild(h('label', { class: 'checkbox-item', title: item.label }, [box, item.label]));
  }
  const setAll = (on) => {
    values[field.name] = on ? (field.items || []).map((i) => i.key) : [];
    for (const box of boxes) box.checked = on;
    onChange();
  };
  wrap.append(
    list,
    h('div', { class: 'stats-picker-actions' }, [
      h('button', { type: 'button', class: 'btn btn-sm', text: 'All', onClick: () => setAll(true) }),
      h('button', { type: 'button', class: 'btn btn-sm', text: 'None', onClick: () => setAll(false) }),
    ]),
  );
  return wrap;
}

function fieldControl(field, values, onChange, refreshers) {
  // The Data menu's composite widgets first — anything not listed there falls through to the
  // plain controls below.
  const extra = EXTRA_FIELDS[field.type];
  if (extra) return extra(field, values, onChange, refreshers);

  if (field.type === 'columns') {
    const options = columnsFor(field.filter);
    const list = h('div', { class: 'checkbox-list' });
    if (!options.length) list.appendChild(h('p', { class: 'muted', text: `No ${field.filter} columns in this worksheet.` }));
    for (const name of options) {
      const box = h('input', { type: 'checkbox' });
      box.checked = (values[field.name] || []).includes(name);
      box.addEventListener('change', () => {
        const current = values[field.name] || [];
        // insertion order is meaningful: it is the order the predictors reach the model
        values[field.name] = box.checked ? [...current, name] : current.filter((c) => c !== name);
        onChange();
      });
      list.appendChild(h('label', { class: 'checkbox-item' }, [box, name]));
    }
    return list;
  }

  if (field.type === 'column') {
    const options = columnsFor(field.filter);
    const select = h('select', {}, [
      h('option', { value: '', text: field.required ? '— choose a column —' : '— none —' }),
      ...options.map((c) => h('option', { value: c, text: c })),
    ]);
    select.value = values[field.name] || '';
    select.addEventListener('change', () => {
      values[field.name] = select.value;
      onChange();
    });
    return select;
  }

  if (field.type === 'value') {
    // Options come from the data in another column, so they are repopulated whenever that column
    // changes rather than being fixed when the form was built.
    const select = h('select', {});
    const fill = () => {
      const source = values[field.from] || values[field.fallbackFrom] || (field.fromList ? (values[field.fromList] || [])[0] : '') || '';
      const options = distinctValues(source);
      const previous = values[field.name];
      select.innerHTML = '';
      select.appendChild(h('option', { value: '', text: options.length ? field.emptyLabel || '— last level —' : '— choose a column first —' }));
      for (const value of options) select.appendChild(h('option', { value, text: value }));
      if (!options.includes(previous)) values[field.name] = '';
      select.value = values[field.name] || '';
    };
    fill();
    refreshers.push(fill);
    select.addEventListener('change', () => {
      values[field.name] = select.value;
      onChange();
    });
    return select;
  }

  if (field.type === 'select') {
    const select = h('select', {}, optionList(field).map((o) => h('option', { value: o.value, text: o.label })));
    select.value = values[field.name] ?? field.default ?? '';
    select.addEventListener('change', () => {
      values[field.name] = select.value;
      onChange();
    });
    return select;
  }

  if (field.type === 'radio') {
    const group = h('div', { class: 'radio-list' });
    const name = `pd-${field.name}-${Math.random().toString(36).slice(2, 8)}`;
    for (const option of optionList(field)) {
      const radio = h('input', { type: 'radio', name });
      radio.value = option.value;
      radio.checked = (values[field.name] ?? field.default) === option.value;
      radio.addEventListener('change', () => {
        if (!radio.checked) return;
        values[field.name] = option.value;
        onChange();
      });
      const label = h('label', { class: 'checkbox-item' }, [radio, option.label]);
      if (option.hint) label.title = option.hint;
      group.appendChild(label);
    }
    return group;
  }

  if (field.type === 'checkbox') {
    const box = h('input', { type: 'checkbox' });
    box.checked = !!values[field.name];
    box.addEventListener('change', () => {
      values[field.name] = box.checked;
      onChange();
    });
    return h('label', { class: 'checkbox-item' }, [box, field.label]);
  }

  if (field.type === 'checkbox-grid') return checkboxGrid(field, values, onChange);

  if (field.type === 'levels') {
    // A multi-select over the levels of another column, where the tick order is the answer (the
    // ordinal response's level order). Rebuilt only when the source column changes, so ticking a
    // box does not tear down the list under the pointer.
    const list = h('div', { class: 'checkbox-list' });
    let lastSource = null;
    const fill = () => {
      const source = values[field.from] || '';
      if (source === lastSource) return;
      lastSource = source;
      const options = distinctValues(source);
      values[field.name] = (values[field.name] || []).filter((v) => options.includes(v));
      list.innerHTML = '';
      if (!options.length) {
        list.appendChild(h('p', { class: 'muted', text: 'Choose the response column first.' }));
        return;
      }
      for (const level of options) {
        const box = h('input', { type: 'checkbox' });
        box.checked = (values[field.name] || []).includes(level);
        box.addEventListener('change', () => {
          const current = values[field.name] || [];
          values[field.name] = box.checked ? [...current, level] : current.filter((v) => v !== level);
          onChange();
        });
        list.appendChild(h('label', { class: 'checkbox-item' }, [box, level]));
      }
    };
    fill();
    refreshers.push(fill);
    return list;
  }

  if (field.type === 'text') {
    const input = h('input', { type: 'text', placeholder: field.placeholder || '' });
    input.value = values[field.name] ?? '';
    if (field.mono) input.className = 'mono-input';
    input.addEventListener('input', () => {
      values[field.name] = input.value;
      onChange();
    });
    return input;
  }

  const input = h('input', { type: 'number', step: field.step ?? 'any', min: field.min, max: field.max });
  input.value = values[field.name] ?? '';
  input.addEventListener('input', () => {
    values[field.name] = input.value;
    onChange();
  });
  return input;
}

/**
 * Builds a procedure form. `onSubmit(values)` runs the procedure; anything it throws is shown in
 * the form's error line rather than reaching the console.
 */
/**
 * Make sure a message the form just produced is actually READABLE.
 *
 * A form window is sized to its content when it opens, so anything that appears afterwards — an error,
 * and the swap button under it — lands below the fold in a window that is now too short, behind a
 * scrollbar nobody expects. The window is refitted to its new content and the message scrolled into
 * view, so a refusal cannot be silently off-screen.
 */
function revealFormMessage(form, node) {
  const win = form.closest('.window');
  if (win && win.id) wm.fitToContent(win.id);
  if (node && node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
}

export function buildForm(config, initialValues, { onSubmit, prefill, secondary } = {}) {
  const values = defaultValues(config);
  if (initialValues) {
    const columns = columnsFor('any');
    for (const field of config.fields) {
      const value = initialValues[field.name];
      if (value === undefined) continue;
      // A saved set of inputs may name columns that have since been deleted — keep only what applies.
      if (field.type === 'columns') values[field.name] = (Array.isArray(value) ? value : []).filter((c) => columns.includes(c));
      else if (field.type === 'column') values[field.name] = columns.includes(value) ? value : '';
      // Reopening a dialog must not hand it the very rows the last run is still holding.
      else if (ARRAY_FIELDS.has(field.type)) values[field.name] = cloneDefault(value);
      else values[field.name] = value;
    }
  } else if (prefill) {
    prefill(values);
  }

  // novalidate: this form's own validate() and the backend's range checks are the authority. Native
  // constraint validation would otherwise refuse to submit — with no message in the window — for a
  // value the procedure is perfectly happy with (a step/min mismatch does exactly that).
  const form = h('form', { class: 'tool-form', novalidate: 'novalidate' });
  const errorP = h('p', { class: 'error' });
  errorP.hidden = true;
  // The error area can carry an action, not just a sentence: a degenerate-group refusal names the two
  // fields that were probably filled in the wrong order (backend check_group_column -> error.swap),
  // and this turns that into one click. Only offered when both named fields are really in this form
  // and both are filled — otherwise the button would have nothing to exchange.
  const errorAction = h('div', { class: 'error-action' });
  errorAction.hidden = true;
  const showError = (err) => {
    errorP.textContent = err.message;
    errorP.hidden = false;
    errorAction.replaceChildren();
    errorAction.hidden = true;
    revealFormMessage(form, errorP);
    const swap = Array.isArray(err.swap) ? err.swap : null;
    if (!swap) return;
    const [a, b] = swap;
    if (!(a in values) || !(b in values) || !values[a] || !values[b]) return;
    const button = h('button', {
      type: 'button',
      class: 'btn btn-sm',
      text: `Swap ${values[a]} and ${values[b]}`,
      onClick: () => {
        const keep = values[a];
        values[a] = values[b];
        values[b] = keep;
        errorP.hidden = true;
        errorAction.hidden = true;
        refresh();
        form.requestSubmit();
      },
    });
    errorAction.appendChild(button);
    errorAction.hidden = false;
    revealFormMessage(form, errorAction);
  };
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', text: config.submitLabel || `Run ${config.title}` });

  const wrappers = new Map();
  const refreshers = [];
  const refresh = () => {
    const visible = new Set(visibleFields(config, values).map((f) => f.name));
    for (const [name, wrapper] of wrappers) wrapper.hidden = !visible.has(name);
    // A section whose every field is hidden is an empty disclosure triangle — hide the section too.
    for (const [, entry] of sections) entry.details.hidden = ![...entry.body.querySelectorAll(':scope > .field')].some((f) => !f.hidden);
    for (const fill of refreshers) fill();
  };

  // Collapsed sections. `advanced: true` is the anonymous one, labelled "Options"; a field can
  // also name its own with `section: 'Comparisons'`, which is how a Minitab sub-dialog's worth of
  // settings reaches the form without a second window. Either way the form opens showing only
  // what the procedure actually needs.
  const sections = new Map(); // label -> {details, body}
  const sectionFor = (label) => {
    let entry = sections.get(label);
    if (!entry) {
      const body = h('div', { class: 'form-advanced-body' });
      entry = { details: h('details', { class: 'form-advanced' }, [h('summary', {}, [h('span', { text: label })]), body]), body };
      sections.set(label, entry);
    }
    return entry;
  };
  const lastGroupIn = new Map();

  for (const field of config.fields) {
    const sectionLabel = field.section || (field.advanced ? config.advancedLabel || 'Options' : null);
    const target = sectionLabel ? sectionFor(sectionLabel).body : form;
    if (field.group && lastGroupIn.get(target) !== field.group) {
      target.appendChild(h('p', { class: 'section-label', text: field.group }));
      lastGroupIn.set(target, field.group);
    }
    const control = fieldControl(field, values, refresh, refreshers);
    const children = field.type === 'checkbox' ? [control] : [h('label', { text: field.label }), control];
    if (field.hint) children.push(h('p', { class: 'settings-hint', text: field.hint }));
    const wrapper = h('div', { class: 'field' }, children);
    wrappers.set(field.name, wrapper);
    target.appendChild(wrapper);
  }
  // Named sections come before the anonymous Options block, which is always the last thing.
  const optionsLabel = config.advancedLabel || 'Options';
  for (const [label, entry] of sections) if (label !== optionsLabel) form.appendChild(entry.details);
  if (sections.has(optionsLabel)) form.appendChild(sections.get(optionsLabel).details);
  refresh();

  // A second, non-committing action next to the primary button — Change Data Type's "Preview
  // conversion", which answers "what would this cost me?" before anything is overwritten.
  const actions = [submit];
  if (secondary) {
    const button = h('button', { type: 'button', class: 'btn', text: secondary.label });
    button.addEventListener('click', async () => {
      const problem = validate(config, values);
      if (problem) {
        errorP.textContent = problem;
        errorP.hidden = false;
        return;
      }
      errorP.hidden = true;
      button.disabled = true;
      const idle = button.textContent;
      button.textContent = 'Working…';
      try {
        await secondary.run(values);
      } catch (err) {
        showError(err);
      } finally {
        button.disabled = false;
        button.textContent = idle;
      }
    });
    actions.push(button);
  }
  form.appendChild(h('div', { class: 'form-actions' }, actions));
  if (config.note) form.appendChild(h('p', { class: 'settings-hint', text: config.note }));
  form.appendChild(errorP);
  form.appendChild(errorAction);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const problem = validate(config, values);
    if (problem) {
      errorP.textContent = problem;
      errorP.hidden = false;
      errorAction.hidden = true;
      revealFormMessage(form, errorP);
      return;
    }
    errorP.hidden = true;
    errorAction.hidden = true;
    submit.disabled = true;
    const idle = submit.textContent;
    submit.textContent = 'Running…';
    try {
      await onSubmit(values);
    } catch (err) {
      showError(err);
    } finally {
      submit.disabled = false;
      submit.textContent = idle;
    }
  });

  return form;
}

// ---------------------------------------------------------------------------
// rendering a result
// ---------------------------------------------------------------------------

// Scalars that belong in the small run-detail table under the findings, in this order. Everything
// else in the payload is either a table, a graph, or already said in the narrative.
const DETAIL_KEYS = [
  ['method', 'Method'],
  ['equation', 'Regression equation'],
  ['null_hypothesis', 'Null hypothesis'],
  ['alternative_hypothesis', 'Alternative hypothesis'],
  ['confidence_level', 'Confidence level'],
  ['note', 'Note'],
];

export function buildDetails(result) {
  const rows = DETAIL_KEYS.filter(([key]) => result[key] !== null && result[key] !== undefined && result[key] !== '');
  if (!rows.length) return null;
  const tbody = h('tbody');
  for (const [key, label] of rows) tbody.appendChild(h('tr', {}, [h('th', { text: label }), h('td', { text: formatCell(result[key]) })]));
  const table = h('div', { class: 'table-scroll' }, [h('table', { class: 'scalar-table' }, [tbody])]);
  return block(
    { kind: 'table', name: 'Run details', rows: rows.map(([key, label]) => ({ Setting: label, Value: formatCell(result[key]) })) },
    table,
  );
}

export function drawGraph(container, entry) {
  const renderer = renderers[entry.renderer] || modelRenderers[entry.renderer];
  if (!renderer) {
    container.appendChild(h('p', { class: 'error', text: `No renderer is registered for '${entry.renderer}'.` }));
    return;
  }
  const wrap = h('div', { class: 'graph-block' });
  if (entry.title) wrap.appendChild(h('p', { class: 'section-label', text: entry.title }));
  // The chart is mounted INSIDE the block wrapper, and mounting needs the node connected — so the
  // block goes into the container before the renderer runs (see the detached-canvas trap).
  // printDraw is the same renderer again, for an export's print-sized host (see resultView.block).
  container.appendChild(
    block({ kind: 'chart', name: entry.title || 'Chart', printDraw: (printHost) => renderer(printHost, entry.data, { values: {} }) }, wrap),
  );
  const outcome = renderer(wrap, entry.data, { values: {} });
  if (outcome && typeof outcome.catch === 'function') outcome.catch((err) => wrap.appendChild(h('p', { class: 'error', text: err.message })));
}

// One PNG of every chart in the window, stacked — so a multi-panel result (four-in-one residuals, a
// graphical summary) reaches the exported report as the figure the user actually saw.
export function captureStack(container, onCapture, attempt = 0) {
  if (!onCapture) return;
  setTimeout(() => {
    const canvases = [...container.querySelectorAll('canvas')].filter((c) => c.width > 8 && c.height > 8);
    if (!canvases.length || !container.isConnected) {
      if (attempt < 3) captureStack(container, onCapture, attempt + 1);
      return;
    }
    try {
      const width = Math.max(...canvases.map((c) => c.width));
      const height = canvases.reduce((sum, c) => sum + c.height, 0);
      const sheet = document.createElement('canvas');
      sheet.width = width;
      sheet.height = height;
      const paint = sheet.getContext('2d');
      paint.fillStyle = theme.SURFACE;
      paint.fillRect(0, 0, width, height);
      let top = 0;
      for (const canvas of canvases) {
        paint.drawImage(canvas, 0, top);
        top += canvas.height;
      }
      const url = sheet.toDataURL('image/png');
      if (url && url.length > 256) onCapture(url);
    } catch {
      /* a tainted or zero-size canvas simply yields no capture */
    }
  }, theme.DRAW_MS + 250);
}

/** The standard result layout: narrative, tiles, output blocks, graphs, run details. */
/**
 * The warnings a procedure attached to its own result — a grouping column with 20 levels, groups
 * holding a single row. Shown above the findings, because they change how the findings should be
 * read; a warning under the last table is a warning nobody sees.
 */
export function buildWarnings(result) {
  const list = (result && result.warnings) || [];
  if (!Array.isArray(list) || !list.length) return null;
  const box = h('div');
  for (const text of list) if (text) box.appendChild(h('p', { class: 'warning', text }));
  if (!box.childElementCount) return null;
  return block({ kind: 'text', name: 'Warnings', text: list.filter(Boolean).join(' ') }, box);
}

export function renderStandard(container, result, { onCapture, extras } = {}) {
  const warnings = buildWarnings(result);
  if (warnings) container.appendChild(warnings);
  const narrative = buildTextBlock(result.conclusion);
  if (narrative) container.appendChild(narrative);
  const grid = buildStatGrid(result.highlights);
  if (grid) container.appendChild(grid);
  for (const table of result.tables || []) {
    const block = buildTableBlock(table.title, table.rows);
    if (block) container.appendChild(block);
  }
  for (const entry of result.graphs || []) drawGraph(container, entry);
  if (typeof extras === 'function') extras(container);
  const details = buildDetails(result);
  if (details) container.appendChild(details);
  captureStack(container, onCapture);
}

// What travels into an exported report and a saved project: the tables, the narrative and the
// scalars. The graph series (thousands of points) stay out — the chart reaches the report as the
// captured PNG instead. tables and highlights are kept so a reopened project still shows findings.
const HEAVY_KEYS = new Set(['graphs', 'panels', 'store_columns', 'matrix', 'p_matrix', 'predict_spec']);

export function reportPayload(result) {
  const payload = {};
  for (const [key, value] of Object.entries(result)) {
    if (key === 'tables' || key === 'highlights') {
      payload[key] = value;
      continue;
    }
    if (HEAVY_KEYS.has(key)) continue;
    if (value !== null && typeof value === 'object') continue;
    payload[key] = value;
  }
  return payload;
}
