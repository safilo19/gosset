// Stored constants — Minitab's K1, K2, … Each holds one value (a number or a short piece of text)
// and an optional name, and the whole store lives with the project: it is written into the .baproj
// file and restored with it, the same way the worksheets and the session log are.
//
// The store is deliberately client-side. A constant is a scratch value the person is carrying
// between dialogs, not data the analysis engine needs — and keeping it here means Copy ▸ Constants
// to Constants never touches the server at all.

import * as wm from './windowManager.js';
import { h } from './resultView.js';

let ctx = { log: () => {}, onChange: () => {} };
let store = []; // [{key: 'K1', name: '', value: 3.5}]

export function init(options) {
  ctx = { ...ctx, ...options };
}

function nextKey() {
  let n = 1;
  const taken = new Set(store.map((c) => c.key));
  while (taken.has(`K${n}`)) n += 1;
  return `K${n}`;
}

export function list() {
  return store.map((c) => ({ ...c }));
}

export function count() {
  return store.length;
}

export function get(key) {
  return store.find((c) => c.key === key || (c.name && c.name === key)) || null;
}

/** Display label for a picker: 'K1 (alpha) = 0.05'. */
export function label(constant) {
  const name = constant.name ? ` (${constant.name})` : '';
  return `${constant.key}${name} = ${constant.value === null || constant.value === undefined || constant.value === '' ? '—' : constant.value}`;
}

export function set(next) {
  store = (next || []).map((c, i) => ({ key: c.key || `K${i + 1}`, name: c.name || '', value: c.value ?? '' }));
  refresh();
}

export function add(value, name) {
  const constant = { key: nextKey(), name: name || '', value: value ?? '' };
  store.push(constant);
  refresh();
  return constant;
}

/** Writes a list of values into constants, reusing `keys` where given — Copy ▸ Column to Constants. */
export function store_values(values, { keys = [], namePrefix = '' } = {}) {
  const applied = [];
  values.forEach((value, i) => {
    const key = keys[i];
    const existing = key ? store.find((c) => c.key === key) : null;
    if (existing) {
      existing.value = value;
      applied.push(existing);
    } else {
      applied.push(add(value, namePrefix ? `${namePrefix} ${i + 1}` : ''));
    }
  });
  refresh();
  return applied;
}

export function remove(key) {
  store = store.filter((c) => c.key !== key);
  refresh();
}

export function clear() {
  store = [];
  refresh();
}

function refresh() {
  ctx.onChange(list());
  const win = wm.get('constants');
  if (win) renderInto(win.body);
}

// ---------------------------------------------------------------------------
// the Constants window
// ---------------------------------------------------------------------------

function renderInto(body) {
  body.innerHTML = '';
  body.appendChild(
    h('p', { class: 'muted', text: 'Stored values you can reuse in dialogs and copy into or out of worksheet columns. Saved with the project.' }),
  );

  if (!store.length) {
    body.appendChild(h('p', { class: 'settings-hint', text: 'No constants yet. Add one below, or use Data > Copy > Column to Constants.' }));
  } else {
    const tbody = h('tbody');
    for (const constant of store) {
      const nameInput = h('input', { type: 'text', placeholder: 'optional name' });
      nameInput.value = constant.name;
      nameInput.addEventListener('change', () => {
        constant.name = nameInput.value.trim();
        ctx.onChange(list());
      });

      const valueInput = h('input', { type: 'text', class: 'mono-input' });
      valueInput.value = constant.value === null || constant.value === undefined ? '' : String(constant.value);
      valueInput.addEventListener('change', () => {
        const raw = valueInput.value.trim();
        const asNumber = Number(raw);
        constant.value = raw !== '' && Number.isFinite(asNumber) ? asNumber : raw;
        ctx.onChange(list());
      });

      tbody.appendChild(
        h('tr', {}, [
          h('th', { class: 'constant-key', text: constant.key }),
          h('td', {}, [nameInput]),
          h('td', {}, [valueInput]),
          h('td', {}, [
            h('button', {
              type: 'button',
              class: 'btn btn-sm',
              text: 'Delete',
              onClick: () => {
                remove(constant.key);
                ctx.log(`> Deleted constant ${constant.key}.`);
              },
            }),
          ]),
        ]),
      );
    }
    body.appendChild(
      h('div', { class: 'table-scroll' }, [
        h('table', { class: 'result-table constants-table' }, [
          h('thead', {}, [h('tr', {}, [h('th', { text: 'Constant' }), h('th', { text: 'Name' }), h('th', { text: 'Value' }), h('th', { text: '' })])]),
          tbody,
        ]),
      ]),
    );
  }

  body.appendChild(
    h('div', { class: 'form-actions' }, [
      h('button', {
        type: 'button',
        class: 'btn btn-primary',
        text: 'Add constant',
        onClick: () => {
          const constant = add('');
          ctx.log(`> Added constant ${constant.key}.`);
        },
      }),
      store.length
        ? h('button', {
            type: 'button',
            class: 'btn',
            text: 'Clear all',
            onClick: () => {
              clear();
              ctx.log('> Cleared every stored constant.');
            },
          })
        : null,
    ]),
  );
}

export function openWindow() {
  if (wm.has('constants')) {
    wm.focus('constants');
    return;
  }
  const body = h('div');
  renderInto(body);
  wm.createWindow({ id: 'constants', title: 'Constants', kind: 'summary', width: 520, content: body });
}
