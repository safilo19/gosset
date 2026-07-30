// The worksheet: the app's base document layer. An editable grid over a real backend dataset,
// with range selection, clipboard interop, row/column deletion and an undo/redo stack.
//
// Undo strategy: single-cell edits and column renames are undone with the same fine-grained
// PATCH endpoints that made them (cheap, and by far the most common edits). Anything that can
// change the grid's shape — a paste that grows it, a row/column delete, a Data-menu operation —
// is undone by putting back a whole-worksheet snapshot via PUT /datasets/{id}/values, which keeps
// the dataset_id stable so open result windows keep pointing at the same dataset.
//
// History is kept PER WORKSHEET. A project holds several at once, and one shared stack would
// happily apply worksheet A's snapshot to worksheet B the moment the user switched tabs.

import { apiClient } from './apiClient.js';
import * as dialogs from './dialogs.js';

const HISTORY_LIMIT = 100;

const scrollEl = document.getElementById('worksheet-scroll');
const metaEl = document.getElementById('worksheet-meta');
const errorEl = document.getElementById('worksheet-error');

let ctx = {
  log: () => {},
  onGridChanged: () => {},
  // Conditional formatting: prepare() recomputes the rules against the grid about to be drawn,
  // colorFor() then answers per cell. Both are no-ops until app.js wires the real module in.
  formatting: { prepare: () => {}, colorFor: () => null },
};
let dataset = null;
let grid = { columns: [], rows: [] }; // last fetched contents, kept for clipboard + snapshots
let cellEls = []; // cellEls[row][col] -> <td>, for repainting selection without a rebuild
let rowHeadEls = [];
let colHeadEls = [];
let sel = null; // {anchor: {r, c}, focus: {r, c}}
let dragging = false;
let dragMoved = false;

const histories = new Map(); // dataset_id -> {stack, index}

function history() {
  const id = dataset ? dataset.dataset_id : '';
  let entry = histories.get(id);
  if (!entry) {
    entry = { stack: [], index: -1 };
    histories.set(id, entry);
  }
  return entry;
}

export function init(options) {
  ctx = { ...ctx, ...options };
}

export function setDataset(next) {
  dataset = next;
  sel = null;
}

/** A closed worksheet takes its undo history with it. */
export function dropHistory(datasetId) {
  histories.delete(datasetId);
}

export function datasetId() {
  return dataset && dataset.dataset_id;
}

export function contents() {
  return { columns: grid.columns.map((c) => c.name), rows: grid.rows };
}

export function hasData() {
  return grid.rows.some((row) => grid.columns.some((c) => row[c.name] !== null && row[c.name] !== undefined && row[c.name] !== ''));
}

export function showError(message) {
  errorEl.textContent = message || '';
  errorEl.hidden = !message;
}

// ---------------------------------------------------------------------------
// selection
// ---------------------------------------------------------------------------

function lastCol() {
  return Math.max(0, grid.columns.length - 1);
}
function lastRow() {
  return Math.max(0, grid.rows.length - 1);
}
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

export function selection() {
  if (!sel) return null;
  return {
    r1: Math.min(sel.anchor.r, sel.focus.r),
    r2: Math.max(sel.anchor.r, sel.focus.r),
    c1: Math.min(sel.anchor.c, sel.focus.c),
    c2: Math.max(sel.anchor.c, sel.focus.c),
  };
}

export function selectionSize() {
  const r = selection();
  return r ? (r.r2 - r.r1 + 1) * (r.c2 - r.c1 + 1) : 0;
}

/** The 0-based row numbers the selection covers — Data > Subset Worksheet's "selected rows". */
export function selectedRowIndices() {
  const r = selection();
  if (!r) return [];
  const rows = [];
  for (let row = r.r1; row <= r.r2; row += 1) rows.push(row);
  return rows;
}

/** The name of the column the selection starts in — Clear Rules > This Column acts on it. */
export function selectedColumnName() {
  const r = selection();
  if (!r) return null;
  const column = grid.columns[r.c1];
  return column ? column.name : null;
}

function paint(previous) {
  const range = selection();
  const touched = [];
  for (const r of [previous, range]) {
    if (!r) continue;
    for (let row = r.r1; row <= r.r2; row += 1) for (let col = r.c1; col <= r.c2; col += 1) touched.push([row, col]);
  }
  for (const [row, col] of touched) {
    const td = cellEls[row] && cellEls[row][col];
    if (!td) continue;
    const inside = range && row >= range.r1 && row <= range.r2 && col >= range.c1 && col <= range.c2;
    td.classList.toggle('cell-selected', !!inside);
    td.classList.toggle('sel-top', !!inside && row === range.r1);
    td.classList.toggle('sel-bottom', !!inside && row === range.r2);
    td.classList.toggle('sel-left', !!inside && col === range.c1);
    td.classList.toggle('sel-right', !!inside && col === range.c2);
  }
  rowHeadEls.forEach((el, row) => el && el.classList.toggle('head-selected', !!range && row >= range.r1 && row <= range.r2));
  colHeadEls.forEach((el, col) => el && el.classList.toggle('head-selected', !!range && col >= range.c1 && col <= range.c2));
}

function setSelection(anchor, focus) {
  const previous = selection();
  sel = {
    anchor: { r: clamp(anchor.r, 0, lastRow()), c: clamp(anchor.c, 0, lastCol()) },
    focus: { r: clamp(focus.r, 0, lastRow()), c: clamp(focus.c, 0, lastCol()) },
  };
  paint(previous);
}

function extendTo(cell) {
  if (!sel) {
    setSelection(cell, cell);
    return;
  }
  setSelection(sel.anchor, cell);
}

export function selectAll() {
  if (!grid.columns.length) return;
  setSelection({ r: 0, c: 0 }, { r: lastRow(), c: lastCol() });
  // Keep the caret out of a single cell so Delete/Copy act on the whole range.
  if (document.activeElement && document.activeElement.classList.contains('worksheet-cell-input')) document.activeElement.blur();
}

export function focusCell(rowIndex, colIndex) {
  const el = scrollEl.querySelector(`td input[data-row="${rowIndex}"][data-col="${colIndex}"]`);
  if (el) {
    el.focus();
    el.select();
    setSelection({ r: rowIndex, c: colIndex }, { r: rowIndex, c: colIndex });
  }
}

// ---------------------------------------------------------------------------
// history
// ---------------------------------------------------------------------------

export function canUndo() {
  return history().index >= 0;
}
export function canRedo() {
  const h = history();
  return h.index < h.stack.length - 1;
}
export function resetHistory() {
  const h = history();
  h.stack = [];
  h.index = -1;
}

function push(entry) {
  const h = history();
  h.stack.length = h.index + 1; // a new edit discards the redo tail
  h.stack.push(entry);
  if (h.stack.length > HISTORY_LIMIT) h.stack.shift();
  h.index = h.stack.length - 1;
}

function snapshot() {
  return { columns: grid.columns.map((c) => c.name), rows: grid.rows.map((r) => ({ ...r })) };
}

/** The grid exactly as it stands — taken before a Data-menu operation edits it server-side. */
export function snapshotNow() {
  return snapshot();
}

/** Closes the undo step a Data-menu operation opened: re-read the grid, then record before→after
 *  as one snapshot, so Edit > Undo puts the whole operation back in a single step. */
export async function commitExternalEdit(label, before) {
  await render();
  push({ kind: 'snapshot', label, before, after: snapshot() });
}

async function applySnapshot(snap) {
  await apiClient.replaceValues(dataset.dataset_id, snap.columns, snap.rows);
}

async function applyEntry(entry, direction) {
  const target = direction === 'undo' ? entry.before : entry.after;
  if (entry.kind === 'cell') {
    await apiClient.updateCell(dataset.dataset_id, entry.row, entry.column, target);
  } else if (entry.kind === 'rename') {
    // undo renames B back to A; redo renames A back to B
    const from = direction === 'undo' ? entry.after : entry.before;
    await apiClient.renameColumn(dataset.dataset_id, from, target);
  } else {
    await applySnapshot(target);
  }
}

export async function undo() {
  if (!canUndo()) return false;
  const h = history();
  const entry = h.stack[h.index];
  try {
    await applyEntry(entry, 'undo');
    h.index -= 1;
    await render();
    ctx.log(`> Undo: ${entry.label}`);
    return true;
  } catch (err) {
    showError(`Undo failed: ${err.message}`);
    return false;
  }
}

export async function redo() {
  if (!canRedo()) return false;
  const h = history();
  const entry = h.stack[h.index + 1];
  try {
    await applyEntry(entry, 'redo');
    h.index += 1;
    await render();
    ctx.log(`> Redo: ${entry.label}`);
    return true;
  } catch (err) {
    showError(`Redo failed: ${err.message}`);
    return false;
  }
}

// Wraps any grid-shape-changing edit: snapshot, run it, snapshot again, record one undo step.
async function withSnapshot(label, fn) {
  const before = snapshot();
  await fn();
  await render();
  push({ kind: 'snapshot', label, before, after: snapshot() });
}

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------

export async function render() {
  if (!dataset) return;
  const keepScroll = { top: scrollEl.scrollTop, left: scrollEl.scrollLeft };
  const keepSel = sel;
  metaEl.textContent = 'loading…';
  try {
    const data = await apiClient.getRows(dataset.dataset_id);
    grid = { columns: data.columns, rows: data.rows };
    // Conditional formatting is recomputed from the data about to be drawn, so a "highest 5" or
    // "outside 3 sigma" rule follows every edit instead of going stale.
    ctx.formatting.prepare(dataset.dataset_id, grid);
    scrollEl.innerHTML = '';
    scrollEl.appendChild(buildTable());
    scrollEl.scrollTop = keepScroll.top;
    scrollEl.scrollLeft = keepScroll.left;
    metaEl.textContent = `${grid.rows.length} rows × ${grid.columns.length} columns · edits save on exit`;
    if (keepSel && grid.rows.length && grid.columns.length) {
      sel = null;
      setSelection(keepSel.anchor, keepSel.focus);
    } else {
      sel = null;
    }
    ctx.onGridChanged({ columns: grid.columns, rows: grid.rows });
  } catch (err) {
    scrollEl.innerHTML = '';
    metaEl.textContent = '';
    showError(err.message);
  }
}

function buildTable() {
  cellEls = [];
  rowHeadEls = [];
  colHeadEls = [];

  const systemRow = document.createElement('tr');
  systemRow.className = 'worksheet-header-row worksheet-header-system';
  const nameRow = document.createElement('tr');
  nameRow.className = 'worksheet-header-row worksheet-header-name';
  for (const row of [systemRow, nameRow]) {
    const corner = document.createElement('th');
    corner.className = 'row-index-cell corner-cell';
    row.appendChild(corner);
  }
  systemRow.firstChild.title = 'Click a column label to select the whole column';

  grid.columns.forEach((col, colIndex) => {
    const label = document.createElement('th');
    label.className = 'worksheet-col-label';
    label.textContent = `C${colIndex + 1}`;
    label.title = `Select column ${col.name}`;
    label.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      if (e.shiftKey && sel) setSelection({ r: 0, c: sel.anchor.c }, { r: lastRow(), c: colIndex });
      else setSelection({ r: 0, c: colIndex }, { r: lastRow(), c: colIndex });
      if (document.activeElement && document.activeElement.classList.contains('worksheet-cell-input')) document.activeElement.blur();
    });
    colHeadEls[colIndex] = label;
    systemRow.appendChild(label);
    nameRow.appendChild(buildNameCell(col, colIndex));
  });

  const tbody = document.createElement('tbody');
  grid.rows.forEach((row, rowIndex) => {
    const tr = document.createElement('tr');
    const head = document.createElement('td');
    head.className = 'row-index-cell';
    head.textContent = String(rowIndex + 1);
    head.title = 'Click to select the whole row';
    head.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      if (e.shiftKey && sel) setSelection({ r: sel.anchor.r, c: 0 }, { r: rowIndex, c: lastCol() });
      else setSelection({ r: rowIndex, c: 0 }, { r: rowIndex, c: lastCol() });
      if (document.activeElement && document.activeElement.classList.contains('worksheet-cell-input')) document.activeElement.blur();
    });
    rowHeadEls[rowIndex] = head;
    tr.appendChild(head);

    cellEls[rowIndex] = [];
    grid.columns.forEach((col, colIndex) => {
      const td = buildCell(rowIndex, colIndex, col, row[col.name]);
      cellEls[rowIndex][colIndex] = td;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  const table = document.createElement('table');
  table.className = 'worksheet-table';
  const thead = document.createElement('thead');
  thead.append(systemRow, nameRow);
  table.append(thead, tbody);

  // one drag listener for the whole grid rather than per-cell enter handlers
  table.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const td = e.target.closest('td[data-row]');
    if (!td) return;
    const r = Number(td.dataset.row);
    const c = Number(td.dataset.col);
    if (!dragMoved && sel && sel.focus.r === r && sel.focus.c === c) return;
    if (!dragMoved) {
      dragMoved = true;
      table.classList.add('range-dragging');
      if (document.activeElement && document.activeElement.classList.contains('worksheet-cell-input')) document.activeElement.blur();
    }
    extendTo({ r, c });
  });
  table.addEventListener('lostpointercapture', endDrag);
  return table;
}

function endDrag() {
  dragging = false;
  dragMoved = false;
  const table = scrollEl.querySelector('.worksheet-table');
  if (table) table.classList.remove('range-dragging');
}
document.addEventListener('pointerup', endDrag);
document.addEventListener('pointercancel', endDrag);

function buildNameCell(col, colIndex) {
  const th = document.createElement('th');
  const input = document.createElement('input');
  input.type = 'text';
  input.size = '1';
  input.className = 'worksheet-cell-input worksheet-header-input';
  input.setAttribute('aria-label', `Name of column ${colIndex + 1}`);
  input.value = col.name;

  const commit = async () => {
    const newName = input.value.trim();
    if (!newName || newName === col.name) {
      input.value = col.name;
      return;
    }
    const before = col.name;
    try {
      const result = await apiClient.renameColumn(dataset.dataset_id, before, newName);
      push({ kind: 'rename', label: `rename ${before} to ${result.new_name}`, column: before, before, after: result.new_name });
      ctx.log(`> Renamed column ${before} to ${result.new_name}.`);
      await render();
    } catch (err) {
      input.value = before;
      showError(err.message);
    }
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') {
      input.value = col.name;
      input.blur();
    }
  });
  input.addEventListener('blur', commit);
  th.appendChild(input);
  return th;
}

function buildCell(rowIndex, colIndex, column, value) {
  const isNumeric = column.dtype.includes('int') || column.dtype.includes('float');
  const td = document.createElement('td');
  td.dataset.row = String(rowIndex);
  td.dataset.col = String(colIndex);
  // A conditional-formatting tint, as a data attribute rather than an inline colour: the two
  // themes give --cf-* different values, so the cell re-tints itself on a theme switch with no
  // JavaScript involved. The selection wash is declared after these in the stylesheet and wins,
  // which is what keeps a selected cell readable however it is highlighted.
  const tint = ctx.formatting.colorFor(column.name, rowIndex);
  if (tint) td.dataset.cf = tint;

  const input = document.createElement('input');
  input.type = 'text';
  input.size = '1';
  input.className = isNumeric ? 'worksheet-cell-input num' : 'worksheet-cell-input';
  input.dataset.row = String(rowIndex);
  input.dataset.col = String(colIndex);
  input.setAttribute('aria-label', `${column.name}, row ${rowIndex + 1}`);
  input.value = value === null || value === undefined ? '' : String(value);
  td.appendChild(input);
  let errorNode = null;

  td.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    dragMoved = false;
    if (e.shiftKey) {
      e.preventDefault();
      extendTo({ r: rowIndex, c: colIndex });
      input.blur();
    } else {
      setSelection({ r: rowIndex, c: colIndex }, { r: rowIndex, c: colIndex });
    }
  });

  input.addEventListener('keydown', (e) => {
    const pos = input.selectionStart;
    const len = input.value.length;
    if (e.shiftKey && e.key.startsWith('Arrow')) {
      e.preventDefault();
      const f = sel ? sel.focus : { r: rowIndex, c: colIndex };
      const delta = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
      if (delta) extendTo({ r: f.r + delta[0], c: f.c + delta[1] });
      return;
    }
    if (e.key === 'Enter') {
      input.blur();
      focusCell(rowIndex + 1, colIndex);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      focusCell(rowIndex - 1, colIndex);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      focusCell(rowIndex + 1, colIndex);
    } else if (e.key === 'ArrowLeft' && pos === 0) {
      focusCell(rowIndex, colIndex - 1);
    } else if (e.key === 'ArrowRight' && pos === len) {
      focusCell(rowIndex, colIndex + 1);
    }
  });

  input.addEventListener('paste', (e) => {
    const text = (e.clipboardData || window.clipboardData).getData('text');
    if (!text) return;
    e.preventDefault();
    pasteText(text, rowIndex, colIndex);
  });

  input.addEventListener('blur', async () => {
    const raw = input.value;
    const previous = value === null || value === undefined ? '' : String(value);
    if (raw === previous) return; // unchanged
    try {
      const result = await apiClient.updateCell(dataset.dataset_id, rowIndex, column.name, raw);
      value = result.value;
      input.value = value === null || value === undefined ? '' : String(value);
      const cached = grid.rows[rowIndex];
      if (cached) cached[column.name] = value;
      push({ kind: 'cell', label: `edit ${column.name} row ${rowIndex + 1}`, row: rowIndex, column: column.name, before: previous, after: raw });
      input.classList.remove('cell-error');
      if (errorNode) {
        errorNode.remove();
        errorNode = null;
      }
      input.classList.remove('cell-flash-success', 'cell-flash-danger');
      void input.offsetWidth; // restart the flash animation even if it just played
      input.classList.add('cell-flash-success');
    } catch (err) {
      input.classList.add('cell-error');
      input.classList.remove('cell-flash-success', 'cell-flash-danger');
      void input.offsetWidth;
      input.classList.add('cell-flash-danger');
      if (!errorNode) {
        errorNode = document.createElement('p');
        errorNode.className = 'worksheet-cell-error';
        td.appendChild(errorNode);
      }
      errorNode.textContent = err.message;
    }
  });

  return td;
}

// ---------------------------------------------------------------------------
// clipboard
// ---------------------------------------------------------------------------

function cellText(rowIndex, colIndex) {
  const col = grid.columns[colIndex];
  if (!col) return '';
  const v = grid.rows[rowIndex] ? grid.rows[rowIndex][col.name] : null;
  return v === null || v === undefined ? '' : String(v);
}

export function selectionText() {
  const range = selection();
  if (!range) return '';
  const lines = [];
  for (let r = range.r1; r <= range.r2; r += 1) {
    const cells = [];
    for (let c = range.c1; c <= range.c2; c += 1) cells.push(cellText(r, c));
    lines.push(cells.join('\t'));
  }
  return lines.join('\n');
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API blocked (insecure context or denied permission) — fall back to the old
    // hidden-textarea trick, which works from a user gesture.
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand && document.execCommand('copy');
    ta.remove();
    return !!ok;
  }
}

export async function copySelection() {
  const text = selectionText();
  if (!text) return false;
  const ok = await writeClipboard(text);
  if (!ok) showError('Could not write to the clipboard. Press Ctrl+C instead — the browser only allows that from a real key press.');
  return ok;
}

export async function cutSelection() {
  const ok = await copySelection();
  if (ok) await clearSelection();
  return ok;
}

function parseTSV(text) {
  const lines = text.replace(/\r/g, '').split('\n');
  while (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines.map((line) => line.split('\t'));
}

async function pasteText(text, rowIndex, colIndex) {
  const values = parseTSV(text);
  if (!values.length) return;
  try {
    await withSnapshot(`paste ${values.length}x${values[0].length} block`, () => apiClient.pasteCells(dataset.dataset_id, rowIndex, colIndex, values));
    ctx.log(`> Pasted ${values.length} row(s) x ${values[0].length} column(s) at row ${rowIndex + 1}, column ${colIndex + 1}.`);
    setSelection({ r: rowIndex, c: colIndex }, { r: rowIndex + values.length - 1, c: colIndex + values[0].length - 1 });
  } catch (err) {
    showError(err.message);
  }
}

export async function pasteFromClipboard() {
  const range = selection();
  if (!range) {
    showError('Select the cell to paste into first.');
    return;
  }
  let text = '';
  try {
    text = await navigator.clipboard.readText();
  } catch {
    showError('The browser did not allow reading the clipboard. Click a cell and press Ctrl+V instead.');
    return;
  }
  if (!text) return;
  await pasteText(text, range.r1, range.c1);
}

// ---------------------------------------------------------------------------
// storing computed columns (Stat > Basic Statistics > Store Descriptive Statistics)
// ---------------------------------------------------------------------------

function columnIsEmpty(name) {
  return grid.rows.every((row) => row[name] === null || row[name] === undefined || row[name] === '');
}

// Where a block of computed columns should land: the first run of untouched default columns, the
// way Minitab fills the first free columns of the worksheet. Falls back to past the right edge,
// which the paste endpoint grows the grid to accommodate.
function firstFreeColumn(count) {
  for (let start = 0; start + count <= grid.columns.length; start += 1) {
    let free = true;
    for (let i = start; i < start + count; i += 1) {
      const column = grid.columns[i];
      if (!/^C\d+$/.test(column.name) || !columnIsEmpty(column.name)) {
        free = false;
        break;
      }
    }
    if (free) return start;
  }
  return grid.columns.length;
}

// Writes [{name, values}] into the grid as named columns, in one undoable step. Uses the ordinary
// paste + rename endpoints, so the new columns are real worksheet columns like any others and
// Edit > Undo puts the sheet back. Returns the names actually applied.
export async function storeColumns(specs) {
  if (!dataset || !specs || !specs.length) return [];
  const before = snapshot();
  const start = firstFreeColumn(specs.length);
  const rowCount = Math.max(...specs.map((s) => (s.values || []).length), 1);

  const block = [];
  for (let r = 0; r < rowCount; r += 1) {
    block.push(specs.map((s) => {
      const value = (s.values || [])[r];
      return value === null || value === undefined ? '' : value;
    }));
  }
  await apiClient.pasteCells(dataset.dataset_id, 0, start, block);

  // The paste may have created columns named C{n}; give each the statistic's name. A name already
  // in use (storing "field" next to an existing "field") gets a numeric suffix rather than failing.
  const written = await apiClient.getRows(dataset.dataset_id);
  const taken = new Set(written.columns.map((c) => c.name));
  const applied = [];
  for (let i = 0; i < specs.length; i += 1) {
    const current = written.columns[start + i] && written.columns[start + i].name;
    if (!current) continue;
    taken.delete(current);
    let target = specs[i].name;
    let suffix = 2;
    while (taken.has(target)) target = `${specs[i].name}_${suffix++}`;
    taken.add(target);
    if (target === current) {
      applied.push(current);
      continue;
    }
    const result = await apiClient.renameColumn(dataset.dataset_id, current, target);
    applied.push(result.new_name);
  }

  await render();
  push({ kind: 'snapshot', label: `store ${specs.length} statistic column(s)`, before, after: snapshot() });
  return applied;
}

// ---------------------------------------------------------------------------
// clear / delete
// ---------------------------------------------------------------------------

export async function clearSelection() {
  const range = selection();
  if (!range) return;
  const blanks = [];
  for (let r = range.r1; r <= range.r2; r += 1) {
    const row = [];
    for (let c = range.c1; c <= range.c2; c += 1) row.push('');
    blanks.push(row);
  }
  const count = blanks.length * blanks[0].length;
  try {
    await withSnapshot(`clear ${count} cell(s)`, () => apiClient.pasteCells(dataset.dataset_id, range.r1, range.c1, blanks));
    ctx.log(`> Cleared ${count} cell(s).`);
    setSelection({ r: range.r1, c: range.c1 }, { r: range.r2, c: range.c2 });
  } catch (err) {
    showError(err.message);
  }
}

function rangeHasData(range, axis) {
  if (axis === 'columns') {
    return grid.columns.slice(range.c1, range.c2 + 1).some((col) => grid.rows.some((row) => row[col.name] !== null && row[col.name] !== undefined && row[col.name] !== ''));
  }
  return grid.rows.slice(range.r1, range.r2 + 1).some((row) => grid.columns.some((col) => row[col.name] !== null && row[col.name] !== undefined && row[col.name] !== ''));
}

export async function deleteSelection() {
  const range = selection();
  if (!range) {
    showError('Select the rows or columns to delete first.');
    return;
  }
  const rowCount = range.r2 - range.r1 + 1;
  const colCount = range.c2 - range.c1 + 1;
  const spansAllColumns = range.c1 === 0 && range.c2 === lastCol();
  const spansAllRows = range.r1 === 0 && range.r2 === lastRow();

  let axis = null;
  if (spansAllColumns && !spansAllRows) axis = 'rows';
  else if (spansAllRows && !spansAllColumns) axis = 'columns';
  else {
    // A partial block (or the whole sheet) doesn't say which the user meant — ask.
    axis = await dialogs.ask({
      title: 'Delete',
      message: 'Delete whole rows or whole columns?',
      detail: 'The selected block spans both, so pick which one to remove entirely.',
      buttons: [
        { label: `${rowCount} row(s)`, value: 'rows', primary: true },
        { label: `${colCount} column(s)`, value: 'columns' },
        { label: 'Cancel', value: null },
      ],
    });
    if (!axis) return;
  }

  if (rangeHasData(range, axis)) {
    const what = axis === 'rows' ? `${rowCount} row(s)` : `${colCount} column(s) (${grid.columns.slice(range.c1, range.c2 + 1).map((c) => c.name).join(', ')})`;
    const ok = await dialogs.confirm({
      title: 'Delete',
      message: `Delete ${what}?`,
      detail: 'They contain data. This can be undone with Edit > Undo.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
  }

  try {
    if (axis === 'rows') {
      const indices = [];
      for (let r = range.r1; r <= range.r2; r += 1) indices.push(r);
      await withSnapshot(`delete ${rowCount} row(s)`, () => apiClient.deleteRows(dataset.dataset_id, indices));
      ctx.log(`> Deleted ${rowCount} row(s) starting at row ${range.r1 + 1}.`);
    } else {
      const names = grid.columns.slice(range.c1, range.c2 + 1).map((c) => c.name);
      await withSnapshot(`delete ${colCount} column(s)`, () => apiClient.deleteColumns(dataset.dataset_id, names));
      ctx.log(`> Deleted column(s): ${names.join(', ')}.`);
    }
    sel = null;
  } catch (err) {
    showError(err.message);
  }
}
