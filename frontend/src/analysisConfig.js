// Declarative shape for the 8 analysis forms. One generic form component reads this,
// instead of 8 near-identical hand-written forms.

export const ANALYSES = [
  {
    id: 'describe',
    label: 'Describe',
    fields: [{ name: 'columns', label: 'Columns (optional — all if none selected)', type: 'columns' }],
  },
  {
    id: 'correlation',
    label: 'Correlation',
    fields: [
      { name: 'columns', label: 'Columns (2+)', type: 'columns', required: true, minSelect: 2 },
      { name: 'method', label: 'Method', type: 'select', options: ['pearson', 'spearman'], default: 'pearson' },
    ],
  },
  {
    id: 'hypothesis',
    label: 'Hypothesis Test',
    fields: [
      { name: 'test_type', label: 'Test type', type: 'select', options: ['t_test', 'anova', 'chi_square'], default: 't_test' },
      {
        name: 'column_a',
        label: 'First column (numeric value, for t_test/anova — either category for chi_square)',
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
    fields: [
      { name: 'target', label: 'Target column', type: 'column', required: true },
      { name: 'features', label: 'Feature columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'model_type', label: 'Model type', type: 'select', options: ['linear', 'logistic'], default: 'linear' },
    ],
  },
  {
    id: 'forecast',
    label: 'Forecast',
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
    fields: [
      { name: 'columns', label: 'Columns', type: 'columns', required: true, minSelect: 1 },
      { name: 'method', label: 'Method', type: 'select', options: ['auto', 'rfm', 'kmeans'], default: 'auto' },
      { name: 'n_clusters', label: 'Clusters (kmeans only)', type: 'number', default: 3, step: 1, min: 2, max: 10 },
    ],
  },
  {
    id: 'chart',
    label: 'Chart',
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
    label: 'Export',
    special: true,
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
