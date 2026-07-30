// Plotly is only needed by the three 3D/contour windows, and it is a large library — so it is
// fetched from the CDN the first time one of those windows opens rather than on every page load.

import * as theme from './theme.js';

const PLOTLY_URL = 'https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js';

let loading = null;

export function plotlyLoaded() {
  return typeof window.Plotly !== 'undefined';
}

export function loadPlotly(container) {
  if (plotlyLoaded()) return Promise.resolve(window.Plotly);
  if (!loading) {
    loading = new Promise((resolve) => {
      const script = document.createElement('script');
      script.src = PLOTLY_URL;
      script.async = true;
      script.onload = () => resolve(window.Plotly || null);
      script.onerror = () => resolve(null);
      document.head.appendChild(script);
    });
  }

  let status = null;
  if (container) {
    status = document.createElement('p');
    status.className = 'status pulse-text';
    status.textContent = 'Loading the 3D plotting library…';
    container.appendChild(status);
  }
  return loading.then((plotly) => {
    if (status) status.remove();
    if (!plotly && container) {
      const error = document.createElement('p');
      error.className = 'error';
      error.textContent = 'The 3D plotting library could not be loaded from the CDN. Check the connection and reopen this window.';
      container.appendChild(error);
    }
    return plotly;
  });
}

// Plotly styled to the app's tokens: same fonts, same ink and border colors, transparent paper so
// it sits on the window surface like the Chart.js canvases do.
export function plotlyLayout({ xTitle = '', yTitle = '', scene = null, legend = false } = {}) {
  const axis = (title) => ({
    title: { text: title, font: { family: theme.FONT_SANS, size: 11, color: theme.MUTED } },
    tickfont: { family: theme.FONT_MONO, size: 10, color: theme.MUTED },
    gridcolor: theme.GRID,
    zerolinecolor: theme.BORDER,
    linecolor: theme.BORDER,
  });

  const interactive = theme.interactive();

  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: theme.FONT_SANS, size: 11, color: theme.INK },
    margin: { l: 56, r: 16, t: 12, b: 44 },
    showlegend: legend,
    legend: { font: { family: theme.FONT_SANS, size: 11, color: theme.INK }, bgcolor: theme.surfaceWash(0.85), bordercolor: theme.BORDER, borderwidth: 1 },
    hoverlabel: { bgcolor: theme.SURFACE, bordercolor: theme.BORDER, font: { family: theme.FONT_MONO, size: 11, color: theme.INK } },
    transition: { duration: theme.animation().duration || 0 },
    // The modebar is Plotly's own chrome, so it needs telling about the tokens or it draws
    // near-black glyphs on a dark surface.
    modebar: { bgcolor: 'rgba(0,0,0,0)', color: theme.MUTED, activecolor: theme.ACCENT },
    // Plain mode, expressed as LAYOUT attributes rather than `config.staticPlot: true`, because
    // config is not relayout-able and staticPlot is a one-way door: it makes Plotly skip
    // initInteractions entirely, so a plot born static could never be made interactive again
    // without a full re-plot — which would throw away the camera angle the user rotated to. These
    // three leaves flip either way through the same flatten-and-relayout path the theme uses.
    // The modebar itself is hidden by `html.charts-plain` in style.css, for the same reason.
    // `null` rather than a literal 'closest'/'zoom' for the interactive side: Plotly reads null as
    // "unset" and falls back to each plot type's own default, so switching back restores exactly
    // what these plots did before the setting existed.
    hovermode: interactive ? null : false,
    dragmode: interactive ? null : false,
  };

  if (scene) {
    layout.scene = {
      xaxis: axis(scene.xTitle || ''),
      yaxis: axis(scene.yTitle || ''),
      zaxis: axis(scene.zTitle || ''),
      bgcolor: 'rgba(0,0,0,0)',
      // A 3D scene has its OWN dragmode; without this the scene stays rotatable in plain mode.
      dragmode: interactive ? null : false,
    };
    layout.margin = { l: 4, r: 4, t: 4, b: 4 };
  } else {
    layout.xaxis = axis(xTitle);
    layout.yaxis = axis(yTitle);
  }
  return layout;
}

// Always built the same way, in both modes: `displayModeBar` is config, and config cannot be
// changed by relayout, so a plot created with the modebar suppressed could never get it back.
// Plain mode hides it in CSS instead — see plotlyLayout().
export function plotlyConfig() {
  return { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['sendDataToCloud', 'lasso2d', 'select2d'] };
}

// ---------------------------------------------------------------------------
// re-theming a live plot
// ---------------------------------------------------------------------------

// A Chart.js chart is cheap to throw away and rebuild on a theme switch. A Plotly 3D plot is not:
// rebuilding it resets the camera, so the rotation the user set up is lost. These plots are
// therefore tracked and updated in place with relayout/restyle instead.
//
// `layout` and `restyle` are factories, not values — they must be evaluated after the tokens have
// been re-read, not when the plot was first drawn.
const tracked = new Set();

export function trackPlot(div, { layout, restyle = null } = {}) {
  tracked.add({ div, layout, restyle });
}

// Plotly.relayout REPLACES any nested object handed to it, so passing the whole `scene` back would
// wipe `scene.camera` — the rotation the user just set — and snap a 3D plot to its default view.
// Flattening the layout into dotted attribute paths updates only the leaves the theme owns and
// never mentions the camera at all. Arrays (colorscales, tick lists) are values, not branches.
function flattenLayout(value, prefix = '', out = {}) {
  for (const [key, v] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (v && typeof v === 'object' && !Array.isArray(v)) flattenLayout(v, path, out);
    else out[path] = v;
  }
  return out;
}

// Re-themes every tracked plot inside `container` (a window body), dropping any whose div has
// since been removed from the document.
export function applyThemeIn(container) {
  if (!plotlyLoaded()) return 0;
  let touched = 0;
  for (const entry of [...tracked]) {
    if (!entry.div.isConnected) {
      tracked.delete(entry);
      continue;
    }
    if (container && !container.contains(entry.div)) continue;
    try {
      // Colorscales are a trace property, so relayout alone would leave a contour or surface
      // plot with a white floor on a dark background.
      if (entry.restyle) window.Plotly.restyle(entry.div, entry.restyle());
      window.Plotly.relayout(entry.div, flattenLayout(entry.layout()));
      touched += 1;
    } catch {
      /* a plot mid-teardown simply keeps its old styling */
    }
  }
  return touched;
}

/**
 * Push the current Charts mode (File > Options) into EVERY tracked plot, wherever its window is.
 *
 * Nothing separate to maintain: `plotlyLayout()` already carries `hovermode` / `dragmode` /
 * `scene.dragmode`, and relayouting the flattened layout is the same operation a theme switch
 * performs. That is exactly why plain mode is expressed as layout attributes — see plotlyLayout().
 */
export function applyInteractivityToAll() {
  return applyThemeIn();
}

// True when this container owns a tracked plot — app.js uses it to re-theme such a window in
// place rather than rebuilding its contents.
export function hasTrackedPlot(container) {
  for (const entry of tracked) {
    if (entry.div.isConnected && container.contains(entry.div)) return true;
  }
  return false;
}
