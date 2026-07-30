// The menu help card: a small panel that explains the menu item under the pointer.
//
// Its whole design problem is to be useful without being annoying, so the behaviour rules matter
// more than the appearance:
//
//   - REST, not travel. A card appears only after the pointer has stopped on one item for
//     REST_MS. Scanning down a 78-item menu restarts the timer at every item and shows nothing,
//     which is why fast scanning produces no flicker.
//   - Once one card has shown, the menu is "primed": moving to another item swaps the card
//     immediately, with no second wait. Someone reading the menu gets instant help; someone
//     passing through gets none. The priming resets when the pointer leaves the bar or the menu
//     closes.
//   - It never takes the mouse. `pointer-events: none` in CSS means the card cannot be hovered,
//     cannot swallow a click, and cannot pull focus — it is incapable of getting in the way.
//   - It is never over a menu. The card is placed outside the panel its item lives in, and the
//     candidate positions are rejected if they would land on ANY open panel — so it can never
//     cover a flyout that is still open on its grace timer.
//   - Submenu parents get no card at all. Their flyout occupies exactly the space a card would
//     want, and the flyout is the better answer to "what is this?" anyway.
//
// Content comes from the item's own DOM, not from a registry lookup: the label from `.mi-label`,
// the icon cloned out of the `.mi-icon` slot, and the text from `data-help` / `data-needs`, which
// menu.js writes from each config entry's `description` / `needs` fields. That keeps this module
// independent of which menu an item came from, and makes the static File / Edit / Window markup in
// index.html work by adding the same two attributes.

import * as settings from './settings.js';

const REST_MS = 600; // how long the pointer must sit still on an item before help appears
const GAP = 8; // between the menu panel and the card
const EDGE = 8; // keep the card this far from the viewport edges
const MENU_ANIMATION_MS = 140; // menu.js's panel entry animation is 120ms; wait past the end of it

const menubar = document.getElementById('menubar');

let card = null;
let timer = null;
let currentItem = null;
let primed = false; // a card has been shown during this pass over the menu bar
let enabled = true;
let suppressedTitle = null; // { item, title } while a card stands in for a native tooltip

// ---------------------------------------------------------------------------
// content
// ---------------------------------------------------------------------------

function helpFor(item) {
  const description = item.dataset.help || '';
  // A greyed-out item's `title` says what it is waiting for — which is exactly what the Needs line
  // is for, so it takes that slot rather than being a second, competing tooltip.
  const blocked = item.getAttribute('aria-disabled') === 'true' && item.title;
  const needs = blocked ? item.title : item.dataset.needs || '';
  if (!description && !needs) return null;
  return {
    // The menu's trailing "…" means "opens a dialog", which is a menu convention rather than part
    // of the tool's name. As a heading on a card it just reads as an unfinished sentence.
    label: (item.querySelector('.mi-label')?.textContent || '').replace(/\s*(…|\.\.\.)$/, ''),
    iconMarkup: item.querySelector('.mi-icon')?.innerHTML || '',
    description,
    needs,
  };
}

function buildCard({ label, iconMarkup, description, needs }) {
  const el = document.createElement('div');
  el.className = 'menu-help-card';
  el.setAttribute('role', 'tooltip');
  el.setAttribute('aria-hidden', 'true'); // the item's own label and title carry this for a reader

  const head = document.createElement('div');
  head.className = 'menu-help-head';
  if (iconMarkup) {
    const icon = document.createElement('span');
    icon.className = 'menu-help-icon';
    icon.innerHTML = iconMarkup;
    head.appendChild(icon);
  }
  const title = document.createElement('span');
  title.className = 'menu-help-title';
  title.textContent = label;
  head.appendChild(title);
  el.appendChild(head);

  if (description) {
    const p = document.createElement('p');
    p.className = 'menu-help-desc';
    p.textContent = description;
    el.appendChild(p);
  }
  if (needs) {
    const p = document.createElement('p');
    p.className = 'menu-help-needs';
    const lead = document.createElement('span');
    lead.className = 'menu-help-needs-label';
    lead.textContent = 'Needs:';
    p.append(lead, ` ${needs}`);
    el.appendChild(p);
  }
  return el;
}

// ---------------------------------------------------------------------------
// placement
// ---------------------------------------------------------------------------

const overlaps = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/** Every menu panel currently on screen — the card must not land on any of them. */
function openPanels() {
  return [...menubar.querySelectorAll('.menu.open > .menu-dropdown, .menu-dropdown.submenu.open')]
    .filter((p) => p.offsetParent !== null || p.classList.contains('open'))
    .map((p) => p.getBoundingClientRect())
    .filter((r) => r.width > 0 && r.height > 0);
}

function place(el, item) {
  const panel = item.closest('.menu-dropdown');
  const panelRect = (panel || item).getBoundingClientRect();
  const itemRect = item.getBoundingClientRect();

  // measure at final width, off-screen but laid out
  el.style.left = '-9999px';
  el.style.top = '0px';
  const width = el.offsetWidth;
  const height = el.offsetHeight;

  // Top-aligned with the hovered item, then pulled back inside the viewport if the item is near
  // the bottom — the last item of a tall flyout must still show a whole card.
  const top = Math.max(EDGE, Math.min(itemRect.top, window.innerHeight - EDGE - height));

  // Right of the panel first, then left. Anything that would sit on top of an open panel — a
  // flyout still fading out on its grace timer, or the parent dropdown when we flip left — is not
  // a candidate at all.
  const candidates = [panelRect.right + GAP, panelRect.left - GAP - width];
  const panels = openPanels();
  for (const left of candidates) {
    if (left < EDGE || left + width > window.innerWidth - EDGE) continue;
    const box = { left, right: left + width, top, bottom: top + height };
    if (panels.some((p) => overlaps(box, p))) continue;
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
    return true;
  }
  return false; // nowhere to put it without covering a menu — better to show nothing
}

// ---------------------------------------------------------------------------
// show / hide
// ---------------------------------------------------------------------------

function restoreTitle() {
  if (suppressedTitle) {
    suppressedTitle.item.title = suppressedTitle.title;
    suppressedTitle = null;
  }
}

function removeCard() {
  if (card) {
    card.remove();
    card = null;
  }
  restoreTitle();
  currentItem = null;
}

function show(item) {
  const help = helpFor(item);
  if (!help) {
    removeCard();
    return;
  }
  removeCard();
  const el = buildCard(help);
  document.body.appendChild(el);
  if (!place(el, item)) {
    el.remove();
    return;
  }
  // The card says everything the native tooltip would, sooner and better formatted. Leaving the
  // title in place would pop a second, duplicate tooltip on top of it a moment later.
  if (item.title) {
    suppressedTitle = { item, title: item.title };
    item.removeAttribute('title');
  }
  card = el;
  currentItem = item;
  if (settings.motionDisabled()) el.classList.add('menu-help-card-instant');
  // one frame later so the transition has a start state to animate from
  requestAnimationFrame(() => el.classList.add('menu-help-card-in'));
  // A panel plays a 120ms entry animation, and on the primed path a card can be placed against an
  // item that is still sliding into position — the pointer crosses from a submenu parent into its
  // fresh flyout in well under that. Placing again after the animation settles corrects it; both
  // calls are idempotent, so this costs a measurement and nothing else.
  setTimeout(() => {
    if (card === el && currentItem === item) place(el, item);
  }, MENU_ANIMATION_MS);
  primed = true;
}

/** Hide immediately and forget the priming: the next card waits the full rest delay again. */
export function hide() {
  clearTimeout(timer);
  timer = null;
  removeCard();
  primed = false;
}

/** Hide but stay primed — used when travelling onto an item that has no card of its own. */
function clearCardOnly() {
  clearTimeout(timer);
  timer = null;
  removeCard();
}

function schedule(item) {
  if (!enabled) return;
  if (currentItem === item) return; // already showing for this item
  clearTimeout(timer);
  if (primed) {
    show(item); // mid-read: swap instantly, no second wait
    return;
  }
  removeCard();
  timer = setTimeout(() => show(item), REST_MS);
}

/** A leaf item, i.e. one that can have a card. Submenu parents deliberately cannot. */
function helpTarget(node) {
  const item = node && node.closest ? node.closest('.menu-item') : null;
  if (!item || !menubar.contains(item)) return null;
  return item.classList.contains('menu-item-submenu') ? null : item;
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

export function setEnabled(next) {
  enabled = !!next;
  if (!enabled) hide();
}

export function init() {
  if (!menubar || menubar.dataset.menuHelpWired === 'true') return;
  menubar.dataset.menuHelpWired = 'true';
  setEnabled(settings.get().menuHelp);
  settings.onChange((s) => setEnabled(s.menuHelp));

  menubar.addEventListener('pointerover', (event) => {
    const item = helpTarget(event.target);
    if (item) schedule(item);
    else if (event.target.closest('.menu-item')) clearCardOnly(); // a submenu parent: no card, still primed
  });

  // Leaving the bar entirely ends the reading pass — the next card waits again.
  menubar.addEventListener('pointerleave', () => hide());

  // A click either runs something or opens a flyout; either way the card's moment has passed.
  menubar.addEventListener('click', () => hide(), true);

  // Keyboard parity: arrow-key navigation focuses items, and a focused item earns the same card
  // after the same delay.
  menubar.addEventListener('focusin', (event) => {
    const item = helpTarget(event.target);
    if (item) schedule(item);
    else clearCardOnly();
  });
  menubar.addEventListener('focusout', (event) => {
    if (!menubar.contains(event.relatedTarget)) hide();
  });

  // Escape closes menus through app.js, but the card is ours to drop.
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') hide();
  });
  // A card is positioned in viewport coordinates, so anything that moves the menu invalidates it.
  window.addEventListener('resize', () => hide());
  window.addEventListener('scroll', () => hide(), true);
}
