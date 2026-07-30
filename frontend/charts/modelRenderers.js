// Renderers for the Stat > Regression output: fitted line plots with confidence and prediction
// bands, the four-in-one residual panel, ROC curves, PLS loading plots and stability plots.
//
// A separate registry from renderers.js (which serves the Graph menu) so neither file grows without
// limit; procedureDialog.js looks in both.

import * as theme from './theme.js';

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

function note(container, text) {
  container.appendChild(el('p', { class: 'chart-note', text }));
}

const fmt = (v, digits = 3) => (v === null || v === undefined ? '' : Number.isInteger(v) ? String(v) : Number(v).toFixed(digits));

// A boxed caption of the model's fit statistics, drawn in the plot's top-right the way Minitab
// prints S / R-sq / R-sq(adj) inside a fitted line plot.
const statBox = {
  id: 'statBox',
  afterDatasetsDraw(chart, _args, opts) {
    const lines = (opts && opts.lines) || [];
    if (!lines.length) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.font = `500 10.5px ${theme.FONT_MONO}`;
    const width = Math.max(...lines.map((line) => ctx.measureText(line).width)) + 14;
    const height = lines.length * 14 + 10;
    const x = chartArea.right - width - 8;
    const y = chartArea.top + 8;
    ctx.fillStyle = theme.surfaceWash(0.92);
    ctx.strokeStyle = theme.BORDER;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.rect(x, y, width, height);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = theme.INK;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    lines.forEach((line, i) => ctx.fillText(line, x + 7, y + 6 + i * 14));
    ctx.restore();
  },
};

// A horizontal reference line at a given y (the spec limit on a stability plot).
const specLine = {
  id: 'specLine',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || opts.value === null || opts.value === undefined) return;
    const { ctx, chartArea } = chart;
    const y = chart.scales.y.getPixelForValue(opts.value);
    if (!Number.isFinite(y) || y < chartArea.top || y > chartArea.bottom) return;
    ctx.save();
    ctx.strokeStyle = opts.color || theme.DANGER;
    ctx.lineWidth = 1.6;
    ctx.setLineDash([7, 4]);
    ctx.beginPath();
    ctx.moveTo(chartArea.left, y);
    ctx.lineTo(chartArea.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
    if (opts.label) {
      ctx.font = `500 10px ${theme.FONT_SANS}`;
      const width = ctx.measureText(opts.label).width;
      ctx.fillStyle = theme.surfaceWash(0.9);
      ctx.fillRect(chartArea.left + 4, y - 14, width + 4, 13);
      ctx.fillStyle = opts.color || theme.DANGER;
      ctx.textBaseline = 'bottom';
      ctx.textAlign = 'left';
      ctx.fillText(opts.label, chartArea.left + 6, y - 2);
    }
    ctx.restore();
  },
};

// A vertical marker at a given x (the estimated shelf life).
const shelfMarker = {
  id: 'shelfMarker',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || opts.value === null || opts.value === undefined) return;
    const { ctx, chartArea } = chart;
    const x = chart.scales.x.getPixelForValue(opts.value);
    if (!Number.isFinite(x) || x < chartArea.left || x > chartArea.right) return;
    ctx.save();
    ctx.strokeStyle = opts.color || theme.INK;
    ctx.lineWidth = 1.3;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    if (opts.label) {
      ctx.font = `500 10px ${theme.FONT_SANS}`;
      const width = ctx.measureText(opts.label).width;
      const left = Math.min(x + 4, chartArea.right - width - 6);
      ctx.fillStyle = theme.surfaceWash(0.9);
      ctx.fillRect(left - 2, chartArea.bottom - 15, width + 4, 13);
      ctx.fillStyle = opts.color || theme.INK;
      ctx.textBaseline = 'bottom';
      ctx.textAlign = 'left';
      ctx.fillText(opts.label, left, chartArea.bottom - 3);
    }
    ctx.restore();
  },
};

// Point labels for the PLS loading plot.
const pointLabels = {
  id: 'pointLabels',
  afterDatasetsDraw(chart, _args, opts) {
    const labels = (opts && opts.labels) || [];
    if (!labels.length) return;
    const { ctx } = chart;
    const meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.font = `500 10px ${theme.FONT_SANS}`;
    ctx.fillStyle = theme.INK;
    ctx.textBaseline = 'bottom';
    ctx.textAlign = 'left';
    meta.data.forEach((element, index) => {
      if (labels[index] === undefined) return;
      ctx.fillText(String(labels[index]), element.x + 6, element.y - 3);
    });
    ctx.restore();
  },
};

// A zero line for residual panels: a residual plot without one is much harder to read.
const zeroLine = {
  id: 'zeroLine',
  beforeDatasetsDraw(chart, _args, opts) {
    if (opts === false) return;
    const { ctx, chartArea } = chart;
    const y = chart.scales.y.getPixelForValue(0);
    if (!Number.isFinite(y) || y < chartArea.top || y > chartArea.bottom) return;
    ctx.save();
    ctx.strokeStyle = theme.MUTED;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(chartArea.left, y);
    ctx.lineTo(chartArea.right, y);
    ctx.stroke();
    ctx.restore();
  },
};

// ---------------------------------------------------------------------------
// small panel helpers, for the multi-chart layouts
// ---------------------------------------------------------------------------

function panelOptions({ xTitle, yTitle, xType = 'linear' } = {}) {
  const options = theme.baseOptions({ xTitle, yTitle, xType });
  options.scales.x.ticks.font = { family: theme.FONT_MONO, size: 9 };
  options.scales.y.ticks.font = { family: theme.FONT_MONO, size: 9 };
  options.scales.x.ticks.maxTicksLimit = 6;
  options.scales.y.ticks.maxTicksLimit = 6;
  options.scales.x.title.font = { family: theme.FONT_SANS, size: 9.5 };
  options.scales.y.title.font = { family: theme.FONT_SANS, size: 9.5 };
  return options;
}

function panel(grid, title) {
  const cell = el('div', { class: 'model-panel' });
  cell.appendChild(el('p', { class: 'model-panel-title', text: title }));
  grid.appendChild(cell);
  return cell;
}

function scatterPanel(cell, points, { xTitle, yTitle, height = 190, showLine = false }) {
  const options = panelOptions({ xTitle, yTitle });
  options.plugins.tooltip.callbacks = { label: (item) => `${fmt(item.raw.x, 3)}, ${fmt(item.raw.y, 3)}` };
  return theme.mountChart(
    cell,
    {
      type: 'scatter',
      data: {
        datasets: [
          {
            data: points,
            backgroundColor: theme.alpha(theme.ACCENT, 0.7),
            borderColor: theme.ACCENT,
            pointRadius: 2.8,
            showLine,
            borderWidth: showLine ? 1.2 : 0,
          },
        ],
      },
      options,
      plugins: [zeroLine],
    },
    { height },
  );
}

function probabilityPanel(cell, data, { height = 190 }) {
  const options = panelOptions({ xTitle: data.x_label, yTitle: data.y_label });
  return theme.mountChart(
    cell,
    {
      type: 'scatter',
      data: {
        datasets: [
          { data: data.points, backgroundColor: theme.alpha(theme.ACCENT, 0.75), borderColor: theme.ACCENT, pointRadius: 2.8 },
          { data: data.line, borderColor: theme.DANGER, borderWidth: 1.4, borderDash: [5, 4], pointRadius: 0, showLine: true },
        ],
      },
      options,
    },
    { height },
  );
}

function histogramPanel(cell, histogram, { height = 190 }) {
  const options = panelOptions({ xTitle: 'residual', yTitle: 'frequency', xType: 'category' });
  options.plugins.tooltip.callbacks = {
    title: (items) => {
      const bin = histogram.bins[items[0].dataIndex];
      return `${fmt(bin.x0, 2)} to ${fmt(bin.x1, 2)}`;
    },
    label: (item) => ` ${item.raw} row(s)`,
  };
  return theme.mountChart(
    cell,
    {
      type: 'bar',
      data: {
        labels: histogram.bins.map((b) => fmt(b.center, 1)),
        datasets: [{ data: histogram.bins.map((b) => b.count), backgroundColor: theme.ACCENT, borderColor: theme.SURFACE, borderWidth: 1, barPercentage: 1, categoryPercentage: 1 }],
      },
      options,
    },
    { height },
  );
}

export const modelRenderers = {
  // Scatter with the fitted curve and, when present, the 95% CI and PI bands. Used by Fitted Line
  // Plot and by Nonlinear Regression (which supplies a curve but no bands).
  fittedLine(container, data, { onCapture }) {
    const curve = data.curve || [];
    const hasBands = curve.length > 0 && curve[0].ci_low !== undefined && curve[0].ci_low !== null;
    const datasets = [];

    if (hasBands) {
      // Drawn widest-first so the prediction band sits behind the confidence band.
      datasets.push({
        label: 'Prediction interval (upper)',
        data: curve.map((p) => ({ x: p.x, y: p.pi_high })),
        borderColor: theme.alpha(theme.MUTED, 0.55),
        borderWidth: 1,
        borderDash: [4, 3],
        pointRadius: 0,
        showLine: true,
        fill: '+1',
        backgroundColor: theme.alpha(theme.MUTED, 0.08),
      });
      datasets.push({
        label: 'PI lower',
        data: curve.map((p) => ({ x: p.x, y: p.pi_low })),
        borderColor: theme.alpha(theme.MUTED, 0.55),
        borderWidth: 1,
        borderDash: [4, 3],
        pointRadius: 0,
        showLine: true,
      });
      datasets.push({
        label: 'Confidence interval (upper)',
        data: curve.map((p) => ({ x: p.x, y: p.ci_high })),
        borderColor: theme.alpha(theme.ACCENT, 0.5),
        borderWidth: 1,
        pointRadius: 0,
        showLine: true,
        fill: '+1',
        backgroundColor: theme.alpha(theme.ACCENT, 0.13),
      });
      datasets.push({
        label: 'CI lower',
        data: curve.map((p) => ({ x: p.x, y: p.ci_low })),
        borderColor: theme.alpha(theme.ACCENT, 0.5),
        borderWidth: 1,
        pointRadius: 0,
        showLine: true,
      });
    }

    datasets.push({
      label: 'Fitted',
      data: curve.map((p) => ({ x: p.x, y: p.fit })),
      borderColor: theme.ACCENT,
      borderWidth: 2.2,
      pointRadius: 0,
      showLine: true,
      tension: 0.15,
    });
    datasets.push({
      label: 'Observed',
      data: data.points,
      backgroundColor: theme.alpha(theme.INK, 0.62),
      borderColor: theme.INK,
      pointRadius: 3,
      showLine: false,
    });

    const options = theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label });
    // Only the three meaningful series belong in the legend; the paired band edges would double it.
    options.plugins.legend.labels = { ...(options.plugins.legend.labels || {}), filter: (item) => !/^(PI lower|CI lower)$/.test(item.text) };
    options.plugins.statBox = { lines: data.annotations || [] };
    theme.mountChart(container, { type: 'scatter', data: { datasets }, options, plugins: [statBox] }, { onCapture, height: 330 });

    const bits = [data.equation];
    if (hasBands) bits.push(`bands: ${Math.round((data.confidence || 0.95) * 100)}% confidence (inner) and prediction (outer)`);
    note(container, bits.filter(Boolean).join(' · '));
  },

  // Minitab's four-in-one: normal probability plot, residuals vs fits, histogram, residuals vs order.
  fourInOne(container, data, { onCapture }) {
    const grid = el('div', { class: 'model-grid model-grid-2' });
    container.appendChild(grid);
    probabilityPanel(panel(grid, 'Normal probability plot'), data.normal, {});
    scatterPanel(panel(grid, 'Residuals versus fits'), data.versus_fits.points, { xTitle: data.versus_fits.x_label, yTitle: data.versus_fits.y_label });
    histogramPanel(panel(grid, 'Histogram of residuals'), data.histogram, {});
    scatterPanel(panel(grid, 'Residuals versus order'), data.versus_order.points, { xTitle: data.versus_order.x_label, yTitle: data.versus_order.y_label, showLine: true });
    note(
      container,
      'Read clockwise from the top left: points on the line mean normal residuals; a shapeless band around zero means constant variance; the histogram should look symmetric; and no drift with order means no time effect.',
    );
    if (onCapture) container.dataset.captureReady = 'true';
  },

  // The lighter pair for models with no four-in-one (nonlinear, PLS, GLM).
  residualPair(container, data, { onCapture }) {
    const grid = el('div', { class: 'model-grid model-grid-2' });
    container.appendChild(grid);
    scatterPanel(panel(grid, 'Residuals versus fits'), data.versus_fits.points, { xTitle: data.versus_fits.x_label, yTitle: data.versus_fits.y_label });
    probabilityPanel(panel(grid, 'Normal probability plot'), data.normal, {});
    if (onCapture) container.dataset.captureReady = 'true';
  },

  // Two fitted lines over the same scatter — orthogonal versus OLS.
  compareFits(container, data, { onCapture }) {
    const datasets = [
      { label: 'Observed', data: data.points, backgroundColor: theme.alpha(theme.INK, 0.55), borderColor: theme.INK, pointRadius: 3, showLine: false },
      ...data.series.map((series, i) => ({
        label: series.label,
        data: series.points,
        borderColor: theme.color(i),
        borderWidth: 2.2,
        borderDash: i === 1 ? [6, 4] : [],
        pointRadius: 0,
        showLine: true,
      })),
    ];
    theme.mountChart(
      container,
      { type: 'scatter', data: { datasets }, options: theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label }) },
      { onCapture, height: 320 },
    );
    note(container, 'Orthogonal regression allows for error in the predictor as well as the response, so its slope is steeper than the OLS slope whenever the predictor is measured with error.');
  },

  // PLS loadings, one labelled point per predictor.
  loadingPlot(container, data, { onCapture }) {
    const options = theme.baseOptions({ xTitle: data.x_label, yTitle: data.y_label });
    options.plugins.pointLabels = { labels: data.points.map((p) => p.label) };
    options.plugins.tooltip.callbacks = { label: (item) => `${data.points[item.dataIndex].label}: ${fmt(item.raw.x, 3)}, ${fmt(item.raw.y, 3)}` };
    theme.mountChart(
      container,
      {
        type: 'scatter',
        data: { datasets: [{ data: data.points.map((p) => ({ x: p.x, y: p.y })), backgroundColor: theme.ACCENT, borderColor: theme.ACCENT, pointRadius: 4.5 }] },
        options,
        plugins: [pointLabels, zeroLine],
      },
      { onCapture, height: 320 },
    );
    note(container, 'Predictors that load together on a component carry the same information; a predictor far from the origin contributes most to that component.');
  },

  // Binary response: the fitted S-curve with the 0/1 observations along the top and bottom.
  binaryFittedLine(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label });
    options.scales.y.min = -0.05;
    options.scales.y.max = 1.05;
    options.plugins.tooltip.callbacks = {
      label: (item) => (item.datasetIndex === 0 ? `P = ${fmt(item.raw.y, 4)} at ${fmt(item.raw.x, 3)}` : `${item.raw.y === 1 ? data.event : data.other} at ${fmt(item.raw.x, 3)}`),
    };
    theme.mountChart(
      container,
      {
        type: 'scatter',
        data: {
          datasets: [
            { label: 'Fitted probability', data: data.curve, borderColor: theme.ACCENT, borderWidth: 2.2, pointRadius: 0, showLine: true, tension: 0.2 },
            { label: 'Observed', data: data.points, backgroundColor: theme.alpha(theme.INK, 0.5), borderColor: theme.INK, pointRadius: 3.2, showLine: false },
          ],
        },
        options,
      },
      { onCapture, height: 320 },
    );
    note(container, `Observations sit at 1 (${data.event}) and 0 (${data.other}); the curve is the fitted probability of ${data.event}.`);
  },

  // ROC curve with the chance diagonal.
  rocCurve(container, data, { onCapture }) {
    const options = theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label });
    options.scales.x.min = 0;
    options.scales.x.max = 1;
    options.scales.y.min = 0;
    options.scales.y.max = 1;
    options.plugins.statBox = { lines: [`AUC = ${fmt(data.auc, 4)}`] };
    theme.mountChart(
      container,
      {
        type: 'scatter',
        data: {
          datasets: [
            { label: 'ROC', data: data.curve, borderColor: theme.ACCENT, backgroundColor: theme.alpha(theme.ACCENT, 0.14), borderWidth: 2, pointRadius: 0, showLine: true, fill: 'origin' },
            { label: 'Chance', data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: theme.MUTED, borderWidth: 1.2, borderDash: [5, 4], pointRadius: 0, showLine: true },
          ],
        },
        options,
        plugins: [statBox],
      },
      { onCapture, height: 320 },
    );
    note(container, 'The further the curve bows above the diagonal, the better the model separates the two outcomes. AUC 0.5 is chance; 1.0 is perfect.');
  },

  // Stability: observations and fitted line per batch, the one-sided bound, the spec limit and the
  // shelf-life marker.
  stabilityPlot(container, data, { onCapture }) {
    const datasets = [];
    (data.series || []).forEach((series, i) => {
      const color = theme.color(i);
      datasets.push({ label: `${series.label} (observed)`, data: series.points, backgroundColor: theme.alpha(color, 0.75), borderColor: color, pointRadius: 3.2, showLine: false });
      datasets.push({ label: `${series.label} (fit)`, data: series.fit.map((p) => ({ x: p.x, y: p.y })), borderColor: color, borderWidth: 2, pointRadius: 0, showLine: true });
      datasets.push({
        label: `${series.label} (bound)`,
        data: series.bound.map((p) => ({ x: p.x, y: p.y })),
        borderColor: theme.alpha(color, 0.65),
        borderWidth: 1.2,
        borderDash: [4, 3],
        pointRadius: 0,
        showLine: true,
      });
    });
    const options = theme.baseOptions({ legend: true, xTitle: data.x_label, yTitle: data.y_label });
    options.plugins.legend.labels = { ...(options.plugins.legend.labels || {}), filter: (item) => /observed/.test(item.text) };
    options.plugins.specLine = { value: data.spec_limit, label: `spec ${fmt(data.spec_limit, 2)}` };
    options.plugins.shelfMarker = { value: data.shelf_life, label: data.shelf_life === null || data.shelf_life === undefined ? '' : `shelf life ${fmt(data.shelf_life, 2)}` };
    theme.mountChart(container, { type: 'scatter', data: { datasets }, options, plugins: [specLine, shelfMarker] }, { onCapture, height: 350 });
    note(
      container,
      `Solid lines are the fitted degradation per batch; dashed lines are the ${Math.round((data.confidence || 0.95) * 100)}% one-sided bound on the mean. Shelf life is where that bound first crosses the ${data.spec_side} spec limit.`,
    );
  },
};
