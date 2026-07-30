// Every item on Stat > Basic Statistics, declared once: its form fields, the backend procedure
// that computes it, and how its inputs turn into a request. The menu, the forms and the request
// bodies are all generated from this — the same split as charts/graphConfig.js and graphs.js.
//
// Field roles: `column` fields build the ordered `columns` array the backend expects (in field
// order); everything else becomes a key in `options`. `showIf` hides a field that the current
// choices make irrelevant, which is what keeps a dialog with two input layouts readable.

import { visibleFields as visible } from './procedureDialog.js';

// ---------------------------------------------------------------------------
// the statistics picker, shared by Display and Store Descriptive Statistics
// ---------------------------------------------------------------------------

// Same keys and same order as backend/core/basic_stats.py's DESCRIPTIVE_STATS.
export const DESCRIPTIVE_STATISTICS = [
  { key: 'n', label: 'N' },
  { key: 'n_missing', label: 'N missing' },
  { key: 'mean', label: 'Mean' },
  { key: 'se_mean', label: 'SE of mean' },
  { key: 'stdev', label: 'Standard deviation' },
  { key: 'variance', label: 'Variance' },
  { key: 'coef_var', label: 'Coefficient of variation' },
  { key: 'minimum', label: 'Minimum' },
  { key: 'q1', label: 'First quartile' },
  { key: 'median', label: 'Median' },
  { key: 'q3', label: 'Third quartile' },
  { key: 'maximum', label: 'Maximum' },
  { key: 'iqr', label: 'Interquartile range' },
  { key: 'range', label: 'Range' },
  { key: 'sum', label: 'Sum' },
  { key: 'skewness', label: 'Skewness' },
  { key: 'kurtosis', label: 'Kurtosis' },
];

export const DEFAULT_STATISTICS = ['n', 'n_missing', 'mean', 'se_mean', 'stdev', 'minimum', 'q1', 'median', 'q3', 'maximum'];

// ---------------------------------------------------------------------------
// field shorthands
// ---------------------------------------------------------------------------

const numCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'numeric', required: true, ...extra });
const anyCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'any', required: true, ...extra });
const groupCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'any', required: true, ...extra });

const alternative = (param = 'μ') => ({
  name: 'alternative',
  label: 'Alternative hypothesis',
  type: 'select',
  role: 'option',
  options: [
    { value: 'two-sided', label: `${param} ≠ hypothesized value` },
    { value: 'less', label: `${param} < hypothesized value` },
    { value: 'greater', label: `${param} > hypothesized value` },
  ],
  default: 'two-sided',
});

// step is deliberately 'any' on every fractional field. A numeric step (0.01) makes the browser
// treat any value that is not min + n×step as invalid and silently refuse to submit the form — so
// a 97.5% confidence level, or a hypothesized proportion of 0.5 under min 0.000001, would block
// the dialog with no visible reason. Ranges are enforced by the backend, which explains itself.
const confidence = () => ({
  name: 'confidence',
  label: 'Confidence level',
  type: 'number',
  role: 'option',
  default: 0.95,
  min: 0.5,
  max: 0.999,
  step: 'any',
  hint: 'Also sets the significance level used to decide the test: α = 1 − confidence.',
});

// The three optional plots the tests of means offer, with the hypothesized value marked on each.
const testGraphs = () => [
  { name: 'graph_histogram', label: 'Histogram of the data', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
  { name: 'graph_boxplot', label: 'Boxplot of the data', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
  { name: 'graph_individual_value', label: 'Individual value plot of the data', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
];

const statisticsPicker = () => ({
  name: 'statistics',
  label: 'Statistics',
  type: 'checkbox-grid',
  items: DESCRIPTIVE_STATISTICS,
  role: 'option',
  default: DEFAULT_STATISTICS,
});

const isSummarized = (values) => values.input === 'summarized';
const isRaw = (values) => values.input !== 'summarized';
const inOneColumn = (values) => values.layout === 'one_column';
const inTwoColumns = (values) => values.layout === 'two_columns';

// ---------------------------------------------------------------------------
// the 18 procedures
// ---------------------------------------------------------------------------

export const PROCEDURES = [
  {
    id: 'display_descriptives',
    icon: 'display-descriptives',
    description: 'Reports the count, mean, standard deviation, quartiles and range of each chosen column, split by groups if a grouping column is given. The usual first look at a new worksheet.',
    needs: 'One or more numeric columns.',
    procedure: 'display_descriptives',
    label: 'Display Descriptive Statistics…',
    title: 'Display Descriptive Statistics',
    submitLabel: 'Display statistics',
    fields: [
      { name: 'variables', label: 'Variables', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      { name: 'group_column', label: 'By variable (optional — one row of statistics per group)', type: 'column', role: 'option', filter: 'any', required: false },
      statisticsPicker(),
      ...testGraphs(),
    ],
  },
  {
    id: 'store_descriptives',
    icon: 'store-descriptives',
    description: 'Computes the same statistics as Display Descriptive Statistics but writes them into worksheet columns instead of printing them, so they can be charted or used in later calculations.',
    needs: 'One or more numeric columns.',
    procedure: 'store_descriptives',
    label: 'Store Descriptive Statistics…',
    title: 'Store Descriptive Statistics',
    submitLabel: 'Store statistics in the worksheet',
    storesColumns: true,
    fields: [
      { name: 'variables', label: 'Variables', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      { name: 'group_column', label: 'By variable (optional — one row per group)', type: 'column', role: 'option', filter: 'any', required: false },
      statisticsPicker(),
    ],
    note: 'The statistics are written into the worksheet as new columns, named like Mean(yield_kg). Edit > Undo removes them again.',
  },
  {
    id: 'graphical_summary',
    icon: 'graphical-summary',
    description: 'One page per column: a histogram with a fitted normal curve, a boxplot, confidence intervals for the mean and the median, and an Anderson-Darling normality verdict. The quickest way to see shape, spread and outliers at once.',
    needs: 'One or more numeric columns, at least 8 values each.',
    procedure: 'graphical_summary',
    label: 'Graphical Summary…',
    title: 'Graphical Summary',
    submitLabel: 'Draw graphical summary',
    fields: [
      { name: 'variables', label: 'Variables', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      confidence(),
    ],
    note: 'One window per variable: a histogram with a fitted normal curve, a boxplot, the statistics table including the Anderson-Darling normality p-value, and confidence intervals for the mean and the median.',
  },

  { separator: true },

  {
    id: 'z1',
    icon: 'z1',
    description: 'Tests whether a mean differs from a hypothesised value when the population standard deviation is KNOWN and typed in. If the standard deviation is estimated from the sample — almost always — use 1-Sample t instead.',
    needs: 'One numeric column, a hypothesised mean, and a known standard deviation.',
    procedure: 'z1',
    label: '1-Sample Z…',
    title: '1-Sample Z',
    submitLabel: 'Run 1-Sample Z',
    fields: [
      numCol('column', 'Sample column'),
      { name: 'sigma', label: 'Known standard deviation (σ)', type: 'number', role: 'option', required: true, step: 'any', min: 0, hint: 'Required — this is what makes it a Z test rather than a t test.' },
      { name: 'hypothesized_mean', label: 'Hypothesized mean', type: 'number', role: 'option', default: 0, step: 'any' },
      alternative('μ'),
      confidence(),
      ...testGraphs(),
    ],
  },
  {
    id: 't1',
    icon: 't1',
    description: 'Tests whether a mean differs from a hypothesised value, estimating the standard deviation from the sample itself. The everyday choice; 1-Sample Z applies only when the standard deviation is genuinely known.',
    needs: 'One numeric column and a hypothesised mean.',
    procedure: 't1',
    label: '1-Sample t…',
    title: '1-Sample t',
    submitLabel: 'Run 1-Sample t',
    fields: [
      numCol('column', 'Sample column'),
      { name: 'hypothesized_mean', label: 'Hypothesized mean', type: 'number', role: 'option', default: 0, step: 'any' },
      alternative('μ'),
      confidence(),
      ...testGraphs(),
    ],
  },
  {
    id: 't2',
    icon: 't2',
    description: 'Tests whether the means of two INDEPENDENT groups differ. Uses Welch\'s approximation by default, which does not assume the two groups share a variance; a pooled option is in Options if they do.',
    needs: 'Two numeric columns, or one value column and a group column with 2 levels.',
    procedure: 't2',
    label: '2-Sample t…',
    title: '2-Sample t',
    submitLabel: 'Run 2-Sample t',
    fields: [
      {
        name: 'layout',
        label: 'Data arrangement',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'one_column', label: 'Both samples are in one column, with a group column' },
          { value: 'two_columns', label: 'Each sample is in its own column' },
        ],
        default: 'one_column',
      },
      numCol('value', 'Samples', { showIf: inOneColumn }),
      groupCol('group', 'Sample IDs (group column, exactly 2 levels)', { showIf: inOneColumn }),
      numCol('first', 'Sample 1', { showIf: inTwoColumns }),
      numCol('second', 'Sample 2', { showIf: inTwoColumns }),
      { name: 'equal_variances', label: 'Assume equal variances (pooled standard deviation)', type: 'checkbox', role: 'option', default: false },
      { name: 'hypothesized_difference', label: 'Hypothesized difference (μ₁ − μ₂)', type: 'number', role: 'option', default: 0, step: 'any' },
      alternative('μ₁ − μ₂'),
      confidence(),
      ...testGraphs(),
    ],
  },
  {
    id: 'paired_t',
    icon: 'paired-t',
    description: 'Tests whether the mean DIFFERENCE within pairs is zero — before and after on the same subject, two instruments on the same part. Pairing removes the between-subject variation that a 2-Sample t would have to fight through.',
    needs: 'Two numeric columns of equal length, matched row by row.',
    procedure: 'paired_t',
    label: 'Paired t…',
    title: 'Paired t',
    submitLabel: 'Run Paired t',
    fields: [
      numCol('first', 'Sample 1'),
      numCol('second', 'Sample 2'),
      { name: 'hypothesized_mean', label: 'Hypothesized mean difference', type: 'number', role: 'option', default: 0, step: 'any' },
      alternative('μ_difference'),
      confidence(),
      ...testGraphs(),
    ],
    note: 'Tests the mean of the paired differences (Sample 1 − Sample 2). Rows where either column is empty are dropped.',
  },

  { separator: true },

  {
    id: 'prop1',
    icon: 'prop1',
    description: 'Tests whether a proportion differs from a hypothesised value, and gives a confidence interval for it.',
    needs: 'One column of two outcomes, or an event count and a sample size.',
    procedure: 'prop1',
    label: '1 Proportion…',
    title: '1 Proportion',
    submitLabel: 'Run 1 Proportion',
    fields: [
      {
        name: 'input',
        label: 'Data',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'raw', label: 'One column of two categories' },
          { value: 'summarized', label: 'Summarized data (type the counts)' },
        ],
        default: 'raw',
      },
      anyCol('column', 'Category column', { showIf: isRaw }),
      { name: 'event_value', label: 'Event (which category counts as a success — the second one by default)', type: 'value', role: 'option', required: false, from: 'column', showIf: isRaw },
      { name: 'events', label: 'Number of events', type: 'number', role: 'option', step: 1, min: 0, required: true, showIf: isSummarized },
      { name: 'trials', label: 'Number of trials', type: 'number', role: 'option', step: 1, min: 1, required: true, showIf: isSummarized },
      { name: 'hypothesized_p', label: 'Hypothesized proportion', type: 'number', role: 'option', default: 0.5, step: 'any', min: 0, max: 1 },
      {
        name: 'method',
        label: 'Method',
        type: 'select',
        role: 'option',
        options: [
          { value: 'exact', label: 'Exact (binomial)' },
          { value: 'normal', label: 'Normal approximation' },
        ],
        default: 'exact',
      },
      alternative('p'),
      confidence(),
    ],
  },
  {
    id: 'prop2',
    icon: 'prop2',
    description: 'Tests whether two proportions differ, and gives a confidence interval for the difference.',
    needs: 'Two columns of two outcomes, or two event counts with their sample sizes.',
    procedure: 'prop2',
    label: '2 Proportions…',
    title: '2 Proportions',
    submitLabel: 'Run 2 Proportions',
    fields: [
      {
        name: 'input',
        label: 'Data',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'raw', label: 'Categories in the worksheet' },
          { value: 'summarized', label: 'Summarized data (type the counts)' },
        ],
        default: 'raw',
      },
      {
        name: 'layout',
        label: 'Data arrangement',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'two_columns', label: 'Each sample is in its own column' },
          { value: 'one_column', label: 'Both samples are in one column, with a group column' },
        ],
        default: 'two_columns',
        showIf: isRaw,
      },
      anyCol('value', 'Samples (category column)', { showIf: (v) => isRaw(v) && inOneColumn(v) }),
      groupCol('group', 'Sample IDs (group column, exactly 2 levels)', { showIf: (v) => isRaw(v) && inOneColumn(v) }),
      anyCol('first', 'Sample 1 (category column)', { showIf: (v) => isRaw(v) && inTwoColumns(v) }),
      anyCol('second', 'Sample 2 (category column)', { showIf: (v) => isRaw(v) && inTwoColumns(v) }),
      { name: 'event_value', label: 'Event (which category counts as a success)', type: 'value', role: 'option', required: false, from: 'value', fallbackFrom: 'first', showIf: isRaw },
      { name: 'events1', label: 'Sample 1 — events', type: 'number', role: 'option', step: 1, min: 0, required: true, showIf: isSummarized },
      { name: 'trials1', label: 'Sample 1 — trials', type: 'number', role: 'option', step: 1, min: 1, required: true, showIf: isSummarized },
      { name: 'events2', label: 'Sample 2 — events', type: 'number', role: 'option', step: 1, min: 0, required: true, showIf: isSummarized },
      { name: 'trials2', label: 'Sample 2 — trials', type: 'number', role: 'option', step: 1, min: 1, required: true, showIf: isSummarized },
      { name: 'hypothesized_difference', label: 'Hypothesized difference (p₁ − p₂)', type: 'number', role: 'option', default: 0, step: 'any' },
      { name: 'pooled', label: 'Use the pooled estimate of p for the test', type: 'checkbox', role: 'option', default: false, hint: 'Only applies when the hypothesized difference is 0.' },
      { name: 'fisher', label: "Also report Fisher's exact test", type: 'checkbox', role: 'option', default: false },
      alternative('p₁ − p₂'),
      confidence(),
    ],
  },

  { separator: true },

  {
    id: 'poisson1',
    icon: 'poisson-rate-1',
    description: 'Tests whether a rate of occurrence differs from a hypothesised rate — defects per unit, calls per hour. Use it for counts over an interval rather than for a proportion of trials.',
    needs: 'One column of counts, and the length of the interval each count covers.',
    procedure: 'poisson1',
    label: '1-Sample Poisson Rate…',
    title: '1-Sample Poisson Rate',
    submitLabel: 'Run 1-Sample Poisson Rate',
    fields: [
      {
        name: 'input',
        label: 'Data',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'raw', label: 'One column of counts' },
          { value: 'summarized', label: 'Summarized data (type the totals)' },
        ],
        default: 'raw',
      },
      numCol('column', 'Counts column', { showIf: isRaw }),
      { name: 'occurrences', label: 'Total occurrences', type: 'number', role: 'option', step: 1, min: 0, required: true, showIf: isSummarized },
      { name: 'observations', label: 'Sample size (number of observations)', type: 'number', role: 'option', step: 1, min: 1, required: true, showIf: isSummarized },
      { name: 'length', label: 'Length of observation', type: 'number', role: 'option', default: 1, step: 'any', min: 0, hint: 'Exposure per observation — leave at 1 for counts per row.' },
      { name: 'hypothesized_rate', label: 'Hypothesized rate', type: 'number', role: 'option', default: 1, step: 'any', min: 0 },
      {
        name: 'method',
        label: 'Method',
        type: 'select',
        role: 'option',
        options: [
          { value: 'exact', label: 'Exact (conditional Poisson)' },
          { value: 'normal', label: 'Normal approximation' },
        ],
        default: 'exact',
      },
      alternative('rate'),
      confidence(),
    ],
  },
  {
    id: 'poisson2',
    icon: 'poisson-rate-2',
    description: 'Tests whether two rates of occurrence differ, and gives a confidence interval for the difference or the ratio.',
    needs: 'Two columns of counts and the interval length each covers.',
    procedure: 'poisson2',
    label: '2-Sample Poisson Rate…',
    title: '2-Sample Poisson Rate',
    submitLabel: 'Run 2-Sample Poisson Rate',
    fields: [
      {
        name: 'input',
        label: 'Data',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'raw', label: 'Two columns of counts' },
          { value: 'summarized', label: 'Summarized data (type the totals)' },
        ],
        default: 'raw',
      },
      numCol('first', 'Sample 1 counts', { showIf: isRaw }),
      numCol('second', 'Sample 2 counts', { showIf: isRaw }),
      { name: 'length', label: 'Length of observation', type: 'number', role: 'option', default: 1, step: 'any', min: 0, showIf: isRaw },
      { name: 'occurrences1', label: 'Sample 1 — total occurrences', type: 'number', role: 'option', step: 1, min: 0, required: true, showIf: isSummarized },
      { name: 'observations1', label: 'Sample 1 — sample size', type: 'number', role: 'option', step: 1, min: 1, required: true, showIf: isSummarized },
      { name: 'length1', label: 'Sample 1 — length of observation', type: 'number', role: 'option', default: 1, step: 'any', min: 0, showIf: isSummarized },
      { name: 'occurrences2', label: 'Sample 2 — total occurrences', type: 'number', role: 'option', step: 1, min: 0, required: true, showIf: isSummarized },
      { name: 'observations2', label: 'Sample 2 — sample size', type: 'number', role: 'option', step: 1, min: 1, required: true, showIf: isSummarized },
      { name: 'length2', label: 'Sample 2 — length of observation', type: 'number', role: 'option', default: 1, step: 'any', min: 0, showIf: isSummarized },
      { name: 'hypothesized_difference', label: 'Hypothesized difference (rate₁ − rate₂)', type: 'number', role: 'option', default: 0, step: 'any' },
      {
        name: 'method',
        label: 'Method',
        type: 'select',
        role: 'option',
        options: [
          { value: 'exact', label: 'Exact (E-test)' },
          { value: 'normal', label: 'Normal approximation' },
        ],
        default: 'exact',
      },
      alternative('rate₁ − rate₂'),
      confidence(),
    ],
  },

  { separator: true },

  {
    id: 'var1',
    icon: 'var1',
    description: 'Tests whether a standard deviation or variance differs from a hypothesised value. Reports both the chi-square test, which assumes normality, and Bonett\'s test, which does not.',
    needs: 'One numeric column and a hypothesised standard deviation or variance.',
    procedure: 'var1',
    label: '1 Variance…',
    title: '1 Variance',
    submitLabel: 'Run 1 Variance',
    fields: [
      {
        name: 'input',
        label: 'Data',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'raw', label: 'One column of values' },
          { value: 'summarized', label: 'Summarized data (type the sample variance)' },
        ],
        default: 'raw',
      },
      numCol('column', 'Sample column', { showIf: isRaw }),
      { name: 'sample_size', label: 'Sample size', type: 'number', role: 'option', step: 1, min: 2, required: true, showIf: isSummarized },
      {
        name: 'sample_kind',
        label: 'The sample value entered is a',
        type: 'select',
        role: 'option',
        options: [
          { value: 'variance', label: 'variance' },
          { value: 'stdev', label: 'standard deviation' },
        ],
        default: 'variance',
        showIf: isSummarized,
      },
      { name: 'sample_value', label: 'Sample variance / standard deviation', type: 'number', role: 'option', step: 'any', min: 0, required: true, showIf: isSummarized },
      {
        name: 'hypothesized_kind',
        label: 'The hypothesized value is a',
        type: 'select',
        role: 'option',
        options: [
          { value: 'variance', label: 'variance (σ²)' },
          { value: 'stdev', label: 'standard deviation (σ)' },
        ],
        default: 'variance',
      },
      { name: 'hypothesized_value', label: 'Hypothesized value', type: 'number', role: 'option', default: 1, step: 'any', min: 0, required: true },
      alternative('σ'),
      confidence(),
      ...testGraphs(),
    ],
    note: 'Both the chi-square method (which assumes normality) and Bonett’s kurtosis-adjusted method are reported when the raw data are available.',
  },
  {
    id: 'var2',
    icon: 'var2',
    description: 'Tests whether two groups have the same variance — often as a check before deciding whether a pooled 2-Sample t is defensible. For more than two groups, use Test for Equal Variances under ANOVA.',
    needs: 'Two numeric columns, or one value column and a group column with 2 levels.',
    procedure: 'var2',
    label: '2 Variances…',
    title: '2 Variances',
    submitLabel: 'Run 2 Variances',
    fields: [
      {
        name: 'layout',
        label: 'Data arrangement',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'one_column', label: 'Both samples are in one column, with a group column' },
          { value: 'two_columns', label: 'Each sample is in its own column' },
        ],
        default: 'one_column',
      },
      numCol('value', 'Samples', { showIf: inOneColumn }),
      groupCol('group', 'Sample IDs (group column, exactly 2 levels)', { showIf: inOneColumn }),
      numCol('first', 'Sample 1', { showIf: inTwoColumns }),
      numCol('second', 'Sample 2', { showIf: inTwoColumns }),
      alternative('σ₁² / σ₂²'),
      confidence(),
      ...testGraphs(),
    ],
    note: "The F-test and Levene's test are both reported, side by side in one table.",
  },

  { separator: true },

  {
    id: 'correlation',
    icon: 'correlation',
    description: 'Measures how strongly pairs of columns move together, on a scale of −1 to 1, with a p-value for each pair. Pearson by default; Spearman ranks the values first, which suits monotonic but non-linear relationships.',
    needs: 'Two or more numeric columns.',
    procedure: 'correlation',
    label: 'Correlation…',
    title: 'Correlation',
    submitLabel: 'Run correlation',
    fields: [
      { name: 'variables', label: 'Variables (2 or more)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 2 },
      {
        name: 'method',
        label: 'Method',
        type: 'select',
        role: 'option',
        options: [
          { value: 'pearson', label: 'Pearson correlation' },
          { value: 'spearman', label: 'Spearman rank correlation' },
        ],
        default: 'pearson',
      },
      { name: 'graph_matrix_plot', label: 'Matrix plot of the variables', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
      confidence(),
    ],
  },
  {
    id: 'covariance',
    icon: 'covariance',
    description: 'Reports the covariance matrix — the same relationships correlation measures, but in the original units rather than scaled to −1 to 1. Correlation is easier to read; covariance is what a later matrix calculation usually wants.',
    needs: 'Two or more numeric columns.',
    procedure: 'covariance',
    label: 'Covariance…',
    title: 'Covariance',
    submitLabel: 'Run covariance',
    fields: [{ name: 'variables', label: 'Variables (2 or more)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 2 }],
  },

  { separator: true },

  {
    id: 'normality',
    icon: 'normality-test',
    description: 'Tests whether a column could plausibly have come from a normal distribution, and draws the probability plot to show HOW it departs. Anderson-Darling by default, which is the most sensitive of the three to the tails.',
    needs: 'One numeric column, at least 8 values.',
    procedure: 'normality',
    label: 'Normality Test…',
    title: 'Normality Test',
    submitLabel: 'Run normality test',
    fields: [
      numCol('column', 'Variable'),
      {
        name: 'method',
        label: 'Test for normality',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'anderson_darling', label: 'Anderson-Darling' },
          { value: 'kolmogorov_smirnov', label: 'Kolmogorov-Smirnov' },
          { value: 'shapiro_wilk', label: 'Shapiro-Wilk' },
        ],
        default: 'anderson_darling',
        hint: 'Shapiro-Wilk stands in for Minitab’s Ryan-Joiner test: Ryan-Joiner is proprietary, and Shapiro-Wilk is the equivalent regression-of-order-statistics test.',
      },
      confidence(),
    ],
  },
  {
    id: 'outlier',
    icon: 'outlier-test',
    description: 'Tests whether the most extreme value in a small sample is a genuine outlier rather than ordinary variation. Grubbs\' test by default; Dixon\'s Q is offered for n up to 30 and reads against published tables.',
    needs: 'One numeric column, 3 to 30 or so values.',
    procedure: 'outlier',
    label: 'Outlier Test…',
    title: 'Outlier Test',
    submitLabel: 'Run outlier test',
    fields: [
      numCol('column', 'Variable'),
      {
        name: 'method',
        label: 'Test',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'grubbs', label: "Grubbs' test (any sample size)" },
          { value: 'dixon', label: "Dixon's Q test (n ≤ 30)" },
        ],
        default: 'grubbs',
      },
      confidence(),
    ],
    note: "The most extreme value is tested. Grubbs' test reports a p-value; Dixon's Q is compared against tabulated critical values, because it has no closed-form p-value.",
  },
  {
    id: 'poisson_gof',
    icon: 'poisson-gof',
    description: 'Tests whether a column of counts is consistent with a Poisson distribution, by comparing the observed frequencies against the ones a Poisson with the same mean would give. Worth running before trusting a Poisson rate test or Poisson regression.',
    needs: 'One column of counts.',
    procedure: 'poisson_gof',
    label: 'Goodness-of-Fit Test for Poisson…',
    title: 'Goodness-of-Fit Test for Poisson',
    submitLabel: 'Run goodness-of-fit test',
    fields: [numCol('column', 'Variable (a column of counts)'), confidence()],
    note: 'The Poisson mean is estimated from the data, and categories with an expected count below 5 are combined — the same rule Minitab applies.',
  },
];

export const PROCEDURE_BY_ID = Object.fromEntries(PROCEDURES.filter((p) => p.id).map((p) => [p.id, p]));

// The Basic Statistics flyout, in Minitab's own order and with its dividers.
export const BASIC_STATS_MENU = PROCEDURES.map((p) =>
  p.separator ? { separator: true } : { label: p.label, stat: p.id, icon: p.icon, description: p.description, needs: p.needs },
);

// ---------------------------------------------------------------------------
// values -> request
// ---------------------------------------------------------------------------


// Defaults, visibility and validation are the shared engine's — imported and re-exported so this
// registry stays the single place a dialog is described.
export { visibleFields, defaultValues, validate } from './procedureDialog.js';

export function buildRequest(config, values) {
  const columns = [];
  const options = {};
  for (const field of visible(config, values)) {
    const value = values[field.name];
    if (field.role === 'column') {
      if (value) columns.push(value);
    } else if (field.role === 'columns') {
      columns.push(...(value || []));
    } else if (field.type === 'checkbox') {
      if (value) options[field.name] = true;
    } else if (value !== '' && value !== undefined && value !== null) {
      options[field.name] = field.type === 'number' ? Number(value) : value;
    }
  }
  return { procedure: config.procedure, columns, options };
}

// One-line description for the window title and the Session Window entry.
export function describe(config, values) {
  const parts = [];
  for (const field of visible(config, values)) {
    const value = values[field.name];
    if (field.role !== 'column' && field.role !== 'columns') continue;
    if (Array.isArray(value) && value.length) parts.push(value.join(', '));
    else if (value) parts.push(String(value));
  }
  const name = config.label.replace(/…$/, '');
  return parts.length ? `${name} (${parts.join('; ')})` : name;
}
