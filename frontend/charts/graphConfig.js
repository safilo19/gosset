// Every item on the Graph menu, declared once: its form fields, the backend graph_type that
// computes its data, and which renderer draws it. The menu, the forms and the Graph Builder are
// all generated from this, so adding a graph means adding one entry.
//
// Field roles: `column` fields build the ordered `columns` array the backend expects; `option`
// fields become the `options` object.

const num = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'numeric', required: true, ...extra });
const anyCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'any', required: true, ...extra });
const groupBy = (label = 'Group / color by (optional)') => ({ name: 'group_column', label, type: 'column', role: 'option', filter: 'any', required: false });

export const GRAPHS = [
  // ---- native Chart.js types ------------------------------------------------
  {
    id: 'scatter',
    icon: 'scatter',
    description: 'Plots one numeric column against another as points, to show the direction, strength and shape of their relationship. Groups can be coloured separately.',
    needs: 'Two numeric columns.',
    label: 'Scatterplot',
    group: 'basic',
    backend: 'scatter',
    renderer: 'scatter',
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)'), groupBy()],
  },
  {
    id: 'bubble',
    icon: 'bubble',
    description: 'A scatterplot where each point\'s SIZE carries a third numeric variable, so three quantities show on two axes.',
    needs: 'Three numeric columns.',
    label: 'Bubble Plot',
    group: 'basic',
    backend: 'bubble',
    renderer: 'bubble',
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)'), num('size', 'Bubble size (numeric)')],
  },
  {
    id: 'line',
    icon: 'line-plot',
    description: 'Joins points in row order, for a quantity measured in sequence. Use Time Series Plot instead when the x axis is a real date.',
    needs: 'One numeric column, optionally an x column.',
    label: 'Line Plot',
    group: 'basic',
    backend: 'line',
    renderer: 'line',
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)')],
  },
  {
    id: 'bar',
    icon: 'bar-chart',
    description: 'Compares a value across categories as bars, either counting rows or aggregating a numeric column by mean or sum.',
    needs: 'One category column, optionally a numeric column to aggregate.',
    label: 'Bar Chart',
    group: 'basic',
    backend: 'bar',
    renderer: 'bar',
    fields: [
      anyCol('category', 'Category'),
      { name: 'value', label: 'Value (optional — counts rows if empty)', type: 'column', role: 'column', filter: 'numeric', required: false },
      { name: 'aggregate', label: 'Aggregate', type: 'select', role: 'option', options: ['mean', 'sum'], default: 'mean' },
      groupBy('Group by (optional)'),
      { name: 'stacked', label: 'Stack the groups', type: 'checkbox', role: 'option', default: false },
    ],
  },
  {
    id: 'pie',
    icon: 'pie-chart',
    description: 'Shows each category\'s share of a whole. Readable for a handful of categories; a bar chart compares many more reliably.',
    needs: 'One category column, optionally a numeric column.',
    label: 'Pie Chart',
    group: 'basic',
    backend: 'pie',
    renderer: 'pie',
    fields: [
      anyCol('category', 'Category'),
      { name: 'value', label: 'Value (optional — counts rows if empty)', type: 'column', role: 'column', filter: 'numeric', required: false },
    ],
  },
  {
    id: 'area',
    icon: 'area-graph',
    description: 'A line plot with the space beneath it filled, which emphasises cumulative size rather than the rate of change.',
    needs: 'One numeric column, optionally an x column.',
    label: 'Area Graph',
    group: 'basic',
    backend: 'area',
    renderer: 'area',
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)')],
  },
  {
    id: 'time_series',
    icon: 'time-series',
    description: 'Plots a quantity against a real date or time axis, spacing points by their actual dates rather than evenly.',
    needs: 'One numeric column and one date/time column.',
    label: 'Time Series Plot',
    group: 'basic',
    backend: 'time_series',
    renderer: 'timeSeries',
    fields: [anyCol('date', 'Date / time column', { filter: 'any' }), num('value', 'Value (numeric)')],
  },
  {
    id: 'histogram',
    icon: 'histogram',
    description: 'Bins a numeric column and draws the count in each bin, to show the shape, centre and spread of a distribution. Bin width can be set or left automatic.',
    needs: 'One numeric column.',
    label: 'Histogram',
    group: 'basic',
    backend: 'histogram',
    renderer: 'histogram',
    fields: [
      num('column', 'Numeric column'),
      { name: 'bin_width', label: 'Bin width (optional — chosen automatically if empty)', type: 'number', role: 'option', step: 'any', min: 0 },
    ],
  },

  // ---- plugin-based types --------------------------------------------------
  {
    id: 'boxplot',
    icon: 'boxplot',
    description: 'Summarises each group as a median, a box spanning the quartiles, whiskers and separately drawn outliers. Compares many groups compactly, but hides how many observations each holds.',
    needs: 'One or more numeric columns, optionally a grouping column.',
    label: 'Boxplot',
    group: 'matrix',
    backend: 'boxplot',
    renderer: 'boxplot',
    requires: 'boxplot',
    fields: [
      { name: 'columns', label: 'Numeric column(s)', type: 'columns', role: 'column', filter: 'numeric', required: true, minSelect: 1 },
      groupBy('Group by (optional — uses the first column as the value)'),
    ],
  },
  {
    id: 'heatmap',
    icon: 'heatmap',
    description: 'Shades a grid of two categories by a third value, so a pattern across many combinations reads at a glance.',
    needs: 'Two category columns, optionally a numeric column to aggregate.',
    label: 'Heatmap',
    group: 'matrix',
    backend: 'heatmap',
    renderer: 'heatmap',
    requires: 'matrix',
    fields: [
      anyCol('rows', 'Rows (category)'),
      anyCol('cols', 'Columns (category)'),
      { name: 'value', label: 'Value (optional — counts rows if empty)', type: 'column', role: 'column', filter: 'numeric', required: false },
      { name: 'aggregate', label: 'Aggregate', type: 'select', role: 'option', options: ['mean', 'sum'], default: 'mean' },
    ],
  },
  {
    id: 'correlogram',
    icon: 'correlogram',
    description: 'Draws the correlation matrix of several columns as a shaded grid, so the strongest relationships in a wide worksheet stand out without reading a table of numbers.',
    needs: 'Two or more numeric columns.',
    label: 'Correlogram',
    group: 'matrix',
    backend: 'correlogram',
    renderer: 'correlogram',
    requires: 'matrix',
    fields: [
      { name: 'columns', label: 'Numeric columns (2+)', type: 'columns', role: 'column', filter: 'numeric', required: true, minSelect: 2 },
      { name: 'method', label: 'Method', type: 'select', role: 'option', options: ['pearson', 'spearman'], default: 'pearson' },
    ],
  },
  {
    id: 'binned_scatter',
    icon: 'binned-scatter',
    description: 'A scatterplot whose points are collected into shaded cells. Use it when there are so many rows that a plain scatterplot becomes a solid block and the density is no longer visible.',
    needs: 'Two numeric columns, best with many rows.',
    label: 'Binned Scatterplot',
    group: 'matrix',
    backend: 'binned_scatter',
    renderer: 'binnedScatter',
    requires: 'matrix',
    fields: [
      num('x', 'X (numeric)'),
      num('y', 'Y (numeric)'),
      { name: 'x_bins', label: 'X bins', type: 'number', role: 'option', default: 12, min: 2, max: 40, step: 1 },
      { name: 'y_bins', label: 'Y bins', type: 'number', role: 'option', default: 10, min: 2, max: 40, step: 1 },
    ],
  },

  // ---- computed statistical plots -----------------------------------------
  {
    id: 'dotplot',
    icon: 'dotplot',
    description: 'Stacks one dot per observation along the value axis. Like a histogram, but every individual value stays visible, which suits small samples.',
    needs: 'One numeric column, optionally a grouping column.',
    label: 'Dotplot',
    group: 'stats',
    backend: 'dotplot',
    renderer: 'dotplot',
    fields: [
      num('column', 'Numeric column'),
      { name: 'bin_width', label: 'Bin width (optional)', type: 'number', role: 'option', step: 'any', min: 0 },
    ],
  },
  {
    id: 'individual_value',
    icon: 'individual-value',
    description: 'Plots every observation in each group as a point. Shows the sample size and any gaps or clusters that a boxplot\'s summary would conceal.',
    needs: 'One numeric column and a grouping column.',
    label: 'Individual Value Plot',
    group: 'stats',
    backend: 'individual_value',
    renderer: 'individualValue',
    fields: [num('column', 'Numeric column'), groupBy('Group by')],
  },
  {
    id: 'interval',
    icon: 'interval-plot',
    description: 'Plots each group\'s mean with a confidence interval, for judging whether groups differ by eye.',
    needs: 'One numeric column and a grouping column.',
    label: 'Interval Plot',
    group: 'stats',
    backend: 'interval',
    renderer: 'interval',
    fields: [
      num('column', 'Numeric column'),
      groupBy('Group by'),
      { name: 'confidence', label: 'Confidence level', type: 'number', role: 'option', default: 0.95, min: 0.5, max: 0.999, step: 0.01 },
    ],
  },
  {
    id: 'main_effects',
    icon: 'main-effects-plot',
    description: 'Plots the mean response at each level of each factor against the overall mean, one panel per factor.',
    needs: 'One numeric response and one or more factors.',
    label: 'Main Effects Plot',
    group: 'stats',
    backend: 'main_effects',
    renderer: 'mainEffects',
    fields: [
      num('column', 'Response'),
      { name: 'factors', label: 'Factors', type: 'columns', role: 'column', filter: 'any', required: true, minSelect: 1 },
    ],
  },
  {
    id: 'interaction',
    icon: 'interaction-plot',
    description: 'Plots mean response as a line per level of one factor across another. Parallel lines mean the factors act independently; crossing lines mean they do not.',
    needs: 'One numeric response and two or more factors.',
    label: 'Interaction Plot',
    group: 'stats',
    backend: 'interaction',
    renderer: 'interactionPlot',
    fields: [
      num('column', 'Response'),
      { name: 'factors', label: 'Factors (2 or more)', type: 'columns', role: 'column', filter: 'any', required: true, minSelect: 2 },
    ],
  },
  {
    id: 'ecdf',
    icon: 'ecdf',
    description: 'Draws the proportion of observations at or below each value as a rising step function. Reads percentiles directly and compares two distributions without choosing bins.',
    needs: 'One numeric column.',
    label: 'Empirical CDF',
    group: 'stats',
    backend: 'ecdf',
    renderer: 'ecdf',
    fields: [num('column', 'Numeric column'), groupBy('Group by (optional)')],
  },
  {
    id: 'probability',
    icon: 'probability-plot',
    description: 'Plots the sorted data against the values a chosen distribution predicts. Points on the straight line mean the distribution fits; systematic curvature says how it fails.',
    needs: 'One numeric column.',
    label: 'Probability Plot',
    group: 'stats',
    backend: 'probability',
    renderer: 'probability',
    fields: [num('column', 'Numeric column')],
  },
  {
    id: 'distribution',
    icon: 'distribution-plot',
    description: 'Draws a theoretical distribution from typed parameters, not from data, with an optional shaded region. Made for showing where a p-value or a critical value sits.',
    needs: 'A distribution and its parameters.',
    label: 'Probability Distribution Plot',
    group: 'stats',
    backend: 'distribution',
    renderer: 'distribution',
    noData: true, // parameters only — needs no columns at all
    fields: [
      {
        name: 'distribution',
        label: 'Distribution',
        type: 'select',
        role: 'option',
        options: ['normal', 't', 'chi_square', 'f', 'binomial', 'poisson'],
        default: 'normal',
      },
      { name: 'curve', label: 'Curve', type: 'select', role: 'option', options: ['pdf', 'cdf'], default: 'pdf' },
      { name: 'p_mean', label: 'Mean (normal / poisson)', type: 'number', role: 'param', param: 'mean', default: 0, step: 'any' },
      { name: 'p_sd', label: 'Standard deviation (normal)', type: 'number', role: 'param', param: 'sd', default: 1, step: 'any', min: 0 },
      { name: 'p_df', label: 'Degrees of freedom (t / chi-square)', type: 'number', role: 'param', param: 'df', default: 10, step: 'any', min: 0 },
      { name: 'p_df1', label: 'df1 (F)', type: 'number', role: 'param', param: 'df1', default: 5, step: 'any', min: 0 },
      { name: 'p_df2', label: 'df2 (F)', type: 'number', role: 'param', param: 'df2', default: 10, step: 'any', min: 0 },
      { name: 'p_n', label: 'Trials n (binomial)', type: 'number', role: 'param', param: 'n', default: 20, step: 1, min: 1 },
      { name: 'p_p', label: 'Probability p (binomial)', type: 'number', role: 'param', param: 'p', default: 0.5, step: 0.01, min: 0, max: 1 },
      { name: 'shade_from', label: 'Shade from x (optional)', type: 'number', role: 'option', step: 'any' },
      { name: 'shade_to', label: 'Shade to x (optional)', type: 'number', role: 'option', step: 'any' },
    ],
  },
  {
    id: 'stem_leaf',
    icon: 'stem-leaf',
    description: 'A text histogram that keeps the digits of every value, so the shape and the actual numbers are both readable. Suits small samples and printed output.',
    needs: 'One numeric column.',
    label: 'Stem-and-Leaf',
    group: 'stats',
    backend: 'stem_leaf',
    renderer: 'stemLeaf',
    text: true, // text output, not a canvas — the way Minitab renders it
    fields: [num('column', 'Numeric column')],
  },

  // ---- composite / multi-panel -------------------------------------------
  {
    id: 'matrix_plot',
    icon: 'matrix-plot',
    description: 'A grid of scatterplots for every pair of the chosen columns, for finding which relationships are worth a closer look.',
    needs: 'Two to five numeric columns.',
    label: 'Matrix Plot',
    group: 'composite',
    backend: 'matrix_plot',
    renderer: 'matrixPlot',
    fields: [{ name: 'columns', label: 'Numeric columns (2–5)', type: 'columns', role: 'column', filter: 'numeric', required: true, minSelect: 2, maxSelect: 5 }],
  },
  {
    id: 'marginal',
    icon: 'marginal-plot',
    description: 'A scatterplot with a histogram or boxplot along each axis, so each variable\'s own distribution shows alongside their joint one.',
    needs: 'Two numeric columns.',
    label: 'Marginal Plot',
    group: 'composite',
    backend: 'marginal',
    renderer: 'marginal',
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)')],
  },
  {
    id: 'parallel_coords',
    icon: 'parallel-coords',
    description: 'Draws one line per row across an axis for each column, so many variables show at once and groups that travel differently stand out.',
    needs: 'Two or more numeric columns.',
    label: 'Parallel Coordinates Plot',
    group: 'composite',
    backend: 'parallel_coords',
    renderer: 'parallelCoords',
    fields: [
      { name: 'columns', label: 'Numeric columns (2+)', type: 'columns', role: 'column', filter: 'numeric', required: true, minSelect: 2 },
      groupBy('Color by (optional)'),
    ],
  },

  // ---- 3D & contour (plotly, lazy-loaded) --------------------------------
  {
    id: 'contour',
    icon: 'contour-plot',
    description: 'Draws a response over two variables as contour lines on a flat map. Easier than a surface for reading off the settings that give a particular value.',
    needs: 'Three numeric columns: two predictors and a response.',
    label: 'Contour Plot',
    group: 'threed',
    backend: 'contour',
    renderer: 'contour',
    plotly: true,
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)'), num('z', 'Z (numeric)')],
  },
  {
    id: 'scatter3d',
    icon: 'scatter3d',
    description: 'Plots points in three dimensions, rotatable by dragging, for seeing structure that no pair of axes shows on its own.',
    needs: 'Three numeric columns.',
    label: '3D Scatterplot',
    group: 'threed',
    backend: 'scatter3d',
    renderer: 'scatter3d',
    plotly: true,
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)'), num('z', 'Z (numeric)'), groupBy('Color by (optional)')],
  },
  {
    id: 'surface',
    icon: 'surface-plot',
    description: 'Draws a response over two variables as a 3D surface. Shows curvature and ridges more vividly than contours, but exact values are harder to read.',
    needs: 'Three numeric columns: two predictors and a response.',
    label: '3D Surface Plot',
    group: 'threed',
    backend: 'surface',
    renderer: 'surface',
    plotly: true,
    fields: [num('x', 'X (numeric)'), num('y', 'Y (numeric)'), num('z', 'Z (numeric)')],
  },
];

// These are the Graph menu's flyout categories; Title Case to match the Stat menu's groups.
export const GRAPH_GROUPS = [
  { id: 'basic', label: 'Basic Plots' },
  { id: 'matrix', label: 'Distribution & Matrix' },
  { id: 'stats', label: 'Statistical Plots' },
  { id: 'composite', label: 'Multi-Panel' },
  { id: 'threed', label: '3D & Contour' },
];

export const GRAPH_BY_ID = Object.fromEntries(GRAPHS.map((g) => [g.id, g]));

// Which fields a distribution's parameters actually need — the rest stay hidden so the form
// doesn't ask for df1 when you picked a normal.
export const DISTRIBUTION_PARAMS = {
  normal: ['p_mean', 'p_sd'],
  t: ['p_df'],
  chi_square: ['p_df'],
  f: ['p_df1', 'p_df2'],
  binomial: ['p_n', 'p_p'],
  poisson: ['p_mean'],
};

export function defaultValues(graph) {
  const values = {};
  for (const field of graph.fields) {
    if (field.type === 'columns') values[field.name] = [];
    else if (field.type === 'checkbox') values[field.name] = !!field.default;
    else values[field.name] = field.default ?? '';
  }
  return values;
}

export function validate(graph, values) {
  for (const field of graph.fields) {
    const value = values[field.name];
    if (field.type === 'columns') {
      const count = (value || []).length;
      if (field.required && count === 0) return `${field.label} is required.`;
      if (field.minSelect && count < field.minSelect) return `${field.label} needs at least ${field.minSelect}.`;
      if (field.maxSelect && count > field.maxSelect) return `${field.label} allows at most ${field.maxSelect}.`;
    } else if (field.required && (value === '' || value === undefined || value === null)) {
      return `${field.label} is required.`;
    }
  }
  return null;
}

// Turn form values into the request the backend expects.
export function buildRequest(graph, values) {
  const columns = [];
  const options = {};
  const parameters = {};
  const active = graph.id === 'distribution' ? DISTRIBUTION_PARAMS[values.distribution] || [] : null;

  for (const field of graph.fields) {
    const value = values[field.name];
    if (field.role === 'column') {
      if (Array.isArray(value)) columns.push(...value);
      else if (value) columns.push(value);
    } else if (field.role === 'param') {
      if (active && active.includes(field.name) && value !== '' && value !== null && value !== undefined) parameters[field.param] = Number(value);
    } else if (value !== '' && value !== null && value !== undefined && !(field.type === 'checkbox' && value === false)) {
      options[field.name] = field.type === 'number' ? Number(value) : value;
    }
  }
  if (Object.keys(parameters).length) options.parameters = parameters;
  return { graph_type: graph.backend, columns, options };
}

// One-line description of what was plotted, for the window title and the session log.
export function describe(graph, values) {
  const parts = [];
  for (const field of graph.fields) {
    const value = values[field.name];
    if (field.role === 'param') continue;
    if (Array.isArray(value) && value.length) parts.push(value.join(', '));
    else if (field.type === 'checkbox') {
      if (value) parts.push(field.name);
    } else if (value !== '' && value !== undefined && value !== null && field.name !== 'aggregate') {
      parts.push(String(value));
    }
  }
  return parts.length ? `${graph.label} (${parts.join('; ')})` : graph.label;
}
