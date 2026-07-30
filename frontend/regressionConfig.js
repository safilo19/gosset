// Every item on Stat > Regression, declared once: form fields, the backend procedure, and how the
// inputs turn into a request. Same split as basicStatsConfig.js / basicStats.js.
//
// Fields marked `advanced: true` are rendered inside a collapsed "Options" section, so a dialog
// with fifteen settings still opens looking like a dialog with four. Field order matters: `column`
// and `columns` fields contribute to the ordered `columns` array in the order they are declared,
// which is the order the backend reads them ([response, *continuous, *categorical]).

const responseCol = (label = 'Response', extra = {}) => ({ name: 'response', label, type: 'column', role: 'column', filter: 'numeric', required: true, ...extra });

const confidence = (extra = {}) => ({
  name: 'confidence',
  label: 'Confidence level',
  type: 'number',
  role: 'option',
  default: 0.95,
  min: 0.5,
  max: 0.999,
  // step 'any': a numeric step makes the browser reject values that are not min + n×step and then
  // silently refuse to submit the form.
  step: 'any',
  advanced: true,
  ...extra,
});

const residualGraphs = () => ({
  name: 'graph_residuals',
  label: 'Four-in-one residual plots',
  type: 'checkbox',
  role: 'option',
  default: true,
  group: 'Graphs',
});

const interactionsField = () => ({
  name: 'interactions',
  label: 'Include two-way interactions',
  type: 'checkbox',
  role: 'option',
  default: false,
  advanced: true,
  hint: 'Adds every pairwise product of the terms above. With many predictors this uses up degrees of freedom quickly.',
});

const continuousField = (extra = {}) => ({
  name: 'continuous',
  label: 'Continuous predictors',
  type: 'columns',
  role: 'columns',
  filter: 'numeric',
  required: false,
  ...extra,
});

const categoricalField = (extra = {}) => ({
  name: 'categorical',
  label: 'Categorical predictors (dummy-coded automatically)',
  type: 'columns',
  role: 'columns',
  filter: 'any',
  required: false,
  ...extra,
});

// The expectation functions offered by Nonlinear Regression, with their formulas shown in the
// dropdown so the choice is not a guess.
export const EXPECTATIONS = [
  { value: 'exponential_growth', label: 'Exponential growth — θ1·exp(θ2·x)' },
  { value: 'exponential_decay', label: 'Exponential decay — θ1·exp(−θ2·x)' },
  { value: 'power', label: 'Power — θ1·x^θ2' },
  { value: 'logistic', label: 'Logistic / sigmoid — θ1 / (1 + exp(−θ2·(x − θ3)))' },
  { value: 'michaelis_menten', label: 'Michaelis-Menten — θ1·x / (θ2 + x)' },
  { value: 'gompertz', label: 'Gompertz — θ1·exp(−θ2·exp(−θ3·x))' },
  { value: 'custom', label: 'Custom formula…' },
];

const isCustomExpectation = (values) => values.expectation === 'custom';

export const PROCEDURES = [
  // ---- core linear suite ---------------------------------------------------
  {
    id: 'fitted_line',
    procedure: 'fitted_line',
    label: 'Fitted Line Plot…',
    title: 'Fitted Line Plot',
    submitLabel: 'Draw fitted line plot',
    fields: [
      responseCol(),
      { name: 'predictor', label: 'Predictor', type: 'column', role: 'column', filter: 'numeric', required: true },
      {
        name: 'order',
        label: 'Type of regression model',
        type: 'radio',
        role: 'option',
        options: [
          { value: '1', label: 'Linear' },
          { value: '2', label: 'Quadratic' },
          { value: '3', label: 'Cubic' },
        ],
        default: '1',
      },
      confidence({ hint: 'Sets both the confidence band around the fitted line and the prediction band for a single new observation.' }),
    ],
    note: 'The plot carries the fitted equation and S / R-sq / R-sq(adj), with the confidence band inside the prediction band.',
  },
  {
    id: 'fit_model',
    procedure: 'fit_model',
    label: 'Fit Regression Model…',
    title: 'Fit Regression Model',
    submitLabel: 'Fit model',
    fields: [
      responseCol(),
      continuousField(),
      categoricalField(),
      interactionsField(),
      confidence(),
      residualGraphs(),
    ],
    note: 'Choose at least one predictor, continuous or categorical. Output includes the ANOVA table, coefficients with VIF, unusual observations, and a Predict panel.',
  },
  {
    id: 'best_subsets',
    procedure: 'best_subsets',
    label: 'Best Subsets…',
    title: 'Best Subsets Regression',
    submitLabel: 'Evaluate all subsets',
    fields: [
      responseCol(),
      { name: 'predictors', label: 'Candidate predictors (up to 12)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1, maxSelect: 12 },
      {
        name: 'models_per_size',
        label: 'Models to report per subset size',
        type: 'number',
        role: 'option',
        default: 2,
        min: 1,
        max: 5,
        step: 1,
        advanced: true,
      },
    ],
    note: 'Every subset of the candidates is fitted (2^k − 1 models), and the best few of each size are tabulated with R-sq, R-sq(adj), Mallows’ Cp and S. Above 10 predictors this gets slow; 12 is the cap.',
  },
  {
    id: 'stepwise',
    procedure: 'stepwise',
    label: 'Stepwise…',
    title: 'Stepwise Regression',
    submitLabel: 'Run stepwise selection',
    fields: [
      responseCol(),
      { name: 'predictors', label: 'Candidate predictors', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 1 },
      {
        name: 'method',
        label: 'Method',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'stepwise', label: 'Stepwise (terms may enter and leave)' },
          { value: 'forward', label: 'Forward selection (terms only enter)' },
          { value: 'backward', label: 'Backward elimination (start full, terms only leave)' },
        ],
        default: 'stepwise',
      },
      { name: 'alpha_enter', label: 'Alpha to enter', type: 'number', role: 'option', default: 0.15, min: 0.001, max: 0.999, step: 'any', advanced: true },
      { name: 'alpha_remove', label: 'Alpha to remove', type: 'number', role: 'option', default: 0.15, min: 0.001, max: 0.999, step: 'any', advanced: true },
      confidence(),
      residualGraphs(),
    ],
    note: 'The output shows which term entered or left at each step with its p-value, then the full output for the final model.',
  },

  // ---- specialized continuous models ---------------------------------------
  {
    id: 'nonlinear',
    procedure: 'nonlinear',
    label: 'Nonlinear Regression…',
    title: 'Nonlinear Regression',
    submitLabel: 'Fit nonlinear model',
    fields: [
      responseCol(),
      { name: 'predictor', label: 'Predictor', type: 'column', role: 'column', filter: 'numeric', required: true },
      { name: 'expectation', label: 'Expectation function', type: 'select', role: 'option', options: EXPECTATIONS, default: 'exponential_growth' },
      {
        name: 'formula',
        label: 'Custom expectation function',
        type: 'text',
        role: 'option',
        mono: true,
        placeholder: 'a + b * log(x)',
        showIf: isCustomExpectation,
        required: true,
        hint: 'Use x for the predictor and any other names as parameters. Arithmetic plus exp, log, sqrt, power, sin, cos, tanh and similar are allowed — nothing else is evaluated.',
      },
      {
        name: 'starting_values',
        label: 'Starting values',
        type: 'text',
        role: 'option',
        mono: true,
        placeholder: 'theta1=60, theta2=0.05',
        advanced: true,
        hint: 'Optional. Left empty, starting values are derived from the data (a log-linear fit for the exponential and power forms, the maximum and median for the sigmoid ones).',
      },
      { name: 'max_iterations', label: 'Maximum function evaluations', type: 'number', role: 'option', default: 2000, min: 200, max: 100000, step: 100, advanced: true },
      confidence(),
    ],
    note: 'Least squares by Levenberg-Marquardt. A nonlinear fit can settle in a local minimum — if the curve looks wrong, set starting values closer to the answer.',
  },
  {
    id: 'stability',
    procedure: 'stability',
    label: 'Stability Study…',
    title: 'Stability Study',
    submitLabel: 'Estimate shelf life',
    fields: [
      responseCol('Response (the measured attribute)'),
      { name: 'time', label: 'Time', type: 'column', role: 'column', filter: 'numeric', required: true },
      { name: 'batch', label: 'Batch (optional)', type: 'column', role: 'column', filter: 'any', required: false },
      { name: 'spec_limit', label: 'Specification limit', type: 'number', role: 'option', step: 'any', required: true },
      {
        name: 'spec_side',
        label: 'The limit is a',
        type: 'radio',
        role: 'option',
        options: [
          { value: 'lower', label: 'Lower limit (the response degrades downwards)' },
          { value: 'upper', label: 'Upper limit (the response rises into failure)' },
        ],
        default: 'lower',
      },
      { name: 'time_units', label: 'Time units (for the wording only)', type: 'text', role: 'option', placeholder: 'months', advanced: true },
      { name: 'pool_alpha', label: 'Alpha for pooling batches', type: 'number', role: 'option', default: 0.25, min: 0.01, max: 0.99, step: 'any', advanced: true, hint: 'ICH Q1E convention is 0.25 — deliberately generous, because pooling is only safe when batch differences are clearly absent.' },
      confidence(),
    ],
    note: 'Batches are tested for equal slopes and then equal intercepts; the most pooled model that survives is fitted. Shelf life is where the one-sided confidence bound on the mean first crosses the spec limit.',
  },
  {
    id: 'orthogonal',
    procedure: 'orthogonal',
    label: 'Orthogonal Regression…',
    title: 'Orthogonal Regression',
    submitLabel: 'Fit orthogonal regression',
    fields: [
      responseCol(),
      { name: 'predictor', label: 'Predictor', type: 'column', role: 'column', filter: 'numeric', required: true },
      {
        name: 'error_ratio',
        label: 'Error variance ratio (response : predictor)',
        type: 'number',
        role: 'option',
        default: 1,
        min: 0.0001,
        step: 'any',
        hint: '1 means both variables are measured with equal error — the usual assumption when comparing two instruments.',
      },
      confidence(),
    ],
    note: 'Also called Deming regression. Unlike ordinary least squares it allows for measurement error in the predictor, so it is the right choice for method-comparison work.',
  },
  {
    id: 'pls',
    procedure: 'pls',
    label: 'Partial Least Squares…',
    title: 'Partial Least Squares Regression',
    submitLabel: 'Fit PLS model',
    fields: [
      responseCol(),
      { name: 'predictors', label: 'Predictors (2 or more)', type: 'columns', role: 'columns', filter: 'numeric', required: true, minSelect: 2 },
      {
        name: 'components',
        label: 'Number of components',
        type: 'text',
        role: 'option',
        default: 'cv',
        placeholder: 'cv',
        hint: 'Leave as "cv" to let cross-validation choose the number with the highest predicted R², or type a number.',
      },
      { name: 'cv_folds', label: 'Cross-validation folds', type: 'number', role: 'option', default: 5, min: 2, max: 20, step: 1, advanced: true },
    ],
    note: 'Useful when the predictors are many or strongly correlated, where ordinary least squares becomes unstable.',
  },

  { separator: true },

  // ---- categorical-response models -----------------------------------------
  {
    id: 'binary_fitted_line',
    procedure: 'binary_fitted_line',
    label: 'Binary Fitted Line Plot…',
    title: 'Binary Fitted Line Plot',
    submitLabel: 'Draw binary fitted line plot',
    fields: [
      { name: 'response', label: 'Binary response', type: 'column', role: 'column', filter: 'any', required: true },
      { name: 'predictor', label: 'Predictor', type: 'column', role: 'column', filter: 'numeric', required: true },
      { name: 'event_value', label: 'Event (which value is the "success")', type: 'value', role: 'option', from: 'response', required: false, advanced: true },
      confidence(),
    ],
    note: 'Fits a one-predictor logistic model and draws the fitted probability as an S-curve through the observed 0/1 values.',
  },
  {
    id: 'binary_logistic',
    procedure: 'binary_logistic',
    label: 'Binary Logistic Regression…',
    title: 'Binary Logistic Regression',
    submitLabel: 'Fit logistic model',
    fields: [
      { name: 'response', label: 'Binary response', type: 'column', role: 'column', filter: 'any', required: true },
      continuousField(),
      categoricalField(),
      { name: 'event_value', label: 'Event (which value is the "success")', type: 'value', role: 'option', from: 'response', required: false },
      interactionsField(),
      confidence({ hint: 'Sets the interval reported for each odds ratio.' }),
    ],
    note: 'Odds ratios and their intervals are the headline output; goodness of fit is reported by the deviance, Pearson and Hosmer-Lemeshow tests, with a classification table and an ROC curve.',
  },
  {
    id: 'ordinal_logistic',
    procedure: 'ordinal_logistic',
    label: 'Ordinal Logistic Regression…',
    title: 'Ordinal Logistic Regression',
    submitLabel: 'Fit ordinal model',
    fields: [
      { name: 'response', label: 'Ordinal response (3 or more ordered levels)', type: 'column', role: 'column', filter: 'any', required: true },
      continuousField(),
      categoricalField(),
      {
        name: 'level_order',
        label: 'Level order, lowest first',
        type: 'levels',
        role: 'option',
        from: 'response',
        required: false,
        hint: 'Tick the levels in order from lowest to highest. Left empty, they are taken in alphabetical order — which is rarely the right order for Low / Medium / High.',
      },
      interactionsField(),
      confidence(),
    ],
    note: 'A proportional-odds model: one odds ratio per predictor applies across every cutpoint, and the cutpoints themselves are reported as thresholds.',
  },
  {
    id: 'nominal_logistic',
    procedure: 'nominal_logistic',
    label: 'Nominal Logistic Regression…',
    title: 'Nominal Logistic Regression',
    submitLabel: 'Fit nominal model',
    fields: [
      { name: 'response', label: 'Nominal response (3 or more unordered levels)', type: 'column', role: 'column', filter: 'any', required: true },
      continuousField(),
      categoricalField(),
      { name: 'reference_level', label: 'Reference level', type: 'value', role: 'option', from: 'response', required: false, emptyLabel: '— first level —' },
      interactionsField(),
      confidence(),
    ],
    note: 'One logit per non-reference outcome level, each compared with the reference. Every coefficient is reported with its odds ratio.',
  },
  {
    id: 'poisson_regression',
    procedure: 'poisson_regression',
    label: 'Poisson Regression…',
    title: 'Poisson Regression',
    submitLabel: 'Fit Poisson model',
    fields: [
      responseCol('Response (a column of counts)'),
      continuousField(),
      categoricalField(),
      {
        name: 'exposure_column',
        label: 'Exposure / offset column (optional)',
        type: 'column',
        role: 'option',
        filter: 'numeric',
        required: false,
        hint: 'Its logarithm enters the model as an offset, so the coefficients describe a rate per unit of exposure rather than a raw count.',
      },
      interactionsField(),
      confidence({ hint: 'Sets the interval reported for each incidence rate ratio.' }),
    ],
    note: 'Incidence rate ratios are the headline output. Deviance/DF far above 1 means overdispersion, which the output flags.',
  },
];

export const PROCEDURE_BY_ID = Object.fromEntries(PROCEDURES.filter((p) => p.id).map((p) => [p.id, p]));

// The Stat > Regression flyout, mirroring Minitab's structure: the three workhorse dialogs sit in
// their own nested "Regression" submenu, and the categorical-response models follow a divider.
export const REGRESSION_MENU = [
  {
      label: 'Fitted Line Plot…',
      stat: 'fitted_line',
      icon: 'fitted-line',
      description: 'Fits one predictor against one response and draws the line through the points with its confidence band. Linear, quadratic or cubic. The quickest way to see the shape of a relationship before modelling it properly.',
      needs: 'One numeric response and one numeric predictor.',
    },
  {
    label: 'Regression',
    items: [
      {
      label: 'Fit Regression Model…',
      stat: 'fit_model',
      icon: 'fit-regression',
      description: 'Fits a response against several predictors, continuous or categorical, and reports the coefficients, R², the ANOVA table and residual diagnostics. The main regression dialog, and the one with the Predict panel.',
      needs: 'One numeric response and one or more predictors.',
    },
      {
      label: 'Best Subsets…',
      stat: 'best_subsets',
      icon: 'best-subsets',
      description: 'Fits every combination of the candidate predictors and ranks them by R², adjusted R² and Mallows\' Cp, so competing models can be compared side by side. Stepwise instead follows a single path.',
      needs: 'One numeric response and several candidate predictors.',
    },
      {
      label: 'Stepwise…',
      stat: 'stepwise',
      icon: 'stepwise',
      description: 'Adds and removes predictors one at a time by their p-values until nothing further qualifies, showing each step. Faster than Best Subsets on many predictors, but it reports one path rather than the whole field.',
      needs: 'One numeric response and several candidate predictors.',
    },
    ],
  },
  {
      label: 'Nonlinear Regression…',
      stat: 'nonlinear',
      icon: 'nonlinear-regression',
      description: 'Fits a curve of a named form — exponential, logistic, power — by least squares from starting values. For relationships that are not a polynomial in the predictors.',
      needs: 'One numeric response, one numeric predictor, and starting values.',
    },
  {
      label: 'Stability Study…',
      stat: 'stability',
      icon: 'stability-study',
      description: 'Estimates shelf life by regressing a quality attribute against time and finding where the confidence bound crosses the specification limit, following ICH Q1E including the batch-poolability tests.',
      needs: 'A response, a time column, a batch column and a specification limit.',
    },
  {
      label: 'Orthogonal Regression…',
      stat: 'orthogonal',
      icon: 'orthogonal-regression',
      description: 'Fits a straight line when BOTH variables carry measurement error, minimising perpendicular rather than vertical distance to the line. The right tool for comparing two instruments.',
      needs: 'Two numeric columns and the ratio of their error variances.',
    },
  {
      label: 'Partial Least Squares…',
      stat: 'pls',
      icon: 'partial-least-squares',
      description: 'Extracts a few components from many heavily correlated predictors and regresses the response on those. For when the predictors outnumber the rows, or ordinary regression fails on collinearity.',
      needs: 'One numeric response and several numeric predictors.',
    },
  { separator: true },
  {
      label: 'Binary Fitted Line Plot…',
      stat: 'binary_fitted_line',
      icon: 'binary-fitted-line',
      description: 'Fits one predictor against a yes/no response and draws the fitted probability curve through the data. The logistic counterpart of Fitted Line Plot.',
      needs: 'One response with 2 outcomes and one numeric predictor.',
    },
  {
      label: 'Binary Logistic Regression…',
      stat: 'binary_logistic',
      icon: 'binary-logistic',
      description: 'Models a yes/no response against several predictors and reports odds ratios with confidence intervals. For when the response is a category rather than a quantity.',
      needs: 'One response with 2 outcomes and one or more predictors.',
    },
  {
      label: 'Ordinal Logistic Regression…',
      stat: 'ordinal_logistic',
      icon: 'ordinal-logistic',
      description: 'Models a response whose categories have a meaningful ORDER — low/medium/high, a 1–5 rating — exploiting that order to gain statistical power over a model that treats the levels as unrelated labels.',
      needs: 'One ordered categorical response with 3 or more levels, and one or more predictors.',
    },
  {
      label: 'Nominal Logistic Regression…',
      stat: 'nominal_logistic',
      icon: 'nominal-logistic',
      description: 'Models a categorical response with NO natural order — which of four brands was chosen. If the categories do have an order, Ordinal Logistic Regression exploits it and needs fewer observations.',
      needs: 'One categorical response with 3 or more levels, and one or more predictors.',
    },
  {
      label: 'Poisson Regression…',
      stat: 'poisson_regression',
      icon: 'poisson-regression',
      description: 'Models a COUNT response using a log link, so predictions stay non-negative. Ordinary regression on counts can predict negative values and mis-states the variance.',
      needs: 'One column of counts and one or more predictors.',
    },
];

// ---------------------------------------------------------------------------
// values -> request
// ---------------------------------------------------------------------------

export function buildRequest(config, values, visible) {
  const fields = visible || config.fields;
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
    } else if (value !== '' && value !== undefined && value !== null) {
      options[field.name] = field.type === 'number' ? Number(value) : value;
    }
  }
  // The backend must not guess which predictors were meant as continuous: a numeric column can
  // legitimately be either, so the split is sent explicitly.
  if (config.fields.some((f) => f.name === 'continuous')) options.n_continuous = (values.continuous || []).length;
  return { procedure: config.procedure, columns, options };
}

export function describe(config, values) {
  const parts = [];
  for (const field of config.fields) {
    if (field.role !== 'column' && field.role !== 'columns') continue;
    const value = values[field.name];
    if (Array.isArray(value) && value.length) parts.push(value.join(', '));
    else if (value) parts.push(String(value));
  }
  const name = config.label.replace(/…$/, '');
  return parts.length ? `${name} (${parts.join('; ')})` : name;
}
