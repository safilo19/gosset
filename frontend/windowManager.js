// Desktop-style MDI window manager: every tool form and every analysis result opens as a
// floating window above the worksheet, instead of being appended to a page-long scroll.
//
// Positioning is done with `transform: translate(x, y)` (not top/left) so dragging never
// triggers layout, and open/close/minimize use the Web Animations API — the animated transform
// has to include the window's current translate, which is awkward to express in a CSS keyframe.

import { motionDisabled } from './settings.js';

const layer = document.getElementById('window-layer');
const tabsHost = document.getElementById('taskbar-tabs');
const taskbarEmpty = document.getElementById('taskbar-empty');

// Sensible defaults per window type: forms compact, results larger, charts larger still.
// `h: null` means "measure the content and fit to it, up to maxH" — a three-row describe table
// and a twenty-row forecast should not both open at the same arbitrary height.
const DEFAULT_SIZE = {
  form: { w: 420, h: null, maxH: 620 },
  result: { w: 640, h: null, maxH: 560 },
  chart: { w: 780, h: null, maxH: 620 },
  chat: { w: 420, h: 560 },
  import: { w: 520, h: 480 },
  summary: { w: 640, h: 520 },
  // tall enough that a dialog's primary button is never pushed below the fold
  dialog: { w: 400, h: null, maxH: 640 },
  builder: { w: 560, h: 620 },
};

const MIN_W = 280;
const MIN_H = 140;
const CASCADE_STEP = 28;
const CASCADE_WRAP = 8;

const windows = new Map(); // id -> record
let zOrder = []; // ids, back to front
let focusedId = null;
let cascadeIndex = 0;
let seq = 1;

function layerSize() {
  const r = layer.getBoundingClientRect();
  return { w: r.width, h: r.height };
}

function clamp(v, lo, hi) {
  return Math.min(Math.max(v, lo), hi);
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 12 12');
  svg.setAttribute('width', '12');
  svg.setAttribute('height', '12');
  svg.setAttribute('aria-hidden', 'true');
  const paths = {
    minimize: 'M2 9h8',
    maximize: 'M2.5 2.5h7v7h-7z',
    restore: 'M2.5 4.5h5v5h-5z M4.5 4.5v-2h5v5h-2',
    close: 'M2.5 2.5l7 7M9.5 2.5l-7 7',
  };
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', paths[name]);
  p.setAttribute('fill', 'none');
  p.setAttribute('stroke', 'currentColor');
  p.setAttribute('stroke-width', '1.2');
  p.setAttribute('stroke-linecap', 'square');
  svg.appendChild(p);
  return svg;
}

function applyBounds(rec) {
  const { x, y, w, h } = rec.bounds;
  rec.el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  rec.el.style.width = `${Math.round(w)}px`;
  rec.el.style.height = `${Math.round(h)}px`;
}

function applyZOrder() {
  zOrder.forEach((id, i) => {
    const rec = windows.get(id);
    if (rec) rec.el.style.zIndex = String(100 + i);
  });
}

function applyFocusClasses() {
  for (const rec of windows.values()) {
    const isFocused = rec.id === focusedId;
    rec.el.classList.toggle('focused', isFocused);
    rec.tab.classList.toggle('active', isFocused);
  }
}

// Re-measure a fit-to-content window. Needed because an <img> (a server-rendered chart PNG)
// has no height until it decodes, so the first measurement would open the window cropped.
// Skipped once the user has taken over the size by resizing or maximizing it.
function refit(rec) {
  if (!rec.autoHeight || rec.userSized || rec.maximized || rec.minimized) return;
  const size = layerSize();
  rec.el.style.height = 'auto';
  const measured = rec.el.offsetHeight;
  const ceiling = Math.max(MIN_H, Math.min(rec.maxH || size.h, size.h - 8));
  rec.bounds.h = clamp(measured, MIN_H, ceiling);
  rec.bounds.y = clamp(rec.bounds.y, 0, Math.max(0, size.h - rec.bounds.h));
  applyBounds(rec);
}

function nextCascadePosition(w, h, skipId) {
  const size = layerSize();
  const maxX = Math.max(0, size.w - w);
  const maxY = Math.max(0, size.h - h);
  const step = cascadeIndex % CASCADE_WRAP;
  cascadeIndex += 1;
  let x = clamp(36 + step * CASCADE_STEP, 0, maxX);
  let y = clamp(20 + step * CASCADE_STEP, 0, maxY);
  // The cascade wraps every CASCADE_WRAP windows, and clamping near the edges can converge on
  // the same spot too, so nudge off any position already taken: a new window must never land
  // exactly on top of an existing one.
  const taken = (px, py) =>
    [...windows.values()].some((r) => r.id !== skipId && !r.minimized && Math.round(r.bounds.x) === Math.round(px) && Math.round(r.bounds.y) === Math.round(py));
  for (let guard = 0; guard < 16 && taken(x, y); guard += 1) {
    x = clamp(x + 14, 0, maxX);
    y = clamp(y + 14, 0, maxY);
    if (x === maxX && y === maxY) break;
  }
  return { x, y };
}

// ---------------------------------------------------------------------------
// drag & resize
// ---------------------------------------------------------------------------

// Pointer capture keeps drag/resize tracking even when the pointer leaves the handle. A
// synthetic pointerdown (no live pointer) makes these throw, and an uncaught error there would
// break the whole gesture — the handle's own pointermove events still work without capture.
function capture(handle, pointerId) {
  try {
    handle.setPointerCapture(pointerId);
  } catch {
    /* no live pointer for this id */
  }
}

function release(handle, pointerId) {
  try {
    if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId);
  } catch {
    /* already released */
  }
}

function wireDrag(rec, handle) {
  let startX = 0;
  let startY = 0;
  let origin = null;

  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.target.closest('.win-btn')) return;
    if (rec.maximized) return; // a maximized window has nowhere to move to
    focus(rec.id);
    startX = e.clientX;
    startY = e.clientY;
    origin = { ...rec.bounds };
    capture(handle, e.pointerId);
    rec.el.classList.add('win-interacting');
    e.preventDefault();
  });

  handle.addEventListener('pointermove', (e) => {
    if (!origin) return;
    const size = layerSize();
    rec.bounds.x = clamp(origin.x + (e.clientX - startX), 0, Math.max(0, size.w - rec.bounds.w));
    rec.bounds.y = clamp(origin.y + (e.clientY - startY), 0, Math.max(0, size.h - rec.bounds.h));
    applyBounds(rec);
  });

  const end = (e) => {
    if (!origin) return;
    origin = null;
    rec.el.classList.remove('win-interacting');
    release(handle, e.pointerId);
  };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
}

function wireResize(rec, handle, dirs) {
  let startX = 0;
  let startY = 0;
  let origin = null;

  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || rec.maximized) return;
    focus(rec.id);
    rec.userSized = true;
    startX = e.clientX;
    startY = e.clientY;
    origin = { ...rec.bounds };
    capture(handle, e.pointerId);
    rec.el.classList.add('win-interacting');
    e.preventDefault();
    e.stopPropagation();
  });

  handle.addEventListener('pointermove', (e) => {
    if (!origin) return;
    const size = layerSize();
    if (dirs.includes('e')) {
      rec.bounds.w = clamp(origin.w + (e.clientX - startX), MIN_W, size.w - origin.x);
    }
    if (dirs.includes('s')) {
      rec.bounds.h = clamp(origin.h + (e.clientY - startY), MIN_H, size.h - origin.y);
    }
    applyBounds(rec);
  });

  const end = (e) => {
    if (!origin) return;
    origin = null;
    rec.el.classList.remove('win-interacting');
    release(handle, e.pointerId);
  };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
}

// ---------------------------------------------------------------------------
// taskbar
// ---------------------------------------------------------------------------

function buildTab(rec) {
  const tab = document.createElement('button');
  tab.type = 'button';
  tab.className = `taskbar-tab kind-${rec.kind}`;
  const dot = document.createElement('span');
  dot.className = 'tab-dot';
  const label = document.createElement('span');
  label.className = 'tab-label';
  label.textContent = rec.title;
  tab.append(dot, label);
  tab.title = rec.title;
  tab.addEventListener('click', () => focus(rec.id));
  tabsHost.appendChild(tab);
  return tab;
}

function refreshTaskbarEmpty() {
  taskbarEmpty.hidden = windows.size > 0;
}

// tab position in window-layer coordinates — the minimize animation flies the window toward
// its own tab, which lives in the taskbar strip below the layer.
function tabTargetInLayer(rec) {
  const t = rec.tab.getBoundingClientRect();
  const l = layer.getBoundingClientRect();
  return { x: t.left - l.left + t.width / 2, y: t.top - l.top + t.height / 2 };
}

// ---------------------------------------------------------------------------
// public API
// ---------------------------------------------------------------------------

export function createWindow({ id, title, kind = 'result', width, height, content, onClose } = {}) {
  const winId = id || `win-${seq++}`;
  if (windows.has(winId)) {
    const existing = windows.get(winId);
    focus(winId);
    return existing.handle;
  }

  const size = layerSize();
  const preset = DEFAULT_SIZE[kind] || DEFAULT_SIZE.result;
  const w = clamp(width || preset.w, MIN_W, Math.max(MIN_W, size.w - 8));
  const autoHeight = height == null && preset.h == null;
  const h = autoHeight ? MIN_H : clamp(height || preset.h, MIN_H, Math.max(MIN_H, size.h - 8));

  const el = document.createElement('section');
  el.className = 'window';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', title);

  const titlebar = document.createElement('header');
  titlebar.className = 'win-titlebar';
  const titleEl = document.createElement('span');
  titleEl.className = 'win-title';
  titleEl.textContent = title;
  const btns = document.createElement('div');
  btns.className = 'win-btns';

  const mkBtn = (name, label, fn) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `win-btn win-btn-${name}`;
    b.setAttribute('aria-label', label);
    b.title = label;
    b.appendChild(icon(name));
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      fn();
    });
    return b;
  };

  const minBtn = mkBtn('minimize', 'Minimize', () => minimize(winId));
  const maxBtn = mkBtn('maximize', 'Maximize', () => toggleMaximize(winId));
  const closeBtn = mkBtn('close', 'Close', () => close(winId));
  btns.append(minBtn, maxBtn, closeBtn);
  titlebar.append(titleEl, btns);

  const body = document.createElement('div');
  body.className = 'win-body';
  if (content) body.appendChild(content);

  const edgeE = document.createElement('div');
  edgeE.className = 'win-edge win-edge-e';
  const edgeS = document.createElement('div');
  edgeS.className = 'win-edge win-edge-s';
  const corner = document.createElement('div');
  corner.className = 'win-corner';

  el.append(titlebar, body, edgeE, edgeS, corner);
  layer.appendChild(el);

  const rec = {
    id: winId,
    kind,
    title,
    el,
    titleEl,
    body,
    maxBtn,
    subtitleEl: null,
    bounds: { x: 0, y: 0, w, h },
    autoHeight,
    maxH: preset.maxH,
    userSized: false,
    minimized: false,
    maximized: false,
    prevBounds: null,
    onClose,
  };

  rec.tab = buildTab(rec);
  windows.set(winId, rec);
  refreshTaskbarEmpty();

  // Fit the window to its content before placing it, so the height is right on the very first
  // paint rather than snapping after the open animation.
  if (autoHeight) {
    el.style.width = `${w}px`;
    el.style.height = 'auto';
    const measured = el.offsetHeight;
    const ceiling = Math.max(MIN_H, Math.min(preset.maxH || size.h, size.h - 8));
    rec.bounds.h = clamp(measured, MIN_H, ceiling);
    for (const img of body.querySelectorAll('img')) {
      if (!img.complete) img.addEventListener('load', () => refit(rec), { once: true });
    }
  }

  const pos = nextCascadePosition(rec.bounds.w, rec.bounds.h, winId);
  rec.bounds.x = pos.x;
  rec.bounds.y = pos.y;
  applyBounds(rec);

  wireDrag(rec, titlebar);
  wireResize(rec, edgeE, 'e');
  wireResize(rec, edgeS, 's');
  wireResize(rec, corner, 'es');

  zOrder.push(winId);
  focus(winId);

  if (!motionDisabled()) {
    const t = `translate(${Math.round(rec.bounds.x)}px, ${Math.round(rec.bounds.y)}px)`;
    el.animate(
      [
        { opacity: 0, transform: `${t} scale(0.96)` },
        { opacity: 1, transform: `${t} scale(1)` },
      ],
      { duration: 160, easing: 'cubic-bezier(0, 0, 0.35, 1)' },
    );
  }

  rec.handle = {
    id: winId,
    body,
    setTitle(next) {
      rec.title = next;
      titleEl.textContent = next;
      el.setAttribute('aria-label', next);
      rec.tab.querySelector('.tab-label').textContent = next;
      rec.tab.title = next;
    },
    // Secondary context next to the title — e.g. which dataset the Assistant is looking at. It
    // is a sibling of the title element, so setTitle() and setSubtitle() don't overwrite each
    // other, and it stays out of the taskbar tab (where there is no room for it).
    setSubtitle(next) {
      if (!next) {
        if (rec.subtitleEl) {
          rec.subtitleEl.remove();
          rec.subtitleEl = null;
        }
        return;
      }
      if (!rec.subtitleEl) {
        rec.subtitleEl = document.createElement('span');
        rec.subtitleEl.className = 'win-subtitle';
        titleEl.after(rec.subtitleEl);
      }
      rec.subtitleEl.textContent = next;
      rec.subtitleEl.title = next;
    },
    setContent(node) {
      body.innerHTML = '';
      if (node) body.appendChild(node);
    },
    bounds: () => ({ ...rec.bounds }),
    close: () => close(winId),
    focus: () => focus(winId),
  };
  return rec.handle;
}

export function focus(id) {
  const rec = windows.get(id);
  if (!rec) return;
  if (rec.minimized) {
    restore(id);
    return;
  }
  if (focusedId !== id) {
    zOrder = zOrder.filter((w) => w !== id);
    zOrder.push(id);
    focusedId = id;
    applyZOrder();
    applyFocusClasses();
  }
}

export function close(id) {
  const rec = windows.get(id);
  if (!rec) return;
  const finish = () => {
    rec.el.remove();
    rec.tab.remove();
    windows.delete(id);
    zOrder = zOrder.filter((w) => w !== id);
    if (focusedId === id) {
      focusedId = zOrder.length ? zOrder[zOrder.length - 1] : null;
      applyFocusClasses();
    }
    refreshTaskbarEmpty();
    if (rec.onClose) rec.onClose();
  };
  // A hidden or backgrounded tab throttles animations, and an animation that never runs never
  // fires onfinish — which left the window on screen forever. Closing must not depend on it.
  if (motionDisabled() || rec.minimized || document.hidden) {
    finish();
    return;
  }
  let settled = false;
  const once = () => {
    if (settled) return;
    settled = true;
    finish();
  };
  const t = `translate(${Math.round(rec.bounds.x)}px, ${Math.round(rec.bounds.y)}px)`;
  const anim = rec.el.animate(
    [
      { opacity: 1, transform: `${t} scale(1)` },
      { opacity: 0, transform: `${t} scale(0.96)` },
    ],
    { duration: 120, easing: 'ease-in' },
  );
  anim.onfinish = once;
  anim.oncancel = once;
  setTimeout(once, 400); // backstop: the window closes even if the animation is throttled away
}

export function minimize(id) {
  const rec = windows.get(id);
  if (!rec || rec.minimized) return;
  rec.minimized = true;
  rec.tab.classList.add('minimized');
  const hide = () => {
    rec.el.style.display = 'none';
  };
  if (focusedId === id) {
    focusedId = zOrder.filter((w) => w !== id && !windows.get(w).minimized).pop() || null;
    applyFocusClasses();
  }
  if (motionDisabled()) {
    hide();
    return;
  }
  const target = tabTargetInLayer(rec);
  const from = `translate(${Math.round(rec.bounds.x)}px, ${Math.round(rec.bounds.y)}px) scale(1)`;
  const to = `translate(${Math.round(target.x - rec.bounds.w / 2)}px, ${Math.round(target.y - rec.bounds.h / 2)}px) scale(0.12)`;
  const anim = rec.el.animate(
    [
      { opacity: 1, transform: from },
      { opacity: 0.1, transform: to },
    ],
    { duration: 220, easing: 'ease-in' },
  );
  anim.onfinish = hide;
  anim.oncancel = hide;
}

export function restore(id) {
  const rec = windows.get(id);
  if (!rec || !rec.minimized) return;
  rec.minimized = false;
  rec.tab.classList.remove('minimized');
  rec.el.style.display = '';
  applyBounds(rec);
  zOrder = zOrder.filter((w) => w !== id);
  zOrder.push(id);
  focusedId = id;
  applyZOrder();
  applyFocusClasses();
  if (motionDisabled()) return;
  const target = tabTargetInLayer(rec);
  const to = `translate(${Math.round(rec.bounds.x)}px, ${Math.round(rec.bounds.y)}px) scale(1)`;
  const from = `translate(${Math.round(target.x - rec.bounds.w / 2)}px, ${Math.round(target.y - rec.bounds.h / 2)}px) scale(0.12)`;
  rec.el.animate(
    [
      { opacity: 0.1, transform: from },
      { opacity: 1, transform: to },
    ],
    { duration: 220, easing: 'cubic-bezier(0, 0, 0.35, 1)' },
  );
}

export function toggleMaximize(id) {
  const rec = windows.get(id);
  if (!rec) return;
  focus(id);
  const size = layerSize();
  if (rec.maximized) {
    rec.bounds = rec.prevBounds || rec.bounds;
    rec.prevBounds = null;
    rec.maximized = false;
    rec.el.classList.remove('maximized');
    rec.maxBtn.replaceChildren(icon('maximize'));
    rec.maxBtn.title = 'Maximize';
    rec.maxBtn.setAttribute('aria-label', 'Maximize');
  } else {
    rec.prevBounds = { ...rec.bounds };
    rec.bounds = { x: 0, y: 0, w: size.w, h: size.h };
    rec.maximized = true;
    rec.userSized = true;
    rec.el.classList.add('maximized');
    rec.maxBtn.replaceChildren(icon('restore'));
    rec.maxBtn.title = 'Restore';
    rec.maxBtn.setAttribute('aria-label', 'Restore');
  }
  applyBounds(rec);
}

export function closeFocused() {
  if (focusedId) {
    close(focusedId);
    return true;
  }
  return false;
}

export function closeAll() {
  for (const id of [...windows.keys()]) close(id);
}

export function has(id) {
  return windows.has(id);
}

// Re-measure a window after its body was filled post-creation (charts render into an attached
// body so Chart.js sees real dimensions, which means the content arrives after the window does).
export function fitToContent(id) {
  const rec = windows.get(id);
  if (rec) refit(rec);
}

// What currently has focus — File > Print needs to know whether it is a result window, and
// Edit/Print items gray out based on it.
export function focused() {
  const rec = focusedId ? windows.get(focusedId) : null;
  if (!rec || rec.minimized) return null;
  return { id: rec.id, kind: rec.kind, title: rec.title, el: rec.el };
}

export function list() {
  return zOrder.map((id) => windows.get(id)).filter(Boolean).map((r) => ({ id: r.id, kind: r.kind, title: r.title, minimized: r.minimized }));
}

/** The live handle for an open window (or null) — lets a module redraw its own window's body in
 *  place when the data behind it changes, instead of closing and reopening it. */
export function get(id) {
  const rec = windows.get(id);
  return rec ? rec.handle : null;
}

export function count() {
  return windows.size;
}

// Re-lay the open windows out in a fresh cascade — the escape hatch once a dozen results
// are overlapping each other.
export function cascade() {
  cascadeIndex = 0;
  for (const id of zOrder) {
    const rec = windows.get(id);
    if (!rec || rec.minimized) continue;
    if (rec.maximized) toggleMaximize(id);
    const pos = nextCascadePosition(rec.bounds.w, rec.bounds.h, id);
    rec.bounds.x = pos.x;
    rec.bounds.y = pos.y;
    applyBounds(rec);
  }
}

// Bring a window to front on any click inside it.
layer.addEventListener('pointerdown', (e) => {
  const el = e.target.closest('.window');
  if (!el) return;
  for (const rec of windows.values()) {
    if (rec.el === el) {
      focus(rec.id);
      return;
    }
  }
});

// Keep everything inside the stage when the browser window changes size.
window.addEventListener('resize', () => {
  const size = layerSize();
  for (const rec of windows.values()) {
    if (rec.maximized) {
      rec.bounds = { x: 0, y: 0, w: size.w, h: size.h };
    } else {
      rec.bounds.w = Math.min(rec.bounds.w, Math.max(MIN_W, size.w));
      rec.bounds.h = Math.min(rec.bounds.h, Math.max(MIN_H, size.h));
      rec.bounds.x = clamp(rec.bounds.x, 0, Math.max(0, size.w - rec.bounds.w));
      rec.bounds.y = clamp(rec.bounds.y, 0, Math.max(0, size.h - rec.bounds.h));
    }
    applyBounds(rec);
  }
});
