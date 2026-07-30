// Every item on Stat > ANOVA, declared once: form fields, the backend procedure, and how the
// inputs turn into a request. Same split as basicStatsConfig.js / regressionConfig.js.
//
// Field order matters: `column` and `columns` fields contribute to the ordered `columns` array in
// declaration order, which is the order the backend reads them. Where the backend has to know
// where one group of columns ends and the next begins — [response, *factors, *covariates] — the
// count is sent explicitly as an option (`n_factors`, `n_responses`, …) rather than guessed.
//
// The six dialogs below "Fit General Linear Model" and the three below "Fit Mixed Effects Model"
// operate on the STORED model: anova.js keeps the `model_spec` the fit returned and posts it back,
// and the backend refits. They declare no response or predictor fields for that reason.

import { visibleFields as visible } from './procedureDialog.js';

// ---------------------------------------------------------------------------
// field shorthands
// ---------------------------------------------------------------------------

const responseCol = (label = 'Response', extra = {}) => ({ name: 'response', label, type: 'column', role: 'column', filter: 'numeric', required: true, ...extra });
const factorCol = (name, label, extra = {}) => ({ name, label, type: 'column', role: 'column', filter: 'any', required: true, ...extra });

const confidence = (extra = {}) => ({
  name: 'confidence',
  label: 'Confidence level',
  type: 'number',
  role: 'option',
  default: 0.95,
  min: 0.5,
  max: 0.999,
  // step 'any': a numeric step makes the browser silently refuse to submit a value that is not
  // min + n×step, with no message anywhere.
  step: 'any',
  advanced: true,
  ...extra,
});

const residualGraphs = (dflt = true) => ({
  name: 'graph_residuals',
  label: 'Four-in-one residual plots',
  type: 'checkbox',
  role: 'option',
  default: dflt,
  group: 'Graphs',
});

// The plots every one-way-shaped dialog offers, in Minitab's own order.
const rawGraphs = () => [
  { name: 'graph_interval', label: 'Interval plot', type: 'checkbox', role: 'option', default: true, group: 'Graphs' },
  { name: 'graph_individual', label: 'Individual value plot', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
  { name: 'graph_boxplot', label: 'Boxplot', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
];

// Minitab puts these behind a "Comparisons" button. This app's idiom for a sub-dialog is a named
// collapsed section, so that is what they get — same settings, one click to reach, and the form
// still opens showing only what the procedure needs.
const comparisonFields = () => [
  {
    name: 'comparisons',
    label: 'Method',
    type: 'select',
    role: 'option',
    section: 'Comparisons',
    options: [
      { value: 'none', label: '— none —' },
      { value: 'tukey', label: 'Tukey — all pairwise, family error rate controlled' },
      { value: 'fisher', label: 'Fisher LSD — all pairwise, no adjustment' },
      { value: 'dunnett', label: 'Dunnett — every level against one control' },
      { value: 'games_howell', label: 'Games-Howell — all pairwise, unequal variances' },
    ],
    default: 'none',
  },
  {
    name: 'control',
    label: 'Control level',
    type: 'value',
    role: 'option',
    section: 'Comparisons',
    from: 'factor',
    emptyLabel: '— choose the control —',
    showIf: (v) => v.comparisons === 'dunnett',
    hint: 'Dunnett compares every other level with this one, and only with this one.',
  },
  {
    name: 'comparison_confidence',
    label: 'Confidence level for the comparisons',
    type: 'number',
    role: 'option',
    section: 'Comparisons',
    min: 0.5,
    max: 0.999,
    step: 'any',
    showIf: (v) => v.comparisons !== 'none',
    hint: 'Leave blank to use the dialog’s confidence level.',
  },
];

const layoutField = (extra = {}) => ({
  name: 'layout',
  label: 'Data are arranged as',
  type: 'radio',
  role: 'option',
  options: [
    { value: 'one_column', label: 'Response in one column, factor in another' },
    { value: 'columns', label: 'Response data in separate columns (one per group)' },
  ],
  default: 'one_column',
  ...extra,
});

const inOneColumn = (v) => v.layout !== 'columns';
const inColumns = (v) => v.layout === 'columns';

const termsField = (extra = {}) => ({
  name: 'terms',
  label: 'Terms in the model',
  type: 'term-picker',
  role: 'option',
  from: ['factors', 'covariates'],
  hint: 'Main effects are always included. Tick the interactions you want, or use the checkbox above for every two-way term.',
  ...extra,
});

const interactionsField = (label = 'Include every two-way interaction') => ({
  name: 'interactions',
  label,
  type: 'checkbox',
  role: 'option',
  default: false,
  hint: 'With many terms this uses up degrees of freedom quickly. Leave it off and pick terms explicitly for more control.',
});

// ---------------------------------------------------------------------------
// the procedures
// ---------------------------------------------------------------------------

export const PROCEDURES = [
  {
    id: 'one_way',
    icon: 'one-way',
    description: 'Tests whether the means of three or more groups all match, from either the stacked layout (one value column, one factor column) or one column per group. Includes Welch\'s version for unequal variances and the comparison procedures with grouping letters.',
    needs: 'One numeric response and one grouping factor with 2 or more levels.',
    procedure: 'one_way',
    label: 'One-Way…',
    title: 'One-Way ANOVA',
    submitLabel: 'Run one-way ANOVA',
    fields: [
      layoutField(),
      responseCol('Response', { showIf: inOneColumn }),
      factorCol('factor', 'Factor', { showIf: inOneColumn }),
      { name: 'samples', label: 'Response columns (one per group)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 2, showIf: inColumns },
      { name: 'value_label', label: 'Name for the response', type: 'text', role: 'option', default: 'response', showIf: inColumns, advanced: true },
      {
        name: 'equal_variances',
        label: 'Assume equal variances',
        type: 'checkbox',
        role: 'option',
        default: true,
        hint: 'On: the classic F-test. Off: Welch’s ANOVA, which does not pool the variances — the same choice Minitab offers.',
      },
      confidence(),
      ...rawGraphs(),
      residualGraphs(false),
      ...comparisonFields(),
    ],
    note: 'Output: the ANOVA table, model summary, per-group means with confidence intervals, and an interval plot. Open Comparisons for Tukey, Fisher, Dunnett or Games-Howell with grouping letters.',
  },
  {
    id: 'equal_variances',
    icon: 'equal-variances',
    description: 'Tests whether several groups share a common variance — the assumption behind pooled ANOVA. Reports Bartlett\'s test, which needs normality, alongside Levene\'s, which does not.',
    needs: 'One numeric response and one grouping factor.',
    procedure: 'equal_variances',
    label: 'Test for Equal Variances…',
    title: 'Test for Equal Variances',
    submitLabel: 'Test equal variances',
    fields: [
      layoutField(),
      responseCol('Response', { showIf: inOneColumn }),
      factorCol('factor', 'Factor', { showIf: inOneColumn }),
      { name: 'samples', label: 'Response columns (one per group)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 2, showIf: inColumns },
      { name: 'value_label', label: 'Name for the response', type: 'text', role: 'option', default: 'response', showIf: inColumns, advanced: true },
      confidence(),
      { name: 'graph_individual', label: 'Individual value plot', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
      { name: 'graph_boxplot', label: 'Boxplot', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
    ],
    note: 'Bartlett and Levene are reported together. The chart is the signature one: a Bonferroni confidence interval for each group’s standard deviation, so intervals that fail to overlap are the groups that differ.',
  },
  { separator: true },
  {
    id: 'balanced_anova',
    icon: 'balanced-anova',
    description: 'Fits a factorial model when every cell holds the SAME number of observations, which keeps the sums of squares independent. If the design has unequal cell counts, use the General Linear Model instead.',
    needs: 'One numeric response and two or more balanced factors.',
    procedure: 'balanced_anova',
    label: 'Balanced ANOVA…',
    title: 'Balanced ANOVA',
    submitLabel: 'Run balanced ANOVA',
    fields: [
      responseCol(),
      { name: 'factors', label: 'Factors', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 1 },
      { name: 'random_factors', label: 'Which of them are random', type: 'subset', role: 'option', from: 'factors', hint: 'A random factor gets a variance component instead of level estimates, and changes which mean square the terms above it are tested against.' },
      interactionsField(),
      termsField(),
      {
        name: 'vc_method',
        label: 'Estimate variance components by',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'ems', label: 'Expected mean squares (balanced design)' },
          { value: 'reml', label: 'REML (statsmodels MixedLM)' },
        ],
        default: 'ems',
        advanced: true,
        showIf: (v) => (v.random_factors || []).length > 0,
      },
      confidence(),
      residualGraphs(),
      { name: 'graph_main_effects', label: 'Main effects plot (fitted means)', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
    ],
    note: 'Every factor-level combination must hold the same number of observations. If the design is unbalanced this says so and points you at the General Linear Model, which handles it.',
  },
  {
    id: 'nested_anova',
    icon: 'nested-anova',
    description: 'Fits factors that are nested rather than crossed — batches within lots, operators within sites — and splits the variance between the levels. Use it when a level of one factor belongs to exactly one level of another.',
    needs: 'One numeric response and two or more nested factors, outermost first.',
    procedure: 'nested_anova',
    label: 'Fully Nested ANOVA…',
    title: 'Fully Nested ANOVA',
    submitLabel: 'Run nested ANOVA',
    fields: [
      responseCol(),
      { name: 'factors', label: 'Nested factors, outermost first', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 2, maxSelect: 4, hint: 'Tick them in nesting order: A, then B within A, then C within A B. Tick order is the order they are read.' },
      residualGraphs(),
    ],
    note: 'Each level below the first is identified by its whole path, so "batch 1" inside lot A is a different batch from "batch 1" inside lot B. Output includes the variance component at each level with its share of the total.',
  },
  {
    id: 'manova',
    icon: 'manova',
    description: 'Tests several responses at once against the same factors, using the correlations between the responses. Catches a shift spread across responses that separate ANOVAs would each miss.',
    needs: 'Two or more numeric responses and one or more factors.',
    procedure: 'manova',
    label: 'General MANOVA…',
    title: 'General MANOVA',
    submitLabel: 'Run MANOVA',
    fields: [
      { name: 'responses', label: 'Responses (2 or more)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 2 },
      { name: 'factors', label: 'Factors', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 1 },
      interactionsField(),
      termsField({ from: ['factors'] }),
      confidence(),
    ],
    note: 'All four multivariate statistics are reported per term — Wilks’ lambda, Pillai’s trace, Hotelling-Lawley trace and Roy’s greatest root — each with its F approximation and p-value.',
  },
  { separator: true },
  {
    id: 'glm',
    icon: 'glm-fit',
    description: 'Fits any combination of crossed and nested factors, covariates and interactions, balanced or not, and reports Type III tests. This is the general case the other ANOVA dialogs are special cases of, and the fit the items below it work from.',
    needs: 'One numeric response and one or more factors or covariates.',
    procedure: 'glm',
    label: 'Fit General Linear Model…',
    title: 'Fit General Linear Model',
    submitLabel: 'Fit general linear model',
    group: 'General Linear Model',
    storesModel: 'glm',
    fields: [
      responseCol(),
      { name: 'factors', label: 'Factors (categorical)', type: 'columns', role: 'columns', filter: 'any', required: false },
      { name: 'covariates', label: 'Covariates (continuous)', type: 'columns', role: 'columns', filter: 'numeric', required: false },
      interactionsField(),
      termsField(),
      {
        name: 'center_covariates',
        label: 'Centre covariates at their means',
        type: 'checkbox',
        role: 'option',
        default: true,
        advanced: true,
        hint: 'Keeps a factor’s main effect meaningful when the model also contains that factor × covariate. Uncentred, the main effect is tested at covariate = 0, which is usually far outside the data.',
      },
      confidence(),
      residualGraphs(),
      { name: 'graph_main_effects', label: 'Main effects plot (fitted means)', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
      { name: 'graph_interactions', label: 'Interaction plot (fitted means)', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
    ],
    note: 'Type III (adjusted) sums of squares, with sum-to-zero coding so they are the real thing. The fitted model is remembered: the rest of this submenu works from it.',
  },
  {
    id: 'glm_comparisons',
    icon: 'comparisons',
    description: 'Compares the fitted means pairwise, or against a control, adjusting for the number of comparisons made. Tukey for all pairs, Fisher unadjusted, Dunnett against a control, Games-Howell when variances differ.',
    needs: 'A fitted general linear model and a factor to compare.',
    procedure: 'glm_comparisons',
    label: 'Comparisons…',
    title: 'Comparisons (General Linear Model)',
    submitLabel: 'Run comparisons',
    group: 'General Linear Model',
    needsModel: 'glm',
    fields: [
      { name: 'factor', label: 'Compare the levels of', type: 'model-factor', role: 'option', required: true },
      {
        name: 'method',
        label: 'Method',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'tukey', label: 'Tukey — family error rate controlled' },
          { value: 'fisher', label: 'Fisher LSD — no adjustment' },
        ],
        default: 'tukey',
      },
      confidence({ advanced: false }),
    ],
    note: 'Comparisons are of the fitted (least-squares) means, so every other term in the model is held constant. Levels sharing a grouping letter are the ones the method could not separate.',
  },
  {
    id: 'glm_predict',
    icon: 'predict',
    description: 'Predicts the response at typed settings, with a confidence interval for the mean and a prediction interval for one new observation. The model is refitted for each prediction, so the panel keeps working for as long as the window is open.',
    needs: 'A fitted general linear model and a value for each term.',
    procedure: 'glm_predict',
    label: 'Predict…',
    title: 'Predict (General Linear Model)',
    group: 'General Linear Model',
    needsModel: 'glm',
    panelOnly: true,
    fields: [],
  },
  {
    id: 'glm_factorial_plots',
    icon: 'factorial-plots',
    description: 'Draws the main effects and interaction plots from the fitted model — fitted means rather than raw averages, so covariates and unequal cell counts are accounted for.',
    needs: 'A fitted general linear model with two or more factors.',
    procedure: 'glm_factorial_plots',
    label: 'Factorial Plots…',
    title: 'Factorial Plots (General Linear Model)',
    submitLabel: 'Draw factorial plots',
    group: 'General Linear Model',
    needsModel: 'glm',
    fields: [
      { name: 'main_effects', label: 'Main effects plot', type: 'checkbox', role: 'option', default: true },
      { name: 'interactions', label: 'Interaction plot', type: 'checkbox', role: 'option', default: true, hint: 'Needs at least two factors in the model.' },
    ],
    note: 'The means plotted are the model’s, not the data’s: each panel holds the other terms constant, which is what makes the panels comparable.',
  },
  {
    id: 'glm_contour',
    icon: 'contour-plot',
    description: 'Draws the response as contour lines over two continuous variables, holding the others at chosen values. The flat map of the surface, and the easier of the two to read a setting off.',
    needs: 'A fitted model with two or more continuous terms.',
    procedure: 'glm_contour',
    label: 'Contour Plot…',
    title: 'Contour Plot (General Linear Model)',
    submitLabel: 'Draw contour plot',
    group: 'General Linear Model',
    needsModel: 'glm',
    fields: [
      { name: 'x', label: 'X axis', type: 'model-covariate', role: 'option', required: true },
      { name: 'y', label: 'Y axis', type: 'model-covariate', role: 'option', required: true },
      { name: 'holds', label: 'Hold the other predictors at', type: 'model-holds', role: 'option' },
      { name: 'resolution', label: 'Grid resolution', type: 'number', role: 'option', default: 40, min: 10, max: 80, step: 1, advanced: true },
    ],
    note: 'The surface is the fitted model over the two chosen predictors, not an interpolation of the data.',
  },
  {
    id: 'glm_surface',
    icon: 'surface-plot',
    description: 'Draws the response as a 3D surface over two continuous variables. Shows the shape of a curved response more vividly than contours, though exact settings are harder to read off.',
    needs: 'A fitted model with two or more continuous terms.',
    procedure: 'glm_surface',
    label: 'Surface Plot…',
    title: 'Surface Plot (General Linear Model)',
    submitLabel: 'Draw surface plot',
    group: 'General Linear Model',
    needsModel: 'glm',
    fields: [
      { name: 'x', label: 'X axis', type: 'model-covariate', role: 'option', required: true },
      { name: 'y', label: 'Y axis', type: 'model-covariate', role: 'option', required: true },
      { name: 'holds', label: 'Hold the other predictors at', type: 'model-holds', role: 'option' },
      { name: 'resolution', label: 'Grid resolution', type: 'number', role: 'option', default: 40, min: 10, max: 80, step: 1, advanced: true },
    ],
  },
  {
    id: 'glm_optimizer',
    icon: 'response-optimizer',
    description: 'Searches the fitted model for the settings that best meet the targets set for the response — maximise, minimise or hit a value — using Derringer-Suich desirability.',
    needs: 'A fitted model and a goal for the response.',
    procedure: 'glm_optimizer',
    label: 'Response Optimizer…',
    title: 'Response Optimizer (General Linear Model)',
    submitLabel: 'Find the optimum',
    group: 'General Linear Model',
    needsModel: 'glm',
    fields: [
      {
        name: 'goal',
        label: 'Goal',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'maximize', label: 'Maximize the response' },
          { value: 'minimize', label: 'Minimize the response' },
          { value: 'target', label: 'Hit a target value' },
        ],
        default: 'maximize',
      },
      { name: 'target', label: 'Target', type: 'number', role: 'option', step: 'any', hint: 'For maximize/minimize this is the value at which desirability reaches 1. Leave blank to use the best value seen in the data.' },
      { name: 'lower', label: 'Lower bound', type: 'number', role: 'option', step: 'any', hint: 'Desirability is 0 at or below this. Leave blank to use the smallest observed response.' },
      { name: 'upper', label: 'Upper bound', type: 'number', role: 'option', step: 'any', hint: 'Desirability is 0 at or above this. Leave blank to use the largest observed response.' },
      { name: 'weight', label: 'Importance weight', type: 'number', role: 'option', default: 1, min: 0.1, max: 10, step: 'any', advanced: true, hint: 'Above 1 makes desirability rise only near the target; below 1 makes anything in range nearly as good.' },
      { name: 'starts', label: 'Optimisation restarts', type: 'number', role: 'option', default: 8, min: 3, max: 40, step: 1, advanced: true, hint: 'A desirability surface saturates at 0 and 1, so a single start can settle on a flat region. Each restart begins somewhere else.' },
      confidence({ advanced: false }),
    ],
    note: 'Derringer-Suich desirability over the fitted model, maximised with L-BFGS-B from several starting points. Categorical factors are searched exhaustively.',
  },
  {
    label: 'Overlaid Contour Plot…',
    icon: 'overlaid-contour',
    description:
      'Lays the contour plots of several responses over each other to show the region of settings where all of them meet their limits at once.',
    group: 'General Linear Model',
    disabled: true,
    title: 'Not supported yet — this needs two response models fitted at once, and the app stores one at a time. Fit each response separately and read their contour plots side by side.',
  },
  { separator: true },
  {
    id: 'mixed_model',
    icon: 'mixed-fit',
    description: 'Fits a model where some factors are RANDOM — a sample of operators or batches standing in for all of them — and estimates their variance components rather than one mean per level. Use it when the levels are a sample and the conclusion should generalise beyond them.',
    needs: 'One numeric response, at least one random factor, and optionally fixed factors.',
    procedure: 'mixed_model',
    label: 'Fit Mixed Effects Model…',
    title: 'Fit Mixed Effects Model',
    submitLabel: 'Fit mixed effects model',
    group: 'Mixed Effects Model',
    storesModel: 'mixed',
    fields: [
      responseCol(),
      { name: 'factors', label: 'Fixed factors (categorical)', type: 'columns', role: 'columns', filter: 'any', required: false },
      { name: 'covariates', label: 'Covariates (continuous)', type: 'columns', role: 'columns', filter: 'numeric', required: false },
      { name: 'random_factors', label: 'Random factors', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 1, hint: 'Each gets a variance component instead of fixed level estimates.' },
      { name: 'random_slopes', label: 'Random slopes for', type: 'subset', role: 'option', from: 'covariates', advanced: true, hint: 'Lets the effect of a covariate differ between levels of the first random factor. Leave empty for random intercepts only.' },
      interactionsField('Include every two-way interaction among the fixed terms'),
      termsField(),
      {
        name: 'method',
        label: 'Estimation',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'reml', label: 'REML — the default; unbiased variance components' },
          { value: 'ml', label: 'Maximum likelihood — comparable across different fixed parts' },
        ],
        default: 'reml',
        advanced: true,
      },
      confidence(),
      residualGraphs(),
    ],
    note: 'Output: fixed-effects coefficients with tests, the variance components with their share of the total, and AIC/BIC. The fitted model is remembered for the three dialogs below.',
  },
  {
    id: 'mixed_comparisons',
    icon: 'comparisons',
    description: 'Compares the fitted means of the fixed factors in the mixed model, adjusted for multiple comparisons and using the mixed model\'s standard errors.',
    needs: 'A fitted mixed effects model with a fixed factor.',
    procedure: 'mixed_comparisons',
    label: 'Comparisons…',
    title: 'Comparisons (Mixed Effects Model)',
    submitLabel: 'Run comparisons',
    group: 'Mixed Effects Model',
    needsModel: 'mixed',
    fields: [
      { name: 'factor', label: 'Compare the levels of', type: 'model-factor', role: 'option', required: true },
      {
        name: 'method',
        label: 'Method',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'tukey', label: 'Tukey — family error rate controlled' },
          { value: 'fisher', label: 'Fisher LSD — no adjustment' },
        ],
        default: 'tukey',
      },
      confidence({ advanced: false }),
    ],
  },
  {
    id: 'mixed_predict',
    icon: 'predict',
    description: 'Predicts the response at typed settings from the mixed model, with its interval.',
    needs: 'A fitted mixed effects model and a value for each term.',
    procedure: 'mixed_predict',
    label: 'Predict…',
    title: 'Predict (Mixed Effects Model)',
    group: 'Mixed Effects Model',
    needsModel: 'mixed',
    panelOnly: true,
    fields: [],
  },
  {
    id: 'mixed_factorial_plots',
    icon: 'factorial-plots',
    description: 'Draws the main effects and interaction plots for the fixed part of the mixed model.',
    needs: 'A fitted mixed effects model with two or more fixed factors.',
    procedure: 'mixed_factorial_plots',
    label: 'Factorial Plots…',
    title: 'Factorial Plots (Mixed Effects Model)',
    submitLabel: 'Draw factorial plots',
    group: 'Mixed Effects Model',
    needsModel: 'mixed',
    fields: [
      { name: 'main_effects', label: 'Main effects plot', type: 'checkbox', role: 'option', default: true },
      { name: 'interactions', label: 'Interaction plot', type: 'checkbox', role: 'option', default: true },
    ],
  },
  { separator: true },
  {
    id: 'interval_plot',
    icon: 'interval-plot',
    description: 'Plots each group\'s mean with a confidence interval around it. Shows whether the intervals overlap, which is the visual companion to a test of means, without fitting a model.',
    needs: 'One numeric response and one grouping factor.',
    procedure: 'interval_plot',
    label: 'Interval Plot…',
    title: 'Interval Plot',
    submitLabel: 'Draw interval plot',
    fields: [
      responseCol(),
      factorCol('factor', 'Group by', { required: false }),
      { name: 'confidence', label: 'Confidence level', type: 'number', role: 'option', default: 0.95, min: 0.5, max: 0.999, step: 'any' },
    ],
    note: 'The same plot as Graph > Interval Plot — one implementation, reachable from either menu.',
  },
  {
    id: 'main_effects_plot',
    icon: 'main-effects-plot',
    description: 'Plots the mean response at each level of each factor, against the overall mean, so the size and direction of every factor\'s effect can be compared on one page.',
    needs: 'One numeric response and one or more factors.',
    procedure: 'main_effects_plot',
    label: 'Main Effects Plot…',
    title: 'Main Effects Plot',
    submitLabel: 'Draw main effects plot',
    fields: [
      responseCol(),
      { name: 'factors', label: 'Factors', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 1 },
    ],
    note: 'Raw means, one panel per factor, all sharing a y-axis so the panels are comparable. For means adjusted for a model, use the General Linear Model’s Factorial Plots.',
  },
  {
    id: 'interaction_plot',
    icon: 'interaction-plot',
    description: 'Plots the mean response for each combination of two factors as a set of lines. Parallel lines say the factors act independently; crossing lines say the effect of one depends on the other.',
    needs: 'One numeric response and two or more factors.',
    procedure: 'interaction_plot',
    label: 'Interaction Plot…',
    title: 'Interaction Plot',
    submitLabel: 'Draw interaction plot',
    fields: [
      responseCol(),
      { name: 'factors', label: 'Factors (2 or more)', type: 'columns', role: 'columns', filter: 'any', required: true, minSelect: 2 },
    ],
    note: 'One panel per pair of factors. Parallel lines mean the factors act independently; lines that cross or diverge are the interaction.',
  },
  { separator: true },
  {
    id: 'anom',
    icon: 'anom',
    description: 'Compares each group\'s mean against the overall mean using decision limits, rather than comparing groups with each other. Answers \'which groups are unusual?\' where one-way ANOVA answers \'are any of them different?\'.',
    needs: 'One numeric response and one grouping factor.',
    procedure: 'anom',
    label: 'Analysis of Means…',
    title: 'Analysis of Means',
    submitLabel: 'Run analysis of means',
    fields: [
      responseCol(),
      factorCol('factor', 'Factor'),
      { name: 'alpha', label: 'Significance level (α)', type: 'number', role: 'option', default: 0.05, min: 0.001, max: 0.499, step: 'any' },
      { name: 'graph_interval', label: 'Interval plot as well', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
      { name: 'graph_boxplot', label: 'Boxplot as well', type: 'checkbox', role: 'option', default: false, group: 'Graphs' },
    ],
    note: 'A decision-limit chart: each group mean against the overall mean, with limits that account for how many groups are being looked at. A point outside the limits is a level that differs. The critical value used is stated in the output.',
  },
];

export const PROCEDURE_BY_ID = Object.fromEntries(PROCEDURES.filter((p) => p.id).map((p) => [p.id, p]));

/** Which items become inert until a model of that kind has been fitted. */
export const MODEL_DEPENDENT = PROCEDURES.filter((p) => p.needsModel).map((p) => ({ id: p.id, kind: p.needsModel }));

// ---------------------------------------------------------------------------
// the Stat > ANOVA flyout, in Minitab's own order
// ---------------------------------------------------------------------------

const itemsInGroup = (group) =>
  PROCEDURES.filter((p) => p.group === group).map((p) => {
    const help = { icon: p.icon, description: p.description, needs: p.needs };
    return p.id ? { label: p.label, stat: p.id, ...help } : { label: p.label, disabled: true, title: p.title, ...help };
  });

const item = (id) => {
  const config = PROCEDURE_BY_ID[id];
  return config ? { label: config.label, stat: id, icon: config.icon, description: config.description, needs: config.needs } : null;
};

export function anovaMenuConfig() {
  return [
    item('one_way'),
    item('equal_variances'),
    { separator: true },
    item('balanced_anova'),
    item('nested_anova'),
    item('manova'),
    { separator: true },
    // Third-level nesting: the ANOVA flyout is itself a flyout of the Stat menu, and these two open
    // a further one. menu.js recurses, so this is a config change rather than a code change.
    { label: 'General Linear Model', items: itemsInGroup('General Linear Model') },
    { label: 'Mixed Effects Model', items: itemsInGroup('Mixed Effects Model') },
    { separator: true },
    item('interval_plot'),
    item('main_effects_plot'),
    item('interaction_plot'),
    { separator: true },
    item('anom'),
  ].filter(Boolean);
}

// ---------------------------------------------------------------------------
// values -> request
// ---------------------------------------------------------------------------

export function buildRequest(config, values, visibleList) {
  const fields = visibleList || visible(config, values);
  const columns = [];
  const options = {};
  for (const field of fields) {
    const value = values[field.name];
    if (field.role === 'column') {
      if (value) columns.push(value);
    } else if (field.role === 'columns') {
      columns.push(...(value || []));
    } else if (field.type === 'checkbox') {
      options[field.name] = !!value;
    } else if (Array.isArray(value)) {
      if (value.length) options[field.name] = value;
    } else if (value !== '' && value !== undefined && value !== null) {
      options[field.name] = field.type === 'number' ? Number(value) : value;
    }
  }
  // The backend must not guess where one block of columns ends and the next begins: a numeric
  // column can legitimately be a factor or a covariate, and only the dialog knows which.
  const names = new Set(config.fields.map((f) => f.name));
  if (names.has('factors') && names.has('covariates')) options.n_factors = (values.factors || []).length;
  if (config.procedure === 'manova') options.n_responses = (values.responses || []).length;
  if (config.procedure === 'mixed_model') {
    options.n_fixed_factors = (values.factors || []).length;
    options.n_covariates = (values.covariates || []).length;
  }
  return { procedure: config.procedure, columns, options };
}

export function describe(config, values) {
  const parts = [];
  for (const field of config.fields) {
    if (field.role !== 'column' && field.role !== 'columns') continue;
    const value = values[field.name];
    if (Array.isArray(value) && value.length) parts.push(value.join(', '));
    else if (value && typeof value === 'string') parts.push(value);
  }
  const name = config.title || config.label.replace(/…$/, '');
  return parts.length ? `${name} (${parts.join('; ')})` : name;
}

export { visibleFields, defaultValues, validate } from './procedureDialog.js';
