// Small modal-style dialogs, built as ordinary windows so they look and behave like the rest of
// the app. Deliberately not window.confirm/prompt: those block the whole UI thread (and would
// stall any automation driving the page), and they cannot be styled to match.

import * as wm from './windowManager.js';

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined) continue;
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return node;
}

let seq = 0;

// Resolves to the value of whichever button was pressed, or null if the dialog was closed
// (Esc, the title bar's X) — so callers can treat "dismissed" as "cancelled".
export function ask({ title, message, detail, buttons, width = 400 }) {
  return new Promise((resolve) => {
    const id = `dialog-${(seq += 1)}`;
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
      if (wm.has(id)) wm.close(id);
    };

    const row = h('div', { class: 'dialog-actions' });
    const content = h('div', { class: 'dialog' }, [h('p', { class: 'dialog-message', text: message }), detail ? h('p', { class: 'dialog-detail', text: detail }) : null, row]);

    for (const b of buttons) {
      row.appendChild(
        h('button', {
          type: 'button',
          class: b.primary ? 'btn btn-primary' : b.danger ? 'btn btn-danger' : 'btn',
          text: b.label,
          onClick: () => finish(b.value),
        }),
      );
    }

    wm.createWindow({ id, title, kind: 'dialog', width, content, onClose: () => finish(null) });
    const first = row.querySelector('.btn-primary, .btn-danger') || row.querySelector('.btn');
    if (first) first.focus();
  });
}

export function confirm({ title = 'Confirm', message, detail, confirmLabel = 'OK', danger = false }) {
  return ask({
    title,
    message,
    detail,
    buttons: [
      { label: confirmLabel, value: true, primary: !danger, danger },
      { label: 'Cancel', value: false },
    ],
  }).then((v) => v === true);
}

// Single-line text prompt. Resolves to the trimmed string, or null if cancelled.
export function prompt({ title, message, label, value = '', placeholder = '', confirmLabel = 'OK', hint = '' }) {
  return new Promise((resolve) => {
    const id = `dialog-${(seq += 1)}`;
    let settled = false;
    const finish = (v) => {
      if (settled) return;
      settled = true;
      resolve(v);
      if (wm.has(id)) wm.close(id);
    };

    const input = h('input', { type: 'text', placeholder });
    input.value = value;
    const form = h('form', { class: 'dialog' }, [
      message ? h('p', { class: 'dialog-message', text: message }) : null,
      h('div', { class: 'field' }, [h('label', { text: label || 'Name' }), input, hint ? h('p', { class: 'settings-hint', text: hint }) : null]),
      h('div', { class: 'dialog-actions' }, [
        h('button', { type: 'submit', class: 'btn btn-primary', text: confirmLabel }),
        h('button', { type: 'button', class: 'btn', text: 'Cancel', onClick: () => finish(null) }),
      ]),
    ]);
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (v) finish(v);
    });

    wm.createWindow({ id, title, kind: 'dialog', width: 420, content: form, onClose: () => finish(null) });
    input.focus();
    input.select();
  });
}

// A dialog whose body is caller-supplied. `render(close)` returns the content element; the
// caller closes it by calling the passed-in function.
export function panel({ title, width = 440, render }) {
  const id = `dialog-${(seq += 1)}`;
  const close = () => {
    if (wm.has(id)) wm.close(id);
  };
  const content = render(close);
  const win = wm.createWindow({ id, title, kind: 'dialog', width, content });
  const focusable = content.querySelector('input, select, button');
  if (focusable) focusable.focus();
  return win;
}
