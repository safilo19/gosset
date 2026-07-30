// Every item on the Calc menu, declared once: form fields, the backend procedure, and how the
// inputs turn into a request. Same split as basicStatsConfig.js / regressionConfig.js /
// anovaConfig.js / dataMenuConfig.js.
//
// The Calculator itself is NOT here — it is a bespoke window (calc.js) because its column list,
// function browser and live validation are not a form the generic builder can describe. Everything
// else is an ordinary registry entry.
//
// The distribution dialogs are generated: one entry per distribution in the Random Data and
// Probability Distributions submenus, all opening the same form preset to that distribution, with
// the parameter fields built at run time from the catalogue the backend serves.

import { visibleFields as visible } from './procedureDialog.js';

// ---------------------------------------------------------------------------
// field shorthands
// ---------------------------------------------------------------------------

const numCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'numeric', required: true, ...extra });
const anyCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'any', required: true, ...extra });
const storeIn = (label = 'Store result in', extra = {}) => ({ name: 'store_in', label, type: 'text', role: 'option', required: true, ...extra });

const repeatFields = () => [
  { name: 'repeat_each', label: 'Repeat each value this many times', type: 'number', role: 'option', default: 1, min: 1, step: 1, advanced: true },
  { name: 'repeat_whole', label: 'Repeat the whole sequence this many times', type: 'number', role: 'option', default: 1, min: 1, step: 1, advanced: true },
];

const STATISTIC_OPTIONS = [
  { value: 'sum', label: 'Sum' },
  { value: 'mean', label: 'Mean' },
  { value: 'stdev', label: 'Standard deviation' },
  { value: 'variance', label: 'Variance' },
  { value: 'median', label: 'Median' },
  { value: 'minimum', label: 'Minimum' },
  { value: 'maximum', label: 'Maximum' },
  { value: 'range', label: 'Range' },
  { value: 'n', label: 'N (non-missing)' },
  { value: 'n_missing', label: 'N missing' },
  { value: 'sum_of_squares', label: 'Sum of squares' },
];

const resampleFields = () => [
  { name: 'resamples', label: 'Number of resamples', type: 'number', role: 'option', default: 1000, min: 50, max: 100000, step: 1 },
  { name: 'confidence', label: 'Confidence level', type: 'number', role: 'option', default: 0.95, min: 0.5, max: 0.999, step: 'any', advanced: true },
];

const alternativeField = () => ({
  name: 'alternative',
  label: 'Alternative hypothesis',
  type: 'select',
  role: 'option',
  options: [
    { value: 'two-sided', label: 'Two-sided — different in either direction' },
    { value: 'less', label: 'Less than the hypothesized value' },
    { value: 'greater', label: 'Greater than the hypothesized value' },
  ],
  default: 'two-sided',
});

const twoSampleLayout = () => [
  {
    name: 'layout',
    label: 'Data are arranged as',
    type: 'radio',
    role: 'option',
    options: [
      { value: 'one_column', label: 'Values in one column, groups in another' },
      { value: 'two_columns', label: 'One column per sample' },
    ],
    default: 'one_column',
  },
  numCol('value', 'Values', { showIf: (v) => v.layout !== 'two_columns' }),
  anyCol('group', 'Group column (exactly two groups)', { showIf: (v) => v.layout !== 'two_columns' }),
  numCol('sample_a', 'First sample', { showIf: (v) => v.layout === 'two_columns' }),
  numCol('sample_b', 'Second sample', { showIf: (v) => v.layout === 'two_columns' }),
];

const matrixPick = (name, label, extra = {}) => ({ name, label, type: 'matrix', role: 'option', required: true, ...extra });

// ---------------------------------------------------------------------------
// the procedures
// ---------------------------------------------------------------------------

export const PROCEDURES = [
  {
    id: 'calculator',
    icon: 'calculator',
    label: 'Calculator…',
    title: 'Calculator',
    bespoke: true,
    description:
      'Builds a new column or a constant from an expression over the existing columns, with 49 functions in a browsable list. Expressions are validated on the server as they are typed, and the error points at the character it objects to.',
    needs: 'An expression, and a column or constant to store the result in.',
  },
  {
    id: 'column_statistics',
    icon: 'column-statistics',
    description: 'Reduces a column to one number — its mean, sum, standard deviation, minimum and so on — and can store the answer as a constant. It works down a column; Row Statistics works across a row.',
    needs: 'One numeric column.',
    procedure: 'column_statistics',
    label: 'Column Statistics…',
    title: 'Column Statistics',
    submitLabel: 'Compute',
    fields: [
      { name: 'statistic', label: 'Statistic', type: 'radio', role: 'option', options: STATISTIC_OPTIONS, default: 'mean' },
      numCol('column', 'Input variable'),
      { name: 'store_in', label: 'Store result in (optional constant)', type: 'text', role: 'option', placeholder: 'K1', hint: 'Leave blank to send the answer to the Session Window only.' },
    ],
    note: 'The statistic is computed down the column. Missing values are left out of every statistic except "N missing".',
  },
  {
    id: 'row_statistics',
    icon: 'row-statistics',
    description: 'Works across each row and writes one value per row into a new column, so several measurements per record become their mean, total or range.',
    needs: 'Two or more numeric columns.',
    procedure: 'row_statistics',
    label: 'Row Statistics…',
    title: 'Row Statistics',
    submitLabel: 'Compute',
    fields: [
      { name: 'statistic', label: 'Statistic', type: 'radio', role: 'option', options: STATISTIC_OPTIONS, default: 'mean' },
      { name: 'columns', label: 'Input variables', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      storeIn('Store result in', { placeholder: 'row mean' }),
    ],
    note: 'The statistic is computed across each row, giving one value per row.',
  },
  {
    id: 'standardize',
    icon: 'standardize',
    description: 'Rescales a column so different measurements can be compared or fed to a distance-based method. Five methods, including the usual z-score (subtract the mean, divide by the standard deviation) and scaling to a 0–1 range.',
    needs: 'One or more numeric columns.',
    procedure: 'standardize',
    label: 'Standardize…',
    title: 'Standardize',
    submitLabel: 'Standardize',
    fields: [
      { name: 'columns', label: 'Input columns', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      {
        name: 'method',
        label: 'Method',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'z', label: 'Subtract mean and divide by standard deviation (z-scores)' },
          { value: 'subtract_mean', label: 'Subtract mean only' },
          { value: 'divide_sd', label: 'Divide by standard deviation only' },
          { value: 'subtract_divide', label: 'Subtract a value, then divide by a value' },
          { value: 'range', label: 'Scale to a range' },
        ],
        default: 'z',
      },
      { name: 'subtract', label: 'Subtract', type: 'number', role: 'option', step: 'any', default: 0, showIf: (v) => v.method === 'subtract_divide' },
      { name: 'divide', label: 'Divide by', type: 'number', role: 'option', step: 'any', default: 1, showIf: (v) => v.method === 'subtract_divide' },
      { name: 'range_low', label: 'Range from', type: 'number', role: 'option', step: 'any', default: 0, showIf: (v) => v.method === 'range' },
      { name: 'range_high', label: 'Range to', type: 'number', role: 'option', step: 'any', default: 1, showIf: (v) => v.method === 'range' },
      { name: 'store_in', label: 'Store in', type: 'names', role: 'option', from: 'columns', placeholder: 'new column name (optional)', advanced: true },
      { name: 'suffix', label: 'Suffix for unnamed columns', type: 'text', role: 'option', default: '_std', advanced: true },
    ],
  },
  { separator: true },
  {
    id: 'patterned_numbers',
    icon: 'patterned-numbers',
    description: 'Fills a column with a regular sequence — from 1 to 100 in steps of 1 — repeating whole values or the whole sequence as many times as needed. The usual way to build the run order or the subscripts of a design.',
    procedure: 'patterned_numbers',
    label: 'Simple Set of Numbers…',
    title: 'Simple Set of Numbers',
    submitLabel: 'Generate',
    group: 'Make Patterned Data',
    fields: [
      storeIn('Store patterned data in', { placeholder: 'C1' }),
      { name: 'from', label: 'From first value', type: 'number', role: 'option', step: 'any', default: 1, required: true },
      { name: 'to', label: 'To last value', type: 'number', role: 'option', step: 'any', default: 10, required: true },
      { name: 'step', label: 'In steps of', type: 'number', role: 'option', step: 'any', default: 1, required: true },
      ...repeatFields(),
    ],
    note: 'Both repeat controls apply: each value is repeated first, then the whole sequence.',
  },
  {
    id: 'patterned_arbitrary',
    icon: 'patterned-arbitrary',
    description: 'Fills a column by repeating a typed list of numbers, rather than a regular sequence.',
    procedure: 'patterned_arbitrary',
    label: 'Arbitrary Set of Numbers…',
    title: 'Arbitrary Set of Numbers',
    submitLabel: 'Generate',
    group: 'Make Patterned Data',
    fields: [
      storeIn('Store patterned data in', { placeholder: 'C1' }),
      { name: 'values', label: 'Numbers', type: 'text', role: 'option', mono: true, required: true, placeholder: '1 4 9 16 25', hint: 'Separated by spaces or commas.' },
      ...repeatFields(),
    ],
  },
  {
    id: 'patterned_text',
    icon: 'patterned-text',
    description: 'Fills a column by repeating a list of text values, which is how a factor column of level names gets built.',
    procedure: 'patterned_text',
    label: 'Text Values…',
    title: 'Text Values',
    submitLabel: 'Generate',
    group: 'Make Patterned Data',
    fields: [
      storeIn('Store patterned data in', { placeholder: 'C1' }),
      { name: 'values', label: 'Text values', type: 'text', role: 'option', required: true, placeholder: 'low, medium, high', hint: 'Separated by commas, so a label may contain spaces.' },
      ...repeatFields(),
    ],
  },
  {
    id: 'patterned_datetime',
    icon: 'patterned-datetime',
    description: 'Fills a column with a regular sequence of dates or times — every day, every third hour — between a start and an end.',
    procedure: 'patterned_datetime',
    label: 'Simple Set of Date/Time Values…',
    title: 'Simple Set of Date/Time Values',
    submitLabel: 'Generate',
    group: 'Make Patterned Data',
    fields: [
      storeIn('Store patterned data in', { placeholder: 'C1' }),
      { name: 'mode', label: 'Values', type: 'text', role: 'option', default: 'simple', omitFromForm: true },
      { name: 'from', label: 'From first date/time', type: 'text', role: 'option', mono: true, required: true, placeholder: '2024-01-01' },
      { name: 'to', label: 'To last date/time', type: 'text', role: 'option', mono: true, required: true, placeholder: '2024-12-31' },
      {
        name: 'unit',
        label: 'In steps of',
        type: 'select',
        role: 'option',
        options: [
          { value: 'day', label: 'Day' },
          { value: 'week', label: 'Week' },
          { value: 'month', label: 'Month' },
          { value: 'quarter', label: 'Quarter' },
          { value: 'year', label: 'Year' },
          { value: 'hour', label: 'Hour' },
          { value: 'minute', label: 'Minute' },
          { value: 'second', label: 'Second' },
        ],
        default: 'day',
      },
      { name: 'step_count', label: 'How many of those per step', type: 'number', role: 'option', default: 1, min: 1, step: 1, advanced: true },
      ...repeatFields(),
    ],
  },
  {
    id: 'patterned_datetime_arbitrary',
    icon: 'patterned-datetime-arbitrary',
    description: 'Fills a column by repeating a typed list of dates or times, rather than a regular sequence.',
    procedure: 'patterned_datetime',
    label: 'Arbitrary Set of Date/Time Values…',
    title: 'Arbitrary Set of Date/Time Values',
    submitLabel: 'Generate',
    group: 'Make Patterned Data',
    fields: [
      storeIn('Store patterned data in', { placeholder: 'C1' }),
      { name: 'mode', label: 'Values', type: 'text', role: 'option', default: 'arbitrary', omitFromForm: true },
      { name: 'values', label: 'Dates', type: 'text', role: 'option', mono: true, required: true, placeholder: '2024-01-31, 2024-06-30, 2024-12-31', hint: 'Separated by commas or newlines.' },
      ...repeatFields(),
    ],
  },
  {
    id: 'mesh_data',
    icon: 'mesh-data',
    description: 'Builds the full grid of x and y pairs over two ranges, which is the input a contour or surface plot needs when the data does not already cover a grid.',
    procedure: 'mesh_data',
    label: 'Make Mesh Data…',
    title: 'Make Mesh Data',
    submitLabel: 'Generate mesh',
    fields: [
      { name: 'store_in', label: 'Store X and Y in', type: 'text-pair', role: 'option', required: true, labels: ['X column', 'Y column'], default: ['X', 'Y'] },
      { name: 'x_from', label: 'X from', type: 'number', role: 'option', step: 'any', default: 0, group: 'X axis' },
      { name: 'x_to', label: 'X to', type: 'number', role: 'option', step: 'any', default: 10, group: 'X axis' },
      { name: 'x_step', label: 'X step', type: 'number', role: 'option', step: 'any', default: 1, group: 'X axis' },
      { name: 'y_from', label: 'Y from', type: 'number', role: 'option', step: 'any', default: 0, group: 'Y axis' },
      { name: 'y_to', label: 'Y to', type: 'number', role: 'option', step: 'any', default: 10, group: 'Y axis' },
      { name: 'y_step', label: 'Y step', type: 'number', role: 'option', step: 'any', default: 1, group: 'Y axis' },
    ],
    note: 'Every combination of the two axes, one row each — the input a contour or surface plot needs.',
  },
  {
    id: 'indicator_variables',
    icon: 'indicator-variables',
    description: 'Turns one category column into a set of 0/1 columns, one per level, so a categorical predictor can be used by a method that only takes numbers.',
    needs: 'One column with a manageable number of distinct values.',
    procedure: 'indicator_variables',
    label: 'Make Indicator Variables…',
    title: 'Make Indicator Variables',
    submitLabel: 'Create indicator columns',
    fields: [
      anyCol('column', 'Categorical column'),
      { name: 'drop_first', label: 'Leave out the first level as a reference', type: 'checkbox', role: 'option', default: false, hint: 'Regression models need one level left out; a plain dummy coding does not.' },
    ],
    note: 'One 0/1 column per level, named like "region_West".',
  },
  { separator: true },
  {
    id: 'set_base',
    icon: 'set-base',
    label: 'Set Base…',
    title: 'Set Base',
    bespoke: true,
    description:
      'Fixes the starting point of the random number generator, so that Random Data and the resampling tests produce the same numbers next time. Set it before generating anything that has to be reproducible.',
  },
  { separator: true },
  {
    id: 'sample_columns',
    icon: 'sample-columns',
    description: 'Draws a random sample of rows from the chosen columns, with or without replacement, keeping each row intact.',
    needs: 'One or more columns and a sample size.',
    procedure: 'sample_columns',
    label: 'Sample From Columns…',
    title: 'Sample From Columns',
    submitLabel: 'Sample rows',
    group: 'Random Data',
    fields: [
      { name: 'rows', label: 'Number of rows to sample', type: 'number', role: 'option', default: 10, min: 1, step: 1, required: true },
      { name: 'columns', label: 'From columns', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 1 },
      { name: 'store_in', label: 'Store samples in', type: 'names', role: 'option', from: 'columns', placeholder: 'new column name (optional)' },
      { name: 'replace', label: 'Sample with replacement', type: 'checkbox', role: 'option', default: false },
    ],
    note: 'Whole rows are drawn, so the sampled columns stay aligned with each other.',
  },
  { separator: true },
  {
    id: 'bootstrap_1sample',
    icon: 'bootstrap-1sample',
    description: 'Resamples one column with replacement many times and shows the distribution of a statistic — mean, median, standard deviation or proportion. Use it for a confidence interval when the sample is small or plainly not normal.',
    needs: 'One numeric column.',
    procedure: 'bootstrap_1sample',
    label: 'Bootstrapping for 1-Sample Function…',
    title: 'Bootstrapping for a 1-Sample Function',
    submitLabel: 'Run bootstrap',
    group: 'Resampling',
    fields: [
      anyCol('column', 'Sample column'),
      {
        name: 'statistic',
        label: 'Statistic to bootstrap',
        type: 'select',
        role: 'option',
        options: [
          { value: 'mean', label: 'Mean' },
          { value: 'median', label: 'Median' },
          { value: 'stdev', label: 'Standard deviation' },
          { value: 'variance', label: 'Variance' },
          { value: 'sum', label: 'Sum' },
          { value: 'minimum', label: 'Minimum' },
          { value: 'maximum', label: 'Maximum' },
          { value: 'range', label: 'Range' },
          { value: 'proportion', label: 'Proportion of an event' },
        ],
        default: 'mean',
      },
      { name: 'event', label: 'Which value counts as the event', type: 'value', role: 'option', from: 'column', showIf: (v) => v.statistic === 'proportion', emptyLabel: '— the second of two values —' },
      ...resampleFields(),
    ],
    note: 'Resamples the column with replacement and reports the bootstrap standard error and a percentile confidence interval.',
  },
  {
    id: 'bootstrap_2sample',
    icon: 'bootstrap-2sample',
    description: 'Resamples two groups with replacement many times and shows the distribution of the difference between their means, with a bootstrap confidence interval for that difference.',
    needs: 'Two numeric columns, or one value column and a group column with 2 levels.',
    procedure: 'bootstrap_2sample',
    label: 'Bootstrapping for 2-Sample Means…',
    title: 'Bootstrapping for 2-Sample Means',
    submitLabel: 'Run bootstrap',
    group: 'Resampling',
    fields: [...twoSampleLayout(), ...resampleFields()],
    note: 'Each sample is resampled at its own size; the statistic is the difference in means.',
  },
  {
    id: 'randomization_1mean',
    icon: 'randomization-1mean',
    description: 'Tests a hypothesised mean by shuffling the signs of the deviations many times and asking how often chance alone produces a mean as far from it as the observed one. The distribution-free counterpart of the 1-Sample t.',
    needs: 'One numeric column and a hypothesised mean.',
    procedure: 'randomization_1mean',
    label: 'Randomization Test for 1-Sample Mean…',
    title: 'Randomization Test for a 1-Sample Mean',
    submitLabel: 'Run randomization test',
    group: 'Resampling',
    fields: [
      numCol('column', 'Sample column'),
      { name: 'null_value', label: 'Hypothesized mean', type: 'number', role: 'option', step: 'any', default: 0, required: true },
      alternativeField(),
      ...resampleFields(),
    ],
    note: 'Minitab’s shift-and-resample: the sample is shifted so its mean equals the hypothesized value, then resampled — which builds the null distribution out of this very data.',
  },
  {
    id: 'randomization_1proportion',
    icon: 'randomization-1proportion',
    description: 'Tests a hypothesised proportion by simulating that many draws over and over and counting how often chance alone gets as far from it as the observed proportion.',
    needs: 'One column of two outcomes, or an event count and a sample size.',
    procedure: 'randomization_1proportion',
    label: 'Randomization Test for 1-Sample Proportion…',
    title: 'Randomization Test for a 1-Sample Proportion',
    submitLabel: 'Run randomization test',
    group: 'Resampling',
    fields: [
      anyCol('column', 'Sample column'),
      { name: 'event', label: 'Which value counts as the event', type: 'value', role: 'option', from: 'column', emptyLabel: '— the second of two values —' },
      { name: 'null_value', label: 'Hypothesized proportion', type: 'number', role: 'option', step: 'any', default: 0.5, min: 0.001, max: 0.999, required: true },
      alternativeField(),
      ...resampleFields(),
    ],
  },
  {
    id: 'randomization_2means',
    icon: 'randomization-2means',
    description: 'Tests whether two groups differ by reshuffling which group each value belongs to many times, building the distribution of the difference under the assumption that the labels do not matter. The distribution-free counterpart of the 2-Sample t.',
    needs: 'Two numeric columns, or one value column and a group column with 2 levels.',
    procedure: 'randomization_2means',
    label: 'Randomization Test for 2-Sample Means…',
    title: 'Randomization Test for 2-Sample Means',
    submitLabel: 'Run randomization test',
    group: 'Resampling',
    fields: [...twoSampleLayout(), alternativeField(), ...resampleFields()],
    note: 'A permutation test: under the null hypothesis the group labels carry no information, so reshuffling them builds the null distribution exactly.',
  },
  { separator: true },
  {
    id: 'matrix_from_columns',
    icon: 'matrix-import',
    description: 'Reads worksheet columns into a stored matrix M1, M2, … so the other matrix operations can work on them.',
    needs: 'Two or more numeric columns of equal length.',
    procedure: 'matrix_from_columns',
    label: 'Import…',
    title: 'Import Columns into a Matrix',
    submitLabel: 'Build matrix',
    group: 'Matrices',
    fields: [
      { name: 'columns', label: 'Columns (each becomes a matrix column)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      storeIn('Store matrix in', { placeholder: 'M1', hint: 'Type an existing name to overwrite it, or leave a new one to create it.' }),
    ],
    note: 'Rows where any chosen column is missing are left out, because a matrix has no missing value.',
  },
  {
    id: 'matrix_to_columns',
    icon: 'matrix-export',
    description: 'Writes a stored matrix out into worksheet columns, one column per matrix column.',
    needs: 'At least one stored matrix.',
    procedure: 'matrix_to_columns',
    label: 'Export…',
    title: 'Export a Matrix to Columns',
    submitLabel: 'Write columns',
    group: 'Matrices',
    fields: [
      matrixPick('matrix', 'Matrix'),
      { name: 'store_in', label: 'Store columns in', type: 'text', role: 'option', placeholder: 'M1_c1 M1_c2', hint: 'Names separated by spaces. Leave blank to name them after the matrix.' },
    ],
  },
  {
    id: 'matrix_transpose',
    icon: 'matrix-transpose',
    description: 'Stores the transpose of a matrix, turning its rows into columns.',
    needs: 'One stored matrix.',
    procedure: 'matrix_transpose',
    label: 'Transpose…',
    title: 'Transpose a Matrix',
    submitLabel: 'Transpose',
    group: 'Matrices',
    fields: [matrixPick('matrix', 'Matrix'), storeIn('Store result in', { placeholder: 'M2' })],
  },
  {
    id: 'matrix_invert',
    icon: 'matrix-invert',
    description: 'Stores the inverse of a square matrix. Fails, with a message, on a matrix that is singular.',
    needs: 'One square stored matrix.',
    procedure: 'matrix_invert',
    label: 'Invert…',
    title: 'Invert a Matrix',
    submitLabel: 'Invert',
    group: 'Matrices',
    fields: [matrixPick('matrix', 'Matrix (must be square)'), storeIn('Store result in', { placeholder: 'M2' })],
    note: 'A singular matrix has no inverse; the message says so and reports the determinant rather than returning nonsense.',
  },
  {
    id: 'matrix_diagonal',
    icon: 'matrix-diagonal',
    description: 'Takes the diagonal of a matrix out into a column, or builds a diagonal matrix from a column.',
    needs: 'One stored matrix or one numeric column.',
    procedure: 'matrix_diagonal',
    label: 'Diagonal…',
    title: 'Matrix Diagonal',
    submitLabel: 'Extract or build',
    group: 'Matrices',
    fields: [
      {
        name: 'direction',
        label: 'Do what',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'extract', label: 'Take a matrix’s diagonal into a worksheet column' },
          { value: 'build', label: 'Build a diagonal matrix from a worksheet column' },
        ],
        default: 'extract',
      },
      matrixPick('matrix', 'Matrix', { showIf: (v) => v.direction === 'extract' }),
      numCol('column', 'Column', { showIf: (v) => v.direction === 'build' }),
      storeIn('Store result in', { placeholder: 'diagonal' }),
    ],
  },
  {
    id: 'matrix_define',
    icon: 'matrix-define',
    description: 'Creates a matrix by typing its values, row by row.',
    procedure: 'matrix_define',
    label: 'Define Constant…',
    title: 'Define a Constant Matrix',
    submitLabel: 'Define matrix',
    group: 'Matrices',
    fields: [
      {
        name: 'kind',
        label: 'Matrix',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'identity', label: 'Identity — 1 on the diagonal, 0 elsewhere' },
          { value: 'constant', label: 'Every element the same value' },
        ],
        default: 'identity',
      },
      { name: 'rows', label: 'Rows', type: 'number', role: 'option', default: 3, min: 1, step: 1, required: true },
      { name: 'columns', label: 'Columns', type: 'number', role: 'option', default: 3, min: 1, step: 1, showIf: (v) => v.kind === 'constant' },
      { name: 'value', label: 'Value', type: 'number', role: 'option', step: 'any', default: 0, showIf: (v) => v.kind === 'constant' },
      storeIn('Store matrix in', { placeholder: 'M1' }),
    ],
  },
  {
    id: 'matrix_eigen',
    icon: 'matrix-eigen',
    description: 'Computes the eigenvalues and eigenvectors of a symmetric matrix — the arithmetic underneath principal components.',
    needs: 'One symmetric stored matrix.',
    procedure: 'matrix_eigen',
    label: 'Eigen Analysis…',
    title: 'Eigen Analysis',
    submitLabel: 'Run eigen analysis',
    group: 'Matrices',
    fields: [
      matrixPick('matrix', 'Matrix (must be square)'),
      { name: 'store_values_in', label: 'Store eigenvalues in the column', type: 'text', role: 'option', placeholder: 'eigenvalues' },
      { name: 'store_vectors_in', label: 'Store eigenvectors in the matrix', type: 'text', role: 'option', placeholder: 'M2', hint: 'One eigenvector per column, in the same order as the eigenvalues.' },
    ],
    note: 'A symmetric matrix goes through numpy.linalg.eigh, which guarantees real eigenvalues; anything else uses eig, and a complex result is reported rather than hidden.',
  },
  {
    id: 'matrix_arithmetic',
    icon: 'matrix-arithmetic',
    description: 'Adds, subtracts or multiplies two matrices, or scales one by a constant.',
    needs: 'One or two stored matrices.',
    procedure: 'matrix_arithmetic',
    label: 'Arithmetic…',
    title: 'Matrix Arithmetic',
    submitLabel: 'Compute',
    group: 'Matrices',
    fields: [
      matrixPick('left', 'First matrix'),
      {
        name: 'operation',
        label: 'Operation',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'add', label: 'Add' },
          { value: 'subtract', label: 'Subtract' },
          { value: 'multiply', label: 'Matrix product' },
          { value: 'elementwise', label: 'Multiply element by element' },
          { value: 'scalar', label: 'Multiply by a number' },
        ],
        default: 'add',
      },
      matrixPick('right', 'Second matrix', { showIf: (v) => v.operation !== 'scalar' }),
      { name: 'scalar', label: 'Number', type: 'number', role: 'option', step: 'any', default: 1, showIf: (v) => v.operation === 'scalar' },
      storeIn('Store result in', { placeholder: 'M3' }),
    ],
  },
  {
    id: 'matrices_window',
    icon: 'matrices-window',
    label: 'Manage Matrices…',
    title: 'Matrices',
    group: 'Matrices',
    bespoke: true,
    description: 'Opens the window listing the stored matrices M1, M2, … with their sizes and values, where they can be renamed or cleared.',
  },
];

export const PROCEDURE_BY_ID = Object.fromEntries(PROCEDURES.filter((p) => p.id).map((p) => [p.id, p]));

// ---------------------------------------------------------------------------
// the generated distribution dialogs
// ---------------------------------------------------------------------------

/** Random Data > <distribution> and Probability Distributions > <distribution>: two families of
 *  generated configs, one entry per distribution, all sharing one form. */
export function distributionConfig(kind, distribution) {
  const isRandom = kind === 'random';
  const base = {
    id: `${kind}_${distribution.id}`,
    procedure: isRandom ? 'random_data' : 'probability',
    label: `${distribution.label}…`,
    title: `${isRandom ? 'Random Data' : 'Probability Distribution'}: ${distribution.label}`,
    submitLabel: isRandom ? 'Generate' : 'Compute',
    group: isRandom ? 'Random Data' : 'Probability Distributions',
    distribution: distribution.id,
    note: distribution.discrete ? 'A discrete distribution: the density mode gives the probability of exactly that value.' : null,
  };

  const parameterFields = (distribution.params || []).map((p) => ({
    name: `p_${p.key}`,
    label: p.label,
    type: 'number',
    role: 'param',
    param: p.key,
    default: p.default,
    step: p.integer ? 1 : 'any',
    hint: p.hint || undefined,
    group: 'Parameters',
  }));

  if (isRandom) {
    const fields = [
      { name: 'rows', label: 'Number of rows of data to generate', type: 'number', role: 'option', default: 100, min: 1, step: 1, required: true },
      { name: 'store_in', label: 'Store in column(s)', type: 'text', role: 'option', required: true, placeholder: 'C1', hint: 'One name, or several separated by spaces for several columns of the same distribution.' },
    ];
    if (distribution.id === 'multivariate_normal') {
      fields.push(
        { name: 'mean_vector', label: 'Mean vector', type: 'text', role: 'option', mono: true, required: true, placeholder: '0 0', group: 'Parameters', hint: 'One value per variable, separated by spaces.' },
        { name: 'covariance', label: 'Covariance matrix', type: 'matrix', role: 'option', required: true, group: 'Parameters' },
      );
    } else if (distribution.id === 'discrete') {
      fields.push(
        { name: 'value_column', label: 'Column of values', type: 'column', role: 'option', filter: 'any', required: true, group: 'Parameters' },
        { name: 'probability_column', label: 'Column of probabilities', type: 'column', role: 'option', filter: 'numeric', required: true, group: 'Parameters' },
      );
    } else {
      fields.push(...parameterFields);
    }
    return { ...base, fields };
  }

  return {
    ...base,
    fields: [
      {
        name: 'mode',
        label: 'Compute',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'pdf', label: distribution.discrete ? 'Probability (exact value)' : 'Probability density' },
          { value: 'cdf', label: 'Cumulative probability' },
          { value: 'icdf', label: 'Inverse cumulative probability' },
        ],
        default: 'cdf',
      },
      {
        name: 'input_kind',
        label: 'Input',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'value', label: 'A single value' },
          { value: 'column', label: 'A column of values' },
        ],
        default: 'value',
      },
      { name: 'input_value', label: 'Value', type: 'number', role: 'option', step: 'any', default: 0, showIf: (v) => v.input_kind !== 'column' },
      { name: 'input_column', label: 'Input column', type: 'column', role: 'option', filter: 'numeric', showIf: (v) => v.input_kind === 'column', required: true },
      { name: 'store_in', label: 'Store result in', type: 'text', role: 'option', placeholder: 'K1 or a column name', hint: 'A single value goes into a constant; a column of values goes into a column. Leave blank for the Session Window only.' },
      ...parameterFields,
      { name: 'plot', label: 'Plot the distribution, with the value marked', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
    ],
  };
}

// ---------------------------------------------------------------------------
// the Calc dropdown, in Minitab's own order
// ---------------------------------------------------------------------------

const itemsInGroup = (group) =>
  PROCEDURES.filter((p) => p.group === group).map((p) => ({ label: p.label, calc: p.id, icon: p.icon, description: p.description, needs: p.needs }));
const item = (id) => {
  const p = PROCEDURE_BY_ID[id];
  return p ? { label: p.label, calc: id, icon: p.icon, description: p.description, needs: p.needs } : null;
};

// Generated for BOTH the Random Data and the Probability Distributions submenus: one shape
// sentence per distribution, prefixed by what the chosen submenu actually does with it. Keeping
// them in one table is what stops the two menus describing the same distribution differently.
const DISTRIBUTION_SHAPES = {
  normal: 'Symmetric and bell-shaped, described by a mean and a standard deviation. The default model for measurement error and for a sample mean.',
  multivariate_normal: 'Several normal variables together, with a covariance matrix saying how they move as a group.',
  chi_square: 'Right-skewed and positive, indexed by degrees of freedom. The distribution of a sum of squared normal values, so it turns up in variance and goodness-of-fit tests.',
  f: 'The ratio of two variances, indexed by two degrees of freedom. The distribution every ANOVA F-test is read against.',
  t: 'Bell-shaped like the normal but with heavier tails, indexed by degrees of freedom. What a sample mean follows when the standard deviation is estimated rather than known.',
  uniform: 'Flat between two endpoints: every value in the range is equally likely.',
  bernoulli: 'A single yes/no trial with probability p of a success.',
  binomial: 'The number of successes in a fixed number of independent yes/no trials, each with the same probability.',
  geometric: 'The number of trials up to and including the first success. Its probabilities fall away geometrically.',
  negative_binomial: 'The number of trials needed to reach a given number of successes — the geometric distribution generalised past the first one.',
  hypergeometric: 'The number of successes when drawing WITHOUT replacement from a finite population, which is what makes it differ from the binomial.',
  discrete: 'Any distribution defined by hand, by naming the values and the probability of each.',
  integer: 'Whole numbers between two endpoints, each equally likely. The discrete counterpart of the uniform.',
  poisson: 'Counts of events in a fixed interval, given a mean rate. Right-skewed, and equal in mean and variance.',
  beta: 'Bounded between 0 and 1 and takes many shapes according to its two parameters. The usual model for a proportion.',
  cauchy: 'Bell-shaped but with tails so heavy that it has no mean or variance at all. Useful for testing how a method copes with extreme values.',
  exponential: 'Time until the next event when events occur at a constant rate. Decays from its highest point at zero.',
  gamma: 'Positive and right-skewed, with a shape and a scale. Models waiting times and, at shape 1, becomes the exponential.',
  laplace: 'Two exponential tails back to back, giving a sharp peak and heavier tails than the normal.',
  largest_extreme_value: 'The distribution of the MAXIMUM of many observations, skewed with its long tail to the right. Used for flood and load extremes.',
  logistic: 'Symmetric and close to the normal but with slightly heavier tails. Its cumulative curve is the S-curve behind logistic regression.',
  loglogistic: 'A logistic distribution on the log scale: positive, right-skewed, and used in reliability work.',
  lognormal: 'Positive and right-skewed, being the distribution of a quantity whose logarithm is normal. Fits concentrations, incomes and times to failure.',
  smallest_extreme_value: 'The distribution of the MINIMUM of many observations, skewed with its long tail to the left. The mirror of Largest Extreme Value.',
  triangular: 'A straight-sided peak between a minimum and a maximum, set by a most-likely value. Used when only those three numbers are known.',
  weibull: 'Positive with a shape parameter that lets it model failure rates that fall, hold steady or climb over time. The workhorse of reliability analysis.',
};

const DISTRIBUTION_NEEDS = {
  multivariate_normal: 'A mean vector and a covariance matrix.',
  discrete: 'A column of values and a column of probabilities that sum to 1.',
};

/** The help text for one generated distribution item. `mode` is "random" or "probability". */
function distributionHelp(distribution, mode) {
  const label = `the ${distribution.label.toLowerCase()} distribution`;
  const shape = DISTRIBUTION_SHAPES[distribution.id] || '';
  const lead =
    mode === 'random'
      ? `Fills worksheet columns with random values drawn from ${label}. `
      : `Computes a probability density, a cumulative probability or an inverse (a percentile) for ${label}. `;
  return {
    description: lead + shape,
    needs: DISTRIBUTION_NEEDS[distribution.id] || (mode === 'random' ? 'A number of rows, the columns to store them in, and the distribution’s parameters.' : 'The distribution’s parameters, and a column of values or one value to evaluate.'),
  };
}

export function calcMenuConfig(distributions) {
  const list = distributions || [];
  // Both generated submenus name the SAME icon per distribution — `dist-<id>` in the registry.
  // Within each flyout all 26 differ from each other, which is what scanning a menu needs; the
  // flyout you are standing in is what says whether you are generating data or reading a density.
  const distIcon = (d) => `dist-${d.id.replace(/_/g, '-')}`;
  const randomItems = [
    { label: 'Sample From Columns…', calc: 'sample_columns', ...item('sample_columns') },
    { separator: true },
    ...list.map((d) => ({ label: `${d.label}…`, calc: `random_${d.id}`, icon: distIcon(d), ...distributionHelp(d, 'random') })),
  ];
  const probabilityItems = list
    .filter((d) => d.id !== 'multivariate_normal')
    .map((d) => ({ label: `${d.label}…`, calc: `probability_${d.id}`, icon: distIcon(d), ...distributionHelp(d, 'probability') }));

  return [
    item('calculator'),
    item('column_statistics'),
    item('row_statistics'),
    item('standardize'),
    { separator: true },
    { label: 'Make Patterned Data', items: itemsInGroup('Make Patterned Data') },
    item('mesh_data'),
    item('indicator_variables'),
    { separator: true },
    item('set_base'),
    { label: 'Random Data', items: randomItems },
    { label: 'Resampling', items: itemsInGroup('Resampling') },
    { label: 'Probability Distributions', items: probabilityItems },
    { separator: true },
    { label: 'Matrices', items: itemsInGroup('Matrices') },
  ].filter(Boolean);
}

// ---------------------------------------------------------------------------
// values -> request
// ---------------------------------------------------------------------------

export function buildRequest(config, values, visibleList) {
  const fields = visibleList || visible(config, values);
  const columns = [];
  const options = {};
  const parameters = {};

  for (const field of fields) {
    const value = values[field.name];
    if (field.role === 'column') {
      if (Array.isArray(value)) columns.push(...value);
      else if (value) columns.push(value);
    } else if (field.role === 'columns') {
      columns.push(...(value || []));
    } else if (field.role === 'param') {
      if (value !== '' && value !== null && value !== undefined) parameters[field.param] = Number(value);
    } else if (field.type === 'checkbox') {
      options[field.name] = !!value;
    } else if (Array.isArray(value)) {
      if (value.length) options[field.name] = value;
    } else if (value !== '' && value !== undefined && value !== null) {
      options[field.name] = field.type === 'number' ? Number(value) : value;
    }
  }
  // Fields that never reach the form still carry the menu item's fixed choice (the date mode).
  for (const field of config.fields || []) {
    if (field.omitFromForm && field.default !== undefined && options[field.name] === undefined) options[field.name] = field.default;
  }
  if (Object.keys(parameters).length) options.parameters = parameters;
  if (config.distribution) options.distribution = config.distribution;

  // The two-sample dialogs collect their columns under layout-specific names; the backend wants
  // them in one ordered list either way.
  if (values.layout === 'two_columns' && values.sample_a && values.sample_b) {
    return { procedure: config.procedure, columns: [values.sample_a, values.sample_b], options };
  }
  return { procedure: config.procedure, columns, options };
}

export function describe(config, values) {
  const parts = [];
  for (const field of config.fields || []) {
    if (field.role !== 'column' && field.role !== 'columns') continue;
    const value = values[field.name];
    if (Array.isArray(value) && value.length) parts.push(value.join(', '));
    else if (value && typeof value === 'string') parts.push(value);
  }
  const name = config.title || config.label.replace(/…$/, '');
  return parts.length ? `${name} (${parts.join('; ')})` : name;
}

export { visibleFields, defaultValues, validate } from './procedureDialog.js';
