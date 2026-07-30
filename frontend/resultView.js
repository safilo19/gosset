// The shared pieces of a result window: the DOM builder, number formatting, the count-up
// animation, the stat-tile grid and the data table. app.js and basicStats.js both render results,
// and they must render them identically — so this lives in one place rather than in each of them.

import * as settings from './settings.js';

export function h(tag, attrs = {}, children = []) {
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

const noMotion = () => settings.motionDisabled();

// ---------------------------------------------------------------------------
// number formatting + the count-up animation (the one signature interaction)
// ---------------------------------------------------------------------------

let activeCounters = [];
let tickerRunning = false;

// Below 10^-decimals a fixed-decimal rendering would collapse to 0.000 and throw away the
// answer (p-values especially), so those switch to exponential notation instead.
export function formatNumberDisplay(value, decimals) {
  if (decimals === 0) return String(Math.round(value));
  if (value !== 0 && Math.abs(value) < Math.pow(10, -decimals)) return value.toExponential(2);
  return value.toFixed(decimals);
}

export function decimalsForValue(v) {
  return Number.isInteger(v) ? 0 : settings.get().decimals;
}

function tick(now) {
  activeCounters = activeCounters.filter((c) => {
    const t = Math.min(1, (now - c.start) / c.duration);
    const eased = 1 - Math.pow(1 - t, 3);
    c.el.textContent = formatNumberDisplay(c.target * eased, c.decimals) + c.suffix;
    return t < 1;
  });
  if (activeCounters.length > 0) requestAnimationFrame(tick);
  else tickerRunning = false;
}

export function countUp(el, target, options = {}) {
  // `?? ` rather than a default parameter: a caller passing decimals: null (a highlight that has
  // no opinion) must still get the per-value default, not Math.pow(10, -null).
  const decimals = options.decimals ?? decimalsForValue(target);
  const suffix = options.suffix || '';
  const duration = options.duration ?? 500;
  if (!Number.isFinite(target)) {
    el.textContent = target === null || target === undefined ? '—' : String(target);
    return;
  }
  // Counting up to a value that renders in exponential notation just flickers — show it at once.
  const tiny = target !== 0 && Math.abs(target) < Math.pow(10, -decimals);
  if (noMotion() || tiny) {
    el.textContent = formatNumberDisplay(target, decimals) + suffix;
    return;
  }
  el.textContent = formatNumberDisplay(0, decimals) + suffix;
  activeCounters.push({ el, target, decimals, suffix, duration, start: performance.now() });
  if (!tickerRunning) {
    tickerRunning = true;
    requestAnimationFrame(tick);
  }
}

export function renderNumberInto(el, value) {
  el.classList.add('num');
  countUp(el, value);
}

export function formatCell(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v);
    return formatNumberDisplay(v, settings.get().decimals);
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

// ---------------------------------------------------------------------------
// the standard output block
// ---------------------------------------------------------------------------

// EVERY output block in a result window goes through block(). That is what gives it the chevron
// action menu (blockMenu.js) for free — Send to Word / PowerPoint / Report, Copy, Copy as Picture,
// Print, Delete. A new kind of output that builds its own bare <div> gets none of that, so it must
// be wrapped here too.
//
// The block's export payload lives in a WeakMap rather than in data-* attributes: rows are arrays of
// objects, and round-tripping them through JSON in the DOM would both bloat the markup and lose
// numeric types. The map is weak, so a closed window's blocks are collectable.
const blockMeta = new WeakMap();

/** What blockMenu.js and the Report pane need to know about a block. */
export function blockInfo(el) {
  return el ? blockMeta.get(el) || null : null;
}

export function allBlocks(root) {
  return [...(root || document).querySelectorAll('.out-block')];
}

/**
 * Wrap one output block. `kind` is 'text' | 'tiles' | 'table' | 'chart', `name` is what the menus and
 * the Report pane call it, and `rows` / `text` carry what Copy and the exporters need.
 *
 * A chart block also carries `printDraw(host)`: the recipe for drawing this same figure again into a
 * host of someone else's choosing. That is what lets every export re-render the chart at print
 * geometry (`theme.renderForExport`) instead of photographing the on-screen canvas at whatever size
 * the window happens to be. A block whose figure cannot be re-derived — a PNG the server rendered —
 * leaves it null, and the exporters fall back to the image it already has.
 */
export function block({ kind, name, rows = null, text = null, printDraw = null }, children) {
  const el = h('section', {
    class: `out-block out-block-${kind}`,
    // Focusable so the menu is reachable without a pointer: Enter opens it, Ctrl+C copies.
    tabindex: '0',
    'data-block-kind': kind,
    'aria-label': `${name || kind} block`,
  });
  const body = h('div', { class: 'out-block-body' }, children);
  el.appendChild(body);
  blockMeta.set(el, { kind, name: name || '', rows, text, printDraw, body });
  return el;
}

export function buildStatGrid(highlights) {
  if (!highlights || !highlights.length) return null;
  const grid = h('div', { class: 'stat-grid' });
  for (const hgh of highlights) {
    const tile = h('div', { class: hgh.tone ? `stat-tile ${hgh.tone}` : 'stat-tile' }, [h('div', { class: 'stat-label', text: hgh.label, title: hgh.label })]);
    const valueEl = h('div', { class: 'stat-value num' });
    tile.appendChild(valueEl);
    grid.appendChild(tile);
    countUp(valueEl, hgh.value, { decimals: hgh.decimals, suffix: hgh.suffix || '' });
  }
  // The tiles are one block: they are one summary, and copying half a summary is not useful.
  // `rows` gives Copy and the exporters a real table — label/value pairs.
  return block(
    { kind: 'tiles', name: 'Summary', rows: highlights.map((x) => ({ Statistic: x.label, Value: x.value })) },
    grid,
  );
}

export function buildDataTable(rows, bestModel) {
  if (!rows || !rows.length) return null;
  // A row may omit a key another row has (side-by-side test methods do), so the header list is
  // the union across rows rather than just the first row's keys.
  const headers = [];
  for (const row of rows) for (const key of Object.keys(row)) if (!headers.includes(key)) headers.push(key);
  const table = h('table', { class: 'result-table' }, [h('thead', {}, [h('tr', {}, headers.map((hd) => h('th', { text: hd })))])]);
  const tbody = h('tbody');
  for (const row of rows) {
    // AutoML's model-comparison table gets its winning row called out in --success.
    const tr = h('tr', { class: bestModel && row.model === bestModel ? 'best-model-row' : undefined });
    for (const hd of headers) {
      const v = row[hd];
      const td = h('td');
      if (typeof v === 'number' && Number.isFinite(v)) renderNumberInto(td, v);
      else if (typeof v === 'string' && v.includes('\n')) {
        // the correlation matrix puts 'r' and 'p = …' on two lines in one cell, as Minitab does
        td.className = 'cell-stacked';
        td.textContent = v;
      } else td.textContent = formatCell(v);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return h('div', { class: 'table-scroll' }, [table]);
}

// A titled table block — Minitab prints each output block under its own small heading.
export function buildTableBlock(title, rows) {
  const table = buildDataTable(rows);
  if (!table) return null;
  const wrap = h('div', { class: 'table-block' });
  if (title) wrap.appendChild(h('p', { class: 'section-label', text: title }));
  wrap.appendChild(table);
  return block({ kind: 'table', name: title || 'Table', rows }, wrap);
}

/** A prose block — the narrative/conclusion line, and the Report pane's own text notes. */
export function buildTextBlock(text, { name = 'Interpretation', className = 'narrative' } = {}) {
  if (!text) return null;
  return block({ kind: 'text', name, text }, h('p', { class: className, text }));
}
