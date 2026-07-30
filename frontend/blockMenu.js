// The chevron action menu on every output block.
//
// One delegated set of listeners on the window layer serves every block in every result window —
// blocks come and go as windows open, close and re-render on a theme change, so per-block wiring
// would leak and would have to be redone on each render. The chevron itself is not in the DOM until
// it is needed: it is created lazily and moved to whichever block is hovered or focused, so a result
// window's markup stays as clean as it looks.
//
// The menu reuses the menu bar's dropdown markup and CSS (.menu-dropdown / .menu-item / .mi-icon) so
// it behaves and reads identically, icons included.

import { h, blockInfo } from './resultView.js';
import { getIcon } from './icons/registry.js';

const UNDO_MS = 5000;

let ctx = null; // injected by app.js: the actions a block menu can perform
let chevron = null;
let dropdown = null;
let openFor = null; // the block whose menu is open

// ---------------------------------------------------------------------------
// the menu definition
// ---------------------------------------------------------------------------

// `enabled` is asked per block, so an item that cannot apply is greyed with a reason rather than
// silently doing nothing (the same rule the menu bar's aria-disabled items follow).
const ITEMS = [
  { id: 'word', label: 'Send to Word…', icon: 'send-word', description: 'Export just this block as a .docx.' },
  { id: 'pptx', label: 'Send to PowerPoint…', icon: 'send-powerpoint', description: 'Export just this block as a one-slide .pptx.' },
  { id: 'report', label: 'Send to Report', icon: 'send-report', description: 'Stage this block in the Report pane.' },
  // Offered only for a table long enough to be truncated (see disabledReason in app.js): the
  // ordinary staging cuts a long table short so it cannot spread over three pages of a report,
  // and this is the deliberate way to ask for all of it.
  { id: 'report-full', label: 'Send to Report (full table)', icon: 'send-report', description: 'Stage this block with every row, however long the table is.' },
  { separator: true },
  { id: 'copy', label: 'Copy', icon: 'copy-block', shortcut: 'Ctrl+C' },
  { id: 'picture', label: 'Copy as Picture', icon: 'copy-picture' },
  { id: 'print', label: 'Print…', icon: 'print-block' },
  { separator: true },
  { id: 'delete', label: 'Delete', icon: 'delete-block' },
];

// ---------------------------------------------------------------------------
// the chevron
// ---------------------------------------------------------------------------

function ensureChevron() {
  if (chevron) return chevron;
  chevron = h('button', {
    type: 'button',
    class: 'block-chevron',
    'aria-haspopup': 'true',
    'aria-expanded': 'false',
    title: 'Block actions',
    'aria-label': 'Block actions',
  });
  chevron.innerHTML = getIcon('block-chevron');
  chevron.addEventListener('click', (event) => {
    event.stopPropagation();
    const host = chevron.parentElement;
    if (openFor === host) closeMenu();
    else openMenu(host);
  });
  return chevron;
}

/** Park the chevron in a block's top-right corner. Called on hover and on focus. */
function attach(target) {
  if (!target || openFor) return; // never move it out from under an open menu
  const btn = ensureChevron();
  if (btn.parentElement !== target) target.appendChild(btn);
}

function detach() {
  if (openFor || !chevron) return;
  chevron.remove();
}

// ---------------------------------------------------------------------------
// the dropdown
// ---------------------------------------------------------------------------

function closeMenu() {
  if (dropdown) dropdown.remove();
  dropdown = null;
  if (chevron) chevron.setAttribute('aria-expanded', 'false');
  const was = openFor;
  openFor = null;
  // The block under the pointer keeps its chevron; anything else loses it.
  if (was && !was.matches(':hover') && was !== document.activeElement) detach();
}

function place(panel, anchor) {
  const rect = anchor.getBoundingClientRect();
  panel.style.visibility = 'hidden';
  panel.style.left = '0px';
  panel.style.top = '0px';
  const width = panel.offsetWidth;
  const height = panel.offsetHeight;
  // Right-aligned under the chevron, flipped up or left when there is no room — the same rules
  // menu.js applies to a flyout.
  let left = rect.right - width;
  if (left < 8) left = 8;
  if (left + width > window.innerWidth - 8) left = window.innerWidth - 8 - width;
  let top = rect.bottom + 4;
  if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - 4 - height);
  panel.style.left = `${Math.round(left)}px`;
  panel.style.top = `${Math.round(top)}px`;
  panel.style.visibility = '';
}

function openMenu(target) {
  closeMenu();
  const info = blockInfo(target);
  if (!info) return;
  openFor = target;
  chevron.setAttribute('aria-expanded', 'true');

  dropdown = h('div', { class: 'menu-dropdown block-menu open', role: 'menu' });
  for (const item of ITEMS) {
    if (item.separator) {
      dropdown.appendChild(h('div', { class: 'menu-separator' }));
      continue;
    }
    const reason = ctx && ctx.disabledReason ? ctx.disabledReason(item.id, info) : null;
    const slot = h('span', { class: 'mi-icon', 'aria-hidden': 'true' });
    slot.innerHTML = getIcon(item.icon);
    const btn = h('button', { type: 'button', class: 'menu-item' }, [
      slot,
      h('span', { class: 'mi-label', text: item.label }),
      h('span', { class: 'mi-key', text: item.shortcut || '' }),
    ]);
    if (reason) {
      // aria-disabled, not the disabled attribute: a truly disabled button shows no tooltip in
      // Chrome, and the reason is the whole point of greying it out.
      btn.classList.add('menu-item-disabled');
      btn.setAttribute('aria-disabled', 'true');
      btn.title = reason;
    } else {
      btn.addEventListener('click', (event) => {
        event.stopPropagation();
        const block = openFor;
        closeMenu();
        run(item.id, block);
      });
    }
    dropdown.appendChild(btn);
  }
  document.body.appendChild(dropdown);
  place(dropdown, chevron);
  const first = dropdown.querySelector('.menu-item:not(.menu-item-disabled)');
  if (first) first.focus();
}

// ---------------------------------------------------------------------------
// running an action
// ---------------------------------------------------------------------------

function run(id, target) {
  if (!ctx || !target) return;
  const info = blockInfo(target);
  if (!info) return;
  const handler = {
    word: () => ctx.sendToWord(target, info),
    pptx: () => ctx.sendToPowerPoint(target, info),
    report: () => ctx.sendToReport(target, info),
    'report-full': () => ctx.sendToReport(target, info, { fullTable: true }),
    copy: () => ctx.copy(target, info),
    picture: () => ctx.copyAsPicture(target, info),
    print: () => ctx.print(target, info),
    delete: () => ctx.remove(target, info),
  }[id];
  if (handler) Promise.resolve(handler()).catch((err) => ctx.notify(err.message || String(err), 'error'));
}

/** Flash the block's chevron in --success — the confirmation for Send to Report. */
export function flash(target, tone = 'success') {
  const btn = chevron && chevron.parentElement === target ? chevron : null;
  const el = btn || target;
  const cls = `block-flash-${tone}`;
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), 900);
}

// ---------------------------------------------------------------------------
// the undo toast — deletion has to be recoverable
// ---------------------------------------------------------------------------

// A toast rather than the worksheet's undo stack: that stack holds DATA snapshots for a worksheet,
// and pushing a view-level "a block was hidden" entry onto it would make Ctrl+Z mean two different
// things depending on what was last touched. The toast keeps block deletion reversible without
// muddying that.
let toast = null;

export function offerUndo(message, undo) {
  if (toast) toast.remove();
  const undoBtn = h('button', { type: 'button', class: 'btn btn-quiet btn-sm', text: 'Undo' });
  toast = h('div', { class: 'block-toast', role: 'status' }, [h('span', { text: message }), undoBtn]);
  document.body.appendChild(toast);
  const close = () => {
    if (!toast) return;
    toast.remove();
    toast = null;
    clearTimeout(timer);
  };
  undoBtn.addEventListener('click', () => {
    undo();
    close();
  });
  const timer = setTimeout(close, UNDO_MS);
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

export function init(context) {
  ctx = context;
  const layer = document.getElementById('window-layer');
  if (!layer || layer.dataset.blockMenuWired === 'true') return;
  layer.dataset.blockMenuWired = 'true';

  layer.addEventListener('pointerover', (event) => {
    const target = event.target.closest ? event.target.closest('.out-block') : null;
    if (target) attach(target);
  });
  layer.addEventListener('pointerout', (event) => {
    const to = event.relatedTarget;
    const target = event.target.closest ? event.target.closest('.out-block') : null;
    if (target && (!to || !target.contains(to))) detach();
  });

  // Keyboard parity: a focused block shows its chevron, Enter opens the menu, Ctrl+C copies.
  layer.addEventListener('focusin', (event) => {
    const target = event.target.closest ? event.target.closest('.out-block') : null;
    if (target) attach(target);
  });
  layer.addEventListener('keydown', (event) => {
    const target = event.target.closest ? event.target.closest('.out-block') : null;
    if (!target) return;
    if (event.key === 'Enter' && event.target === target) {
      event.preventDefault();
      attach(target);
      openMenu(target);
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c' && event.target === target) {
      event.preventDefault();
      run('copy', target);
    }
  });

  // Anything outside the open menu closes it.
  document.addEventListener('click', (event) => {
    if (!dropdown) return;
    if (event.target.closest && (event.target.closest('.block-menu') || event.target === chevron)) return;
    closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && dropdown) {
      const target = openFor;
      closeMenu();
      if (target) target.focus();
    }
  });
  // The menu is positioned in viewport coordinates against a block that scrolls with its window.
  window.addEventListener('resize', closeMenu);
  window.addEventListener('scroll', closeMenu, true);
}
