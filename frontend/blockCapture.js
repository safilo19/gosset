// Turning any output block into a PNG.
//
// Charts already have a canvas (or a server-rendered <img>), so those are a direct draw. Tables and
// text have to be rasterised from DOM, and this does it with an SVG <foreignObject> wrapping a clone
// of the node — no html2canvas, no dependency, ~200 lines less than a layout engine.
//
// The catch that makes or breaks this approach: an SVG rendered through an <img> is a SEPARATE
// document. It cannot reach the page's stylesheet, its CSS variables, or its webfonts. So the clone
// has to carry everything it needs:
//
//   - every CSS property that affects how it looks is read off the LIVE node with
//     getComputedStyle and written onto the clone as an inline style. That is why the capture
//     matches the screen in either theme: --ink and friends are already resolved to real colours by
//     the time getComputedStyle sees them.
//   - the font stack is inlined as a literal family list. IBM Plex will be missing inside the SVG
//     document, so the capture falls back to the same system sans the app would fall back to.
//   - the markup must be valid XML (XHTML namespace, closed tags), or the <img> silently fails to
//     load and the promise rejects with nothing useful. serializeToString on a cloned node gives
//     that; innerHTML does not.

import * as theme from './charts/theme.js';

// Properties worth copying. A blanket copy of all ~340 computed properties produces a megabyte of
// markup per table and makes Chrome noticeably chug, so this is the list that actually shows.
const COPIED = [
  'font-family',
  'font-size',
  'font-weight',
  'font-style',
  'font-variant-numeric',
  'letter-spacing',
  'line-height',
  'text-align',
  'text-transform',
  'text-decoration',
  'white-space',
  'color',
  'background-color',
  'border-top-width',
  'border-right-width',
  'border-bottom-width',
  'border-left-width',
  'border-top-color',
  'border-right-color',
  'border-bottom-color',
  'border-left-color',
  'border-top-style',
  'border-right-style',
  'border-bottom-style',
  'border-left-style',
  'border-radius',
  'padding-top',
  'padding-right',
  'padding-bottom',
  'padding-left',
  'margin-top',
  'margin-right',
  'margin-bottom',
  'margin-left',
  'display',
  'flex-direction',
  'flex-wrap',
  'align-items',
  'justify-content',
  'gap',
  'grid-template-columns',
  'width',
  'height',
  'min-width',
  'max-width',
  'box-sizing',
  'vertical-align',
  'border-collapse',
  'border-spacing',
  'opacity',
];

const SCALE = 2; // draw at 2x so the PNG is crisp when pasted at 100%

function inlineStyles(source, clone) {
  const from = source.querySelectorAll('*');
  const to = clone.querySelectorAll('*');
  const pairs = [[source, clone], ...[...from].map((el, i) => [el, to[i]])];
  for (const [live, copy] of pairs) {
    if (!live || !copy || copy.nodeType !== 1) continue;
    const computed = getComputedStyle(live);
    let css = '';
    for (const prop of COPIED) {
      const value = computed.getPropertyValue(prop);
      if (value) css += `${prop}:${value};`;
    }
    // Scrollers must not clip the capture — the point of a picture is the WHOLE table.
    css += 'overflow:visible;max-height:none;';
    copy.setAttribute('style', css);
    copy.removeAttribute('class');
    copy.removeAttribute('tabindex');
  }
}

/** Rasterise a DOM node via SVG foreignObject. Resolves to a canvas. */
async function nodeToCanvas(node) {
  const rect = node.getBoundingClientRect();
  const width = Math.ceil(rect.width);
  // scrollHeight, not the rect: a table inside a .table-scroll is taller than the box showing it.
  const height = Math.ceil(Math.max(rect.height, node.scrollHeight));
  if (!width || !height) throw new Error('This block has no size to capture.');

  const clone = node.cloneNode(true);
  inlineStyles(node, clone);

  // A wrapper carrying the surface colour, so the PNG is not transparent-on-transparent when pasted
  // into a document that happens to be dark.
  const holder = document.createElementNS('http://www.w3.org/1999/xhtml', 'div');
  holder.setAttribute(
    'style',
    `width:${width}px;background:${theme.SURFACE};color:${getComputedStyle(node).color};padding:8px;box-sizing:border-box;` +
      'font-family:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,sans-serif;',
  );
  holder.appendChild(clone);

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('xmlns', svgNS);
  svg.setAttribute('width', String(width + 16));
  svg.setAttribute('height', String(height + 16));
  const fo = document.createElementNS(svgNS, 'foreignObject');
  fo.setAttribute('width', '100%');
  fo.setAttribute('height', '100%');
  fo.appendChild(holder);
  svg.appendChild(fo);

  const markup = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = () => reject(new Error('The browser could not rasterise this block.'));
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
  });

  const canvas = document.createElement('canvas');
  canvas.width = (width + 16) * SCALE;
  canvas.height = (height + 16) * SCALE;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = theme.SURFACE;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(SCALE, 0, 0, SCALE, 0, 0);
  ctx.drawImage(img, 0, 0);
  return canvas;
}

/**
 * Whether a canvas has anything drawn on it, judged from three horizontal strips. Cheap enough to
 * poll: a full getImageData every frame on a 500x300 canvas is ~600 KB of readback.
 *
 * A tainted canvas throws on read; treat that as "drawn" rather than waiting forever for a signal
 * that can never arrive.
 */
function hasInk(canvas) {
  try {
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    if (!w || !h) return false;
    for (const y of [Math.floor(h * 0.25), Math.floor(h * 0.5), Math.floor(h * 0.75)]) {
      const d = ctx.getImageData(0, y, w, 1).data;
      const first = `${d[0]},${d[1]},${d[2]},${d[3]}`;
      for (let i = 4; i < d.length; i += 4) {
        if (`${d[i]},${d[i + 1]},${d[i + 2]},${d[i + 3]}` !== first) return true;
      }
    }
    return false;
  } catch {
    return true;
  }
}

/**
 * Wait for a chart to actually paint before reading its pixels.
 *
 * Without this a capture taken while Chart.js is still animating — or in the first frames after a
 * theme switch rebuilds every window — returns a BLANK PNG. It fails silently: the file is a valid
 * image of nothing, so a staged chart exports as an empty picture and only a human looking at the
 * report notices. procedureDialog's own captureStack waits `theme.DRAW_MS + 250` for the same reason;
 * this waits on the actual pixels instead of a fixed delay, so it is both faster when the chart is
 * already drawn and safer when it is slow.
 */
/**
 * Whether every Chart.js chart on these canvases has finished animating. This is the precise signal
 * and the one tried first: `hasInk` alone can catch the instant mid-redraw when Chart.js has cleared
 * the canvas and not yet repainted, which reads as "blank" and burns the whole timeout on a chart
 * that was actually ready.
 *
 * Returns false when Chart.js is absent or a canvas has no chart, so the pixel check still decides
 * for a server-rendered image or a non-Chart canvas.
 */
function chartsSettled(canvases) {
  if (typeof Chart === 'undefined' || !Chart.getChart || !Chart.animator || typeof Chart.animator.has !== 'function') return false;
  const charts = canvases.map((c) => Chart.getChart(c));
  if (!charts.length || charts.some((c) => !c)) return false;
  return charts.every((c) => !Chart.animator.has(c));
}

async function waitForPaint(canvases, timeoutMs = 1200) {
  if (chartsSettled(canvases) || canvases.some(hasInk)) return;
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    // requestAnimationFrame ALONE would hang here: a backgrounded or throttled tab stops firing it,
    // and the await would never settle, so a capture (and the action waiting on it) would block
    // forever. The timer is the backstop — same rule as windowManager's close(), which never trusts
    // an animation event to fire on its own.
    await new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        resolve();
      };
      requestAnimationFrame(finish);
      setTimeout(finish, 60);
    });
    if (chartsSettled(canvases) || canvases.some(hasInk)) return;
  }
  // Timed out: capture whatever is there rather than failing the action outright.
}

/** Every canvas in a chart block, stacked into one — a four-in-one residual plot is four canvases. */
function stackCanvases(canvases) {
  const width = Math.max(...canvases.map((c) => c.width));
  const height = canvases.reduce((sum, c) => sum + c.height, 0);
  const sheet = document.createElement('canvas');
  sheet.width = width;
  sheet.height = height;
  const ctx = sheet.getContext('2d');
  ctx.fillStyle = theme.SURFACE;
  ctx.fillRect(0, 0, width, height);
  let top = 0;
  for (const canvas of canvases) {
    ctx.drawImage(canvas, 0, top);
    top += canvas.height;
  }
  return sheet;
}

async function imgToCanvas(img) {
  if (!img.complete) await img.decode().catch(() => {});
  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth || img.width;
  canvas.height = img.naturalHeight || img.height;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = theme.SURFACE;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);
  return canvas;
}

/**
 * A PNG of one block, whatever it is made of.
 *
 * A CHART block is re-rendered for print when its `printDraw` recipe is available (`info` from
 * `resultView.blockInfo`) — never photographed off the screen, so the exported figure has a fixed
 * print geometry, print-sized type and a correctly composed multi-panel layout instead of inheriting
 * whatever size the window happened to be. `theme.renderForExport` owns all of that.
 *
 * Everything else — tables, text, a server-rendered PNG, and a chart with no recipe (a reopened
 * project has no live render function) — takes the old paths, which are still the right ones.
 */
export async function blockToCanvas(el, info = null) {
  const canvases = [...el.querySelectorAll('canvas')].filter((c) => c.width > 8 && c.height > 8);
  if (canvases.length) {
    await waitForPaint(canvases);
    return stackCanvases(canvases);
  }
  const img = el.querySelector('img.result-image, img');
  if (img && (img.naturalWidth || img.width)) return imgToCanvas(img);
  // A Plotly 3D/contour plot draws into WebGL and has no readable 2D canvas; the SVG path at least
  // captures its surrounding markup rather than failing outright.
  return nodeToCanvas(el.querySelector('.out-block-body') || el);
}

/** The print-quality PNG of a chart block, or null when the block has no recipe to re-render from. */
async function printFigureUrl(info) {
  if (!info || info.kind !== 'chart' || typeof info.printDraw !== 'function') return null;
  try {
    return await theme.renderForExport(info.printDraw);
  } catch {
    return null; // fall back to the on-screen capture rather than exporting nothing
  }
}

export async function blockToDataUrl(el, info = null) {
  return (await printFigureUrl(info)) || (await blockToCanvas(el, info)).toDataURL('image/png');
}

/**
 * A small PNG for a list preview. Used for the Report pane's thumbnails, which are also what gets
 * written into the .baproj — a full-resolution table capture is ~100 KB, and a project with a dozen
 * staged tables would carry a megabyte of pictures nothing ever displays at that size. A chart keeps
 * its full capture, because there the PNG IS what gets exported.
 */
export async function blockToThumbDataUrl(el, maxWidth = 240, info = null) {
  const full = await blockToCanvas(el, info);
  if (full.width <= maxWidth) return full.toDataURL('image/png');
  const scale = maxWidth / full.width;
  const small = document.createElement('canvas');
  small.width = maxWidth;
  small.height = Math.max(1, Math.round(full.height * scale));
  const ctx = small.getContext('2d');
  ctx.fillStyle = theme.SURFACE;
  ctx.fillRect(0, 0, small.width, small.height);
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(full, 0, 0, small.width, small.height);
  return small.toDataURL('image/png');
}

export async function blockToBlob(el, info = null) {
  // Copy as Picture gets the same print-quality figure the documents get, so pasting into Word and
  // exporting to Word cannot disagree. A data: URL is fetchable, which is the shortest route to a Blob.
  const printed = await printFigureUrl(info);
  if (printed) return (await fetch(printed)).blob();
  const canvas = await blockToCanvas(el, info);
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('The PNG could not be encoded.'))), 'image/png');
  });
}
