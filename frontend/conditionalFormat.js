// Conditional formatting for the worksheet grid: per-column rules that tint the cells they match.
//
// A rule is data, not a style — {worksheet, column, kind, params, color} — so the whole set is
// written into the .baproj project file and comes back with it. Rules are recomputed from the live
// grid on every render, which is what makes "highest 5" and "outside 3 sigma" stay right as cells
// are edited.
//
// Colors are token pairs (--cf-amber-light / --cf-amber-dark equivalents live in style.css, one
// value per theme), so a highlight that reads as a soft wash in light mode reads as a soft wash in
// dark mode too rather than as a solid block. The tint sits *under* the selection wash: a selected
// cell must always show its selection, so the grid's own selection rule wins where they overlap.

import * as wm from './windowManager.js';
import * as dialogs from './dialogs.js';
import * as dialog from './procedureDialog.js';
import { h } from './resultView.js';

export const COLORS = [
  { value: 'amber', label: 'Amber' },
  { value: 'blue', label: 'Blue' },
  { value: 'green', label: 'Green' },
  { value: 'red', label: 'Red' },
  { value: 'teal', label: 'Teal' },
  { value: 'grey', label: 'Grey' },
];

const COLOR_VALUES = new Set(COLORS.map((c) => c.value));

let ctx = { log: () => {}, dataset: () => null, gridValues: () => [], repaint: () => {} };
let rules = [];
let seq = 1;

// Recomputed by prepare(): column name -> Map(rowIndex -> color)
let painted = new Map();

export function init(options) {
  ctx = { ...ctx, ...options };
}

// ---------------------------------------------------------------------------
// the rule kinds
// ---------------------------------------------------------------------------

const colorField = () => ({
  name: 'color',
  label: 'Highlight colour',
  type: 'select',
  options: COLORS,
  default: 'amber',
});

const numericColumn = (label = 'Column') => ({ name: 'column', label, type: 'column', filter: 'numeric', required: true });
const anyColumn = (label = 'Column') => ({ name: 'column', label, type: 'column', filter: 'any', required: true });

export const RULE_KINDS = [
  {
    kind: 'greater',
    icon: 'cf-greater',
    description: 'Tints the cells of a column whose value is above a given number.',
    needs: 'One numeric column.',
    label: 'Greater Than…',
    title: 'Highlight Cells Greater Than',
    group: 'Highlight Cell',
    fields: [numericColumn(), { name: 'value', label: 'Greater than', type: 'number', step: 'any', required: true }, colorField()],
    describe: (r) => `> ${r.params.value}`,
  },
  {
    kind: 'less',
    icon: 'cf-less',
    description: 'Tints the cells of a column whose value is below a given number.',
    needs: 'One numeric column.',
    label: 'Less Than…',
    title: 'Highlight Cells Less Than',
    group: 'Highlight Cell',
    fields: [numericColumn(), { name: 'value', label: 'Less than', type: 'number', step: 'any', required: true }, colorField()],
    describe: (r) => `< ${r.params.value}`,
  },
  {
    kind: 'equal',
    icon: 'cf-equal',
    description: 'Tints the cells exactly matching a value. Works on text as well as numbers.',
    needs: 'One column.',
    label: 'Equal To…',
    title: 'Highlight Cells Equal To',
    group: 'Highlight Cell',
    fields: [anyColumn(), { name: 'value', label: 'Equal to', type: 'text', required: true }, colorField()],
    describe: (r) => `= ${r.params.value}`,
  },
  {
    kind: 'between',
    icon: 'cf-between',
    description: 'Tints the cells falling inside a range, endpoints included.',
    needs: 'One numeric column.',
    label: 'Between…',
    title: 'Highlight Cells Between',
    group: 'Highlight Cell',
    fields: [
      numericColumn(),
      { name: 'low', label: 'From', type: 'number', step: 'any', required: true },
      { name: 'high', label: 'To', type: 'number', step: 'any', required: true },
      colorField(),
    ],
    describe: (r) => `between ${r.params.low} and ${r.params.high}`,
  },
  {
    kind: 'contains',
    icon: 'cf-contains',
    description: 'Tints the cells whose text contains a fragment, anywhere in the value.',
    needs: 'One column.',
    label: 'Contains Text…',
    title: 'Highlight Cells Containing Text',
    group: 'Highlight Cell',
    fields: [anyColumn(), { name: 'text', label: 'Contains', type: 'text', required: true }, colorField()],
    describe: (r) => `contains "${r.params.text}"`,
  },
  {
    kind: 'top_n',
    icon: 'cf-top-n',
    description: 'Tints the N largest values in a column. Recomputed after every edit, so the highlight follows the data.',
    needs: 'One numeric column.',
    label: 'Highest N Values…',
    title: 'Highlight the Highest N Values',
    group: 'High/Low',
    fields: [numericColumn(), { name: 'n', label: 'How many', type: 'number', min: 1, step: 1, default: 5, required: true }, colorField()],
    describe: (r) => `highest ${r.params.n}`,
  },
  {
    kind: 'bottom_n',
    icon: 'cf-bottom-n',
    description: 'Tints the N smallest values in a column. Recomputed after every edit, so the highlight follows the data.',
    needs: 'One numeric column.',
    label: 'Lowest N Values…',
    title: 'Highlight the Lowest N Values',
    group: 'High/Low',
    fields: [numericColumn(), { name: 'n', label: 'How many', type: 'number', min: 1, step: 1, default: 5, required: true }, colorField()],
    describe: (r) => `lowest ${r.params.n}`,
  },
  {
    kind: 'sigma3',
    icon: 'cf-sigma3',
    description: 'Tints values further than three standard deviations from the column mean — the control-chart rule for a point that is out of family.',
    needs: 'One numeric column.',
    label: 'Out of 3-Sigma Control…',
    title: 'Highlight Values Outside 3 Sigma',
    group: 'Statistical',
    fields: [numericColumn(), { ...colorField(), default: 'red' }],
    describe: () => 'outside mean ± 3 s',
    note: 'Highlights every value further than three standard deviations from the column mean.',
  },
  {
    kind: 'iqr_outlier',
    icon: 'cf-iqr-outlier',
    description: 'Tints values below Q1 − 1.5 × IQR or above Q3 + 1.5 × IQR: the same rule a boxplot uses to decide which points to draw separately. More robust than the 3-sigma rule on skewed data.',
    needs: 'One numeric column.',
    label: 'Outliers (IQR rule)…',
    title: 'Highlight Outliers',
    group: 'Statistical',
    fields: [numericColumn(), { ...colorField(), default: 'red' }],
    describe: () => 'IQR outlier',
    note: 'Highlights values below Q1 − 1.5 × IQR or above Q3 + 1.5 × IQR — the same rule a boxplot uses to draw its outlier points.',
  },
  {
    kind: 'pareto',
    icon: 'cf-pareto',
    description: 'Ranks categories by their share of a value column\'s total and tints the few that together make up the named share — the vital few of a Pareto analysis.',
    needs: 'A category column and a numeric value column.',
    label: 'Top X% of a Total…',
    title: 'Highlight the Pareto "Vital Few"',
    group: 'Pareto',
    fields: [
      anyColumn('Category column (the cells that get highlighted)'),
      { name: 'value_column', label: 'Value column (what is totalled)', type: 'column', filter: 'numeric', required: true },
      { name: 'percent', label: 'Top share of the total (%)', type: 'number', min: 1, max: 100, step: 'any', default: 80, required: true },
      { ...colorField(), default: 'amber' },
    ],
    describe: (r) => `top ${r.params.percent}% of ${r.params.value_column}`,
    note: 'Categories are ranked by their share of the value column’s total; the ones that together make up the chosen share are highlighted.',
  },
];

export const RULE_BY_KIND = Object.fromEntries(RULE_KINDS.map((r) => [r.kind, r]));

/** The Conditional Formatting flyout, grouped the way the rule kinds are. */
export function menuConfig() {
  const entries = [];
  let lastGroup = null;
  for (const kind of RULE_KINDS) {
    if (kind.group !== lastGroup) {
      if (lastGroup !== null) entries.push({ separator: true });
      entries.push({ groupLabel: kind.group });
      lastGroup = kind.group;
    }
    entries.push({ label: kind.label, action: `cf-${kind.kind}`, icon: kind.icon, description: kind.description, needs: kind.needs });
  }
  entries.push({ separator: true });
  entries.push({
    label: 'Manage Rules…',
    action: 'cf-manage',
    icon: 'cf-manage',
    description: 'Lists every formatting rule on every worksheet, and removes them one at a time.',
  });
  entries.push({
    label: 'Clear Rules',
    items: [
      {
        label: 'This Column',
        action: 'cf-clear-column',
        icon: 'cf-clear-column',
        description: 'Removes the formatting rules on the selected column only.',
        needs: 'A cell selected in the column to clear.',
      },
      {
        label: 'All Columns',
        action: 'cf-clear-all',
        icon: 'cf-clear-all',
        description: 'Removes every formatting rule on this worksheet.',
      },
    ],
  });
  return entries;
}

// ---------------------------------------------------------------------------
// the rule store
// ---------------------------------------------------------------------------

export function all() {
  return rules.map((r) => ({ ...r, params: { ...r.params } }));
}

export function forWorksheet(worksheetId) {
  return rules.filter((r) => r.worksheet === worksheetId);
}

export function setRules(next) {
  rules = (next || []).map((r) => ({
    id: r.id || `cf-${seq++}`,
    worksheet: r.worksheet || null,
    // A rule out of a project file names its worksheet by index, not by id — carry that through
    // so remapWorksheets() below can still find it. Dropping it here left every restored rule
    // pointing at no worksheet, which is a rule that quietly never fires.
    worksheetIndex: typeof r.worksheetIndex === 'number' ? r.worksheetIndex : undefined,
    column: r.column,
    kind: r.kind,
    params: { ...(r.params || {}) },
    color: COLOR_VALUES.has(r.color) ? r.color : 'amber',
  }));
  seq = rules.reduce((max, r) => Math.max(max, Number(String(r.id).replace(/\D/g, '')) || 0), 0) + 1;
  ctx.repaint();
}

export function addRule(rule) {
  const record = { id: `cf-${seq++}`, ...rule, params: { ...(rule.params || {}) } };
  rules.push(record);
  ctx.repaint();
  return record;
}

export function removeRule(id) {
  rules = rules.filter((r) => r.id !== id);
  ctx.repaint();
}

export function clearColumn(worksheetId, column) {
  const before = rules.length;
  rules = rules.filter((r) => !(r.worksheet === worksheetId && r.column === column));
  ctx.repaint();
  return before - rules.length;
}

export function clearWorksheet(worksheetId) {
  const before = rules.length;
  rules = rules.filter((r) => r.worksheet !== worksheetId);
  ctx.repaint();
  return before - rules.length;
}

/** Worksheet ids change every time a project is reopened; rules are re-pointed by index. */
export function remapWorksheets(idByIndex) {
  for (const rule of rules) {
    if (typeof rule.worksheetIndex === 'number') {
      rule.worksheet = idByIndex[rule.worksheetIndex] || null;
      delete rule.worksheetIndex;
    }
  }
  ctx.repaint();
}

// ---------------------------------------------------------------------------
// evaluation
// ---------------------------------------------------------------------------

const num = (v) => {
  if (v === null || v === undefined || v === '') return NaN;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
};

function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function matchingRows(rule, rows) {
  const column = rule.column;
  const hits = [];
  const values = rows.map((row) => (row ? row[column] : null));

  switch (rule.kind) {
    case 'greater':
    case 'less': {
      const target = num(rule.params.value);
      values.forEach((v, i) => {
        const n = num(v);
        if (!Number.isNaN(n) && (rule.kind === 'greater' ? n > target : n < target)) hits.push(i);
      });
      return hits;
    }
    case 'equal': {
      const raw = String(rule.params.value ?? '').trim();
      const target = num(raw);
      values.forEach((v, i) => {
        if (v === null || v === undefined || v === '') return;
        const n = num(v);
        if (!Number.isNaN(n) && !Number.isNaN(target)) {
          if (n === target) hits.push(i);
        } else if (String(v).trim() === raw) hits.push(i);
      });
      return hits;
    }
    case 'between': {
      let lo = num(rule.params.low);
      let hi = num(rule.params.high);
      if (lo > hi) [lo, hi] = [hi, lo];
      values.forEach((v, i) => {
        const n = num(v);
        if (!Number.isNaN(n) && n >= lo && n <= hi) hits.push(i);
      });
      return hits;
    }
    case 'contains': {
      const needle = String(rule.params.text ?? '').toLowerCase();
      if (!needle) return hits;
      values.forEach((v, i) => {
        if (v !== null && v !== undefined && String(v).toLowerCase().includes(needle)) hits.push(i);
      });
      return hits;
    }
    case 'top_n':
    case 'bottom_n': {
      const n = Math.max(1, Math.round(num(rule.params.n) || 1));
      const indexed = values.map((v, i) => ({ i, n: num(v) })).filter((e) => !Number.isNaN(e.n));
      indexed.sort((a, b) => (rule.kind === 'top_n' ? b.n - a.n : a.n - b.n));
      // Ties at the cut-off are all kept, so "highest 3" never picks arbitrarily between equals.
      if (!indexed.length) return hits;
      const cutoff = indexed[Math.min(n, indexed.length) - 1].n;
      for (const entry of indexed) {
        if (rule.kind === 'top_n' ? entry.n >= cutoff : entry.n <= cutoff) hits.push(entry.i);
      }
      return hits;
    }
    case 'sigma3': {
      const numbers = values.map(num).filter((n) => !Number.isNaN(n));
      if (numbers.length < 2) return hits;
      const mean = numbers.reduce((a, b) => a + b, 0) / numbers.length;
      const sd = Math.sqrt(numbers.reduce((a, b) => a + (b - mean) ** 2, 0) / (numbers.length - 1));
      if (!(sd > 0)) return hits;
      values.forEach((v, i) => {
        const n = num(v);
        if (!Number.isNaN(n) && Math.abs(n - mean) > 3 * sd) hits.push(i);
      });
      return hits;
    }
    case 'iqr_outlier': {
      const numbers = values.map(num).filter((n) => !Number.isNaN(n)).sort((a, b) => a - b);
      if (numbers.length < 4) return hits;
      const q1 = quantile(numbers, 0.25);
      const q3 = quantile(numbers, 0.75);
      const iqr = q3 - q1;
      values.forEach((v, i) => {
        const n = num(v);
        if (!Number.isNaN(n) && (n < q1 - 1.5 * iqr || n > q3 + 1.5 * iqr)) hits.push(i);
      });
      return hits;
    }
    case 'pareto': {
      const valueColumn = rule.params.value_column;
      const share = Math.min(100, Math.max(1, num(rule.params.percent) || 80)) / 100;
      const totals = new Map();
      rows.forEach((row) => {
        const key = row && row[column] !== null && row[column] !== undefined && row[column] !== '' ? String(row[column]) : null;
        const n = num(row ? row[valueColumn] : null);
        if (key === null || Number.isNaN(n) || n <= 0) return;
        totals.set(key, (totals.get(key) || 0) + n);
      });
      const grand = [...totals.values()].reduce((a, b) => a + b, 0);
      if (!(grand > 0)) return hits;
      const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]);
      const vital = new Set();
      let running = 0;
      for (const [key, value] of ranked) {
        vital.add(key);
        running += value;
        if (running / grand >= share) break; // this category is the one that crosses the line
      }
      rows.forEach((row, i) => {
        const key = row && row[column] !== null && row[column] !== undefined && row[column] !== '' ? String(row[column]) : null;
        if (key !== null && vital.has(key)) hits.push(i);
      });
      return hits;
    }
    default:
      return hits;
  }
}

/** Recompute every rule for the worksheet about to be drawn. Called once per grid render. */
export function prepare(worksheetId, grid) {
  painted = new Map();
  const columns = new Set((grid.columns || []).map((c) => c.name));
  for (const rule of rules) {
    if (rule.worksheet !== worksheetId) continue;
    if (!columns.has(rule.column)) continue; // the column was renamed or deleted — the rule sleeps
    if (rule.kind === 'pareto' && !columns.has(rule.params.value_column)) continue;
    let map = painted.get(rule.column);
    if (!map) {
      map = new Map();
      painted.set(rule.column, map);
    }
    // Later rules win where two overlap, matching the order Manage Rules lists them in.
    for (const rowIndex of matchingRows(rule, grid.rows || [])) map.set(rowIndex, rule.color);
  }
  return painted;
}

export function colorFor(columnName, rowIndex) {
  const map = painted.get(columnName);
  return map ? map.get(rowIndex) || null : null;
}

export function activeCount() {
  let total = 0;
  for (const map of painted.values()) total += map.size;
  return total;
}

// ---------------------------------------------------------------------------
// dialogs
// ---------------------------------------------------------------------------

export function describeRule(rule) {
  const kind = RULE_BY_KIND[rule.kind];
  return kind ? kind.describe(rule) : rule.kind;
}

export function openRuleDialog(kind, initialValues) {
  const config = RULE_BY_KIND[kind];
  if (!config) return;
  const dataset = ctx.dataset();
  if (!dataset) return;

  const winId = `cf-form-${kind}`;
  if (wm.has(winId)) {
    wm.focus(winId);
    return;
  }

  let win;
  const content = dialog.buildForm({ ...config, submitLabel: 'Apply highlight' }, initialValues, {
    onSubmit: (values) => {
      const params = {};
      for (const field of config.fields) {
        if (field.name === 'column' || field.name === 'color') continue;
        params[field.name] = values[field.name];
      }
      const rule = addRule({ worksheet: dataset.dataset_id, column: values.column, kind, params, color: values.color });
      ctx.log(`> Conditional formatting: ${rule.column} ${describeRule(rule)} → ${rule.color}.`);
      if (win) win.close();
    },
  });
  win = wm.createWindow({ id: winId, title: config.title, kind: 'form', content });
}

function renderManageInto(body) {
  body.innerHTML = '';
  const dataset = ctx.dataset();
  const mine = dataset ? forWorksheet(dataset.dataset_id) : [];
  const elsewhere = rules.length - mine.length;

  body.appendChild(
    h('p', { class: 'muted', text: dataset ? `Rules on ${dataset.name || dataset.source}. They are recomputed whenever the data changes, and saved with the project.` : 'No worksheet.' }),
  );

  if (!mine.length) {
    body.appendChild(h('p', { class: 'settings-hint', text: 'No rules on this worksheet yet. Add one from Data > Conditional Formatting.' }));
  } else {
    const tbody = h('tbody');
    for (const rule of mine) {
      tbody.appendChild(
        h('tr', {}, [
          h('td', { text: rule.column }),
          h('td', { text: RULE_BY_KIND[rule.kind] ? RULE_BY_KIND[rule.kind].group : '' }),
          h('td', { text: describeRule(rule) }),
          h('td', {}, [h('span', { class: `cf-swatch cf-${rule.color}`, title: rule.color }), h('span', { class: 'cf-swatch-label', text: rule.color })]),
          h('td', {}, [
            h('button', {
              type: 'button',
              class: 'btn btn-sm',
              text: 'Edit',
              onClick: () => {
                const values = { column: rule.column, color: rule.color, ...rule.params };
                removeRule(rule.id);
                renderManageInto(body);
                openRuleDialog(rule.kind, values);
              },
            }),
            h('button', {
              type: 'button',
              class: 'btn btn-sm',
              text: 'Delete',
              onClick: () => {
                removeRule(rule.id);
                ctx.log(`> Removed the ${describeRule(rule)} rule on ${rule.column}.`);
                renderManageInto(body);
              },
            }),
          ]),
        ]),
      );
    }
    body.appendChild(
      h('div', { class: 'table-scroll' }, [
        h('table', { class: 'result-table' }, [
          h('thead', {}, [h('tr', {}, [h('th', { text: 'Column' }), h('th', { text: 'Kind' }), h('th', { text: 'Rule' }), h('th', { text: 'Colour' }), h('th', { text: '' })])]),
          tbody,
        ]),
      ]),
    );
    body.appendChild(h('p', { class: 'settings-hint', text: 'Where two rules cover the same cell, the one further down this list wins.' }));
  }

  const actions = h('div', { class: 'form-actions' }, [
    mine.length
      ? h('button', {
          type: 'button',
          class: 'btn btn-danger',
          text: 'Clear all rules on this worksheet',
          onClick: async () => {
            const ok = await dialogs.confirm({
              title: 'Clear Rules',
              message: `Remove all ${mine.length} rule(s) on this worksheet?`,
              confirmLabel: 'Clear rules',
              danger: true,
            });
            if (!ok) return;
            const removed = clearWorksheet(dataset.dataset_id);
            ctx.log(`> Cleared ${removed} conditional formatting rule(s).`);
            renderManageInto(body);
          },
        })
      : null,
  ]);
  body.appendChild(actions);
  if (elsewhere) body.appendChild(h('p', { class: 'settings-hint', text: `${elsewhere} more rule(s) belong to other worksheets.` }));
}

export function openManageWindow() {
  if (wm.has('cf-manage')) {
    wm.focus('cf-manage');
    return;
  }
  const body = h('div');
  renderManageInto(body);
  wm.createWindow({ id: 'cf-manage', title: 'Manage Conditional Formatting Rules', kind: 'summary', width: 640, content: body });
}

/** Keeps an open Manage Rules window in step with a rule added from the menu. */
export function refreshManageWindow() {
  const win = wm.get('cf-manage');
  if (win) renderManageInto(win.body);
}
