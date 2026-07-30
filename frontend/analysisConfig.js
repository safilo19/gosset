// Declarative shape for the 8 analysis forms. One generic form builder reads this,
// instead of 8 near-identical hand-written forms.

export const ANALYSES = [
  {
    id: 'describe',
    label: 'Descriptive statistics',
    submitLabel: 'Run descriptive statistics',
    fields: [{ name: 'columns', label: 'Columns (optional — all if none selected)', type: 'columns' }],
  },
  {
    id: 'correlation',
    label: 'Correlation',
    submitLabel: 'Run correlation',
    fields: [
      { name: 'columns', label: 'Columns (2+)', type: 'columns', required: true, minSelect: 2 },
      { name: 'method', label: 'Method', type: 'select', options: ['pearson', 'spearman'], default: 'pearson' },
    ],
  },
  {
    // The two-sample t case moved to Stat > Basic Statistics > 2-Sample t, which offers the layout
    // and equal-variance options Minitab does; what is left here is one-way ANOVA and the
    // chi-square test for association, which Minitab keeps under their own menus too.
    id: 'hypothesis',
    label: 'ANOVA / chi-square test',
    submitLabel: 'Run test',
    fields: [
      { name: 'test_type', label: 'Test type', type: 'select', options: ['anova', 'chi_square'], default: 'anova' },
      {
        name: 'column_a',
        label: 'First column (numeric value for anova — either category for chi_square)',
        type: 'column',
        required: true,
        group: 'columns',
      },
      {
        name: 'column_b',
        label: 'Second column (group/category)',
        type: 'column',
        required: true,
        group: 'columns',
      },
      { name: 'alpha', label: 'Alpha', type: 'number', default: 0.05, step: 0.001, min: 0.001, max: 0.5 },
    ],
  },
  {
    id: 'regression',
    label: 'Regression',
    submitLabel: 'Run regression',
    fields: [
      { name: 'target', label: 'Target column', type: 'column', required: true },
      { name: 'features', label: 'Feature columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'model_type', label: 'Model type', type: 'select', options: ['linear', 'logistic'], default: 'linear' },
    ],
  },
  {
    id: 'forecast',
    label: 'Forecast',
    submitLabel: 'Run forecast',
    fields: [
      { name: 'date_column', label: 'Date column', type: 'column', required: true },
      { name: 'value_column', label: 'Value column', type: 'column', required: true },
      { name: 'periods', label: 'Periods ahead', type: 'number', default: 6, step: 1, min: 1, max: 365 },
      {
        name: 'method',
        label: 'Method',
        type: 'select',
        options: ['auto', 'exponential_smoothing', 'arima'],
        default: 'auto',
      },
    ],
  },
  {
    id: 'segmentation',
    label: 'Segmentation',
    submitLabel: 'Run segmentation',
    fields: [
      { name: 'columns', label: 'Columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'method', label: 'Method', type: 'select', options: ['auto', 'rfm', 'kmeans'], default: 'auto' },
      { name: 'n_clusters', label: 'Clusters (kmeans only)', type: 'number', default: 3, step: 1, min: 2, max: 10 },
    ],
  },
  {
    id: 'decision_tree',
    label: 'Decision tree',
    submitLabel: 'Fit decision tree',
    fields: [
      { name: 'target', label: 'Target column', type: 'column', required: true },
      { name: 'features', label: 'Feature columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'task_type', label: 'Task type', type: 'select', options: ['auto', 'classification', 'regression'], default: 'auto' },
    ],
  },
  {
    id: 'random_forest',
    label: 'Random forest',
    submitLabel: 'Fit random forest',
    fields: [
      { name: 'target', label: 'Target column', type: 'column', required: true },
      { name: 'features', label: 'Feature columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'task_type', label: 'Task type', type: 'select', options: ['auto', 'classification', 'regression'], default: 'auto' },
    ],
  },
  {
    id: 'gradient_boosting',
    label: 'Gradient boosting',
    submitLabel: 'Fit gradient boosting',
    fields: [
      { name: 'target', label: 'Target column', type: 'column', required: true },
      { name: 'features', label: 'Feature columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'task_type', label: 'Task type', type: 'select', options: ['auto', 'classification', 'regression'], default: 'auto' },
    ],
  },
  {
    id: 'automl',
    label: 'AutoML',
    submitLabel: 'Compare models',
    fields: [
      { name: 'target', label: 'Target column', type: 'column', required: true },
      { name: 'features', label: 'Feature columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'task_type', label: 'Task type', type: 'select', options: ['auto', 'classification', 'regression'], default: 'auto' },
    ],
  },
  {
    id: 'chart',
    label: 'Chart',
    submitLabel: 'Draw chart',
    fields: [
      {
        name: 'chart_type',
        label: 'Chart type',
        type: 'select',
        options: ['bar', 'line', 'scatter', 'histogram', 'heatmap'],
        default: 'scatter',
      },
      { name: 'columns', label: 'Columns', type: 'columns', required: true, minSelect: 1 },
    ],
  },
  {
    id: 'export',
    label: 'Report files',
    submitLabel: 'Write report files',
    special: true,
  },
];

// How the Stat menu is grouped. Labels are the menu's own wording (a little more explicit than the
// dialog titles), and each group becomes a flyout submenu — see menu.js. The Basic Statistics
// flyout is spliced in from basicStatsConfig.js, which holds Minitab's own 18 items and dividers.
export const STAT_MENU = [
  // One-way ANOVA now has its own dialog under Stat > ANOVA, with layouts, Welch, comparisons and
  // the plots Minitab offers. What is left of the old generic form is the chi-square test for
  // association — and the form itself stays, because the chat parser still emits 'hypothesis'.
  { label: 'Tables', items: [{
      label: 'Chi-Square Test for Association…',
      analysis: 'hypothesis',
      icon: 'chi-square-association',
      description: 'Tests whether two categorical variables are related, by comparing the observed cross-tabulation against the counts expected if they were independent.',
      needs: 'Two category columns.',
    }] },
  { label: 'Time Series', items: [{
      label: 'Forecast',
      analysis: 'forecast',
      icon: 'forecast',
      description: 'Projects a time series forward with a confidence band, from its trend and any seasonal pattern it finds.',
      needs: 'One numeric column in time order, ideally 20 or more values.',
    }] },
  { label: 'Multivariate', items: [{
      label: 'Segmentation',
      analysis: 'segmentation',
      icon: 'segmentation',
      description: 'Groups rows into clusters that resemble each other across the chosen columns, and describes what makes each cluster distinct.',
      needs: 'Two or more numeric columns.',
    }] },
  {
    label: 'Predictive Analytics',
    items: [
      {
      label: 'Decision tree',
      analysis: 'decision_tree',
      icon: 'decision-tree',
      description: 'Fits a single tree of yes/no splits to predict a response. The most readable of the predictive models — the tree itself is the explanation — though usually the least accurate.',
      needs: 'One response column and one or more predictors.',
    },
      {
      label: 'Random forest',
      analysis: 'random_forest',
      icon: 'random-forest',
      description: 'Fits many trees on random subsets and averages them. More accurate than one decision tree and much harder to overfit, at the cost of no longer being readable as a single set of rules.',
      needs: 'One response column and one or more predictors.',
    },
      {
      label: 'Gradient boosting',
      analysis: 'gradient_boosting',
      icon: 'gradient-boosting',
      description: 'Fits trees in sequence, each correcting what the ones before it got wrong. Usually the most accurate of the three on tabular data, and the most sensitive to its settings.',
      needs: 'One response column and one or more predictors.',
    },
      {
      label: 'AutoML model comparison',
      analysis: 'automl',
      icon: 'automl',
      description: 'Fits several model types on the same data and ranks them on a common metric, so the choice of model is made by comparison rather than by assumption.',
      needs: 'One response column and one or more predictors.',
    },
    ],
  },
];

export function defaultValues(config) {
  const values = {};
  for (const f of config.fields) {
    if (f.type === 'columns') values[f.name] = [];
    else if (f.type === 'column') values[f.name] = '';
    else values[f.name] = f.default ?? '';
  }
  return values;
}

export function validateValues(config, values) {
  for (const f of config.fields) {
    const val = values[f.name];
    if (f.type === 'columns') {
      const n = (val || []).length;
      if (f.required && n === 0) return `${f.label} is required.`;
      if (f.minSelect && n < f.minSelect) return `${f.label} needs at least ${f.minSelect}.`;
      if (f.maxSelect && n > f.maxSelect) return `${f.label} allows at most ${f.maxSelect}.`;
    } else if (f.required && !val) {
      return `${f.label} is required.`;
    }
  }
  return null;
}

// Most fields map 1:1 to an API param by name. A field with `group: 'columns'` instead
// contributes its value, in field order, to a shared array param named after the group
// (used by hypothesis-test's ordered [value_column, group_column] pair).
export function buildParams(config, values) {
  const params = {};
  const groups = {};
  for (const f of config.fields) {
    const v = f.type === 'number' ? Number(values[f.name]) : values[f.name];
    if (f.group) {
      (groups[f.group] = groups[f.group] || []).push(v);
    } else {
      params[f.name] = v;
    }
  }
  return { ...params, ...groups };
}

export function summarizeParams(config, values) {
  const parts = [];
  for (const f of config.fields) {
    const v = values[f.name];
    if (Array.isArray(v) && v.length) parts.push(v.join(', '));
    else if (f.type !== 'select' && v !== '' && v !== undefined && v !== null) parts.push(String(v));
  }
  return parts.length ? `${config.label} (${parts.join('; ')})` : config.label;
}
