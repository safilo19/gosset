// Stored matrices — Minitab's M1, M2, … Each holds a rectangular block of numbers and an optional
// name, and the whole store lives with the project: it is written into the .baproj file and
// restored with it, exactly like the constants store in constants.js.
//
// The store is client-side; the arithmetic is not. An operation posts the matrices it needs to
// /calc and gets a new one back, so numpy does the linear algebra and nothing about a matrix has
// to live on the server between calls.

import * as wm from './windowManager.js';
import * as dialogs from './dialogs.js';
import { h, formatCell } from './resultView.js';

let ctx = { log: () => {}, onChange: () => {} };
let store = []; // [{key: 'M1', name: '', rows: [[...]]}]

export function init(options) {
  ctx = { ...ctx, ...options };
}

function nextKey() {
  let n = 1;
  const taken = new Set(store.map((m) => m.key));
  while (taken.has(`M${n}`)) n += 1;
  return `M${n}`;
}

export function list() {
  return store.map((m) => ({ key: m.key, name: m.name, rows: m.rows.map((r) => [...r]) }));
}

export function count() {
  return store.length;
}

export function get(key) {
  return store.find((m) => m.key === key || (m.name && m.name === key)) || null;
}

export function rowsOf(key) {
  const matrix = get(key);
  return matrix ? matrix.rows : null;
}

/** 'M1 (3×2)' — what a picker shows. */
export function label(matrix) {
  const name = matrix.name ? ` ${matrix.name}` : '';
  const rows = matrix.rows.length;
  const cols = rows ? matrix.rows[0].length : 0;
  return `${matrix.key}${name} (${rows}×${cols})`;
}

export function options() {
  return store.map((m) => ({ key: m.key, label: label(m) }));
}

export function set(next) {
  store = (next || [])
    .filter((m) => Array.isArray(m && m.rows))
    .map((m, i) => ({ key: m.key || `M${i + 1}`, name: m.name || '', rows: m.rows.map((r) => [...r]) }));
  refresh();
}

/** Store under an explicit key when one is given, otherwise mint the next free M-number. */
export function put(key, rows, name) {
  const cleaned = (rows || []).map((r) => r.map((v) => (v === null || v === undefined ? 0 : Number(v))));
  const wanted = String(key || '').trim();
  const existing = wanted ? store.find((m) => m.key === wanted) : null;
  if (existing) {
    existing.rows = cleaned;
    if (name !== undefined) existing.name = name;
    refresh();
    return existing;
  }
  const record = { key: wanted || nextKey(), name: name || '', rows: cleaned };
  store.push(record);
  refresh();
  return record;
}

export function remove(key) {
  store = store.filter((m) => m.key !== key);
  refresh();
}

export function clear() {
  store = [];
  refresh();
}

function refresh() {
  ctx.onChange(list());
  const win = wm.get('matrices');
  if (win) renderInto(win.body);
}

// ---------------------------------------------------------------------------
// the Matrices window
// ---------------------------------------------------------------------------

function viewMatrix(matrix) {
  const rows = matrix.rows;
  const cols = rows.length ? rows[0].length : 0;
  const shownRows = Math.min(rows.length, 40);
  const shownCols = Math.min(cols, 20);
  const body = h('div');
  body.appendChild(h('p', { class: 'muted', text: `${label(matrix)}${rows.length > shownRows || cols > shownCols ? ` — showing the first ${shownRows}×${shownCols}` : ''}` }));
  const head = h('tr', {}, [h('th', { text: '' }), ...Array.from({ length: shownCols }, (_, j) => h('th', { text: `c${j + 1}` }))]);
  const tbody = h('tbody');
  for (let i = 0; i < shownRows; i += 1) {
    tbody.appendChild(h('tr', {}, [h('th', { text: `r${i + 1}` }), ...Array.from({ length: shownCols }, (_, j) => h('td', { class: 'num', text: formatCell(rows[i][j]) }))]));
  }
  body.appendChild(h('div', { class: 'table-scroll' }, [h('table', { class: 'result-table' }, [h('thead', {}, [head]), tbody])]));
  wm.createWindow({ id: `matrix-view-${matrix.key}`, title: `Matrix ${matrix.key}`, kind: 'summary', width: Math.min(880, 180 + shownCols * 90), content: body });
}

function renderInto(body) {
  body.innerHTML = '';
  body.appendChild(h('p', { class: 'muted', text: 'Matrices built by Calc > Matrices. They are saved with the project and can be copied to and from worksheet columns.' }));

  if (!store.length) {
    body.appendChild(h('p', { class: 'settings-hint', text: 'No matrices yet. Use Calc > Matrices > Import to build one from worksheet columns, or Define Constant for an identity matrix.' }));
  } else {
    const tbody = h('tbody');
    for (const matrix of store) {
      const nameInput = h('input', { type: 'text', placeholder: 'optional name' });
      nameInput.value = matrix.name;
      nameInput.addEventListener('change', () => {
        matrix.name = nameInput.value.trim();
        ctx.onChange(list());
      });
      const rows = matrix.rows.length;
      const cols = rows ? matrix.rows[0].length : 0;
      tbody.appendChild(
        h('tr', {}, [
          h('th', { class: 'constant-key', text: matrix.key }),
          h('td', {}, [nameInput]),
          h('td', { class: 'num', text: `${rows} × ${cols}` }),
          h('td', {}, [
            h('button', { type: 'button', class: 'btn btn-sm', text: 'View', onClick: () => viewMatrix(matrix) }),
            h('button', {
              type: 'button',
              class: 'btn btn-sm',
              text: 'Delete',
              onClick: async () => {
                const ok = await dialogs.confirm({ title: 'Delete Matrix', message: `Delete ${label(matrix)}?`, confirmLabel: 'Delete', danger: true });
                if (!ok) return;
                remove(matrix.key);
                ctx.log(`> Deleted matrix ${matrix.key}.`);
              },
            }),
          ]),
        ]),
      );
    }
    body.appendChild(
      h('div', { class: 'table-scroll' }, [
        h('table', { class: 'result-table constants-table' }, [
          h('thead', {}, [h('tr', {}, [h('th', { text: 'Matrix' }), h('th', { text: 'Name' }), h('th', { text: 'Size' }), h('th', { text: '' })])]),
          tbody,
        ]),
      ]),
    );
  }

  if (store.length) {
    body.appendChild(
      h('div', { class: 'form-actions' }, [
        h('button', {
          type: 'button',
          class: 'btn',
          text: 'Clear all',
          onClick: async () => {
            const ok = await dialogs.confirm({ title: 'Clear Matrices', message: `Delete all ${store.length} matrices?`, confirmLabel: 'Clear', danger: true });
            if (!ok) return;
            clear();
            ctx.log('> Cleared every stored matrix.');
          },
        }),
      ]),
    );
  }
}

export function openWindow() {
  if (wm.has('matrices')) {
    wm.focus('matrices');
    return;
  }
  const body = h('div');
  renderInto(body);
  wm.createWindow({ id: 'matrices', title: 'Matrices', kind: 'summary', width: 560, content: body });
}
