// One render function per graph type. Each receives the server-computed data and draws it — no
// statistics happen here. Every renderer reports a PNG through `onCapture` so the chart reaches
// PDF/Word/Excel/Markdown exports.

import * as theme from './theme.js';
import { loadPlotly, plotlyLayout, plotlyConfig, trackPlot } from './plotly.js';

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  return node;
}

function note(container, text, interactiveHint = '') {
  const p = el('p', { class: 'chart-note', text });
  // A hint that only holds when charts are interactive ("drag to rotate", "hover a cell") is marked
  // rather than baked into the sentence, and `:root.charts-plain` hides it. A CSS class, not a
  // rebuild, because a Plotly window is re-layouted in place when the setting changes — rebuilding
  // it would throw away the camera angle — so its caption has to follow the mode on its own.
  if (interactiveHint) p.appendChild(el('span', { class: 'chart-note-interactive', text: ` · ${interactiveHint}` }));
  container.appendChild(p);
}

function missingPlugin(container, what) {
  container.appendChild(
    el('p', { class: 'error', text: `The ${what} plugin did not load, so this chart can't be drawn. Check the connection to the CDN and reopen this window.` }),
  );
}

const fmt = (v, digits = 3) => (v === null || v === undefined ? '' : Number.isInteger(v) ? String(v) : Number(v).toFixed(digits));

// ---------------------------------------------------------------------------
// composite capture: several canvases stitched into one PNG for the exports
// ---------------------------------------------------------------------------

/**
 * One PNG of a multi-panel figure, composed FROM THE LAYOUT rather than from a guess about it.
 *
 * Hand it the element that holds the panels — the marginal plot's grid, a matrix plot's grid, a row of
 * factorial panels — and `theme.compositeFromLayout` reads each canvas's position inside it and draws
 * them at those positions and their own sizes.
 *
 * Its predecessor took an array of canvases and a column count and drew every one into a cell the size
 * of the FIRST canvas. For anything whose panels differ in size that was wrong twice over: a marginal
 * plot (74px histogram strip, 250px scatter, 250px side histogram) had its scatter squashed into the
 * strip's box and its histograms stretched into solid blocks, and a matrix plot's diagonal cells hold
 * no canvas at all, so every panel after the first diagonal was drawn one square early.
 *
 * This is the on-screen record's capture; exports go through `theme.renderForExport`, which composes
 * the same way at print geometry.
 */
function captureGrid(container, onCapture) {
  if (!onCapture || !container) return;
  requestAnimationFrame(() => {
    setTimeout(() => {
      const url = theme.compositeFromLayout(container);
      if (url) onCapture(url);
    }, theme.DRAW_MS + 120);
  });
}

// ---------------------------------------------------------------------------
// inline Chart.js plugins (kept local so no extra CDN dependency is needed)
// ---------------------------------------------------------------------------

// Prints each matrix cell's value inside the cell — what makes a correlogram readable.
const cellLabels = {
  id: 'cellLabels',
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx } = chart;
    const meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.font = `500 ${opts.fontSize || 10}px ${theme.FONT_MONO}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    meta.data.forEach((element, index) => {
      const raw = chart.data.datasets[0].data[index];
      if (raw == null || raw.v == null) return;
      const strong = Math.abs(raw.v) > (opts.contrastAt ?? 0.62);
      ctx.fillStyle = strong ? theme.ON_ACCENT : theme.INK;
      ctx.fillText((opts.format || ((v) => fmt(v, 2)))(raw.v), element.x, element.y);
    });
    ctx.restore();
  },
};

/**
 * Pads a marginal histogram so its bars line up with the scatter's PLOT AREA, not its canvas.
 *
 * Without this the top histogram spans the full cell width while the scatter's plot area starts after
 * its y-axis gutter, so the two are offset by ~40px and the figure stops meaning what a marginal plot
 * means: that each bar sits above the slice of x it describes. Done in `beforeLayout` so it re-aligns
 * itself on every update — a window resize, and the re-layout that print-tuning triggers.
 *
 * Writes only LEAF numbers into `options.layout.padding`, which the marginal renderer supplies as a
 * real object up front. `chart.options` is a resolver proxy: reading a branch off it hands back
 * another proxy, and assigning that back (`options.layout = options.layout || {}`) sends the set trap
 * through itself until the stack runs out. Leaf assignment is ordinary and safe.
 */
const alignMarginal = {
  id: 'alignMarginal',
  beforeLayout(chart, _args, opts) {
    const main = opts && typeof opts.main === 'function' ? opts.main() : null;
    const area = main && main.chartArea;
    if (!area || !main.width || !main.height) return;
    const padding = chart.options.layout && chart.options.layout.padding;
    if (!padding || typeof padding !== 'object') return;
    if (opts.axis === 'x') {
      padding.left = Math.max(0, Math.round(area.left));
      padding.right = Math.max(0, Math.round(main.width - area.right));
    } else {
      padding.top = Math.max(0, Math.round(area.top));
      padding.bottom = Math.max(0, Math.round(main.height - area.bottom));
    }
  },
};

// Vertical 95% CI whiskers with caps, for the interval plot.
const errorBars = {
  id: 'errorBars',
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx } = chart;
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;
    ctx.save();
    ctx.strokeStyle = opts.color || theme.ACCENT;
    ctx.lineWidth = 1.4;
    for (const group of opts.groups || []) {
      if (group.ci_low == null || group.ci_high == null) continue;
      const x = xScale.getPixelForValue(group.index);
      const top = yScale.getPixelForValue(group.ci_high);
      const bottom = yScale.getPixelForValue(group.ci_low);
      const cap = 7;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.moveTo(x - cap, top);
      ctx.lineTo(x + cap, top);
      ctx.moveTo(x - cap, bottom);
      ctx.lineTo(x + cap, bottom);
      ctx.stroke();
    }
    ctx.restore();
  },
};

// Short horizontal rule at each group's mean. Done as a plugin rather than an extra dataset with
// `pointStyle: 'line'`: Chart.js animates dataset properties by interpolating them, and it has no
// interpolator for string values, so animating pointStyle throws inside its own animation tick.
const meanMarkers = {
  id: 'meanMarkers',
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx } = chart;
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;
    ctx.save();
    ctx.strokeStyle = opts.color || theme.INK;
    ctx.lineWidth = 2;
    for (const group of opts.groups || []) {
      if (group.mean == null) continue;
      const x = xScale.getPixelForValue(group.index);
      const y = yScale.getPixelForValue(group.mean);
      ctx.beginPath();
      ctx.moveTo(x - 14, y);
      ctx.lineTo(x + 14, y);
      ctx.stroke();
    }
    ctx.restore();
  },
};

// Maps a data value to a pixel on a histogram's category x axis by locating its bin and
// interpolating inside it. The bars are categories, so the scale itself cannot do this — but a
// hypothesized mean or a fitted curve has to land at its real position, not on a bin boundary.
function histogramPixel(chart, bins, value) {
  const count = (bins || []).length;
  if (!count || !chart.chartArea) return null;
  const step = chart.chartArea.width / count;
  let index = bins.findIndex((b) => value >= b.x0 && value <= b.x1);
  if (index === -1) index = value < bins[0].x0 ? 0 : count - 1;
  const bin = bins[index];
  const span = bin.x1 - bin.x0 || 1;
  return chart.scales.x.getPixelForValue(index) + ((value - bin.x0) / span - 0.5) * step;
}

// A dashed marker for a hypothesized value: vertical on a histogram (value on x), horizontal on a
// boxplot or individual value plot (value on y).
const refLine = {
  id: 'refLine',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || opts.value === null || opts.value === undefined) return;
    const area = chart.chartArea;
    const { ctx } = chart;
    let from;
    let to;
    if (opts.axis === 'x') {
      // `bins` means a histogram, whose x axis is categorical — the value has to be located inside
      // its bin. Without bins the x axis is an ordinary linear one and can place the value itself.
      const x = opts.bins ? histogramPixel(chart, opts.bins, opts.value) : chart.scales.x.getPixelForValue(opts.value);
      if (x === null || !Number.isFinite(x) || x < area.left - 1 || x > area.right + 1) return;
      from = [x, area.top];
      to = [x, area.bottom];
    } else {
      const y = chart.scales.y.getPixelForValue(opts.value);
      if (!Number.isFinite(y) || y < area.top - 1 || y > area.bottom + 1) return;
      from = [area.left, y];
      to = [area.right, y];
    }
    ctx.save();
    ctx.strokeStyle = opts.color || theme.DANGER;
    ctx.lineWidth = 1.4;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(from[0], from[1]);
    ctx.lineTo(to[0], to[1]);
    ctx.stroke();
    ctx.setLineDash([]);
    if (opts.label) {
      ctx.font = `500 10px ${theme.FONT_SANS}`;
      ctx.textBaseline = 'top';
      const flip = opts.axis === 'x' && from[0] > area.right - 70;
      ctx.textAlign = flip ? 'right' : 'left';
      const x = opts.axis === 'x' ? from[0] + (flip ? -4 : 4) : area.left + 4;
      const y = opts.axis === 'x' ? area.top + 2 : from[1] + 3;
      // A white pad behind the text: the label often sits over a histogram bar, where red on
      // accent-blue is unreadable.
      const width = ctx.measureText(opts.label).width;
      ctx.fillStyle = theme.surfaceWash(0.88);
      ctx.fillRect(flip ? x - width - 2 : x - 2, y - 1, width + 4, 13);
      ctx.fillStyle = opts.color || theme.DANGER;
      ctx.fillText(opts.label, x, y);
    }
    ctx.restore();
  },
};

// The fitted normal curve on a Graphical Summary histogram, drawn in the same bin space.
const overlayCurve = {
  id: 'overlayCurve',
  afterDatasetsDraw(chart, _args, opts) {
    const points = (opts && opts.points) || [];
    if (points.length < 2) return;
    const { ctx } = chart;
    ctx.save();
    ctx.strokeStyle = opts.color || theme.DANGER;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    let started = false;
    for (const point of points) {
      const x = histogramPixel(chart, opts.bins, point.x);
      const y = chart.scales.y.getPixelForValue(point.y);
      if (x === null || !Number.isFinite(y)) continue;
      if (started) ctx.lineTo(x, y);
      else {
        ctx.moveTo(x, y);
        started = true;
      }
    }
    ctx.stroke();
    ctx.restore();
  },
};

// Applies a payload's `reference` (a hypothesized value) to a chart's options, if it has one.
function applyReference(options, data, axis) {
  if (data.reference === null || data.reference === undefined) return;
  options.plugins.refLine = { value: data.reference, axis, bins: data.bins, label: data.reference_label || null };
}

function categoryTicks(labels) {
  // linear x axis showing group labels at integer positions — lets points be jittered off-centre
  return {
    min: -0.5,
    max: labels.length - 0.5,
    // Chart.js chooses its own "nice" tick positions on a linear axis, and with two groups it
    // lands on -0.5/0.5/1.5 — none of which is where a group sits, so every label came out blank.
    // Pin exactly one tick per group instead.
    afterBuildTicks: (axis) => {
      axis.ticks = labels.map((_label, index) => ({ value: index }));
    },
    ticks: {
      stepSize: 1,
      autoSkip: false,
      color: theme.MUTED,
      font: { family: theme.FONT_SANS, size: 10.5 },
      callback: (value) => labels[value] ?? '',
    },
    grid: { display: false },
    border: { color: theme.BORDER },
  };
}

// The whiskers are drawn by the errorBars plugin, so Chart.js has no idea they exist when it scales
// the y axis to the mean points — without this the caps are clipped off the top and bottom.
function fitIntervalAxis(options, groups) {
  const values = [];
  for (const group of groups) for (const value of [group.mean, group.ci_low, group.ci_high]) if (Number.isFinite(value)) values.push(value);
  if (values.length < 2) return;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low) * 0.12 || Math.abs(high) * 0.05 || 1;
  options.scales.y.min = low - pad;
  options.scales.y.max = high + pad;
  // Chart.js labels the explicit bounds as well as its own nice ticks, and a padded bound usually
  // lands a hair beyond the last nice one — which prints as the same number twice at the end of the
  // axis ("-0.6, -0.6"). The bounds still clip the scale; they just stop being labelled.
  options.scales.y.ticks = { ...(options.scales.y.ticks || {}), includeBounds: false };
}

// ---------------------------------------------------------------------------
// renderers
// ---------------------------------------------------------------------------

export const renderers = {
  scatter(container, data, { onCapture }) {
    const datasets = data.series.map((s, i) => ({
      label: s.label,
      data: s.points,
      backgroundColor: theme.alpha(theme.color(i), 0.75),
      borderColor: theme.color(i),
      pointRadius: 3.2,
      pointHoverRadius: 5,
      showLine: false,
    }));
    theme.mountChart(
      container,
      { type: 'scatter', data: { datasets }, options: theme.baseOptions({ legend: datasets.length > 1, xTitle: data.x_label, yTitle: data.y_label }) },
      { onCapture, height: 300 },
    );
    note(container, `${data.n} point(s)${data.group_column ? ` · colored by ${data.group_column}` : ''}`);
  },

  bubble(container, data, { onCapture }) {
    const options = theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label });
    options.plugins.tooltip.callbacks = {
      label: (item) => `${data.x_label} ${fmt(item.raw.x)}, ${data.y_label} ${fmt(item.raw.y)}, ${data.size_label} ${fmt(item.raw.size)}`,
    };
    theme.mountChart(
      container,
      {
        type: 'bubble',
        data: { datasets: [{ label: data.size_label, data: data.points, backgroundColor: theme.alpha(theme.ACCENT, 0.45), borderColor: theme.ACCENT, borderWidth: 1 }] },
        options,
      },
      { onCapture, height: 300 },
    );
    note(container, `Bubble area scales with ${data.size_label} (${fmt(data.size_min)} – ${fmt(data.size_max)}).`);
  },

  line(container, data, { onCapture }) {
    theme.mountChart(
      container,
      {
        type: 'line',
        data: { datasets: [{ label: data.y_label, data: data.points, borderColor: theme.ACCENT, backgroundColor: theme.alpha(theme.ACCENT, 0.12), pointRadius: 2.5, borderWidth: 2, tension: 0.25 }] },
        options: theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label }),
      },
      { onCapture, height: 290 },
    );
  },

  area(container, data, { onCapture }) {
    theme.mountChart(
      container,
      {
        type: 'line',
        data: {
          datasets: [
            { label: data.y_label, data: data.points, borderColor: theme.ACCENT, backgroundColor: theme.alpha(theme.ACCENT, 0.22), fill: true, pointRadius: 0, borderWidth: 2, tension: 0.25 },
          ],
        },
        options: theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label }),
      },
      { onCapture, height: 290 },
    );
  },

  bar(container, data, { onCapture }) {
    const datasets = data.series.map((s, i) => ({
      label: s.label,
      data: s.values,
      backgroundColor: theme.color(i),
      borderWidth: 0,
      maxBarThickness: 46,
    }));
    const options = theme.baseOptions({ legend: datasets.length > 1, xTitle: data.x_label, yTitle: data.y_label, xType: 'category', stacked: !!data.stacked });
    theme.mountChart(container, { type: 'bar', data: { labels: data.labels, datasets }, options }, { onCapture, height: 300 });
  },

  pie(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, axes: false });
    options.plugins.legend.position = 'right';
    options.plugins.tooltip.callbacks = {
      label: (item) => ` ${item.label}: ${fmt(item.raw)} (${(data.shares[item.dataIndex] * 100).toFixed(1)}%)`,
    };
    theme.mountChart(
      container,
      {
        type: 'pie',
        data: { labels: data.labels, datasets: [{ data: data.values, backgroundColor: data.labels.map((_, i) => theme.color(i)), borderColor: theme.SURFACE, borderWidth: 2 }] },
        options,
      },
      { onCapture, height: 300 },
    );
    note(container, `${data.value_label} by ${data.category_label}`);
  },

  timeSeries(container, data, { onCapture }) {
    const hasAdapter = typeof Chart !== 'undefined' && Chart._adapters && Chart._adapters._date && typeof Chart._adapters._date.prototype.format === 'function';
    const points = data.points.map((p) => ({ x: hasAdapter ? p.t : new Date(p.t).getTime(), y: p.y }));
    const options = theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label, xType: hasAdapter ? 'time' : 'linear' });
    if (hasAdapter) {
      options.scales.x.time = { tooltipFormat: 'PP' };
    } else {
      // no date adapter: fall back to timestamps formatted by hand rather than failing
      options.scales.x.ticks.callback = (value) => new Date(value).toISOString().slice(0, 10);
    }
    theme.mountChart(
      container,
      {
        type: 'line',
        data: { datasets: [{ label: data.y_label, data: points, borderColor: theme.ACCENT, backgroundColor: theme.alpha(theme.ACCENT, 0.12), pointRadius: 2, borderWidth: 2, tension: 0.2 }] },
        options,
      },
      { onCapture, height: 290 },
    );
    note(container, `${data.n} observation(s) over time`);
  },

  histogram(container, data, { onCapture }) {
    const labels = data.bins.map((b) => fmt(b.center, 1));
    const options = theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label, xType: 'category' });
    options.plugins.tooltip.callbacks = {
      title: (items) => {
        const bin = data.bins[items[0].dataIndex];
        return `${fmt(bin.x0, 2)} to ${fmt(bin.x1, 2)}`;
      },
      label: (item) => ` ${item.raw} row(s)`,
    };
    applyReference(options, data, 'x');
    const plugins = [refLine];
    if (Array.isArray(data.curve) && data.curve.length) {
      options.plugins.overlayCurve = { points: data.curve, bins: data.bins };
      plugins.push(overlayCurve);
    }
    theme.mountChart(
      container,
      {
        type: 'bar',
        data: { labels, datasets: [{ label: 'frequency', data: data.bins.map((b) => b.count), backgroundColor: theme.ACCENT, borderColor: theme.SURFACE, borderWidth: 1, barPercentage: 1, categoryPercentage: 1 }] },
        options,
        plugins,
      },
      { onCapture, height: 290 },
    );
    const bits = [`${data.n} values in ${data.bins.length} bins of width ${fmt(data.bin_width, 3)}`];
    if (data.curve_label) bits.push(`fitted ${data.curve_label}`);
    if (data.reference_label) bits.push(data.reference_label);
    note(container, bits.join(' · '));
  },

  boxplot(container, data, { onCapture }) {
    if (!theme.hasChartType('boxplot')) return missingPlugin(container, 'boxplot');
    const options = theme.baseOptions({ xType: 'category', yTitle: data.value_label });
    options.plugins.tooltip.callbacks = {
      label: (item) => {
        const g = data.groups[item.dataIndex];
        return [`median ${fmt(g.median)}`, `Q1 ${fmt(g.q1)} · Q3 ${fmt(g.q3)}`, `min ${fmt(g.min)} · max ${fmt(g.max)}`, `mean ${fmt(g.mean)} · n=${g.n}`];
      },
    };
    applyReference(options, data, 'y');
    theme.mountChart(
      container,
      {
        type: 'boxplot',
        plugins: [refLine],
        data: {
          labels: data.groups.map((g) => g.label),
          datasets: [
            {
              label: data.value_label,
              data: data.groups.map((g) => ({ min: g.min, q1: g.q1, median: g.median, q3: g.q3, max: g.max, outliers: g.outliers })),
              backgroundColor: theme.alpha(theme.ACCENT, 0.28),
              borderColor: theme.ACCENT,
              borderWidth: 1.4,
              itemRadius: 2.5,
              outlierBackgroundColor: theme.DANGER,
              outlierRadius: 3,
            },
          ],
        },
        options,
      },
      { onCapture, height: 300 },
    );
    const outliers = data.groups.reduce((sum, g) => sum + g.outliers.length, 0);
    note(container, `${data.groups.length} box(es)${data.group_label ? ` by ${data.group_label}` : ''} · ${outliers} outlier(s) beyond 1.5×IQR`);
  },

  heatmap(container, data, { onCapture }) {
    if (!theme.hasChartType('matrix')) return missingPlugin(container, 'matrix');
    const span = (data.max ?? 1) - (data.min ?? 0) || 1;
    const options = theme.baseOptions({ xType: 'category', xTitle: data.x_label, yTitle: data.y_label });
    options.scales.x.labels = data.x_labels;
    options.scales.x.offset = true;
    options.scales.x.grid.display = false;
    options.scales.y = { type: 'category', labels: data.y_labels, offset: true, reverse: true, grid: { display: false }, border: { color: theme.BORDER }, ticks: { color: theme.MUTED, font: { family: theme.FONT_SANS, size: 10.5 } } };
    options.plugins.tooltip.callbacks = {
      title: () => '',
      label: (item) => `${item.raw.y} × ${item.raw.x}: ${fmt(item.raw.v)}`,
    };
    theme.mountChart(
      container,
      {
        type: 'matrix',
        data: {
          datasets: [
            {
              label: data.value_label,
              data: data.cells.map((c) => ({ x: c.x, y: c.y, v: c.value })),
              backgroundColor: (ctx) => {
                const v = ctx.raw?.v;
                if (v == null) return theme.SURFACE_2;
                return theme.alpha(theme.ACCENT, 0.12 + 0.8 * ((v - data.min) / span));
              },
              borderColor: theme.SURFACE,
              borderWidth: 1,
              width: ({ chart }) => (chart.chartArea || {}).width / Math.max(1, data.x_labels.length) - 2,
              height: ({ chart }) => (chart.chartArea || {}).height / Math.max(1, data.y_labels.length) - 2,
            },
          ],
        },
        options,
      },
      { onCapture, height: Math.max(240, Math.min(520, 60 + data.y_labels.length * 42)) },
    );
    note(container, data.value_label, 'hover a cell for its value');
  },

  correlogram(container, data, { onCapture }) {
    if (!theme.hasChartType('matrix')) return missingPlugin(container, 'matrix');
    const options = theme.baseOptions({ xType: 'category' });
    options.scales.x.labels = data.x_labels;
    options.scales.x.offset = true;
    options.scales.x.grid.display = false;
    options.scales.y = { type: 'category', labels: data.y_labels, offset: true, reverse: true, grid: { display: false }, border: { color: theme.BORDER }, ticks: { color: theme.MUTED, font: { family: theme.FONT_SANS, size: 10.5 } } };
    options.plugins.tooltip.callbacks = { title: () => '', label: (item) => `${item.raw.y} vs ${item.raw.x}: r = ${fmt(item.raw.v)}` };
    options.plugins.cellLabels = { fontSize: 10, format: (v) => fmt(v, 2) };
    theme.mountChart(
      container,
      {
        type: 'matrix',
        data: {
          datasets: [
            {
              label: data.value_label,
              data: data.cells.map((c) => ({ x: c.x, y: c.y, v: c.value })),
              // diverging: red for negative, blue for positive, near-white at zero
              backgroundColor: (ctx) => {
                const v = ctx.raw?.v;
                if (v == null) return theme.SURFACE_2;
                return v >= 0 ? theme.alpha(theme.ACCENT, 0.08 + 0.85 * v) : theme.alpha(theme.DANGER, 0.08 + 0.85 * -v);
              },
              borderColor: theme.SURFACE,
              borderWidth: 1,
              width: ({ chart }) => (chart.chartArea || {}).width / Math.max(1, data.x_labels.length) - 2,
              height: ({ chart }) => (chart.chartArea || {}).height / Math.max(1, data.y_labels.length) - 2,
            },
          ],
        },
        options,
        plugins: [cellLabels],
      },
      { onCapture, height: Math.max(260, Math.min(560, 70 + data.y_labels.length * 54)) },
    );
    note(container, `${data.method} correlation · blue positive, red negative`);
  },

  binnedScatter(container, data, { onCapture }) {
    if (!theme.hasChartType('matrix')) return missingPlugin(container, 'matrix');
    const options = theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label });
    options.plugins.tooltip.callbacks = {
      title: () => '',
      label: (item) => `${data.x_label} ${fmt(item.raw.x0, 1)}–${fmt(item.raw.x1, 1)}, ${data.y_label} ${fmt(item.raw.y0, 1)}–${fmt(item.raw.y1, 1)}: ${item.raw.v} row(s)`,
    };
    const xEdges = data.x_edges;
    const yEdges = data.y_edges;
    theme.mountChart(
      container,
      {
        type: 'matrix',
        data: {
          datasets: [
            {
              label: 'count',
              data: data.cells.map((c) => ({ x: c.x, y: c.y, v: c.count, x0: c.x0, x1: c.x1, y0: c.y0, y1: c.y1 })),
              backgroundColor: (ctx) => theme.alpha(theme.ACCENT, 0.15 + 0.8 * ((ctx.raw?.v || 0) / (data.max_count || 1))),
              borderColor: theme.SURFACE,
              borderWidth: 0.5,
              width: ({ chart }) => Math.max(4, (chart.chartArea || {}).width / Math.max(1, xEdges.length - 1) - 1),
              height: ({ chart }) => Math.max(4, (chart.chartArea || {}).height / Math.max(1, yEdges.length - 1) - 1),
            },
          ],
        },
        options,
      },
      { onCapture, height: 320 },
    );
    note(container, `${data.n} rows in ${data.cells.length} occupied bins · darkest cell holds ${data.max_count}`);
  },

  dotplot(container, data, { onCapture }) {
    const options = theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label });
    options.scales.y.min = 0;
    options.scales.y.max = data.max_stack + 1;
    options.scales.y.ticks.stepSize = 1;
    options.plugins.tooltip.callbacks = { label: (item) => `${data.x_label} ≈ ${fmt(item.raw.value)}` };
    theme.mountChart(
      container,
      { type: 'scatter', data: { datasets: [{ label: data.x_label, data: data.points, backgroundColor: theme.ACCENT, pointRadius: 4, pointHoverRadius: 6 }] }, options },
      { onCapture, height: Math.max(220, Math.min(400, 90 + data.max_stack * 14)) },
    );
    note(container, `${data.n} values · one dot per row, stacked within bins of ${fmt(data.bin_width, 3)}`);
  },

  individualValue(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: data.groups.length > 1, yTitle: data.value_label, xTitle: data.group_label });
    options.scales.x = { ...options.scales.x, ...categoryTicks(data.labels) };
    options.plugins.tooltip.callbacks = { label: (item) => `${data.value_label} ${fmt(item.raw.y)}` };
    const datasets = data.groups.map((g, i) => ({
      label: `${g.label} (n=${g.n})`,
      data: g.points,
      backgroundColor: theme.alpha(theme.color(i), 0.7),
      borderColor: theme.color(i),
      pointRadius: 3.4,
    }));
    options.plugins.meanMarkers = { groups: data.groups, color: theme.INK };
    applyReference(options, data, 'y');
    theme.mountChart(container, { type: 'scatter', data: { datasets }, options, plugins: [meanMarkers, refLine] }, { onCapture, height: 300 });
    note(container, 'Points are jittered horizontally so overlapping values stay visible; the bar marks each group mean.' + (data.reference_label ? ` The dashed line is ${data.reference_label}.` : ''));
  },

  // Grubbs / Dixon: every value as one jittered column, with the flagged value drawn in --danger.
  outlierPlot(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, yTitle: data.value_label });
    options.scales.x = { ...options.scales.x, ...categoryTicks(data.labels) };
    options.plugins.tooltip.callbacks = { label: (item) => `${data.value_label} ${fmt(item.raw.y)}` };
    options.plugins.meanMarkers = { groups: data.groups.filter((g) => g.mean !== null && g.mean !== undefined), color: theme.INK };
    const datasets = data.groups.map((group, i) => {
      const flagged = i === data.highlight_dataset;
      return {
        label: flagged ? group.label : `${group.label} (n=${group.n})`,
        data: group.points,
        backgroundColor: flagged ? theme.DANGER : theme.alpha(theme.ACCENT, 0.65),
        borderColor: flagged ? theme.DANGER : theme.ACCENT,
        pointRadius: flagged ? 6 : 3.4,
        pointHoverRadius: flagged ? 8 : 5,
      };
    });
    theme.mountChart(container, { type: 'scatter', data: { datasets }, options, plugins: [meanMarkers] }, { onCapture, height: 300 });
    note(container, 'The larger red point is the most extreme value — the one the test examined. The bar marks the mean of the rest.');
  },

  // Poisson goodness of fit: observed counts against the counts the fitted Poisson predicts.
  observedExpected(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, xType: 'category', xTitle: data.x_label, yTitle: data.y_label });
    const datasets = data.series.map((series, i) => ({
      label: series.label,
      data: series.values,
      backgroundColor: i === 0 ? theme.ACCENT : theme.alpha(theme.MUTED, 0.55),
      borderColor: i === 0 ? theme.ACCENT : theme.MUTED,
      borderWidth: i === 0 ? 0 : 1,
      maxBarThickness: 44,
    }));
    theme.mountChart(container, { type: 'bar', data: { labels: data.labels, datasets }, options }, { onCapture, height: 290 });
    note(container, 'Bars in accent are the observed counts; the grey bars are what a Poisson distribution with the estimated mean predicts.');
  },

  // Mean and median with their confidence intervals — the interval plots at the bottom of a
  // Minitab graphical summary. Same machinery as the Graph menu's Interval Plot, so the two look
  // like the same chart.
  ciIntervals(container, data, { onCapture }) {
    const rows = (data.rows || []).filter((r) => r.Lower !== null && r.Upper !== null);
    if (!rows.length) {
      note(container, 'The confidence intervals could not be computed for this sample.');
      return;
    }
    const labels = rows.map((r) => r.Parameter);
    const groups = rows.map((r, i) => ({ label: r.Parameter, index: i, mean: r.Estimate, ci_low: r.Lower, ci_high: r.Upper }));
    const options = theme.baseOptions({ yTitle: data.value_label });
    options.scales.x = { ...options.scales.x, ...categoryTicks(labels) };
    options.plugins.errorBars = { groups, color: theme.ACCENT };
    fitIntervalAxis(options, groups);
    options.plugins.tooltip.callbacks = {
      label: (item) => {
        const row = rows[item.dataIndex];
        return [`${row.Parameter} ${fmt(row.Estimate)}`, `${Math.round((data.confidence || 0.95) * 100)}% CI ${fmt(row.Lower)} to ${fmt(row.Upper)}`];
      },
    };
    theme.mountChart(
      container,
      {
        type: 'scatter',
        data: { datasets: [{ label: 'estimate', data: groups.map((g) => ({ x: g.index, y: g.mean })), backgroundColor: theme.ACCENT, borderColor: theme.ACCENT, pointRadius: 5 }] },
        options,
        plugins: [errorBars],
      },
      { onCapture, height: 210 },
    );
    note(container, `Each point is the estimate; the whiskers are its ${Math.round((data.confidence || 0.95) * 100)}% confidence interval.`);
  },

  interval(container, data, { onCapture }) {
    const options = theme.baseOptions({ yTitle: data.value_label, xTitle: data.group_label });
    options.scales.x = { ...options.scales.x, ...categoryTicks(data.labels) };
    options.plugins.errorBars = { groups: data.groups, color: theme.ACCENT };
    fitIntervalAxis(options, data.groups);
    options.plugins.tooltip.callbacks = {
      label: (item) => {
        const g = data.groups[item.dataIndex];
        return [`mean ${fmt(g.mean)}`, `${Math.round(data.confidence * 100)}% CI ${fmt(g.ci_low)} to ${fmt(g.ci_high)}`, `n=${g.n}`];
      },
    };
    theme.mountChart(
      container,
      {
        type: 'scatter',
        data: { datasets: [{ label: 'mean', data: data.groups.map((g) => ({ x: g.index, y: g.mean })), backgroundColor: theme.ACCENT, borderColor: theme.ACCENT, pointRadius: 5 }] },
        options,
        plugins: [errorBars],
      },
      { onCapture, height: 300 },
    );
    note(container, `Each point is a group mean; whiskers are the ${Math.round(data.confidence * 100)}% confidence interval for that mean.`);
  },

  // One small panel per factor: the response mean at each level, with the grand mean as a
  // reference line. Flat panel = that factor does nothing. Shared by the Graph menu's Main Effects
  // Plot and the GLM's Factorial Plots — the only difference is whether the means are raw or fitted.
  mainEffects(container, data, { onCapture }) {
    const panels = data.panels || [];
    if (!panels.length) {
      note(container, 'No factor levels to plot.');
      return;
    }
    // A shared y-axis across the panels is the whole point: it is what makes one factor's effect
    // visibly bigger than another's rather than every panel filling its own box.
    const all = panels.flatMap((p) => p.points.map((q) => q.y)).filter((v) => Number.isFinite(v));
    all.push(data.grand_mean);
    const low = Math.min(...all);
    const high = Math.max(...all);
    const pad = (high - low) * 0.15 || Math.abs(high) * 0.05 || 1;

    const grid = el('div', { class: 'model-grid model-grid-2' });
    container.appendChild(grid);
    const canvases = [];
    for (const panel of panels) {
      const cell = el('div', { class: 'model-panel' });
      cell.appendChild(el('p', { class: 'model-panel-title', text: panel.factor }));
      grid.appendChild(cell);
      const options = theme.baseOptions({ yTitle: data.value_label, xTitle: panel.factor });
      options.scales.x = { ...options.scales.x, ...categoryTicks(panel.labels) };
      options.scales.y.min = low - pad;
      options.scales.y.max = high + pad;
      options.plugins.refLine = { value: data.grand_mean, axis: 'y', color: theme.MUTED, label: 'overall mean' };
      options.plugins.tooltip.callbacks = {
        label: (item) => {
          const point = panel.points[item.dataIndex];
          return [`${point.label}: ${fmt(point.y)}`, point.n === null || point.n === undefined ? '' : `n=${point.n}`].filter(Boolean);
        },
      };
      const chart = theme.mountChart(
        cell,
        {
          type: 'line',
          data: {
            datasets: [
              {
                label: panel.factor,
                data: panel.points.map((p) => ({ x: p.x, y: p.y })),
                borderColor: theme.ACCENT,
                backgroundColor: theme.ACCENT,
                pointRadius: 4,
                borderWidth: 2,
                tension: 0,
              },
            ],
          },
          options,
          plugins: [refLine],
        },
        { height: 220 },
      );
      if (chart) canvases.push(chart.canvas);
    }
    captureGrid(grid, onCapture);
    note(
      container,
      `${data.fitted ? 'Fitted (least-squares) means' : 'Raw means'} of ${data.value_label}; the dashed line is the overall mean. ` +
        'All panels share one y-axis, so a steeper panel is a bigger effect.',
    );
  },

  // One panel per pair of factors, one line per level of the second. Parallel lines mean the
  // factors act independently; crossing lines are the interaction.
  interactionPlot(container, data, { onCapture }) {
    const panels = data.panels || [];
    if (!panels.length) {
      note(container, 'An interaction plot needs at least two factors.');
      return;
    }
    const all = panels.flatMap((p) => p.series.flatMap((s) => s.points.map((q) => q.y))).filter((v) => Number.isFinite(v));
    const low = Math.min(...all);
    const high = Math.max(...all);
    const pad = (high - low) * 0.15 || Math.abs(high) * 0.05 || 1;

    const grid = el('div', { class: 'model-grid model-grid-2' });
    container.appendChild(grid);
    const canvases = [];
    for (const panel of panels) {
      const cell = el('div', { class: 'model-panel' });
      cell.appendChild(el('p', { class: 'model-panel-title', text: `${panel.x_factor} × ${panel.trace_factor}` }));
      grid.appendChild(cell);
      const options = theme.baseOptions({ legend: true, yTitle: data.value_label, xTitle: panel.x_factor });
      options.scales.x = { ...options.scales.x, ...categoryTicks(panel.labels) };
      options.scales.y.min = low - pad;
      options.scales.y.max = high + pad;
      const chart = theme.mountChart(
        cell,
        {
          type: 'line',
          data: {
            datasets: panel.series.map((series, i) => ({
              label: series.label,
              // A cell with no data is a null y, which Chart.js draws as a gap rather than a zero.
              data: series.points.map((p) => ({ x: p.x, y: p.y })),
              borderColor: theme.color(i),
              backgroundColor: theme.color(i),
              pointRadius: 4,
              borderWidth: 2,
              tension: 0,
              spanGaps: false,
            })),
          },
          options,
        },
        { height: 240 },
      );
      if (chart) canvases.push(chart.canvas);
    }
    captureGrid(grid, onCapture);
    note(container, `${data.fitted ? 'Fitted (least-squares) means' : 'Raw means'} — parallel lines mean no interaction; lines that cross or diverge are the interaction.`);
  },

  // The bootstrap / randomization distribution, with the observed value marked on it. Reading the
  // observed value against the spread of resamples IS the test, so the marks are the point of the
  // chart rather than decoration.
  resampleHistogram(container, data, { onCapture }) {
    const bins = data.bins || [];
    if (!bins.length) {
      note(container, 'No resampled values to draw.');
      return;
    }
    const options = theme.baseOptions({ xTitle: data.value_label || 'resampled statistic', yTitle: 'count' });
    // A histogram's x axis is categorical, so a mark at an arbitrary value has to be located
    // inside its bin — which is exactly what the refLine plugin's `bins` mode does.
    const marks = (data.marks || []).filter((m) => Number.isFinite(m.value));
    if (marks.length) {
      options.plugins.refLine = { value: marks[0].value, axis: 'x', bins, color: theme.DANGER, label: marks[0].label };
      if (marks[1]) options.plugins.refLineSecond = { value: marks[1].value, axis: 'x', bins, color: theme.MUTED, label: marks[1].label };
    }
    options.plugins.tooltip.callbacks = {
      title: (items) => `${fmt(bins[items[0].dataIndex].x0)} to ${fmt(bins[items[0].dataIndex].x1)}`,
      label: (item) => `${item.raw} resample(s)`,
    };
    const opts = { ...options, scales: { ...options.scales, x: { ...options.scales.x, type: 'category' } } };
    theme.mountChart(
      container,
      {
        type: 'bar',
        data: { labels: bins.map((b) => fmt(b.center, 2)), datasets: [{ data: bins.map((b) => b.count), backgroundColor: theme.alpha(theme.ACCENT, 0.75), borderColor: theme.ACCENT, borderWidth: 0, barPercentage: 1, categoryPercentage: 1 }] },
        options: opts,
        // The second mark needs its own plugin instance, since one plugin id carries one option set.
        plugins: [refLine, { ...refLine, id: 'refLineSecond' }],
      },
      { onCapture, height: 300 },
    );
    const described = marks.map((m) => `${m.label} ${fmt(m.value, 4)}`).join(' · ');
    note(container, `${data.n} resamples in ${bins.length} bins${described ? `. Marked: ${described}.` : '.'}`);
  },

  // Pairwise differences with their confidence intervals, zero marked. An interval clear of zero
  // is a difference the comparison method called significant.
  differenceIntervals(container, data, { onCapture }) {
    const rows = data.rows || [];
    if (!rows.length) {
      note(container, 'No pairwise differences to draw.');
      return;
    }
    const groups = rows.map((r, i) => ({ label: r.label, index: i, mean: r.difference, ci_low: r.low, ci_high: r.high }));
    const options = theme.baseOptions({ yTitle: data.value_label });
    options.scales.x = { ...options.scales.x, ...categoryTicks(rows.map((r) => r.label)) };
    options.plugins.errorBars = { groups, color: theme.MUTED };
    fitIntervalAxis(options, groups);
    if (options.scales.y.min > 0) options.scales.y.min = 0; // zero has to be on the chart to be read against
    if (options.scales.y.max < 0) options.scales.y.max = 0;
    options.plugins.refLine = { value: 0, axis: 'y', color: theme.DANGER, label: 'no difference' };
    options.plugins.tooltip.callbacks = {
      label: (item) => {
        const row = rows[item.dataIndex];
        return [`${row.label}: ${fmt(row.difference)}`, `${Math.round((data.confidence || 0.95) * 100)}% CI ${fmt(row.low)} to ${fmt(row.high)}`, row.significant ? 'significant' : 'not significant'];
      },
    };
    theme.mountChart(
      container,
      {
        type: 'scatter',
        data: {
          datasets: [
            {
              label: 'difference',
              data: groups.map((g) => ({ x: g.index, y: g.mean })),
              backgroundColor: rows.map((r) => (r.significant ? theme.ACCENT : theme.alpha(theme.MUTED, 0.7))),
              borderColor: rows.map((r) => (r.significant ? theme.ACCENT : theme.MUTED)),
              pointRadius: 5,
            },
          ],
        },
        options,
        plugins: [errorBars, refLine],
      },
      { onCapture, height: Math.max(240, Math.min(420, 120 + rows.length * 26)) },
    );
    note(container, 'An interval that does not cross the red line is a significant difference. Grey intervals cross it.');
  },

  // ANOM: group means against a centre line, between decision limits. A point outside the limits
  // is a level whose mean differs from the overall mean — the chart IS the test.
  anomChart(container, data, { onCapture }) {
    const groups = data.groups || [];
    const options = theme.baseOptions({ yTitle: data.value_label, xTitle: data.group_label });
    options.scales.x = { ...options.scales.x, ...categoryTicks(data.labels) };
    const all = groups.flatMap((g) => [g.mean, g.udl, g.ldl]).filter((v) => Number.isFinite(v));
    const low = Math.min(...all);
    const high = Math.max(...all);
    const pad = (high - low) * 0.15 || 1;
    options.scales.y.min = low - pad;
    options.scales.y.max = high + pad;
    options.plugins.refLine = { value: data.center, axis: 'y', color: theme.MUTED, label: 'centre line' };
    options.plugins.tooltip.callbacks = {
      label: (item) => {
        const g = groups[item.dataIndex];
        return [`mean ${fmt(g.mean)}`, `limits ${fmt(g.ldl)} to ${fmt(g.udl)}`, `n=${g.n}`, g.outside ? 'outside the decision limits' : 'inside the limits'];
      },
    };
    theme.mountChart(
      container,
      {
        type: 'line',
        data: {
          datasets: [
            {
              label: 'upper decision limit',
              data: groups.map((g) => ({ x: g.index, y: g.udl })),
              borderColor: theme.DANGER,
              borderWidth: 1.5,
              borderDash: [5, 4],
              pointRadius: 0,
              tension: 0,
            },
            {
              label: 'lower decision limit',
              data: groups.map((g) => ({ x: g.index, y: g.ldl })),
              borderColor: theme.DANGER,
              borderWidth: 1.5,
              borderDash: [5, 4],
              pointRadius: 0,
              tension: 0,
            },
            {
              label: 'group mean',
              data: groups.map((g) => ({ x: g.index, y: g.mean })),
              borderColor: theme.ACCENT,
              backgroundColor: groups.map((g) => (g.outside ? theme.DANGER : theme.ACCENT)),
              pointBackgroundColor: groups.map((g) => (g.outside ? theme.DANGER : theme.ACCENT)),
              pointRadius: groups.map((g) => (g.outside ? 6.5 : 4.5)),
              borderWidth: 2,
              tension: 0,
            },
          ],
        },
        options: { ...options, plugins: { ...options.plugins, legend: { display: true, labels: { color: theme.MUTED, boxWidth: 10 } } } },
        plugins: [refLine],
      },
      { onCapture, height: 320 },
    );
    note(container, `Centre line is the overall mean. A point beyond a dashed limit is a level whose mean differs from it at α = ${fmt(data.alpha, 3)}.`);
  },

  // Response Optimizer: one panel per predictor, showing what happens to the fitted response (and
  // its desirability) as that predictor moves with the others held at the optimum.
  desirabilityProfile(container, data, { onCapture }) {
    const panels = data.panels || [];
    if (!panels.length) {
      note(container, 'Nothing to profile.');
      return;
    }
    const grid = el('div', { class: 'model-grid model-grid-2' });
    container.appendChild(grid);
    const canvases = [];
    for (const panel of panels) {
      const cell = el('div', { class: 'model-panel' });
      // A factor's optimum is a level name, not a number — fmt() would turn "M2" into NaN.
      const best = typeof panel.optimum === 'number' ? fmt(panel.optimum, 4) : String(panel.optimum ?? '');
      cell.appendChild(el('p', { class: 'model-panel-title', text: `${panel.predictor} — optimum ${best}` }));
      grid.appendChild(cell);
      const options = theme.baseOptions({ legend: true, yTitle: data.response, xTitle: panel.predictor });
      if (!panel.continuous) options.scales.x = { ...options.scales.x, ...categoryTicks(panel.labels || []) };
      // Desirability rides on its own 0–1 axis on the right; the response keeps the left one.
      options.scales.d = { type: 'linear', position: 'right', min: 0, max: 1, grid: { drawOnChartArea: false }, ticks: { color: theme.MUTED, font: { family: theme.FONT_MONO, size: 10 } }, title: { display: true, text: 'desirability', color: theme.MUTED, font: { family: theme.FONT_SANS, size: 10 } } };
      if (panel.continuous) options.plugins.refLine = { value: panel.optimum, axis: 'x', color: theme.SUCCESS, label: 'optimum' };
      const chart = theme.mountChart(
        cell,
        {
          type: 'line',
          data: {
            datasets: [
              {
                label: `fitted ${data.response}`,
                data: panel.points.map((p) => ({ x: p.x, y: p.y })),
                borderColor: theme.ACCENT,
                backgroundColor: theme.ACCENT,
                pointRadius: panel.continuous ? 0 : 4,
                borderWidth: 2,
                tension: 0,
              },
              {
                label: 'desirability',
                yAxisID: 'd',
                data: panel.points.map((p) => ({ x: p.x, y: p.d })),
                borderColor: theme.SUCCESS,
                backgroundColor: theme.SUCCESS,
                pointRadius: panel.continuous ? 0 : 4,
                borderWidth: 1.5,
                borderDash: [4, 3],
                tension: 0,
              },
            ],
          },
          options,
          plugins: [refLine],
        },
        { height: 230 },
      );
      if (chart) canvases.push(chart.canvas);
    }
    captureGrid(grid, onCapture);
    note(container, `Each panel moves one predictor with the others held at the optimum. Overall desirability at the optimum: ${fmt(data.desirability, 4)}.`);
  },

  ecdf(container, data, { onCapture }) {
    const datasets = data.series.map((s, i) => ({
      label: `${s.label} (n=${s.n})`,
      data: s.points,
      borderColor: theme.color(i),
      backgroundColor: theme.alpha(theme.color(i), 0.1),
      stepped: 'after',
      pointRadius: 0,
      borderWidth: 1.8,
    }));
    const options = theme.baseOptions({ legend: datasets.length > 1, xTitle: data.x_label, yTitle: data.y_label });
    options.scales.y.min = 0;
    options.scales.y.max = 1;
    theme.mountChart(container, { type: 'line', data: { datasets }, options }, { onCapture, height: 290 });
  },

  probability(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label });
    const bandStyle = (label, points) => ({
      label,
      data: points,
      borderColor: theme.alpha(theme.MUTED, 0.75),
      borderWidth: 1.2,
      borderDash: [3, 3],
      pointRadius: 0,
      showLine: true,
    });
    const datasets = [
      { label: 'sample', data: data.points, backgroundColor: theme.alpha(theme.ACCENT, 0.8), borderColor: theme.ACCENT, pointRadius: 3.2 },
      { label: 'normal reference', data: data.line, borderColor: theme.DANGER, borderWidth: 1.6, borderDash: [5, 4], pointRadius: 0, showLine: true },
    ];
    // The Normality Test supplies pointwise confidence bands; the plain Graph menu item does not.
    if (Array.isArray(data.band_lower) && data.band_lower.length) {
      const pct = Math.round((data.confidence || 0.95) * 100);
      datasets.push(bandStyle(`${pct}% CI`, data.band_lower));
      datasets.push({ ...bandStyle(`${pct}% CI upper`, data.band_upper), label: '' });
      options.plugins.legend.labels = { ...(options.plugins.legend.labels || {}), filter: (item) => !!item.text };
    }
    theme.mountChart(container, { type: 'scatter', data: { datasets }, options }, { onCapture, height: 300 });
    const bits = [`n=${data.n}`, `R² of fit ${fmt(data.r_squared)}`];
    if (data.shapiro_p != null) bits.push(`Shapiro-Wilk p = ${data.shapiro_p < 0.001 ? data.shapiro_p.toExponential(2) : fmt(data.shapiro_p)}`);
    note(container, `${bits.join(' · ')} — points close to the dashed line indicate an approximately normal sample.`);
  },

  distribution(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label });
    const datasets = [];
    if (data.discrete) {
      datasets.push({ label: data.label, data: data.points.map((p) => p.y), backgroundColor: theme.ACCENT, maxBarThickness: 26 });
      if (data.shaded) {
        const inRange = new Set(data.shaded.points.map((p) => p.x));
        datasets[0].backgroundColor = data.points.map((p) => (inRange.has(p.x) ? theme.DANGER : theme.ACCENT));
      }
      const opts = { ...options, scales: { ...options.scales, x: { ...options.scales.x, type: 'category' } } };
      theme.mountChart(container, { type: 'bar', data: { labels: data.points.map((p) => p.x), datasets }, options: opts }, { onCapture, height: 300 });
    } else {
      if (data.shaded) {
        datasets.push({
          label: `P(${fmt(data.shaded.from, 2)} ≤ x ≤ ${fmt(data.shaded.to, 2)}) = ${fmt(data.shaded.probability, 4)}`,
          data: data.shaded.points,
          borderColor: 'transparent',
          backgroundColor: theme.alpha(theme.DANGER, 0.28),
          fill: 'origin',
          pointRadius: 0,
        });
      }
      datasets.push({ label: data.label, data: data.points, borderColor: theme.ACCENT, borderWidth: 2, pointRadius: 0, tension: 0.1 });
      theme.mountChart(container, { type: 'line', data: { datasets }, options }, { onCapture, height: 300 });
    }
    const bits = [data.label, `mean ${fmt(data.mean)}`, `sd ${fmt(data.sd)}`];
    if (data.shaded) bits.push(`shaded probability ${fmt(data.shaded.probability, 4)}`);
    note(container, bits.join(' · '));
  },

  stemLeaf(container, data) {
    // Text output, not a canvas — exactly how Minitab presents this one.
    container.appendChild(el('pre', { class: 'stem-leaf', text: data.text }));
    note(container, `${data.n} values · ${data.stems} stems · leaf unit ${fmt(data.leaf_unit)}`);
  },

  matrixPlot(container, data, { onCapture }) {
    const size = data.columns.length;
    const grid = el('div', { class: 'model-grid model-grid-2' });
    grid.style.gridTemplateColumns = `repeat(${size}, minmax(0, 1fr))`;
    container.appendChild(grid);

    const canvases = [];
    for (const panel of data.panels) {
      const cell = el('div', { class: 'model-panel' });
      grid.appendChild(cell);
      if (panel.diagonal) {
        cell.appendChild(el('div', { class: 'panel-diagonal', text: panel.x_col }));
        continue;
      }
      const options = theme.baseOptions({});
      options.scales.x.ticks.font = { family: theme.FONT_MONO, size: 8.5 };
      options.scales.y.ticks.font = { family: theme.FONT_MONO, size: 8.5 };
      options.scales.x.ticks.maxTicksLimit = 4;
      options.scales.y.ticks.maxTicksLimit = 4;
      options.plugins.tooltip.callbacks = { label: (item) => `${panel.x_col} ${fmt(item.raw.x)}, ${panel.y_col} ${fmt(item.raw.y)}` };
      const chart = theme.mountChart(
        cell,
        { type: 'scatter', data: { datasets: [{ data: panel.points, backgroundColor: theme.alpha(theme.ACCENT, 0.55), pointRadius: 2 }] }, options },
        { height: 150 },
      );
      if (chart) canvases.push(chart.canvas);
    }
    captureGrid(grid, onCapture);
    note(container, `Every pair of ${data.columns.join(', ')} · ${data.n} rows${data.truncated_columns ? ` · ${data.truncated_columns} extra column(s) omitted (5 max)` : ''}`);
  },

  marginal(container, data, { onCapture }) {
    const layout = el('div', { class: 'marginal-layout' });
    const topCell = el('div', { class: 'marginal-top' });
    const mainCell = el('div', { class: 'marginal-main' });
    const sideCell = el('div', { class: 'marginal-side' });
    const corner = el('div', { class: 'marginal-corner' });
    layout.append(topCell, corner, mainCell, sideCell);
    container.appendChild(layout);

    const bare = () => {
      const o = theme.baseOptions({});
      o.scales.x.ticks.display = false;
      o.scales.y.ticks.display = false;
      o.scales.x.title.display = false;
      o.scales.y.title.display = false;
      return o;
    };

    // The marginals are laid out against the scatter's plot area (alignMarginal), so `mainChart` is
    // read lazily through a getter: the top histogram is built first, and the scatter it aligns to
    // does not exist yet.
    let mainChart = null;
    const topOptions = bare();
    topOptions.scales.x.type = 'category';
    topOptions.layout = { padding: { top: 0, right: 0, bottom: 0, left: 0 } };
    topOptions.plugins.alignMarginal = { axis: 'x', main: () => mainChart };
    const topChart = theme.mountChart(
      topCell,
      {
        type: 'bar',
        data: { labels: data.x_hist.bins.map((b) => fmt(b.center, 1)), datasets: [{ data: data.x_hist.bins.map((b) => b.count), backgroundColor: theme.alpha(theme.ACCENT, 0.55), barPercentage: 1, categoryPercentage: 1 }] },
        options: topOptions,
        plugins: [alignMarginal],
      },
      { height: 74 },
    );

    mainChart = theme.mountChart(
      mainCell,
      {
        type: 'scatter',
        data: { datasets: [{ data: data.points, backgroundColor: theme.alpha(theme.ACCENT, 0.7), borderColor: theme.ACCENT, pointRadius: 3 }] },
        options: theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label }),
      },
      { height: 250 },
    );

    const sideOptions = bare();
    sideOptions.indexAxis = 'y';
    sideOptions.scales.y.type = 'category';
    sideOptions.layout = { padding: { top: 0, right: 0, bottom: 0, left: 0 } };
    sideOptions.plugins.alignMarginal = { axis: 'y', main: () => mainChart };
    const sideChart = theme.mountChart(
      sideCell,
      {
        type: 'bar',
        data: { labels: data.y_hist.bins.map((b) => fmt(b.center, 1)), datasets: [{ data: data.y_hist.bins.map((b) => b.count), backgroundColor: theme.alpha(theme.ACCENT, 0.55), barPercentage: 1, categoryPercentage: 1 }] },
        options: sideOptions,
        plugins: [alignMarginal],
      },
      { height: 250 },
    );

    // The scatter lays out after both marginals were first drawn, so they are nudged once it exists —
    // alignMarginal reads its plot area in beforeLayout and has nothing to read before then.
    theme.afterLayout(() => {
      for (const chart of [topChart, sideChart]) {
        if (!chart) continue;
        try {
          chart.update('none');
        } catch {
          /* a chart torn down before the nudge simply keeps its own padding */
        }
      }
    });

    // one composite PNG: scatter with its two marginal histograms
    captureGrid(layout, onCapture);
    note(container, `${data.n} points with the marginal distribution of ${data.x_label} above and ${data.y_label} at the side`);
  },

  parallelCoords(container, data, { onCapture }) {
    const labels = data.axes.map((a) => a.name);
    const groups = [...new Set(data.rows.map((r) => r.group).filter((g) => g !== null && g !== undefined))];
    const datasets = data.rows.map((row) => {
      const groupIndex = row.group == null ? 0 : groups.indexOf(row.group);
      return {
        label: row.group == null ? '' : String(row.group),
        data: row.values,
        borderColor: theme.alpha(theme.color(groupIndex), data.rows.length > 120 ? 0.28 : 0.6),
        borderWidth: 1,
        pointRadius: 0,
        tension: 0,
        raw: row.raw,
      };
    });
    const options = theme.baseOptions({ xType: 'category' });
    options.scales.y.min = 0;
    options.scales.y.max = 1;
    options.scales.y.ticks.callback = (v) => (v === 0 ? 'min' : v === 1 ? 'max' : '');
    options.plugins.tooltip.callbacks = {
      title: (items) => labels[items[0].dataIndex],
      label: (item) => {
        const raw = item.dataset.raw?.[item.dataIndex];
        const suffix = item.dataset.label ? ` · ${item.dataset.label}` : '';
        return `${fmt(raw)}${suffix}`;
      },
    };
    if (data.rows.length > 120) options.animation = { duration: 0 }; // hundreds of lines: draw at once
    theme.mountChart(container, { type: 'line', data: { labels, datasets }, options }, { onCapture, height: 320 });

    const axisNote = data.axes.map((a) => `${a.name} [${fmt(a.min, 1)}–${fmt(a.max, 1)}]`).join(' · ');
    note(container, `Each column scaled 0–1. ${axisNote}`);
    if (data.truncated) note(container, `Showing the first ${data.n_drawn} of ${data.n_total} rows (capped at ${data.row_cap} to stay readable).`);
  },

  // ---- plotly (lazy-loaded) ------------------------------------------------
  async contour(container, data, { onCapture }) {
    const plotly = await loadPlotly(container);
    if (!plotly) return;
    const div = el('div', { class: 'plotly-wrap' });
    container.appendChild(div);
    await plotly.newPlot(
      div,
      [{ type: 'contour', x: data.x, y: data.y, z: data.z, colorscale: plotlyScale(), contours: { showlabels: true, labelfont: { family: theme.FONT_MONO, size: 10, color: theme.INK } }, colorbar: colorbar(data.z_label) }],
      plotlyLayout({ xTitle: data.x_label, yTitle: data.y_label }),
      plotlyConfig(),
    );
    trackPlot(div, { layout: () => plotlyLayout({ xTitle: data.x_label, yTitle: data.y_label }), restyle: () => ({ colorscale: [plotlyScale()] }) });
    capturePlotly(plotly, div, onCapture);
    note(container, `${data.n} readings interpolated onto a ${data.x.length}×${data.y.length} grid`);
  },

  async scatter3d(container, data, { onCapture }) {
    const plotly = await loadPlotly(container);
    if (!plotly) return;
    const div = el('div', { class: 'plotly-wrap' });
    container.appendChild(div);
    const traces = data.series.map((s, i) => ({
      type: 'scatter3d',
      mode: 'markers',
      name: s.label,
      x: s.x,
      y: s.y,
      z: s.z,
      marker: { size: 3.5, color: theme.color(i), opacity: 0.85 },
    }));
    await plotly.newPlot(div, traces, plotlyLayout({ scene: { xTitle: data.x_label, yTitle: data.y_label, zTitle: data.z_label }, legend: traces.length > 1 }), plotlyConfig());
    // Only the layout is re-themed on a theme switch: the marker colours come from the palette,
    // which is re-read by plotlyLayout's caller on the next draw, and relayout preserves the
    // camera the user rotated to.
    trackPlot(div, { layout: () => plotlyLayout({ scene: { xTitle: data.x_label, yTitle: data.y_label, zTitle: data.z_label }, legend: traces.length > 1 }), restyle: () => ({ 'marker.color': data.series.map((_, i) => theme.color(i)) }) });
    capturePlotly(plotly, div, onCapture);
    note(container, `${data.n} points${data.group_label ? ` colored by ${data.group_label}` : ''}`, 'drag to rotate');
  },

  async surface(container, data, { onCapture }) {
    const plotly = await loadPlotly(container);
    if (!plotly) return;
    const div = el('div', { class: 'plotly-wrap' });
    container.appendChild(div);
    await plotly.newPlot(
      div,
      [{ type: 'surface', x: data.x, y: data.y, z: data.z, colorscale: plotlyScale(), colorbar: colorbar(data.z_label) }],
      plotlyLayout({ scene: { xTitle: data.x_label, yTitle: data.y_label, zTitle: data.z_label } }),
      plotlyConfig(),
    );
    trackPlot(div, {
      layout: () => plotlyLayout({ scene: { xTitle: data.x_label, yTitle: data.y_label, zTitle: data.z_label } }),
      restyle: () => ({ colorscale: [plotlyScale()] }),
    });
    capturePlotly(plotly, div, onCapture);
    note(container, `${data.n} readings interpolated onto a ${data.x.length}×${data.y.length} surface grid`, 'drag to rotate');
  },
};

function plotlyScale() {
  return [
    [0, theme.SURFACE],
    [0.5, theme.alpha(theme.ACCENT, 0.55)],
    [1, theme.ACCENT],
  ];
}

function colorbar(title) {
  return { title: { text: title, font: { family: theme.FONT_SANS, size: 11, color: theme.MUTED } }, tickfont: { family: theme.FONT_MONO, size: 10, color: theme.MUTED }, outlinewidth: 0, thickness: 12 };
}

function capturePlotly(plotly, div, onCapture) {
  if (!onCapture) return;
  setTimeout(() => {
    plotly
      .toImage(div, { format: 'png', width: 900, height: 560 })
      .then(onCapture)
      .catch(() => {
        /* export just won't include this figure */
      });
  }, 400);
}
