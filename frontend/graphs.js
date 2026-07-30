// The Graph menu: builds its dropdown from the registry, opens a form window per graph type,
// fetches the computed series from the backend, renders it into a result window, and registers a
// PNG capture so any chart type can appear in an exported report.

import { apiClient } from './apiClient.js';
import * as wm from './windowManager.js';
import { GRAPHS, GRAPH_GROUPS, GRAPH_BY_ID, DISTRIBUTION_PARAMS, defaultValues, validate, buildRequest, describe } from './charts/graphConfig.js';
import { buildDropdown } from './menu.js';
import { renderers } from './charts/renderers.js';
import * as theme from './charts/theme.js';
// Only the block wrapper: this module has its own local h() for its forms.
import { block } from './resultView.js';
// ...and the shared warning renderer, so a crowded grouping column reads the same here as in the
// Stat menu's dialogs.
import { buildWarnings } from './procedureDialog.js';

let ctx = {
  dataset: () => null,
  addGraphResult: () => {},
  log: () => {},
};

export function init(options) {
  ctx = { ...ctx, ...options };
  buildMenu();
}

// ---------------------------------------------------------------------------
// menu
// ---------------------------------------------------------------------------

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  return node;
}

// The Graph menu is one short list of categories, each a flyout — 25 items in a single flat
// dropdown overflowed the viewport and made the last group unreachable.
export function graphMenuConfig() {
  const config = [
    {
      label: 'Graph Builder…',
      graph: '__builder__',
      icon: 'graph-builder',
      description: 'One dialog for every chart type: pick the chart first, then the columns it needs. The same charts are listed individually below.',
      needs: 'A worksheet with data in it.',
    },
    { separator: true },
  ];
  for (const group of GRAPH_GROUPS) {
    const items = GRAPHS.filter((g) => g.group === group.id);
    if (!items.length) continue;
    config.push({
      label: group.label,
      items: items.map((g) => ({ label: g.label, graph: g.id, icon: g.icon, description: g.description, needs: g.needs })),
    });
  }
  return config;
}

function buildMenu() {
  buildDropdown('graph', graphMenuConfig());
}

// ---------------------------------------------------------------------------
// column pickers
// ---------------------------------------------------------------------------

function columnsFor(filter) {
  const dataset = ctx.dataset();
  const all = (dataset && dataset.columns) || [];
  if (filter === 'numeric') return all.filter((c) => /int|float|number/i.test(c.dtype)).map((c) => c.name);
  if (filter === 'date') return all.filter((c) => /date|time/i.test(c.dtype)).map((c) => c.name);
  return all.map((c) => c.name);
}

function isNumericColumn(name) {
  return columnsFor('numeric').includes(name);
}

function fieldControl(field, values, onChange) {
  if (field.type === 'columns') {
    const options = columnsFor(field.filter);
    const list = h('div', { class: 'checkbox-list' });
    if (!options.length) list.appendChild(h('p', { class: 'muted', text: `No ${field.filter} columns in this worksheet.` }));
    for (const name of options) {
      const box = h('input', { type: 'checkbox' });
      box.checked = (values[field.name] || []).includes(name);
      box.addEventListener('change', () => {
        const current = values[field.name] || [];
        values[field.name] = box.checked ? [...current, name] : current.filter((c) => c !== name);
        onChange();
      });
      list.appendChild(h('label', { class: 'checkbox-item' }, [box, name]));
    }
    return list;
  }
  if (field.type === 'column') {
    const options = columnsFor(field.filter);
    const select = h('select', {}, [h('option', { value: '', text: field.required ? '— choose a column —' : '— none —' }), ...options.map((c) => h('option', { value: c, text: c }))]);
    select.value = values[field.name] || '';
    select.addEventListener('change', () => {
      values[field.name] = select.value;
      onChange();
    });
    return select;
  }
  if (field.type === 'select') {
    const select = h('select', {}, field.options.map((o) => h('option', { value: o, text: o })));
    select.value = values[field.name] ?? field.default ?? field.options[0];
    select.addEventListener('change', () => {
      values[field.name] = select.value;
      onChange();
    });
    return select;
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
  const input = h('input', { type: 'number', step: field.step ?? 'any', min: field.min, max: field.max });
  input.value = values[field.name] ?? '';
  input.addEventListener('input', () => {
    values[field.name] = input.value;
    onChange();
  });
  return input;
}

function buildGraphForm(graph, { onSubmit }) {
  const values = defaultValues(graph);
  const form = h('form', { class: 'tool-form' });
  const errorP = h('p', { class: 'error' });
  errorP.hidden = true;
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', text: `Draw ${graph.label.toLowerCase()}` });
  const wrappers = new Map();

  const refresh = () => {
    // the distribution form only asks for the parameters the chosen distribution actually has
    if (graph.id !== 'distribution') return;
    const active = DISTRIBUTION_PARAMS[values.distribution] || [];
    for (const [name, wrapper] of wrappers) {
      const field = graph.fields.find((f) => f.name === name);
      if (field && field.role === 'param') wrapper.hidden = !active.includes(name);
    }
  };

  for (const field of graph.fields) {
    const control = fieldControl(field, values, refresh);
    const wrapper =
      field.type === 'checkbox' ? h('div', { class: 'field' }, [control]) : h('div', { class: 'field' }, [h('label', { text: field.label }), control]);
    wrappers.set(field.name, wrapper);
    form.appendChild(wrapper);
  }
  refresh();

  // A refusal can carry its own fix: the backend's degenerate-group check names the two fields that
  // were probably filled the wrong way round (error.swap), and this offers the exchange as one click.
  // Same treatment as the Stat menu's dialogs — this menu just builds its own forms.
  const errorAction = h('div', { class: 'error-action' });
  errorAction.hidden = true;
  const reveal = (node) => {
    // Same reason as the Stat dialogs: a form window is sized when it opens, so a later error would
    // sit below the fold behind an unexpected scrollbar.
    const win = form.closest('.window');
    if (win && win.id) wm.fitToContent(win.id);
    if (node && node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
  };
  const showError = (err) => {
    errorP.textContent = err.message;
    errorP.hidden = false;
    errorAction.replaceChildren();
    errorAction.hidden = true;
    reveal(errorP);
    const swap = Array.isArray(err.swap) ? err.swap : null;
    if (!swap) return;
    const [a, b] = swap;
    const fields = graph.fields.map((f) => f.name);
    if (!fields.includes(a) || !fields.includes(b) || !values[a] || !values[b]) return;
    errorAction.appendChild(
      h('button', {
        type: 'button',
        class: 'btn btn-sm',
        text: `Swap ${values[a]} and ${values[b]}`,
        onClick: () => {
          const keep = values[a];
          values[a] = values[b];
          values[b] = keep;
          for (const [name, wrapper] of wrappers) {
            if (name !== a && name !== b) continue;
            const select = wrapper.querySelector('select');
            if (select) select.value = values[name] || '';
          }
          errorP.hidden = true;
          errorAction.hidden = true;
          form.requestSubmit();
        },
      }),
    );
    errorAction.hidden = false;
    reveal(errorAction);
  };

  form.appendChild(h('div', { class: 'form-actions' }, [submit]));
  form.appendChild(errorP);
  form.appendChild(errorAction);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const problem = validate(graph, values);
    if (problem) {
      errorP.textContent = problem;
      errorP.hidden = false;
      errorAction.hidden = true;
      reveal(errorP);
      return;
    }
    errorP.hidden = true;
    errorAction.hidden = true;
    submit.disabled = true;
    const idle = submit.textContent;
    submit.textContent = 'Drawing…';
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
// rendering a graph into a result window
// ---------------------------------------------------------------------------

// Point arrays can be thousands of rows; a report wants the summary and the picture, not the raw
// coordinates. This keeps the scalars and any table small enough to actually print.
const BIG_ARRAY_KEYS = new Set(['points', 'rows', 'panels', 'cells', 'series', 'z', 'x', 'y', 'shaded']);

function reportPayload(graph, data, values, summaryText) {
  const payload = { summary: summaryText, graph_type: graph.backend };
  for (const [key, value] of Object.entries(data)) {
    if (BIG_ARRAY_KEYS.has(key)) continue;
    if (Array.isArray(value)) {
      if (value.length && value.length <= 30 && value.every((v) => v && typeof v === 'object')) payload[key] = value;
      continue;
    }
    if (value !== null && typeof value === 'object') continue;
    payload[key] = value;
  }
  return payload;
}

function graphWindowKind(graph) {
  if (graph.text) return 'result';
  return 'chart';
}

async function renderGraph(graph, values) {
  const dataset = ctx.dataset();
  if (!dataset) throw new Error('Load a worksheet first.');
  const request = buildRequest(graph, values);
  const response = await apiClient.graphData(dataset.dataset_id, request);
  const data = response.data;
  const label = describe(graph, values);

  const render = (container, { onCapture } = {}) => {
    const renderer = renderers[graph.renderer];
    if (!renderer) {
      container.appendChild(h('p', { class: 'error', text: `No renderer is registered for '${graph.renderer}'.` }));
      return;
    }
    // A Graph-menu result renders through its own path rather than renderStandard, so it wraps itself
    // in the standard block — otherwise the entire Graph menu's output is the one thing in the app
    // with no chevron menu. The wrapper is attached BEFORE the renderer runs: a Chart.js chart built
    // in a detached element paints nothing.
    // A crowded grouping column is allowed but called out — above the chart, where it will be read
    // (the outright refusals never get this far; the backend raises them). Same wording the Stat menu
    // shows, from the same check in procedures.check_group_column.
    const warnings = buildWarnings(data);
    if (warnings) container.appendChild(warnings);

    const host = h('div');
    // printDraw re-runs this very renderer into an export-sized host, so the figure in a report is
    // rendered for print rather than photographed off the screen (see resultView.block).
    container.appendChild(
      block({ kind: 'chart', name: graph.label, printDraw: (printHost) => renderer(printHost, data, { values }) }, host),
    );
    const result = renderer(host, data, { values, onCapture });
    if (result && typeof result.catch === 'function') {
      result.catch((err) => host.appendChild(h('p', { class: 'error', text: err.message })));
    }
  };

  const summaryText = `${label} — drawn from ${dataset.source}.`;
  ctx.addGraphResult({
    analysisId: `graph_${graph.id}`,
    label,
    data: reportPayload(graph, data, values, summaryText),
    kind: graphWindowKind(graph),
    values,
    render,
  });
}

export function openGraph(graphId) {
  if (graphId === '__builder__') return openBuilder();
  const graph = GRAPH_BY_ID[graphId];
  if (!graph) return;

  const winId = `graph-form-${graph.id}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }
  if (!ctx.dataset() && !graph.noData) {
    wm.createWindow({ id: winId, title: graph.label, kind: 'form', content: h('p', { class: 'muted', text: 'Load a worksheet first — the column pickers come from it.' }) });
    return;
  }

  let win;
  const content = buildGraphForm(graph, {
    onSubmit: async (values) => {
      await renderGraph(graph, values);
      if (win) win.close();
    },
  });
  win = wm.createWindow({ id: winId, title: graph.label, kind: 'form', content });
}

// ---------------------------------------------------------------------------
// Graph Builder — dropdown-driven, with a live preview
// ---------------------------------------------------------------------------

// Which graphs make sense for the chosen columns, and how to fill their fields from X/Y/Group.
function builderCandidates(xCol, yCol) {
  if (!xCol) return [];
  const xNum = isNumericColumn(xCol);
  const yNum = yCol ? isNumericColumn(yCol) : false;
  const dataset = ctx.dataset();
  const dtype = ((dataset && dataset.columns) || []).find((c) => c.name === xCol)?.dtype || '';
  const xDate = /date|time/i.test(dtype);

  const pick = (id, map) => ({ id, label: GRAPH_BY_ID[id].label, map });

  if (yCol && xDate) return [pick('time_series', () => ({ date: xCol, value: yCol }))];
  if (yCol && xNum && yNum) {
    return [
      pick('scatter', (g) => ({ x: xCol, y: yCol, group_column: g })),
      pick('line', () => ({ x: xCol, y: yCol })),
      pick('area', () => ({ x: xCol, y: yCol })),
      pick('binned_scatter', () => ({ x: xCol, y: yCol, x_bins: 12, y_bins: 10 })),
      pick('marginal', () => ({ x: xCol, y: yCol })),
    ];
  }
  if (yCol && !xNum && yNum) {
    return [
      pick('bar', (g) => ({ category: xCol, value: yCol, aggregate: 'mean', group_column: g })),
      pick('boxplot', () => ({ columns: [yCol], group_column: xCol })),
      pick('individual_value', () => ({ column: yCol, group_column: xCol })),
      pick('interval', () => ({ column: yCol, group_column: xCol, confidence: 0.95 })),
    ];
  }
  if (!yCol && xNum) {
    return [
      pick('histogram', () => ({ column: xCol })),
      pick('dotplot', () => ({ column: xCol })),
      pick('ecdf', (g) => ({ column: xCol, group_column: g })),
      pick('probability', () => ({ column: xCol })),
      pick('boxplot', (g) => ({ columns: [xCol], group_column: g })),
    ];
  }
  return [pick('bar', () => ({ category: xCol, aggregate: 'mean' })), pick('pie', () => ({ category: xCol }))];
}

export function openBuilder() {
  if (wm.has('graph-builder')) {
    wm.focus('graph-builder');
    return;
  }
  const dataset = ctx.dataset();
  if (!dataset) {
    wm.createWindow({ id: 'graph-builder', title: 'Graph Builder', kind: 'form', content: h('p', { class: 'muted', text: 'Load a worksheet first.' }) });
    return;
  }

  const state = { x: '', y: '', group: '', type: '' };
  const allColumns = columnsFor('any');

  const select = (placeholder, onChange) => {
    const node = h('select', {}, [h('option', { value: '', text: placeholder }), ...allColumns.map((c) => h('option', { value: c, text: c }))]);
    node.addEventListener('change', () => onChange(node.value));
    return node;
  };

  const typeSelect = h('select', {});
  const preview = h('div', { class: 'builder-preview' });
  const status = h('p', { class: 'status' });
  status.hidden = true;
  const errorP = h('p', { class: 'error' });
  errorP.hidden = true;
  const addBtn = h('button', { type: 'button', class: 'btn btn-primary', text: 'Add to session' });
  addBtn.disabled = true;

  let candidates = [];
  let lastRender = null;
  let timer = null;

  function refreshTypes() {
    candidates = builderCandidates(state.x, state.y);
    typeSelect.innerHTML = '';
    for (const candidate of candidates) typeSelect.appendChild(h('option', { value: candidate.id, text: candidate.label }));
    if (!candidates.some((c) => c.id === state.type)) state.type = candidates.length ? candidates[0].id : '';
    typeSelect.value = state.type;
    typeSelect.disabled = !candidates.length;
  }

  function schedulePreview() {
    clearTimeout(timer);
    timer = setTimeout(drawPreview, 220); // live, but not one request per keystroke
  }

  async function drawPreview() {
    const candidate = candidates.find((c) => c.id === state.type);
    preview.innerHTML = '';
    addBtn.disabled = true;
    lastRender = null;
    if (!state.x || !candidate) {
      preview.appendChild(h('p', { class: 'muted', text: 'Choose an X column to see a preview.' }));
      return;
    }
    const graph = GRAPH_BY_ID[candidate.id];
    const values = { ...defaultValues(graph), ...candidate.map(state.group || '') };
    const problem = validate(graph, values);
    if (problem) {
      preview.appendChild(h('p', { class: 'muted', text: problem }));
      return;
    }
    status.hidden = false;
    errorP.hidden = true;
    try {
      const response = await apiClient.graphData(dataset.dataset_id, buildRequest(graph, values));
      preview.innerHTML = '';
      const renderer = renderers[graph.renderer];
      const outcome = renderer(preview, response.data, { values });
      if (outcome && typeof outcome.catch === 'function') await outcome;
      lastRender = { graph, values, data: response.data };
      addBtn.disabled = false;
    } catch (err) {
      preview.innerHTML = '';
      errorP.textContent = err.message;
      errorP.hidden = false;
    } finally {
      status.hidden = true;
    }
  }

  const xSelect = select('— choose X —', (v) => {
    state.x = v;
    refreshTypes();
    schedulePreview();
  });
  const ySelect = select('— none —', (v) => {
    state.y = v;
    refreshTypes();
    schedulePreview();
  });
  const groupSelect = select('— none —', (v) => {
    state.group = v;
    schedulePreview();
  });
  typeSelect.addEventListener('change', () => {
    state.type = typeSelect.value;
    schedulePreview();
  });

  addBtn.addEventListener('click', async () => {
    if (!lastRender) return;
    addBtn.disabled = true;
    try {
      await renderGraph(lastRender.graph, lastRender.values);
    } finally {
      addBtn.disabled = false;
    }
  });

  refreshTypes();
  const content = h('div', { class: 'builder' }, [
    h('div', { class: 'builder-controls' }, [
      h('div', { class: 'field' }, [h('label', { text: 'X' }), xSelect]),
      h('div', { class: 'field' }, [h('label', { text: 'Y (optional)' }), ySelect]),
      h('div', { class: 'field' }, [h('label', { text: 'Group / color (optional)' }), groupSelect]),
      h('div', { class: 'field' }, [h('label', { text: 'Chart type' }), typeSelect]),
    ]),
    status,
    errorP,
    preview,
    h('div', { class: 'form-actions' }, [addBtn]),
  ]);

  wm.createWindow({ id: 'graph-builder', title: 'Graph Builder', kind: 'builder', content });
  drawPreview();
}

export function graphMenuIds() {
  return GRAPHS.map((g) => g.id);
}

export { theme };
