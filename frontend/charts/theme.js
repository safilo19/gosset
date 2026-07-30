// One place that decides how every chart in the app looks — Chart.js global defaults, the
// categorical palette, and the shared option builder. Analysis-result charts and everything on
// the Graph menu import from here, so old and new charts read as one product.
//
// Every color is READ FROM THE CSS TOKENS in style.css rather than written here, which is what
// lets one token set serve both themes: refresh() re-reads them and re-applies the Chart.js
// defaults when the theme switches. Purple/indigo are deliberately absent from the palette:
// they were the previous theme, and a purple series would still read as it.
//
// These are `let`, not `const`, and importers must reach them through the namespace
// (`theme.INK`, not a destructured `INK`) — a destructured copy snapshots the value at import
// time and would keep painting the old theme's colors after a switch.

import { motionDisabled, get as getSettings } from '../settings.js';

export let INK = '#161616';
export let MUTED = '#6f6f6f';
export let BORDER = '#d5dae1';
export let GRID = '#e5e8ec';
export let SURFACE = '#ffffff';
export let SURFACE_2 = '#f6f7f9';
export let ACCENT = '#0f62fe';
export let SUCCESS = '#24a148';
export let DANGER = '#da1e28';
// Ink for text drawn ON a saturated accent fill (a strongly-coloured matrix cell). White in light,
// near-black in dark, where the accent itself is a light blue.
export let ON_ACCENT = '#ffffff';

// 8 categorical hues, accent first, ordered so neighbours stay far apart. The dark theme defines
// its own brighter/less saturated variant of the same eight (--chart-1..8 in style.css).
export let PALETTE = ['#0f62fe', '#007d79', '#d02670', '#198038', '#ff832b', '#1192e8', '#a2191f', '#6f6f6f'];

export const FONT_SANS = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif";
export const FONT_MONO = "'IBM Plex Mono', ui-monospace, Consolas, monospace";

export const DRAW_MS = 600;

// The declared values above are the light-theme fallbacks, kept here so a print capture has something
// correct to fall back to; readTokens() overwrites them from the stylesheet immediately below.
const LIGHT_FALLBACK = Object.freeze({
  '--ink': INK, '--muted': MUTED, '--border': BORDER, '--grid': GRID, '--surface': SURFACE,
  '--surface-2': SURFACE_2, '--accent': ACCENT, '--success': SUCCESS, '--danger': DANGER,
  '--on-accent': ON_ACCENT,
  ...Object.fromEntries(PALETTE.map((hex, i) => [`--chart-${i + 1}`, hex])),
});

/** Look a token up in an element's computed style — the ordinary path. */
function domLookup(element) {
  const cs = getComputedStyle(element);
  return (name) => cs.getPropertyValue(name).trim();
}

/**
 * Look a token up in the `:root[data-theme='light']` STYLESHEET RULE, without applying that theme.
 *
 * Needed because the two token sets are declared on `:root` (by design — the theme belongs to the
 * document), so there is no element other than `<html>` that a light token can be read from: putting
 * `data-theme='light'` on a div matches nothing, and the div just inherits the dark values. Reading the
 * rule is how a print capture gets light colours while the app stays dark.
 */
function lightRuleLookup() {
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // a cross-origin stylesheet throws on cssRules rather than returning null
    }
    for (const rule of rules || []) {
      const selector = rule.selectorText || '';
      if (selector.includes(':root') && selector.replace(/["\s]/g, '').includes("[data-theme='light']")) {
        return (name) => rule.style.getPropertyValue(name).trim();
      }
    }
  }
  return null;
}

function readTokens(lookup = domLookup(document.documentElement)) {
  const token = (name, fallback) => lookup(name) || fallback;

  INK = token('--ink', INK);
  MUTED = token('--muted', MUTED);
  BORDER = token('--border', BORDER);
  GRID = token('--grid', GRID);
  SURFACE = token('--surface', SURFACE);
  SURFACE_2 = token('--surface-2', SURFACE_2);
  ACCENT = token('--accent', ACCENT);
  SUCCESS = token('--success', SUCCESS);
  DANGER = token('--danger', DANGER);
  ON_ACCENT = token('--on-accent', ON_ACCENT);
  PALETTE = PALETTE.map((fallback, i) => token(`--chart-${i + 1}`, fallback));
}

readTokens();

// True only inside withPrintRendering(): makes mountChart build at 2x for print.
let printing = false;

export function isPrinting() {
  return printing;
}

/**
 * Build charts for PRINT inside `fn`: the LIGHT palette, at 2x resolution.
 *
 * A report is printed on white paper whatever the screen is showing, so a chart captured for one has
 * to be rebuilt in light colours — and per the re-theme rule, rebuilt is the only way: a Chart.js
 * chart copies its axis, grid and tooltip colours into its own options at construction time and no
 * `update()` reaches them.
 *
 * `fn` may be async, and the palette is held for as long as it takes: construction is NOT the only
 * moment the colours are read. A plugin that fills the chart area in its `beforeDraw` reads
 * `theme.SURFACE` when the chart DRAWS, and mountChart deliberately draws on a later frame (it waits
 * for the canvas to be connected). Restoring the theme as soon as `new Chart(...)` returned put the
 * dark surface back under exactly those charts — a report exported from dark mode came out with dark
 * plot backgrounds and light axes. So: await, then restore.
 *
 * The light values are read out of the stylesheet RULE rather than by flipping `<html>` to light and
 * back: the flip would repaint the whole app for a frame, which reads as a flash of white every time
 * someone exports from dark mode.
 *
 * A capture is also always PLAIN, whatever File > Options > Charts says — see interactive(). An
 * exported document is the same document in either mode.
 */
export async function withPrintRendering(fn) {
  printing = true;
  try {
    readTokens(lightRuleLookup() || ((name) => LIGHT_FALLBACK[name] || ''));
    styled = false;
    applyDefaults();
    return await fn();
  } finally {
    printing = false;
    refresh(); // back to whatever the app is actually showing
  }
}

// ---------------------------------------------------------------------------
// print figures: the ONLY path an export may take to a chart PNG
// ---------------------------------------------------------------------------

/**
 * A figure is rendered for print, never photographed off the screen.
 *
 * The old contract was "the chart travels as the picture the user is looking at", which sounds
 * faithful and is not: the PNG then carried whatever size the window happened to be, so the same
 * chart exported at one aspect from a tall window and another from a short one, tick labels came out
 * at whatever size fit a 300px-wide panel, and a composite (marginal, matrix) was reassembled from
 * its live canvases by a helper that stretched every panel into the first panel's box.
 *
 * `renderForExport` renders the figure again, offscreen, at a fixed print geometry in the light
 * palette with print-tuned type — and composes multi-panel figures from the OFFSCREEN LAYOUT, so the
 * grid geometry is whatever the CSS says it is rather than a guess. 800x500 CSS px at devicePixelRatio
 * 2 is 1600x1000 real pixels, which lands at ~200dpi in a report's ~460pt figure frame.
 */
export const PRINT_FIGURE = Object.freeze({ width: 800, height: 500, scale: 2 });

// Print-figure type: bigger than the screen's, because the figure is scaled DOWN into the document's
// frame (~0.6x for a 460pt frame), and 10.5px ticks land at ~6.5pt there.
const PRINT_TYPE = Object.freeze({ tick: 12.5, axisTitle: 13.5, legend: 12.5, panelTitle: 12 });

let printFigure = false;

/** True only inside renderForExport() — makes baseOptions() build print-tuned type. */
export function isPrintFigure() {
  return printFigure;
}

function nextFrame() {
  // Never rAF alone: a backgrounded tab stops firing it and an export would hang forever waiting for
  // a frame that never comes. Same rule as windowManager.close() and blockCapture's paint wait.
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    requestAnimationFrame(finish);
    setTimeout(finish, 40);
  });
}

/**
 * Run `fn` once the charts mounted in this tick have had their layout pass.
 *
 * For the cross-chart alignments: a composite's panels are built one after another, so a panel that
 * lays itself out against a sibling has nothing to read until that sibling exists and has drawn.
 * Two frames, with a timer backstop — a backgrounded tab stops firing rAF and a nudge that never
 * arrives would leave the figure misaligned rather than merely late.
 */
export function afterLayout(fn) {
  let done = false;
  const run = () => {
    if (done) return;
    done = true;
    try {
      fn();
    } catch {
      /* a nudge must never be the thing that fails a render */
    }
  };
  requestAnimationFrame(() => requestAnimationFrame(run));
  setTimeout(run, DRAW_MS);
}

/** Every Chart.js instance inside a host, in DOM order. */
function chartsIn(host) {
  if (typeof Chart === 'undefined' || !Chart.getChart) return [];
  return [...host.querySelectorAll('canvas')].map((c) => Chart.getChart(c)).filter(Boolean);
}

/** Wait until every chart in the host has been laid out and drawn (mountChart draws on a later frame). */
async function settleFigure(host, timeoutMs = 2500) {
  const deadline = performance.now() + timeoutMs;
  await nextFrame();
  while (performance.now() < deadline) {
    const canvases = [...host.querySelectorAll('canvas')];
    const charts = chartsIn(host);
    const ready =
      canvases.length > 0 &&
      charts.length === canvases.length &&
      charts.every((c) => c.width > 0 && !(Chart.animator && Chart.animator.has && Chart.animator.has(c)));
    if (ready) return;
    await nextFrame();
  }
}

/**
 * Give the figure a definite print height, in the one way each kind of layout needs.
 *
 * A standalone chart: the wrap takes the full print height.
 *
 * A `.marginal-layout`: the GRID takes it, and the rows (`82px minmax(0, 1fr)`) divide it up. This is
 * the part that has to be handed down rather than left alone — on screen the grid inherits a definite
 * height from the window body, so `1fr` resolves to a tall main panel, but in an offscreen host of
 * auto height `1fr` collapses to min-content and the scatter comes out as a letterbox strip. Setting
 * the height on the grid lets the CSS do the dividing, which is the point: the layout stays the
 * specification.
 *
 * A `.model-grid` (matrix plot, factorial panels) needs nothing: its cells carry explicit chart
 * heights, so its rows already resolve.
 */
function applyPrintGeometry(host, height) {
  const marginal = host.querySelector('.marginal-layout');
  if (marginal) {
    marginal.style.height = `${height}px`;
    for (const chart of chartsIn(host)) chart.resize();
    return;
  }
  const wraps = [...host.querySelectorAll('.chart-wrap')];

  // A panel grid holding a SINGLE panel is still a two-column grid, so composing it faithfully gives a
  // half-width figure floating in the left half of the frame (an interaction plot of two factors has
  // exactly one panel). One panel is not a grid: give it the whole width and the full print height.
  const grid = host.querySelector('.model-grid, .panel-grid');
  if (grid && wraps.length === 1) {
    grid.style.gridTemplateColumns = 'minmax(0, 1fr)';
    wraps[0].style.height = `${height}px`;
    for (const chart of chartsIn(host)) chart.resize();
    return;
  }

  if (wraps.length !== 1 || grid) return;
  wraps[0].style.height = `${height}px`;
  for (const chart of chartsIn(host)) chart.resize();
}

/** Recompute and repaint every chart in the host at its current container size. */
function redrawCharts(host) {
  for (const chart of chartsIn(host)) {
    try {
      chart.resize();
      chart.update('none');
      chart.draw();
    } catch {
      /* a chart that cannot re-layout keeps whatever it last painted */
    }
  }
}

/**
 * Print-tune every chart in the host, then redraw.
 *
 * Applied to the built charts rather than only through baseOptions() because a dozen renderers set
 * their own tick fonts and tick limits (the matrix plot's 8.5px, for one), and those would otherwise
 * win over the print sizes. One pass, after the fact, is the only place that catches all of them.
 */
function printTuneCharts(host) {
  for (const chart of chartsIn(host)) {
    const o = chart.options;
    for (const scale of Object.values(o.scales || {})) {
      if (!scale) continue;
      if (scale.ticks) {
        scale.ticks.font = { ...(scale.ticks.font || {}), size: PRINT_TYPE.tick };
        scale.ticks.color = MUTED;
      }
      if (scale.title) {
        scale.title.font = { ...(scale.title.font || {}), size: PRINT_TYPE.axisTitle };
        scale.title.color = MUTED;
      }
      // Thinner gridlines: at print scale the screen's 1px reads as a cage around the data.
      if (scale.grid) {
        scale.grid.lineWidth = 0.6;
        scale.grid.color = GRID;
      }
      if (scale.border) scale.border.color = BORDER;
    }
    if (o.plugins && o.plugins.legend) {
      o.plugins.legend.labels = { ...(o.plugins.legend.labels || {}), font: { family: FONT_SANS, size: PRINT_TYPE.legend }, boxWidth: 12, boxHeight: 12 };
    }
    fitCategoryLabels(chart);
    try {
      chart.update('none');
      chart.draw();
    } catch {
      /* a chart that cannot re-layout still contributes whatever it last painted */
    }
  }
  // A second pass, after every panel has been tuned: a panel that lays itself out against a sibling's
  // plot area (a marginal histogram) read that area before the sibling's own type changed, so its
  // padding is one tune behind. Cheap, and it is what makes the alignment survive print-tuning.
  for (const chart of chartsIn(host)) {
    try {
      chart.update('none');
      chart.draw();
    } catch {
      /* as above */
    }
  }
}

/**
 * Keep a categorical axis legible instead of rendering overlapping mush.
 *
 * Three remedies, in the order the design prefers them: thin the ticks out, then truncate long labels
 * with an ellipsis, then rotate to 45°. Applied progressively — each is tried only if the axis is still
 * too tight after the previous one — and measured from the axis's real width, so the same function
 * serves a 300px screen panel and a 1600px print figure. Called from mountChart for every chart and
 * again by printTuneCharts at print geometry.
 *
 * Only ever touches a real `category` scale: the group plots fake a category axis out of a linear one
 * (see `categoryTicks`) and already pin one tick per group, which this must not fight.
 */
export function fitCategoryLabels(chart) {
  const scale = chart && chart.scales && chart.scales.x;
  if (!scale || scale.type !== 'category' || !scale.options || !scale.options.ticks) return;
  const labels = (chart.data.labels || []).map((l) => String(l ?? ''));
  if (labels.length < 2) return;
  const axisWidth = scale.width || chart.width || 0;
  if (!axisWidth) return;

  const ticks = scale.options.ticks;
  const fontSize = (ticks.font && ticks.font.size) || 11;
  const charWidth = fontSize * 0.58; // ballpark for IBM Plex Sans/Mono at these sizes
  const longest = labels.reduce((n, l) => Math.max(n, l.length), 0);
  const slot = axisWidth / labels.length;

  if (longest * charWidth + 6 <= slot) return; // everything fits as it is

  // 1. skip ticks
  const fitCount = Math.max(2, Math.floor(axisWidth / (longest * charWidth + 10)));
  if (fitCount < labels.length) ticks.maxTicksLimit = Math.min(ticks.maxTicksLimit || Infinity, fitCount);

  // 2. truncate — only when the renderer has not written its own callback to defer to
  const shown = Math.min(labels.length, ticks.maxTicksLimit || labels.length);
  const perLabel = axisWidth / shown;
  const maxChars = Math.max(4, Math.floor((perLabel - 6) / charWidth));
  if (longest > maxChars && !ticks.callback) {
    ticks.callback = function truncate(value, index) {
      const label = labels[index] !== undefined ? labels[index] : String(value);
      return label.length > maxChars ? `${label.slice(0, maxChars - 1)}…` : label;
    };
  }

  // 3. rotate, when even a truncated label has no room
  if (perLabel < fontSize * 3.2) {
    ticks.maxRotation = 45;
    ticks.minRotation = 45;
  }
}

/** Draw the figure's DOM-only labels (a matrix plot's diagonal, a panel's title) onto the composite. */
function drawFigureLabels(ctx, host, hostRect) {
  const items = [];
  for (const el of host.querySelectorAll('.panel-diagonal, .model-panel-title')) {
    const text = (el.textContent || '').trim();
    if (!text) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    items.push({ text, diagonal: el.classList.contains('panel-diagonal'), x: r.left - hostRect.left, y: r.top - hostRect.top, w: r.width, h: r.height });
  }
  for (const item of items) {
    if (item.diagonal) {
      ctx.fillStyle = SURFACE_2;
      ctx.fillRect(item.x, item.y, item.w, item.h);
      ctx.fillStyle = INK;
      ctx.font = `600 ${PRINT_TYPE.panelTitle + 1}px ${FONT_SANS}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(item.text, item.x + item.w / 2, item.y + item.h / 2, item.w - 8);
    } else {
      ctx.fillStyle = MUTED;
      ctx.font = `600 ${PRINT_TYPE.panelTitle}px ${FONT_SANS}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(item.text.toUpperCase(), item.x, item.y, item.w);
    }
  }
  return items;
}

/**
 * Compose every panel in the host onto ONE canvas, at the positions the layout gave them.
 *
 * This is what makes composites correct without a per-composite recipe: `.marginal-layout` and the
 * matrix `.model-grid` already encode the geometry in CSS, so reading each canvas's offset inside the
 * host reproduces it exactly — main scatter large, top histogram thin and sharing its x span, side
 * histogram thin at the right, matrix cells square with the diagonal labels in place. Each panel is
 * drawn at ITS OWN size; nothing is stretched into a uniform cell.
 *
 * Every canvas was built with devicePixelRatio 2 (mountChart, while printing) and is drawn at CSS
 * coordinates under a matching 2x transform, so the mapping is 1:1 and nothing is resampled.
 */
function compositeFigure(host, scale) {
  const hostRect = host.getBoundingClientRect();
  const panels = [];
  for (const canvas of host.querySelectorAll('canvas')) {
    const r = canvas.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    panels.push({ canvas, x: r.left - hostRect.left, y: r.top - hostRect.top, w: r.width, h: r.height });
  }
  if (!panels.length) return null;

  const labelBoxes = [];
  for (const el of host.querySelectorAll('.panel-diagonal, .model-panel-title')) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    labelBoxes.push({ x: r.left - hostRect.left, y: r.top - hostRect.top, w: r.width, h: r.height });
  }

  const boxes = [...panels, ...labelBoxes];
  const pad = 6;
  const width = Math.ceil(Math.max(...boxes.map((b) => b.x + b.w)) + pad);
  const height = Math.ceil(Math.max(...boxes.map((b) => b.y + b.h)) + pad);

  const out = document.createElement('canvas');
  out.width = Math.round(width * scale);
  out.height = Math.round(height * scale);
  const ctx = out.getContext('2d');
  // Opaque, always: reportlab draws a PNG with an alpha channel as an invisible rectangle.
  ctx.fillStyle = SURFACE;
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  drawFigureLabels(ctx, host, hostRect);
  for (const panel of panels) ctx.drawImage(panel.canvas, panel.x, panel.y, panel.w, panel.h);
  return out;
}

/**
 * Compose whatever is laid out inside `container` into one PNG, at the geometry the layout gave it.
 *
 * Exported so the renderers' own on-screen capture (`captureGrid`) uses the same composition as the
 * export path. Its predecessor assumed every panel was the size of the first one and drew each into a
 * uniform cell — which stretched a marginal plot's 74px-tall histogram strip over the whole figure and
 * skipped a matrix plot's diagonal cells, shifting every panel after them into the wrong square.
 */
export function compositeFromLayout(container, scale = 1) {
  if (!container) return null;
  try {
    const canvas = compositeFigure(container, scale);
    return canvas ? canvas.toDataURL('image/png') : null;
  } catch {
    return null; // a figure that cannot be composed simply has no capture
  }
}

/** Plotly draws into WebGL, which drawImage cannot read — but Plotly renders its own PNG at any size. */
async function plotlyFigure(host, width, height, scale) {
  const div = host.querySelector('.js-plotly-plot');
  if (!div || typeof window.Plotly === 'undefined') return null;
  try {
    return await window.Plotly.toImage(div, { format: 'png', width, height, scale });
  } catch {
    return null;
  }
}

/**
 * Render a figure for export and hand back a PNG data URL.
 *
 * `draw(host)` is the caller's business — it is handed an ATTACHED, print-sized, light-palette host
 * and may render a single chart, a composite, or a whole result into it. Everything about geometry,
 * palette, type, settling and composition is this function's business, which is what makes "every
 * export path uses renderForExport" a single-point guarantee.
 *
 * `scope(host)` picks the ONE figure to compose when the draw produced several — a whole result
 * renders as a stack of blocks, and a report section wants its own chart, not all of them merged.
 */
export async function renderForExport(draw, { width = PRINT_FIGURE.width, height = PRINT_FIGURE.height, scale = PRINT_FIGURE.scale, scope = null } = {}) {
  if (typeof draw !== 'function') return null;
  printFigure = true;
  try {
    return await withPrintRendering(async () => {
      const host = document.createElement('div');
      host.className = 'print-figure';
      // Attached and really sized: a Chart.js chart built in a detached or zero-size element paints
      // nothing, so the host is parked far offscreen rather than hidden.
      host.style.cssText = `position:fixed;left:-99999px;top:0;width:${width}px;pointer-events:none;z-index:-1;`;
      document.body.appendChild(host);
      try {
        await draw(host, { width, height });
        await settleFigure(host);
        const target = (scope ? scope(host) : host) || host;
        applyPrintGeometry(target, height);
        printTuneCharts(target);
        await settleFigure(host);
        // Applied a SECOND time, and this is not redundant. The first pass can land while the layout is
        // still resolving — a composite grid's `1fr` rows only have a height once their panels have
        // been sized, and a chart's own deferred resize can arrive after it. When that happened the
        // figure composed at the collapsed height and a marginal plot came out as a letterbox strip,
        // intermittently. The pass is idempotent, so re-running it either changes nothing or fixes
        // exactly that race; the redraw after it is what puts the pixels at the corrected size.
        applyPrintGeometry(target, height);
        redrawCharts(target);
        await settleFigure(host);
        const plotly = await plotlyFigure(target, width, height, scale);
        if (plotly) return plotly;
        const canvas = compositeFigure(target, scale);
        return canvas ? canvas.toDataURL('image/png') : null;
      } finally {
        for (const chart of chartsIn(host)) {
          try {
            chart.destroy();
          } catch {
            /* cleanup must never fail the export */
          }
        }
        host.remove();
      }
    });
  } finally {
    printFigure = false;
    refresh(); // withPrintRendering restored the palette; this restores the screen's type sizes
  }
}

export function color(index) {
  return PALETTE[index % PALETTE.length];
}

export function alpha(hex, a) {
  const n = hex.replace('#', '');
  const int = parseInt(n.length === 3 ? n.split('').map((c) => c + c).join('') : n, 16);
  return `rgba(${(int >> 16) & 255}, ${(int >> 8) & 255}, ${int & 255}, ${a})`;
}

// A translucent pad in the current surface colour — used by the plugins that print a label over a
// bar or a matrix cell. Hardcoding white there would put a white slab on a dark chart.
export function surfaceWash(a) {
  return alpha(SURFACE, a);
}

/**
 * Chart DRAW animation is off, deliberately.
 *
 * Chart.js interpolates every changed element property and only ships interpolators for numbers and
 * colours. Several properties our charts set — `pointStyle`, and (because a per-type `animations`
 * object REPLACES the defaults rather than merging) even `backgroundColor` and `borderColor` — end up
 * with no interpolator, and the animation throws from inside Chart.js's tick. The animation then never
 * completes: the chart stays in Chart.js's animator forever and its backing canvas is left CLEARED
 * immediately after clearRect. What you see is a stale composited frame, so the chart looks right
 * while `getImageData` on it returns nothing — which is why captured chart PNGs came out blank.
 *
 * The `snap` config below and propagateSharedAnimations() were both attempts to give those properties
 * an interpolator. They are correct and worth keeping — and the reason they appeared not to work is
 * now known and fixed in applyStructuralDefaults(): this object must be MUTATED into the defaults,
 * never assigned over them, or Chart.js loses the very key list it copies `type` and `fn` through.
 *
 * Turning the draw animation off removes the whole class of failure and costs nothing the design
 * asked for — the app's one signature motion is the ~500ms numeric count-up in the stat tiles, which
 * is unaffected. It also makes every capture deterministic, which is what the block menu's
 * Copy as Picture, Send to Word/PowerPoint and the Report pane depend on.
 *
 * DRAW_MS is still exported: procedureDialog's captureStack uses it to time its own settle.
 *
 * File > Options > Charts does NOT reach this. "Interactive charts" turns hover, zoom/pan and
 * legend clicks on; it must not turn draw animation back on, because everything above is still
 * true when it does.
 */
export function animation() {
  return { duration: 0 };
}

// ---------------------------------------------------------------------------
// interactive vs plain charts — File > Options > Charts
// ---------------------------------------------------------------------------

/**
 * Whether charts get the interactive suite (hover details, zoom/pan, clickable legends).
 *
 * THE one switch point, with `interactionOptions()` below: `baseOptions()` and `mountChart()` are
 * its only readers, so no renderer ever asks the question and no chart can be out of step with the
 * preference.
 *
 * Always false while PRINTING, whatever the setting says. A report figure is a static image either
 * way, and forcing plain here is what makes an export identical in both modes: no hover state, no
 * leftover zoom transform, no plugin registered on the chart being captured. This is deliberate —
 * do not "fix" it later by honouring the setting during a capture. An exported document must not
 * depend on a screen preference.
 */
export function interactive() {
  return !printing && getSettings().interactiveCharts !== false;
}

/** True when chartjs-plugin-zoom actually loaded from the CDN (see index.html). */
export function hasZoomPlugin() {
  if (typeof Chart === 'undefined') return false;
  try {
    return !!Chart.registry.getPlugin('zoom');
  } catch {
    return false; // the registry throws for an unknown id rather than returning undefined
  }
}

function zoomOptions() {
  if (!hasZoomPlugin()) return undefined;
  return {
    // Gesture animation is off for the same reason DRAW animation is (see animation() above): every
    // route back into Chart.js's animator is a route to a stranded, cleared canvas.
    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'xy', animation: { duration: 0 } },
    pan: { enabled: true, mode: 'xy', animation: { duration: 0 } },
  };
}

/**
 * The interaction half of a chart's options, in whichever mode is current.
 *
 * Plain mode's off switch is `events: []`. That is Chart.js's own list of the DOM events it
 * attaches, so emptying it registers NO listeners at all — and tooltips, the hover highlight and
 * legend clicks all stop from that one line, because the legend's click handling runs through the
 * same chart event system. `tooltip.enabled` and the no-op `legend.onClick` are belt and braces for
 * anything that re-enables an event later. Nothing is merely hidden, which is the point on a
 * session with a dozen chart windows open.
 *
 * Interactive mode deliberately adds ONLY the zoom config: hover, tooltips and legend clicks are
 * Chart.js defaults, and a renderer that picked its own `interaction` mode keeps it.
 */
export function interactionOptions() {
  if (interactive()) return { plugins: { zoom: zoomOptions() } };
  return {
    events: [],
    hover: { mode: null },
    interaction: { mode: null },
    plugins: { tooltip: { enabled: false }, legend: { onClick: () => {} } },
  };
}

/**
 * Merge the interaction fragment into a chart's `plugins`, one level deep.
 *
 * Shallow-replacing would drop what a renderer put there: nearly every chart sets
 * `plugins.tooltip.callbacks`, and `{tooltip: {enabled: false}}` landing on top of it would throw
 * those callbacks away — invisible in plain mode, and wrong the moment the chart is rebuilt
 * interactive. One level is all this fragment ever needs; a plugin's own nested config is not
 * something it touches.
 */
function mergePlugins(base = {}, patch = {}) {
  const out = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue; // the zoom plugin did not load
    const mergeable = value && typeof value === 'object' && !Array.isArray(value) && out[key] && typeof out[key] === 'object';
    out[key] = mergeable ? { ...out[key], ...value } : value;
  }
  return out;
}

/**
 * Copy `colors` and `snap` into every chart type's OWN `animations`, because a per-type `animations`
 * object REPLACES Chart.defaults.animations rather than merging with it.
 *
 * The one that actually bites is `Chart.defaults.datasets.bar.animations`, which Chart.js ships as
 * `{ numbers: { properties: [x, y, base, width, height] } }`. For any bar chart that is the whole
 * config: `colors` and `snap` are gone, so backgroundColor, borderColor and pointStyle end up with no
 * interpolator. `Chart.overrides[type].animations` is checked too, since a plugin may put it there.
 *
 * Existing entries win, so a type keeps whatever it defines for itself.
 *
 * Call again after registering a new chart type; the boxplot and matrix plugins self-register from
 * their CDN scripts, which run before this module, so one call at setup covers them.
 */
function propagateSharedAnimations() {
  const shared = {};
  for (const key of ['colors', 'snap']) {
    if (Chart.defaults.animations && Chart.defaults.animations[key]) shared[key] = Chart.defaults.animations[key];
  }
  const targets = [];
  for (const bag of [Chart.defaults.datasets, Chart.overrides]) {
    for (const type of Object.keys(bag || {})) {
      const entry = bag[type];
      if (entry && entry.animations) targets.push(entry.animations);
    }
  }
  for (const animations of targets) {
    for (const [key, value] of Object.entries(shared)) {
      if (!animations[key]) animations[key] = value;
    }
  }
}

/**
 * Tooltip styled like the app's own surfaces: white, 1px border, 4px radius, mono numbers.
 *
 * It also owns the one chart animation the app keeps: a 200ms opacity fade, in the functional
 * 120–220ms band, dropped to 0 when the OS or File > Options asks for reduced motion. Declaring
 * `animations` explicitly also REPLACES Chart.js's `numbers` group for the tooltip, so the box snaps
 * to its position instead of gliding there from the last point — six fewer animations, and a tooltip
 * that never appears to lag the cursor. Re-read on every rebuild, so the motion setting applies
 * without a reload.
 */
export function tooltipStyle() {
  const fade = motionDisabled() ? 0 : 200;
  return {
    animation: { duration: fade },
    animations: { opacity: { duration: fade, easing: 'linear' } },
    backgroundColor: SURFACE,
    borderColor: BORDER,
    borderWidth: 1,
    cornerRadius: 4,
    padding: 9,
    titleColor: INK,
    bodyColor: INK,
    titleFont: { family: FONT_SANS, weight: '600', size: 11.5 },
    bodyFont: { family: FONT_MONO, size: 11.5 },
    displayColors: true,
    boxWidth: 9,
    boxHeight: 9,
    boxPadding: 4,
  };
}

// A Chart.js canvas is transparent by default, so a captured PNG carries an alpha channel — and
// reportlab draws such a PNG as an invisible rectangle in the exported PDF. Painting the surface
// colour underneath every chart makes each capture opaque; on screen nothing changes, because the
// canvas already sits on a .chart-wrap painted in that same surface colour. Reading SURFACE at
// draw time (not at registration) is what keeps a capture matching the theme it was taken in.
const opaqueBackground = {
  id: 'opaqueBackground',
  beforeDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.globalCompositeOperation = 'destination-over';
    ctx.fillStyle = SURFACE;
    ctx.fillRect(0, 0, chart.width, chart.height);
    ctx.restore();
  },
};

let registered = false; // structural defaults + plugin: once per page
let styled = false; // colour defaults: again after every theme switch

export function applyDefaults() {
  if (typeof Chart === 'undefined') return;
  if (!registered) {
    registered = true;
    applyStructuralDefaults();
  }
  if (styled) return;
  styled = true;
  applyThemeDefaults();
}

// Re-reads the CSS tokens and pushes them back into Chart.js. Charts built after this call are
// styled for the new theme; the ones already on screen are rebuilt by their owner (app.js), since
// each chart baked the old axis and grid colours into its own options object at build time and no
// amount of .update() will refresh those.
export function refresh() {
  readTokens();
  styled = false;
  applyDefaults();
}

function applyStructuralDefaults() {
  Chart.register(opaqueBackground);

  // chartjs-plugin-zoom ships as a UMD global and does not self-register. Registering it here, once,
  // is what keeps "every chart" true — no call site opts in. If the CDN script did not load,
  // hasZoomPlugin() reports false and the zoom options are simply never built.
  if (typeof window !== 'undefined' && window.ChartZoom && !hasZoomPlugin()) {
    try {
      Chart.register(window.ChartZoom);
    } catch {
      /* a version that DID self-register throws on the second attempt; either way it is available */
    }
  }

  Chart.defaults.font.family = FONT_SANS;
  Chart.defaults.font.size = 11;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.responsive = true;

  /**
   * MERGED into the shipped defaults, never assigned over them — and this is load-bearing.
   *
   * `Animations.configure()` builds each animated property's config with
   * `for (const option of Object.keys(Chart.defaults.animation)) resolved[option] = cfg[option]`.
   * That object's KEYS are the list of per-animation option names Chart.js will carry across, which
   * is why Chart.js ships it with `type`, `fn`, `from`, `to`, `easing`, `delay` and `loop` all
   * present-but-undefined. Assigning `{duration: 0}` over it cut the list down to `['duration']`, so
   * `colors`' `type: 'color'` and `snap`'s `fn` were dropped from EVERY animation and each one fell
   * back to `interpolators[typeof from]` — undefined for a string.
   *
   * That was the real hole behind trap 2, and it was still open: hovering any bar or point created a
   * `backgroundColor` animation from `rgba(...)` to `#059BFF7F` with no interpolator, which threw
   * `this._fn is not a function` from the animator's tick and left `Chart.animator` wedged for the
   * whole page — one dead rAF, `_lastDate` frozen. Every later animation then silently never ran,
   * which is why hover TOOLTIPS activated and stayed at opacity 0.03, and why a legend click (a
   * `show`/`hide` transition, whose `colors` config carries its own `type`) could not repaint.
   *
   * `duration: 0` still wins for draw animation — everything in the note on animation() holds.
   */
  Chart.defaults.animation = { ...Chart.defaults.animation, ...animation() };

  // Hover feedback is instant rather than a 400ms colour fade: `transitions.active` is the one
  // animation a chart still creates once draw animation is off (it carries its own duration, so
  // `animation.duration = 0` does not reach it), and the design asks for functional motion only. At
  // duration 0 the new colour is assigned directly and the animator is never involved.
  if (Chart.defaults.transitions && Chart.defaults.transitions.active) {
    Chart.defaults.transitions.active.animation = { ...Chart.defaults.transitions.active.animation, duration: 0 };
  }

  // Chart.js interpolates every changed element property, but only ships interpolators for
  // numbers and colors — animating a string or array one ("stepped: 'after'", "borderDash",
  // "pointStyle") throws `this._fn is not a function` from inside its animation tick. Supplying
  // `fn` for those properties bypasses the interpolator lookup and just snaps to the new value.
  // Chart.js only treats color/borderColor/backgroundColor as colors, so the boxplot plugin's own
  // color options land here too.
  Chart.defaults.animations.snap = {
    fn: (from, to, factor) => (factor < 1 ? from : to),
    properties: [
      'pointStyle',
      'stepped',
      'borderDash',
      'borderDashOffset',
      'fill',
      'borderCapStyle',
      'borderJoinStyle',
      'segment',
      // booleans have no interpolator either (showLine flips from its default on the probability
      // plot's reference line)
      'showLine',
      'spanGaps',
      'circular',
      'hidden',
      // The boxplot plugin animates these too: an array of outlier values, and three string style
      // names. Found by wrapping Chart.js's animation tick and logging the property whose
      // interpolator was missing — there is no other way to discover them.
      'outliers',
      'outlierStyle',
      'itemStyle',
      'meanStyle',
      'outlierBackgroundColor',
      'outlierBorderColor',
      'itemBackgroundColor',
      'itemBorderColor',
      'medianColor',
      'meanBackgroundColor',
      'meanBorderColor',
      'lowerBackgroundColor',
    ],
  };
  // ...and declaring `snap` on Chart.defaults is not enough to make it apply.
  //
  // A chart's `animations` is resolved from its TYPE OVERRIDE, and that object REPLACES
  // Chart.defaults.animations rather than merging with it. Chart.js's own bar override defines only
  // `{numbers}`, so for every bar chart both `colors` AND `snap` disappear — leaving backgroundColor,
  // borderColor and pointStyle with no interpolator at all.
  //
  // The consequence is worse than a console error. The failing animation throws from inside the tick
  // every frame, so it NEVER completes: the chart stays in Chart.js's animator forever, and its
  // backing canvas is left cleared right after clearRect. What you see on screen is a stale
  // composited frame — read the canvas and it is blank, which is why captured chart PNGs were
  // intermittently empty.
  //
  // So the shared configs are pushed into every type's own `animations`, without disturbing the
  // entries that type defines for itself.
  propagateSharedAnimations();

  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.legend.labels.usePointStyle = false;
  Chart.defaults.plugins.legend.labels.font = { family: FONT_SANS, size: 11 };
}

function applyThemeDefaults() {
  Chart.defaults.color = MUTED;
  Chart.defaults.borderColor = GRID;
  Object.assign(Chart.defaults.plugins.tooltip, tooltipStyle());

  // Numeric tick values in mono with tabular figures; category labels stay in the sans face,
  // since a region name is a label rather than a value.
  for (const scaleType of ['linear', 'logarithmic']) {
    if (!Chart.defaults.scales[scaleType]) continue;
    Chart.defaults.scales[scaleType].ticks = {
      ...Chart.defaults.scales[scaleType].ticks,
      color: MUTED,
      font: { family: FONT_MONO, size: 10.5 },
    };
  }
  if (Chart.defaults.scales.category) {
    Chart.defaults.scales.category.ticks = { ...Chart.defaults.scales.category.ticks, color: MUTED, font: { family: FONT_SANS, size: 10.5 } };
  }
  if (Chart.defaults.scales.time) {
    Chart.defaults.scales.time.ticks = { ...Chart.defaults.scales.time.ticks, color: MUTED, font: { family: FONT_MONO, size: 10.5 } };
  }
}

// The per-chart options every plot starts from. `axes: false` drops the scales entirely, for
// pie/doughnut and other scale-less charts.
export function baseOptions({ legend = false, axes = true, xTitle = '', yTitle = '', xType = 'linear', stacked = false } = {}) {
  const interactionFragment = interactionOptions();
  // A print figure is scaled down into the document's frame, so it is built with larger type and
  // thinner gridlines from the start. printTuneCharts() re-applies these after the fact as well,
  // because renderers routinely override the tick font for their own layout.
  const tickSize = printFigure ? PRINT_TYPE.tick : 10.5;
  const titleSize = printFigure ? PRINT_TYPE.axisTitle : 11;
  const gridWidth = printFigure ? 0.6 : 1;
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: animation(),
    interaction: { mode: 'nearest', intersect: true },
    ...interactionFragment,
    plugins: mergePlugins(
      {
        legend: legend ? { display: true, position: 'top', align: 'start' } : { display: false },
        tooltip: tooltipStyle(),
      },
      interactionFragment.plugins,
    ),
  };
  if (!axes) return options;

  const axisTitle = (text) => ({ display: !!text, text, color: MUTED, font: { family: FONT_SANS, size: titleSize } });
  options.scales = {
    x: {
      type: xType,
      stacked,
      title: axisTitle(xTitle),
      grid: { color: GRID, drawTicks: false, lineWidth: gridWidth },
      border: { color: BORDER },
      ticks: { color: MUTED, font: { family: xType === 'category' ? FONT_SANS : FONT_MONO, size: tickSize }, maxRotation: 30 },
    },
    y: {
      stacked,
      title: axisTitle(yTitle),
      grid: { color: GRID, drawTicks: false, lineWidth: gridWidth },
      border: { color: BORDER },
      ticks: { color: MUTED, font: { family: FONT_MONO, size: tickSize } },
    },
  };
  return options;
}

// ---------------------------------------------------------------------------
// mounting + export capture
// ---------------------------------------------------------------------------

/**
 * The reset affordance for zoom and pan: a small button in the corner of the chart frame, shown only
 * once the view has actually been moved, plus double-click anywhere on the plot (the plugin has no
 * double-click handling of its own).
 *
 * A DOM node in the `.chart-wrap`, not something drawn on the canvas — so it can never appear in a
 * captured PNG, and it re-themes itself through the CSS tokens like every other control.
 *
 * Built BEFORE the chart because its callbacks belong in the chart's own options at construction
 * time; patching `chart.options.plugins.zoom` afterwards works only until something calls update().
 */
function createZoomReset(wrap) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'chart-reset-zoom';
  button.textContent = 'Reset zoom';
  button.title = 'Back to the full view — or double-click the chart';
  button.hidden = true;
  wrap.appendChild(button);

  let chart = null;
  const sync = () => {
    let moved = false;
    try {
      moved = !!(chart && chart.isZoomedOrPanned && chart.isZoomedOrPanned());
    } catch {
      moved = false; // an older plugin build without the helper: the button just stays hidden
    }
    button.hidden = !moved;
  };
  const reset = () => {
    try {
      if (chart && chart.resetZoom) chart.resetZoom('none');
    } catch {
      /* nothing to reset, or a chart mid-teardown */
    }
    sync();
  };

  button.addEventListener('click', reset);
  return {
    onGesture: sync,
    bind(instance) {
      chart = instance;
      instance.canvas.addEventListener('dblclick', reset);
      sync();
    },
  };
}

// Every chart hands a PNG of exactly what was drawn to `onCapture`, which is how any chart type
// reaches the PDF/Word/Excel/Markdown exports without a per-type server-side renderer.
export function mountChart(container, config, { height = 260, compact = false, onCapture } = {}) {
  if (!config || typeof Chart === 'undefined') return null;
  applyDefaults();

  const wrap = document.createElement('div');
  wrap.className = compact ? 'chart-wrap chart-wrap-sm' : 'chart-wrap';
  wrap.style.height = `${compact ? Math.min(height, 180) : height}px`;
  const canvas = document.createElement('canvas');
  wrap.appendChild(canvas);
  container.appendChild(wrap);

  let chart = null;
  let captured = false;

  // Takes the PNG from whichever chart instance is available. `onComplete` can fire before the
  // `chart` variable is assigned (Chart.js may finish an animation from inside its constructor),
  // so the instance is preferred from the event and the timer below is the backstop for charts
  // whose animation never completes — e.g. one drawn with animation switched off.
  const grab = (instance) => {
    if (captured || !onCapture) return;
    const target = instance || chart;
    try {
      const url = target && target.toBase64Image ? target.toBase64Image('image/png', 1) : canvas.toDataURL('image/png');
      if (url && url.length > 256) {
        captured = true;
        onCapture(url);
      }
    } catch {
      /* a tainted or zero-size canvas simply yields no capture */
    }
  };

  // Interactive or plain, applied here as well as in baseOptions(): this is the gate EVERY chart in
  // the app passes through (nothing else calls `new Chart`), so a config assembled by hand or a
  // renderer that rebuilt its own `plugins` still lands in the right mode.
  const interactionFragment = interactionOptions();
  const zoomReset = interactive() && hasZoomPlugin() ? createZoomReset(wrap) : null;
  if (zoomReset && interactionFragment.plugins.zoom) {
    const z = interactionFragment.plugins.zoom;
    interactionFragment.plugins = {
      ...interactionFragment.plugins,
      zoom: {
        ...z,
        zoom: { ...z.zoom, onZoomComplete: zoomReset.onGesture },
        pan: { ...z.pan, onPanComplete: zoomReset.onGesture },
      },
    };
  }

  const withCapture = {
    ...config,
    options: {
      ...(config.options || {}),
      // 2x for a print capture: toBase64Image returns the backing store, which is CSS size x this. The
      // engine halves it back to points, so the figure lands at ~144dpi rather than the screen's 96.
      ...(printing ? { devicePixelRatio: 2 } : {}),
      ...interactionFragment,
      plugins: mergePlugins((config.options || {}).plugins, interactionFragment.plugins),
      animation: {
        ...animation(),
        ...((config.options || {}).animation || {}),
        onComplete: (event) => grab(event && event.chart),
      },
    },
  };

  chart = new Chart(canvas.getContext('2d'), withCapture);
  if (zoomReset) zoomReset.bind(chart);

  // A chart is usually built while its window body is still detached — the window manager measures
  // the content to size the window before attaching it. Giving a canvas a new size clears it, so a
  // chart created detached can end up with correct element geometry and no pixels at all (which is
  // exactly what it looked like: a blank chart area, and a blank capture in exported reports).
  // Forcing one resize + draw once the canvas is really in the document fixes both.
  // rAF is the right clock for "has it been laid out yet", and the WRONG one to trust on its own: a
  // hidden or backgrounded tab stops firing it entirely. Without the timer the whole settle below
  // never runs — the chart keeps whatever size it was constructed at, which is how an export taken
  // while the tab was in the background came out at the on-screen height instead of the print height.
  // Same rule as windowManager.close() and blockCapture's paint wait: never depend only on a frame.
  const soon = (fn) => {
    let done = false;
    const once = () => {
      if (done) return;
      done = true;
      fn();
    };
    requestAnimationFrame(once);
    setTimeout(once, 32);
  };

  const ensureDrawn = (attempt = 0) => {
    if (!canvas.isConnected) {
      if (attempt < 90) soon(() => ensureDrawn(attempt + 1));
      return;
    }
    chart.resize();
    // Category labels are fitted here, after resize, because the remedy depends on the axis's real
    // width — which is only known once the canvas has its final size. On screen as well as in print:
    // a bar chart of 40 regions in a 400px panel is mush either way.
    fitCategoryLabels(chart);
    // update('none') recomputes every element to its final value without animating, and draw()
    // then paints them. Each alone is not enough: draw() by itself can leave an element stuck at
    // its animation start (a boxplot box collapsed onto zero), while update()/render() by
    // themselves paint nothing once Chart.js believes the chart is already settled.
    chart.update('none');
    chart.draw();
    if (onCapture) setTimeout(() => grab(chart), DRAW_MS + 150);
  };
  soon(() => ensureDrawn());
  return chart;
}

// Chart.js only ships the types Chart.register()-ed by its UMD bundle; the boxplot and matrix
// plugins self-register when their CDN scripts load. This reports what is actually available so
// a graph can explain itself instead of failing silently.
export function hasChartType(type) {
  if (typeof Chart === 'undefined') return false;
  try {
    return !!Chart.registry.getController(type);
  } catch {
    return false; // registry throws for unknown ids rather than returning undefined
  }
}
