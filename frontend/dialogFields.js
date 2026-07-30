// The composite field types the Data menu needs, kept out of procedureDialog.js so that engine
// stays the small, readable thing it is. procedureDialog delegates any field type it does not
// recognise to the table at the bottom of this file.
//
// They are all the same shape: a small repeating-row widget whose value is an ARRAY of little
// records (a sort key, a condition, an old→new mapping, a block of columns). Rows are added and
// removed in place, and the widget only rebuilds itself when a field it depends on changes —
// rebuilding on every keystroke would pull focus out of the input being typed into.

import * as pd from './procedureDialog.js';
import { h } from './resultView.js';

export const CONDITION_OPERATORS = [
  { value: '=', label: '= equals' },
  { value: '≠', label: '≠ does not equal' },
  { value: '>', label: '> greater than' },
  { value: '<', label: '< less than' },
  { value: '≥', label: '≥ at least' },
  { value: '≤', label: '≤ at most' },
  { value: 'contains', label: 'contains' },
  { value: 'starts with', label: 'starts with' },
  { value: 'ends with', label: 'ends with' },
  { value: 'between', label: 'between (two values)' },
  { value: 'is missing', label: 'is missing' },
  { value: 'is not missing', label: 'is not missing' },
];

const NO_VALUE_OPERATORS = new Set(['is missing', 'is not missing']);

// ---------------------------------------------------------------------------
// small builders
// ---------------------------------------------------------------------------

function columnSelect(options, value, placeholder, onPick) {
  const select = h('select', {}, [h('option', { value: '', text: placeholder }), ...options.map((c) => h('option', { value: c, text: c }))]);
  select.value = options.includes(value) ? value : '';
  select.addEventListener('change', () => onPick(select.value));
  return select;
}

function plainSelect(options, value, onPick) {
  const select = h('select', {}, options.map((o) => h('option', { value: o.value, text: o.label })));
  select.value = value;
  select.addEventListener('change', () => onPick(select.value));
  return select;
}

function textInput(value, placeholder, onType, { mono = false } = {}) {
  const input = h('input', { type: 'text', placeholder: placeholder || '' });
  if (mono) input.className = 'mono-input';
  input.value = value === null || value === undefined ? '' : String(value);
  input.addEventListener('input', () => onType(input.value));
  return input;
}

/**
 * The shared skeleton: a list of rows, an "Add" button and a per-row remove button.
 * `buildRow(row, index)` returns the row's controls; `blank()` returns a fresh empty record.
 */
function repeatingRows(field, values, onChange, { blank, buildRow, addLabel, rowClass = 'dialog-row' }) {
  const wrap = h('div', { class: 'repeat-rows' });
  const list = h('div', { class: 'repeat-rows-list' });
  const max = field.max || 8;

  const redraw = () => {
    list.innerHTML = '';
    const rows = values[field.name] || (values[field.name] = [blank()]);
    if (!rows.length) rows.push(blank());
    rows.forEach((row, index) => {
      const line = h('div', { class: rowClass });
      for (const control of buildRow(row, index)) if (control) line.appendChild(control);
      line.appendChild(
        h('button', {
          type: 'button',
          class: 'btn btn-sm repeat-row-remove',
          text: '×',
          title: 'Remove this row',
          'aria-label': 'Remove this row',
          onClick: () => {
            rows.splice(index, 1);
            if (!rows.length) rows.push(blank());
            redraw();
            onChange();
          },
        }),
      );
      list.appendChild(line);
    });
    addBtn.disabled = rows.length >= max;
  };

  const addBtn = h('button', {
    type: 'button',
    class: 'btn btn-sm',
    text: addLabel || 'Add',
    onClick: () => {
      const rows = values[field.name] || (values[field.name] = []);
      if (rows.length >= max) return;
      rows.push(blank());
      redraw();
      onChange();
    },
  });

  wrap.append(list, h('div', { class: 'repeat-rows-actions' }, [addBtn]));
  redraw();
  return { wrap, redraw };
}

// ---------------------------------------------------------------------------
// the field types
// ---------------------------------------------------------------------------

// Up to four sort keys, each a column and a direction — Minitab's Sort dialog exactly.
function sortBy(field, values, onChange) {
  const columns = pd.columnsFor(field.filter || 'any');
  const { wrap } = repeatingRows(field, values, onChange, {
    blank: () => ({ column: '', direction: 'ascending' }),
    addLabel: 'Add sort column',
    buildRow: (row, index) => [
      h('span', { class: 'repeat-row-index', text: index === 0 ? 'By' : 'then' }),
      columnSelect(columns, row.column, '— choose a column —', (v) => {
        row.column = v;
        onChange();
      }),
      plainSelect(
        [
          { value: 'ascending', label: 'Ascending' },
          { value: 'descending', label: 'Descending' },
        ],
        row.direction,
        (v) => {
          row.direction = v;
          onChange();
        },
      ),
    ],
  });
  return wrap;
}

// How many value boxes an operator needs — a row is only rebuilt when this changes, so choosing
// '>' after '<' leaves the select the user is still holding alone.
const valueBoxes = (operator) => (NO_VALUE_OPERATORS.has(operator) ? 0 : operator === 'between' ? 2 : 1);

// The condition builder shared by Subset Worksheet and the Copy dialogs.
function conditions(field, values, onChange) {
  const columns = pd.columnsFor('any');
  let inner;
  const { wrap, redraw } = repeatingRows(field, values, onChange, {
    blank: () => ({ column: '', operator: '=', value: '', value2: '' }),
    addLabel: 'Add condition',
    rowClass: 'dialog-row condition-row',
    buildRow: (row, index) => {
      const needsValue = !NO_VALUE_OPERATORS.has(row.operator);
      const controls = [
        h('span', { class: 'repeat-row-index', text: index === 0 ? 'Where' : (values[field.joinerFrom] || 'and').toUpperCase() }),
        columnSelect(columns, row.column, '— column —', (v) => {
          row.column = v;
          onChange();
        }),
        plainSelect(CONDITION_OPERATORS, row.operator, (v) => {
          const before = valueBoxes(row.operator);
          row.operator = v;
          // 'between' grows a second box and 'is missing' loses the first — only those need the
          // row rebuilt. Rebuilding on every operator change would yank the select out from
          // under the pointer that just used it.
          if (valueBoxes(v) !== before) inner.redraw();
          onChange();
        }),
      ];
      if (needsValue) {
        controls.push(
          textInput(row.value, 'value', (v) => {
            row.value = v;
            onChange();
          }),
        );
      }
      if (row.operator === 'between') {
        controls.push(h('span', { class: 'repeat-row-index', text: 'and' }));
        controls.push(
          textInput(row.value2, 'value', (v) => {
            row.value2 = v;
            onChange();
          }),
        );
      }
      return controls;
    },
  });
  inner = { redraw };
  return wrap;
}

// Old value → new value rows (Recode). Free text on both sides: the backend decides how to read
// them from the target type, so '3' recoding to 'high' and 'high' recoding to 3 both work.
function mapRows(field, values, onChange) {
  const { wrap } = repeatingRows(field, values, onChange, {
    blank: () => ({ from: '', to: '' }),
    addLabel: 'Add value',
    buildRow: (row) => [
      textInput(
        row.from,
        'old value',
        (v) => {
          row.from = v;
          onChange();
        },
        { mono: true },
      ),
      h('span', { class: 'repeat-row-index', text: '→' }),
      textInput(
        row.to,
        'new value',
        (v) => {
          row.to = v;
          onChange();
        },
        { mono: true },
      ),
    ],
  });
  return wrap;
}

// Numeric range → new value rows, for recoding a measurement into bands.
function rangeRows(field, values, onChange) {
  const { wrap } = repeatingRows(field, values, onChange, {
    blank: () => ({ low: '', high: '', to: '', low_inclusive: true, high_inclusive: true }),
    addLabel: 'Add range',
    buildRow: (row) => [
      textInput(
        row.low,
        'from',
        (v) => {
          row.low = v;
          onChange();
        },
        { mono: true },
      ),
      h('span', { class: 'repeat-row-index', text: 'to' }),
      textInput(
        row.high,
        'to',
        (v) => {
          row.high = v;
          onChange();
        },
        { mono: true },
      ),
      h('span', { class: 'repeat-row-index', text: '→' }),
      textInput(
        row.to,
        'new value',
        (v) => {
          row.to = v;
          onChange();
        },
        { mono: true },
      ),
    ],
  });
  return wrap;
}

// One worksheet, chosen from the ones open right now.
function worksheetPick(field, values, onChange) {
  const options = pd.worksheetOptions(field.includeActive === true);
  const select = h('select', {}, [
    h('option', { value: '', text: options.length ? '— choose a worksheet —' : '— no other worksheet is open —' }),
    ...options.map((w) => h('option', { value: w.id, text: w.label })),
  ]);
  select.value = options.some((w) => w.id === values[field.name]) ? values[field.name] : '';
  values[field.name] = select.value;
  select.addEventListener('change', () => {
    values[field.name] = select.value;
    onChange();
  });
  return select;
}

// Several worksheets at once (Stack Worksheets, Merge Side-by-Side).
function worksheetsPick(field, values, onChange) {
  const options = pd.worksheetOptions(field.includeActive === true);
  const list = h('div', { class: 'checkbox-list' });
  if (!options.length) list.appendChild(h('p', { class: 'muted', text: 'No other worksheet is open. Open or create one first.' }));
  values[field.name] = (values[field.name] || []).filter((id) => options.some((w) => w.id === id));
  for (const worksheet of options) {
    const box = h('input', { type: 'checkbox' });
    box.checked = (values[field.name] || []).includes(worksheet.id);
    box.addEventListener('change', () => {
      const current = values[field.name] || [];
      values[field.name] = box.checked ? [...current, worksheet.id] : current.filter((id) => id !== worksheet.id);
      onChange();
    });
    list.appendChild(h('label', { class: 'checkbox-item' }, [box, worksheet.label]));
  }
  return list;
}

// A column of ANOTHER worksheet — `from` names the worksheet field it follows.
function otherColumn(field, values, onChange, refreshers) {
  const select = h('select', {});
  let lastSource = null;
  const fill = () => {
    const source = values[field.from] || '';
    if (source === lastSource) return;
    lastSource = source;
    const options = pd.columnsOf(source);
    select.innerHTML = '';
    select.appendChild(h('option', { value: '', text: options.length ? '— choose a column —' : '— choose a worksheet first —' }));
    for (const name of options) select.appendChild(h('option', { value: name, text: name }));
    if (!options.includes(values[field.name])) values[field.name] = '';
    select.value = values[field.name] || '';
  };
  fill();
  refreshers.push(fill);
  select.addEventListener('change', () => {
    values[field.name] = select.value;
    onChange();
  });
  return select;
}

// Key pairs for Merge ▸ Match Values: a column here, the column it matches over there.
function pairs(field, values, onChange, refreshers) {
  let lastSource = null;
  const leftColumns = pd.columnsFor('any');

  const build = () => {
    const rightColumns = pd.columnsOf(values[field.rightFrom] || '');
    const { wrap } = repeatingRows(field, values, onChange, {
      blank: () => ({ left: '', right: '' }),
      addLabel: 'Add key column',
      buildRow: (row, index) => {
        const right = columnSelect(rightColumns, row.right, rightColumns.length ? '— other worksheet —' : '— choose a worksheet —', (v) => {
          row.right = v;
          onChange();
        });
        const left = columnSelect(leftColumns, row.left, '— this worksheet —', (v) => {
          row.left = v;
          // Same name on both sides is the common case — prefill it, but by moving the other
          // select's value rather than rebuilding the row the pointer is still in.
          if (!row.right && rightColumns.includes(v)) {
            row.right = v;
            right.value = v;
          }
          onChange();
        });
        return [h('span', { class: 'repeat-row-index', text: index === 0 ? 'Match' : 'and' }), left, h('span', { class: 'repeat-row-index', text: 'with' }), right];
      },
    });
    return wrap;
  };

  const host = h('div');
  const fill = () => {
    const source = values[field.rightFrom] || '';
    if (source === lastSource) return;
    lastSource = source;
    host.innerHTML = '';
    host.appendChild(build());
  };
  fill();
  refreshers.push(fill);
  return host;
}

// Blocks of columns for Stack ▸ Blocks of Columns: every block must be the same width, so the
// widget says so and shows each block's width as it is built.
function columnBlocks(field, values, onChange) {
  const columns = pd.columnsFor(field.filter || 'any');
  const wrap = h('div', { class: 'repeat-rows' });
  const list = h('div', { class: 'repeat-rows-list' });
  const max = field.max || 8;

  // Ticking a column only changes the counts in the headings, so only the headings are rewritten.
  // A full redraw would destroy the checkbox that was just clicked — and with it the scroll
  // position of the list the next tick is aimed at.
  const counters = [];
  const updateHeads = () => {
    const blocks = values[field.name] || [];
    const width = (blocks[0] || []).length;
    counters.forEach((el, index) => {
      const size = (blocks[index] || []).length;
      el.textContent = `${size} column(s)${index > 0 && width && size !== width ? ` — block 1 has ${width}` : ''}`;
    });
  };

  const redraw = () => {
    list.innerHTML = '';
    counters.length = 0;
    const blocks = values[field.name] || (values[field.name] = [[], []]);
    while (blocks.length < 2) blocks.push([]);
    blocks.forEach((block, index) => {
      const picker = h('div', { class: 'checkbox-list checkbox-list-inline' });
      for (const name of columns) {
        const box = h('input', { type: 'checkbox' });
        box.checked = block.includes(name);
        box.addEventListener('change', () => {
          // Tick order is meaningful: it is the order the columns line up across blocks.
          if (box.checked) {
            if (!block.includes(name)) block.push(name);
          } else {
            const at = block.indexOf(name);
            if (at >= 0) block.splice(at, 1);
          }
          updateHeads();
          onChange();
        });
        picker.appendChild(h('label', { class: 'checkbox-item' }, [box, name]));
      }
      const counter = h('span', { class: 'settings-hint' });
      counters.push(counter);
      const head = h('div', { class: 'block-head' }, [
        h('span', { class: 'section-label', text: `Block ${index + 1}` }),
        counter,
        blocks.length > 2
          ? h('button', {
              type: 'button',
              class: 'btn btn-sm',
              text: 'Remove',
              onClick: () => {
                blocks.splice(index, 1);
                redraw();
                onChange();
              },
            })
          : null,
      ]);
      list.appendChild(h('div', { class: 'column-block' }, [head, picker]));
    });
    updateHeads();
    addBtn.disabled = blocks.length >= max;
  };

  const addBtn = h('button', {
    type: 'button',
    class: 'btn btn-sm',
    text: 'Add block',
    onClick: () => {
      const blocks = values[field.name] || (values[field.name] = []);
      if (blocks.length >= max) return;
      blocks.push([]);
      redraw();
      onChange();
    },
  });

  wrap.append(list, h('div', { class: 'repeat-rows-actions' }, [addBtn]));
  redraw();
  return wrap;
}

// One text box per column picked in another field — "store these in…" naming.
function names(field, values, onChange, refreshers) {
  const host = h('div', { class: 'repeat-rows-list' });
  let lastKey = null;
  const fill = () => {
    const sources = values[field.from] || [];
    const key = sources.join(' ');
    if (key === lastKey) return;
    lastKey = key;
    host.innerHTML = '';
    values[field.name] = values[field.name] || [];
    if (!sources.length) {
      host.appendChild(h('p', { class: 'muted', text: 'Choose the columns first.' }));
      return;
    }
    sources.forEach((source, index) => {
      host.appendChild(
        h('div', { class: 'dialog-row' }, [
          h('span', { class: 'repeat-row-index', text: source }),
          textInput(values[field.name][index] || '', field.placeholder || 'new name (optional)', (v) => {
            values[field.name][index] = v;
            onChange();
          }),
        ]),
      );
    });
  };
  fill();
  refreshers.push(fill);
  return host;
}

// The stored constants, for Copy ▸ Constants to Column / Constants to Constants.
function constantsPick(field, values, onChange) {
  const options = pd.constantOptions();
  const list = h('div', { class: 'checkbox-list' });
  if (!options.length) list.appendChild(h('p', { class: 'muted', text: 'No constants are stored yet. Add some in Data > Constants.' }));
  values[field.name] = (values[field.name] || []).filter((key) => options.some((c) => c.key === key));
  for (const constant of options) {
    const box = h('input', { type: 'checkbox' });
    box.checked = (values[field.name] || []).includes(constant.key);
    box.addEventListener('change', () => {
      const current = values[field.name] || [];
      values[field.name] = box.checked ? [...current, constant.key] : current.filter((k) => k !== constant.key);
      onChange();
    });
    list.appendChild(h('label', { class: 'checkbox-item' }, [box, constant.label]));
  }
  return list;
}

// ---------------------------------------------------------------------------
// the ANOVA menu's field types
// ---------------------------------------------------------------------------

// A subset of the columns another field has already chosen — "which of these factors are random",
// "which of these covariates get a random slope". Rebuilt only when the source selection changes.
function subset(field, values, onChange, refreshers) {
  const host = h('div', { class: 'checkbox-list' });
  let lastKey = null;
  const fill = () => {
    const sources = values[field.from] || [];
    const key = sources.join(' ');
    if (key === lastKey) return;
    lastKey = key;
    values[field.name] = (values[field.name] || []).filter((c) => sources.includes(c));
    host.innerHTML = '';
    if (!sources.length) {
      host.appendChild(h('p', { class: 'muted', text: 'Choose the columns above first.' }));
      return;
    }
    for (const name of sources) {
      const box = h('input', { type: 'checkbox' });
      box.checked = (values[field.name] || []).includes(name);
      box.addEventListener('change', () => {
        const current = values[field.name] || [];
        values[field.name] = box.checked ? [...current, name] : current.filter((c) => c !== name);
        onChange();
      });
      host.appendChild(h('label', { class: 'checkbox-item' }, [box, name]));
    }
  };
  fill();
  refreshers.push(fill);
  return host;
}

/** Every 2-way and 3-way combination of the chosen predictors, as `a*b` strings. */
function candidateTerms(sources) {
  const terms = [];
  for (let i = 0; i < sources.length; i += 1) {
    for (let j = i + 1; j < sources.length; j += 1) {
      terms.push(`${sources[i]}*${sources[j]}`);
      for (let k = j + 1; k < sources.length; k += 1) terms.push(`${sources[i]}*${sources[j]}*${sources[k]}`);
    }
  }
  return terms;
}

// The explicit term picker: main effects are listed as fixed (they are always in the model) and
// every interaction is a checkbox. Sending an explicit term list is what lets a model hold
// `a*b` without also holding `a*c`, which the "all two-way" checkbox cannot express.
function termPicker(field, values, onChange, refreshers) {
  const host = h('div');
  let lastKey = null;
  const sourcesOf = () => [].concat(...(field.from || []).map((name) => values[name] || []));
  const fill = () => {
    const sources = sourcesOf();
    const key = sources.join(' ');
    if (key === lastKey) return;
    lastKey = key;
    host.innerHTML = '';
    if (sources.length < 2) {
      host.appendChild(h('p', { class: 'muted', text: 'Choose at least two factors or covariates to build interaction terms from.' }));
      values[field.name] = [];
      return;
    }
    const candidates = candidateTerms(sources);
    // Main effects are not optional, so they are shown as context rather than as choices.
    host.appendChild(h('p', { class: 'settings-hint', text: `Always included: ${sources.join(', ')}` }));
    const chosen = new Set((values[field.name] || []).filter((t) => t.includes('*')));
    const list = h('div', { class: 'checkbox-list checkbox-list-inline' });
    for (const term of candidates) {
      const box = h('input', { type: 'checkbox' });
      box.checked = chosen.has(term);
      box.addEventListener('change', () => {
        if (box.checked) chosen.add(term);
        else chosen.delete(term);
        // The value sent is the WHOLE term list — main effects first, then the ticked interactions.
        values[field.name] = chosen.size ? [...sources, ...candidates.filter((t) => chosen.has(t))] : [];
        onChange();
      });
      list.appendChild(h('label', { class: 'checkbox-item' }, [box, term.replace(/\*/g, ' × ')]));
    }
    host.appendChild(list);
    values[field.name] = chosen.size ? [...sources, ...candidates.filter((t) => chosen.has(t))] : [];
  };
  fill();
  refreshers.push(fill);
  return host;
}

// One of the stored model's factors / covariates. These dialogs have no column pickers of their
// own — the model decides what can be chosen.
function modelPart(field, values, onChange, which) {
  const model = pd.storedModel();
  const options = model ? model[which] || [] : [];
  const select = h('select', {}, [
    h('option', { value: '', text: options.length ? `— choose a ${which === 'factors' ? 'factor' : 'covariate'} —` : `the stored model has no ${which}` }),
    ...options.map((name) => h('option', { value: name, text: name })),
  ]);
  if (!options.includes(values[field.name])) values[field.name] = options.length === 1 ? options[0] : '';
  select.value = values[field.name] || '';
  select.addEventListener('change', () => {
    values[field.name] = select.value;
    onChange();
  });
  return select;
}

const modelFactor = (field, values, onChange) => modelPart(field, values, onChange, 'factors');
const modelCovariate = (field, values, onChange) => modelPart(field, values, onChange, 'covariates');

// The "hold everything else at" block on a contour/surface dialog: a number box per covariate not
// on an axis, a level picker per factor. Rebuilt when the axis choices change.
function modelHolds(field, values, onChange, refreshers) {
  const host = h('div', { class: 'repeat-rows-list' });
  let lastKey = null;
  const fill = () => {
    const model = pd.storedModel();
    if (!model) {
      host.innerHTML = '';
      host.appendChild(h('p', { class: 'muted', text: 'Fit a model first.' }));
      return;
    }
    const axes = [values.x, values.y].filter(Boolean);
    const key = axes.join('|');
    if (key === lastKey) return;
    lastKey = key;
    host.innerHTML = '';
    const holds = { ...(values[field.name] || {}) };

    const remaining = (model.covariates || []).filter((c) => !axes.includes(c));
    for (const name of remaining) {
      const mean = (model.means || {})[name];
      const input = h('input', { type: 'number', step: 'any' });
      input.value = holds[name] !== undefined ? holds[name] : mean !== undefined ? Number(mean).toFixed(4).replace(/\.?0+$/, '') : '';
      holds[name] = input.value;
      input.addEventListener('input', () => {
        holds[name] = input.value;
        values[field.name] = holds;
        onChange();
      });
      host.appendChild(h('div', { class: 'dialog-row' }, [h('span', { class: 'repeat-row-index', text: name }), input]));
    }
    for (const name of model.factors || []) {
      const levels = (model.levels || {})[name] || [];
      const select = h('select', {}, levels.map((level) => h('option', { value: level, text: level })));
      select.value = holds[name] !== undefined && levels.includes(holds[name]) ? holds[name] : levels[0] || '';
      holds[name] = select.value;
      select.addEventListener('change', () => {
        holds[name] = select.value;
        values[field.name] = holds;
        onChange();
      });
      host.appendChild(h('div', { class: 'dialog-row' }, [h('span', { class: 'repeat-row-index', text: name }), select]));
    }
    if (!remaining.length && !(model.factors || []).length) host.appendChild(h('p', { class: 'settings-hint', text: 'Nothing else to hold — both predictors are on the axes.' }));
    values[field.name] = holds;
  };
  fill();
  refreshers.push(fill);
  return host;
}

// ---------------------------------------------------------------------------
// the Calc menu's field types
// ---------------------------------------------------------------------------

// One of the stored matrices. The value sent is the matrix's ROWS, not its key: the backend has no
// matrix store, so a matrix operation carries its operands with it.
function matrixPick(field, values, onChange) {
  const options = pd.matrixOptions();
  const select = h('select', {}, [
    h('option', { value: '', text: options.length ? '— choose a matrix —' : '— no matrices stored yet —' }),
    ...options.map((m) => h('option', { value: m.key, text: m.label })),
  ]);
  const current = values[field.name];
  // The stored value is the key; buildRequest swaps it for the rows just before sending.
  select.value = options.some((m) => m.key === current) ? current : options.length === 1 ? options[0].key : '';
  values[field.name] = select.value;
  select.addEventListener('change', () => {
    values[field.name] = select.value;
    onChange();
  });
  return select;
}

// Two named text boxes in one field — the mesh generator's X and Y column names.
function textPair(field, values, onChange) {
  const labels = field.labels || ['First', 'Second'];
  const current = Array.isArray(values[field.name]) ? [...values[field.name]] : [...(field.default || ['', ''])];
  values[field.name] = current;
  const row = h('div', { class: 'dialog-row' });
  for (let i = 0; i < 2; i += 1) {
    row.appendChild(h('span', { class: 'repeat-row-index', text: labels[i] }));
    row.appendChild(
      textInput(current[i] || '', labels[i], (v) => {
        current[i] = v;
        values[field.name] = current;
        onChange();
      }),
    );
  }
  return row;
}

// Several stored matrices at once (Data > Copy > Matrices to Matrices). The value is a list of
// keys, not of rows: this one never leaves the browser.
function matricesPick(field, values, onChange) {
  const options = pd.matrixOptions();
  const list = h('div', { class: 'checkbox-list' });
  if (!options.length) list.appendChild(h('p', { class: 'muted', text: 'No matrices are stored yet. Build one with Calc > Matrices > Import.' }));
  values[field.name] = (values[field.name] || []).filter((key) => options.some((m) => m.key === key));
  for (const matrix of options) {
    const box = h('input', { type: 'checkbox' });
    box.checked = (values[field.name] || []).includes(matrix.key);
    box.addEventListener('change', () => {
      const current = values[field.name] || [];
      values[field.name] = box.checked ? [...current, matrix.key] : current.filter((k) => k !== matrix.key);
      onChange();
    });
    list.appendChild(h('label', { class: 'checkbox-item' }, [box, matrix.label]));
  }
  return list;
}

export const EXTRA_FIELDS = {
  'sort-by': sortBy,
  conditions,
  'map-rows': mapRows,
  'range-rows': rangeRows,
  worksheet: worksheetPick,
  worksheets: worksheetsPick,
  'other-column': otherColumn,
  pairs,
  'column-blocks': columnBlocks,
  names,
  constants: constantsPick,
  subset,
  'term-picker': termPicker,
  'model-factor': modelFactor,
  'model-covariate': modelCovariate,
  'model-holds': modelHolds,
  matrix: matrixPick,
  matrices: matricesPick,
  'text-pair': textPair,
};

// Field types whose value is an array, so defaults and validation treat them as lists.
export const ARRAY_FIELDS = new Set([
  'sort-by',
  'conditions',
  'map-rows',
  'range-rows',
  'worksheets',
  'pairs',
  'column-blocks',
  'names',
  'constants',
  'subset',
  'term-picker',
  'text-pair',
  'matrices',
]);
