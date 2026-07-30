// The Report pane: a staging area for building a curated report out of individual output blocks.
//
// Why it exists: File > Export Report exports whole analyses in the order they were run, which is a
// session log, not a report. The pane lets a block be sent over, reordered, annotated and exported —
// which is what turns a pile of output into something you would hand in.
//
// The staged list is app state, not DOM state. The window is a view of it and can be closed and
// reopened without losing anything, and the list is what goes into the .baproj.

import * as wm from './windowManager.js';
import { h } from './resultView.js';
import { getIcon } from './icons/registry.js';

const WINDOW_ID = 'report';

let ctx = null;
let items = []; // [{ id, kind, name, source, data, capture, text, card }]
let nextId = 1;
let listEl = null;
let countEl = null;

export function init(context) {
  ctx = context;
}

// ---------------------------------------------------------------------------
// the staged list
// ---------------------------------------------------------------------------

export function count() {
  return items.length;
}

/** What File > Save Project writes, and what the export sends. Blocks carry their own PNG. */
export function serialize() {
  return items.map(({ id, ...rest }) => rest);
}

export function restore(saved) {
  items = [];
  nextId = 1;
  for (const entry of Array.isArray(saved) ? saved : []) {
    if (!entry || typeof entry !== 'object') continue;
    // Rebuilt field by field rather than spread, so a stray key from an older project cannot become
    // app state — which is why every NEW field has to be listed here too. `fullTable` was staged
    // deliberately; dropping it on reopen would quietly shorten a table someone asked for in full.
    items.push({
      id: nextId++,
      kind: entry.kind || 'table',
      name: entry.name || 'Block',
      source: entry.source || '',
      data: entry.data || null,
      capture: entry.capture || null,
      text: entry.text || '',
      fullTable: !!entry.fullTable,
      card: entry.card || null,
    });
  }
  render();
}

export function clear() {
  items = [];
  nextId = 1;
  render();
}

/**
 * Stage one block. `capture` is its PNG, already rendered by the caller; `card` is the report-card
 * metadata (analysis_id, columns, timestamp) captured NOW, because the result window it came from may
 * be closed long before the report is exported.
 */
export function add({ kind, name, source, data, capture, text, card }) {
  items.push({ id: nextId++, kind, name: name || 'Block', source: source || '', data: data || null, capture: capture || null, text: text || '', card: card || null });
  render();
  return items[items.length - 1];
}

export function addNote(text = '') {
  const note = add({ kind: 'note', name: 'Note', source: '', text });
  render();
  return note;
}

function remove(id) {
  items = items.filter((i) => i.id !== id);
  render();
}

function move(fromId, toIndex) {
  const from = items.findIndex((i) => i.id === fromId);
  if (from < 0) return;
  const [moved] = items.splice(from, 1);
  items.splice(Math.max(0, Math.min(items.length, toIndex)), 0, moved);
  render();
}

/**
 * The sections to export, in the curated order. A note becomes a section whose only content is its
 * text, so commentary lands in the document between the results it is about.
 */
export function sections() {
  return items.map((item) => {
    // A note has no title, so the document renderers give it prose and no numbered heading.
    if (item.kind === 'note') {
      // `note` is the field the report engine renders as a NoteBlock; `data.conclusion` is kept
      // alongside it so a project saved before that field existed still exports its commentary.
      return { title: '', note: item.text || '', data: { conclusion: item.text }, chart_image_base64: null, chart_path: null, allow_generated_chart: false };
    }
    const isChart = item.kind === 'chart';
    return {
      title: item.source ? `${item.source} — ${item.name}` : item.name,
      data: item.data || {},
      chart_path: null,
      // Only a CHART block contributes a picture. Every staged block has a `capture` — the pane needs
      // one for its own preview thumbnail — but sending a table's thumbnail here put the table in the
      // document twice: once typeset from its rows, and again as a small photograph of itself.
      chart_image_base64: isChart ? item.capture || null : null,
      // Same rule as a block sent straight to Word: one block, one thing in the document.
      allow_generated_chart: false,
      // Staged through "Send to Report (full table)": the document keeps every row rather than
      // cutting the table short. Only ever true when someone asked for it explicitly.
      full_tables: !!item.fullTable,
      analysis_id: item.card?.analysis_id || '',
      columns: item.card?.columns || '',
      timestamp: item.card?.timestamp || '',
      // Not part of the API: app.js uses these to re-render this figure for print, then strips them.
      result_id: isChart ? item.card?.result_id ?? null : null,
      chart_index: item.card?.chart_index || 0,
    };
  });
}

// ---------------------------------------------------------------------------
// the view
// ---------------------------------------------------------------------------

function rowFor(item, index) {
  const row = h('div', { class: `report-row report-row-${item.kind}`, draggable: 'true', 'data-id': String(item.id) });

  const handle = h('span', { class: 'report-handle', 'aria-hidden': 'true', title: 'Drag to reorder' });
  handle.innerHTML = getIcon('drag-handle');

  const thumb = h('span', { class: 'report-thumb' });
  if (item.capture) thumb.appendChild(h('img', { src: item.capture, alt: '' }));
  else thumb.innerHTML = getIcon(item.kind === 'note' ? 'add-text' : item.kind === 'chart' ? 'scatter' : 'display-data');

  const body = h('div', { class: 'report-row-body' });
  if (item.kind === 'note') {
    // A note is editable in place — that is the whole point of it.
    const area = h('textarea', { class: 'report-note', rows: '2', placeholder: 'Commentary to appear here in the report…' });
    area.value = item.text;
    area.addEventListener('input', () => {
      item.text = area.value;
    });
    body.append(area);
  } else {
    body.append(h('p', { class: 'report-row-name', text: item.name }));
    if (item.source) body.append(h('p', { class: 'report-row-source', text: item.source }));
  }

  const removeBtn = h('button', { type: 'button', class: 'report-remove', title: 'Remove from the report', 'aria-label': `Remove ${item.name}`, text: '×' });
  removeBtn.addEventListener('click', () => remove(item.id));

  row.append(handle, thumb, body, removeBtn);

  row.addEventListener('dragstart', (event) => {
    event.dataTransfer.setData('text/plain', String(item.id));
    event.dataTransfer.effectAllowed = 'move';
    row.classList.add('report-row-dragging');
  });
  row.addEventListener('dragend', () => row.classList.remove('report-row-dragging'));
  row.addEventListener('dragover', (event) => {
    event.preventDefault();
    // Drop above or below depending on which half of the row the pointer is over, so a drag reads
    // the way it looks rather than always landing before the target.
    const rect = row.getBoundingClientRect();
    row.classList.toggle('report-drop-after', event.clientY > rect.top + rect.height / 2);
    row.classList.toggle('report-drop-before', event.clientY <= rect.top + rect.height / 2);
  });
  row.addEventListener('dragleave', () => row.classList.remove('report-drop-before', 'report-drop-after'));
  row.addEventListener('drop', (event) => {
    event.preventDefault();
    row.classList.remove('report-drop-before', 'report-drop-after');
    const draggedId = Number(event.dataTransfer.getData('text/plain'));
    if (!draggedId || draggedId === item.id) return;
    const rect = row.getBoundingClientRect();
    const after = event.clientY > rect.top + rect.height / 2;
    const target = items.findIndex((i) => i.id === item.id);
    const draggedIndex = items.findIndex((i) => i.id === draggedId);
    // Removing the dragged row first shifts every later index down by one.
    let to = after ? target + 1 : target;
    if (draggedIndex < to) to -= 1;
    move(draggedId, to);
  });

  return row;
}

function render() {
  if (countEl) countEl.textContent = items.length ? `${items.length} block(s), in this order` : 'Nothing staged yet.';
  if (!listEl) return;
  listEl.innerHTML = '';
  if (!items.length) {
    listEl.appendChild(
      h('p', { class: 'report-empty', text: 'Use a block’s chevron menu → Send to Report to stage it here, then reorder, annotate and export.' }),
    );
    return;
  }
  items.forEach((item, i) => listEl.appendChild(rowFor(item, i)));
}

function buildContent() {
  listEl = h('div', { class: 'report-list' });
  countEl = h('p', { class: 'muted report-count' });

  const addTextBtn = h('button', { type: 'button', class: 'btn btn-sm' });
  addTextBtn.innerHTML = `${getIcon('add-text')}<span>Add text</span>`;
  addTextBtn.classList.add('btn-with-icon');
  addTextBtn.addEventListener('click', () => {
    addNote('');
    const areas = listEl.querySelectorAll('.report-note');
    if (areas.length) areas[areas.length - 1].focus();
  });

  const exportBtn = h('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Export report…' });
  exportBtn.addEventListener('click', () => ctx.openExport());

  const clearBtn = h('button', { type: 'button', class: 'btn btn-quiet btn-sm', text: 'Clear' });
  clearBtn.addEventListener('click', async () => {
    if (!items.length) return;
    const ok = await ctx.confirm(`Remove all ${items.length} staged block(s) from the report?`);
    if (ok) clear();
  });

  const content = h('div', { class: 'report-pane' }, [
    h('p', { class: 'settings-hint', text: 'A curated report: staged blocks export in the order below, with any notes in between. Saved inside the project file.' }),
    countEl,
    listEl,
    h('div', { class: 'report-actions' }, [addTextBtn, exportBtn, clearBtn]),
  ]);
  render();
  return content;
}

/** Open (or refocus) the pane. */
export function open() {
  if (wm.has(WINDOW_ID)) {
    wm.focus(WINDOW_ID);
    render();
    return;
  }
  wm.createWindow({
    id: WINDOW_ID,
    title: 'Report',
    kind: 'result',
    width: 420,
    height: 460,
    content: buildContent(),
    onClose: () => {
      // The list lives in this module, not in the DOM, so closing the window loses nothing.
      listEl = null;
      countEl = null;
    },
  });
}

/** Open it the first time something is staged, and refresh it if it is already open. */
export function reveal() {
  if (wm.has(WINDOW_ID)) render();
  else open();
}
