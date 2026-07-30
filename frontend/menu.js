// The menu-bar's dropdown/flyout mechanism, in one place. Menus are described by a nested config
// (see buildDropdown) and rendered into the existing .menu-dropdown markup, so Graph, Stat and any
// future menu share the same behaviour instead of each growing its own copy.
//
// What this owns:
//   - rendering a nested config into items, separators and cascading flyouts
//   - the 16px icon slot every item carries: a leaf names its icon with `icon: 'name'` and gets
//     that inline SVG from icons/registry.js; a submenu parent and any leaf without one get the
//     slot empty, so labels always align in a single column (see the registry's rule 8)
//   - passing each leaf's `description` / `needs` through to the DOM as data-help / data-needs,
//     which is where menuHelp.js reads the hover help card's content from
//   - hover intent: ~150ms to open, ~300ms grace to close, so diagonal travel from a parent item
//     into its flyout never closes it
//   - positioning every panel against the viewport: flyouts open right of their parent, flip left
//     near the right edge, shift up rather than run off the bottom, and scroll internally if they
//     are taller than the screen — a panel must never be clipped offscreen
//   - keyboard navigation across levels (Up/Down, Right to open, Left to go back, Enter, Esc)

import { getIcon } from './icons/registry.js';

const HOVER_OPEN_MS = 150;
const GRACE_CLOSE_MS = 300;
const EDGE = 8; // keep panels this far from the viewport edges

const menubar = document.getElementById('menubar');

let openHost = null; // the .submenu-host whose flyout is showing
let openTimer = null;
let closeTimer = null;

// ---------------------------------------------------------------------------
// building
// ---------------------------------------------------------------------------

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  return node;
}

/**
 * The icon slot. Always rendered, always 16px, whether or not there is an icon to put in it — an
 * item with no icon must still hold the column open or its label steps out of line with the rest.
 * The SVG inside strokes with currentColor, so it follows the item's normal / hover / disabled
 * colour with no CSS of its own.
 */
function iconSlot(name) {
  const slot = h('span', { class: 'mi-icon', 'aria-hidden': 'true' });
  const markup = getIcon(name);
  if (markup) {
    slot.innerHTML = markup;
    // The registry name, kept on the slot so the Icon Gallery can join a rendered menu item back to
    // its icon. Comparing serialised SVG would not work — the browser rewrites the markup it parses.
    slot.dataset.icon = name;
  }
  return slot;
}

function leafItem(entry) {
  const attrs = { type: 'button', class: 'menu-item' };
  if (entry.action) attrs['data-action'] = entry.action;
  if (entry.analysis) attrs['data-analysis'] = entry.analysis;
  if (entry.stat) attrs['data-stat'] = entry.stat;
  if (entry.graph) attrs['data-graph'] = entry.graph;
  if (entry.data) attrs['data-data'] = entry.data; // a Data menu procedure id
  if (entry.calc) attrs['data-calc'] = entry.calc; // a Calc menu procedure id
  if (entry.title) attrs.title = entry.title;
  // The hover help card (menuHelp.js) reads these off the DOM rather than looking the item up in a
  // registry, so one config entry — icon, description, needs — fully describes a menu item.
  if (entry.description) attrs['data-help'] = entry.description;
  if (entry.needs) attrs['data-needs'] = entry.needs;
  const item = h('button', attrs, [iconSlot(entry.icon), h('span', { class: 'mi-label', text: entry.label }), h('span', { class: 'mi-key', text: entry.shortcut || '' })]);
  if (entry.disabled) {
    // aria-disabled, NOT the disabled attribute: a disabled button receives no pointer events at
    // all in Chrome, so its title never appears — and for an item that is greyed out precisely
    // because it needs explaining ("not supported yet — here's why"), the tooltip is the whole
    // point. The click dispatch and the keyboard navigation both skip it instead.
    item.classList.add('menu-item-disabled');
    item.setAttribute('aria-disabled', 'true');
  }
  return item;
}

function submenuHost(entry, depth) {
  const host = h('div', { class: 'submenu-host' });
  // A category gets the slot but never an icon (registry rule 8) — its label still lines up with
  // its siblings', and the ▸ is what says it opens something.
  const parent = h('button', { type: 'button', class: 'menu-item menu-item-submenu', 'aria-haspopup': 'true', 'aria-expanded': 'false' }, [
    iconSlot(null),
    h('span', { class: 'mi-label', text: entry.label }),
    h('span', { class: 'mi-arrow', 'aria-hidden': 'true', text: '▸' }), // ▸
  ]);
  const flyout = h('div', { class: 'menu-dropdown submenu', role: 'menu' });
  fill(flyout, entry.items, depth + 1);
  host.append(parent, flyout);
  return host;
}

function fill(container, entries, depth = 0) {
  for (const entry of entries || []) {
    if (!entry) continue;
    if (entry.separator) container.appendChild(h('div', { class: 'menu-separator' }));
    else if (entry.groupLabel) container.appendChild(h('div', { class: 'menu-section-label', text: entry.groupLabel }));
    else if (entry.items) container.appendChild(submenuHost(entry, depth));
    else container.appendChild(leafItem(entry));
  }
}

/**
 * Give an icon slot to items that were NOT built from a config: the File / Edit / Window menus,
 * which are static markup in index.html, and File > Recent, which app.js builds by hand. They name
 * their icon in a `data-icon` attribute instead of an `icon:` field — same registry, same slot, so
 * every item in the menu bar aligns on the same column whichever way it was created.
 *
 * Idempotent: an item that already has a slot is left alone, so this is safe to call again after
 * app.js rebuilds the Recent list.
 */
export function hydrateIcons(root) {
  for (const item of (root || menubar).querySelectorAll('.menu-item')) {
    if (item.querySelector(':scope > .mi-icon')) continue;
    item.prepend(iconSlot(item.dataset.icon));
  }
}

/** Render a nested config into the named menu's dropdown, replacing whatever was there. */
export function buildDropdown(menuName, entries) {
  const dropdown = document.querySelector(`.menu[data-menu="${menuName}"] > .menu-dropdown`);
  if (!dropdown) return null;
  dropdown.innerHTML = '';
  dropdown.setAttribute('role', 'menu');
  fill(dropdown, entries, 0);
  return dropdown;
}

// ---------------------------------------------------------------------------
// positioning
// ---------------------------------------------------------------------------

const flyoutOf = (host) => host.querySelector(':scope > .menu-dropdown.submenu');
const parentItemOf = (host) => host.querySelector(':scope > .menu-item-submenu');

function fitVertically(panel, preferredTop, height) {
  const vh = window.innerHeight;
  let top = preferredTop;
  if (top + height > vh - EDGE) top = vh - EDGE - height;
  return Math.max(EDGE, top);
}

function capHeight(panel) {
  const vh = window.innerHeight;
  panel.style.maxHeight = '';
  panel.style.overflowY = '';
  if (panel.offsetHeight > vh - 2 * EDGE) {
    panel.style.maxHeight = `${vh - 2 * EDGE}px`;
    panel.style.overflowY = 'auto';
  }
  return panel.offsetHeight;
}

function placeFlyout(host) {
  const item = parentItemOf(host);
  const panel = flyoutOf(host);
  if (!item || !panel) return;

  // measure while hidden from view but laid out
  panel.style.visibility = 'hidden';
  panel.classList.add('open');
  panel.style.left = '0px';
  panel.style.top = '0px';
  const height = capHeight(panel);
  const width = panel.offsetWidth;

  const rect = item.getBoundingClientRect();
  const vw = window.innerWidth;

  // right of the parent, overlapping 2px so the pointer never crosses a gap; flip left if the
  // flyout would not fit on the right
  let left = rect.right - 2;
  if (left + width > vw - EDGE) left = rect.left - width + 2;
  left = Math.max(EDGE, Math.min(left, vw - EDGE - width));

  panel.style.left = `${Math.round(left)}px`;
  panel.style.top = `${Math.round(fitVertically(panel, rect.top - 5, height))}px`;
  panel.style.visibility = '';
}

/** A top-level dropdown gets the same treatment: capped height and never past the bottom edge. */
export function placeDropdown(menuEl) {
  const panel = menuEl.querySelector(':scope > .menu-dropdown');
  if (!panel) return;
  panel.style.top = '';
  panel.style.bottom = '';
  const height = capHeight(panel);
  const rect = panel.getBoundingClientRect();
  const overflow = rect.top + height - (window.innerHeight - EDGE);
  // menu bar is at the very top, so pulling the panel up is enough; the cap above handles the
  // case where even the full viewport height is not enough
  panel.style.marginTop = overflow > 0 ? `${-Math.min(overflow, Math.max(0, rect.top - EDGE))}px` : '';
}

// ---------------------------------------------------------------------------
// open / close
// ---------------------------------------------------------------------------

function clearTimers() {
  clearTimeout(openTimer);
  clearTimeout(closeTimer);
  openTimer = null;
  closeTimer = null;
}

export function closeFlyouts(within) {
  clearTimers();
  const scope = within || menubar;
  for (const panel of scope.querySelectorAll('.menu-dropdown.submenu.open')) {
    panel.classList.remove('open');
    panel.style.maxHeight = '';
    panel.style.overflowY = '';
  }
  for (const item of scope.querySelectorAll('.menu-item-submenu[aria-expanded="true"]')) item.setAttribute('aria-expanded', 'false');
  if (!within || within.contains(openHost)) openHost = null;
}

export function openFlyout(host) {
  if (!host || openHost === host) return;
  // only one flyout per level: close any sibling before opening this one
  const level = host.parentElement;
  closeFlyouts(level);
  placeFlyout(host);
  parentItemOf(host).setAttribute('aria-expanded', 'true');
  openHost = host;
}

function scheduleOpen(host) {
  clearTimers();
  if (openHost === host) return;
  openTimer = setTimeout(() => openFlyout(host), HOVER_OPEN_MS);
}

function scheduleClose() {
  clearTimeout(openTimer);
  clearTimeout(closeTimer);
  closeTimer = setTimeout(() => closeFlyouts(), GRACE_CLOSE_MS);
}

// ---------------------------------------------------------------------------
// interaction
// ---------------------------------------------------------------------------

function visibleItems(level) {
  return [...level.querySelectorAll(':scope > .menu-item, :scope > .submenu-host > .menu-item-submenu')].filter(
    (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true' && el.offsetParent !== null,
  );
}

function levelOf(item) {
  const host = item.closest('.submenu-host');
  return host && host.querySelector(':scope > .menu-item-submenu') === item ? host.parentElement : item.parentElement;
}

function focusItem(item) {
  if (item) item.focus();
}

export function initMenus() {
  if (!menubar || menubar.dataset.menusWired === 'true') return;
  menubar.dataset.menusWired = 'true';

  // Hover intent. Delegated, so generated menus need no extra wiring.
  menubar.addEventListener('pointerover', (event) => {
    const inFlyout = event.target.closest('.menu-dropdown.submenu');
    const host = event.target.closest('.submenu-host');
    if (host && event.target.closest('.menu-item-submenu') === parentItemOf(host)) {
      scheduleOpen(host);
      return;
    }
    if (inFlyout) {
      // travelling inside an open flyout (or into a nested one) keeps everything open
      clearTimeout(closeTimer);
      closeTimer = null;
      return;
    }
    if (host) {
      clearTimeout(closeTimer);
      closeTimer = null;
      return;
    }
    // a plain item in the same level: the open flyout is no longer wanted
    if (event.target.closest('.menu-item') && openHost) scheduleClose();
  });

  menubar.addEventListener('pointerout', (event) => {
    const to = event.relatedTarget;
    if (!to || !menubar.contains(to)) scheduleClose();
  });

  // Click a parent item to open its flyout (and keep the menu open).
  menubar.addEventListener(
    'click',
    (event) => {
      const parent = event.target.closest('.menu-item-submenu');
      if (!parent) return;
      event.preventDefault();
      event.stopPropagation(); // never reaches the menubar's leaf dispatch or the document closer
      const host = parent.parentElement;
      if (openHost === host) closeFlyouts(host.parentElement);
      else openFlyout(host);
    },
    true,
  );

  // Keyboard navigation across levels.
  menubar.addEventListener('keydown', (event) => {
    const item = event.target.closest('.menu-item');
    if (!item) return;
    const level = levelOf(item);
    const items = visibleItems(level);
    const index = items.indexOf(item);
    const isParent = item.classList.contains('menu-item-submenu');

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!items.length) return;
      const next = event.key === 'ArrowDown' ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
      focusItem(items[next]);
      return;
    }
    if (event.key === 'ArrowRight' && isParent) {
      event.preventDefault();
      const host = item.parentElement;
      openFlyout(host);
      focusItem(visibleItems(flyoutOf(host))[0]);
      return;
    }
    if (event.key === 'ArrowLeft') {
      const host = item.closest('.submenu-host');
      const owner = host && !isParent ? host : host && isParent ? host.parentElement.closest('.submenu-host') : null;
      if (owner) {
        event.preventDefault();
        closeFlyouts(owner.parentElement);
        focusItem(parentItemOf(owner));
      }
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      if (isParent) {
        event.preventDefault();
        const host = item.parentElement;
        openFlyout(host);
        focusItem(visibleItems(flyoutOf(host))[0]);
      }
    }
  });

  // A menu-bar trigger opens its dropdown and drops focus into it.
  menubar.addEventListener('keydown', (event) => {
    const trigger = event.target.closest('.menu-trigger');
    if (!trigger || event.key !== 'ArrowDown') return;
    event.preventDefault();
    const menu = trigger.parentElement;
    if (!menu.classList.contains('open')) trigger.click();
    const panel = menu.querySelector(':scope > .menu-dropdown');
    focusItem(visibleItems(panel)[0]);
  });

  window.addEventListener('resize', () => closeFlyouts());
}
