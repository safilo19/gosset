// The worksheet tab strip along the bottom of the worksheet area — Minitab's way of showing that
// a project holds several worksheets at once.
//
// This module is a pure view: app.js owns the registry of open worksheets and which one is active,
// and calls render() whenever either changes. Clicking a tab switches the app-wide active dataset,
// so the Assistant and every Stat/Graph dialog follow it — they all resolve the active dataset at
// the moment they act rather than holding one.
//
// Interactions: click to switch, double-click (or F2) to rename in place, × to close, + to add a
// blank worksheet.

const strip = document.getElementById('worksheet-tabs');

let ctx = {
  onSwitch: () => {},
  onRename: () => {},
  onClose: () => {},
  onNew: () => {},
};

let editing = null; // dataset_id currently being renamed in place

export function init(options) {
  ctx = { ...ctx, ...options };
}

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c !== null && c !== undefined) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  return node;
}

function startRename(record) {
  editing = record.dataset_id;
  render(lastList, lastActiveId);
}

function buildNameEditor(record) {
  const input = h('input', { type: 'text', class: 'worksheet-tab-rename', 'aria-label': 'Worksheet name' });
  input.value = record.name;
  let settled = false;
  const finish = (commit) => {
    if (settled) return;
    settled = true;
    editing = null;
    const value = input.value.trim();
    if (commit && value && value !== record.name) ctx.onRename(record.dataset_id, value);
    else render(lastList, lastActiveId);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      finish(true);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      finish(false);
    }
    e.stopPropagation(); // the app's global shortcuts must not fire while typing a name
  });
  input.addEventListener('blur', () => finish(true));
  // Focus after the strip is in the DOM, or .select() lands on a detached node.
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
  return input;
}

let lastList = [];
let lastActiveId = null;

export function render(list, activeId) {
  if (!strip) return;
  const switched = activeId !== lastActiveId;
  lastList = list || [];
  lastActiveId = activeId;
  strip.innerHTML = '';

  for (const record of lastList) {
    const isActive = record.dataset_id === activeId;
    const tab = h('div', {
      class: `worksheet-tab${isActive ? ' active' : ''}`,
      role: 'tab',
      'aria-selected': String(isActive),
      title: `${record.name} — ${record.row_count} rows × ${(record.columns || []).length} columns`,
    });

    if (editing === record.dataset_id) {
      tab.appendChild(buildNameEditor(record));
    } else {
      const label = h('button', {
        type: 'button',
        class: 'worksheet-tab-label',
        text: record.name,
        onClick: () => ctx.onSwitch(record.dataset_id),
        onDblclick: () => startRename(record),
        onKeydown: (e) => {
          if (e.key === 'F2') {
            e.preventDefault();
            startRename(record);
          }
        },
      });
      const close = h('button', {
        type: 'button',
        class: 'worksheet-tab-close',
        title: `Close ${record.name}`,
        'aria-label': `Close ${record.name}`,
        text: '×',
        onClick: (e) => {
          e.stopPropagation();
          ctx.onClose(record.dataset_id);
        },
      });
      tab.append(label, close);
    }
    strip.appendChild(tab);
  }

  strip.appendChild(
    h('button', {
      type: 'button',
      class: 'worksheet-tab-add',
      title: 'New blank worksheet',
      'aria-label': 'New blank worksheet',
      text: '+',
      onClick: () => ctx.onNew(),
    }),
  );

  // Keep the active tab in view when the strip has scrolled — a Data operation that opens a new
  // worksheet must not leave its tab off the right-hand edge. Only on an actual switch: this
  // renders on every grid change too, and yanking the strip about while someone types would be
  // motion for nothing.
  const active = strip.querySelector('.worksheet-tab.active');
  if (switched && active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

/** Kicks off the in-place rename of a tab from outside (Data > Rename Worksheet). */
export function beginRename(datasetId) {
  const record = lastList.find((r) => r.dataset_id === datasetId);
  if (record) startRename(record);
}
