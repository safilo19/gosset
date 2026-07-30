// Every item on the Data menu, declared once: its form fields, the backend operation it runs, and
// how its inputs turn into a request. The menu, the forms and the request bodies are all generated
// from this — the same config/behaviour split as basicStatsConfig.js and charts/graphConfig.js.
//
// Adding a Data operation = one entry here + one handler in backend/core/data_ops.py. Nothing else.
//
// Fields become keys of `options` under their own name, so a field called `columns` is the
// `columns` the Python handler reads. A field marked `advanced: true` goes into the collapsed
// "Options" section, which is what keeps a dialog with a dozen settings looking like one with four.

import { liveRows, visibleFields as visible } from './procedureDialog.js';
import { ARRAY_FIELDS } from './dialogFields.js';
import { menuConfig as conditionalFormattingMenu } from './conditionalFormat.js';

// ---------------------------------------------------------------------------
// field shorthands
// ---------------------------------------------------------------------------

const anyCol = (name, label, extra = {}) => ({ name, label, type: 'column', filter: 'any', required: true, ...extra });
const numCol = (name, label, extra = {}) => ({ name, label, type: 'column', filter: 'numeric', required: true, ...extra });
const anyCols = (name, label, extra = {}) => ({ name, label, type: 'columns', filter: 'any', required: true, ...extra });

const rowSpec = (name = 'rows', label = 'Rows', extra = {}) => ({
  name,
  label,
  type: 'text',
  mono: true,
  placeholder: '1:5 12 20:25',
  hint: 'Row numbers and a:b ranges, separated by spaces. Row numbers are the ones in the worksheet’s row headers.',
  ...extra,
});

const newName = (label = 'Name for the new worksheet') => ({
  name: 'new_name',
  label,
  type: 'text',
  advanced: true,
  hint: 'Leave blank to let the app name it after this worksheet.',
});

const conditionBuilder = (extra = {}) => ({
  name: 'conditions',
  label: 'Rows that match',
  type: 'conditions',
  max: 3,
  joinerFrom: 'joiner',
  default: [{ column: '', operator: '=', value: '', value2: '' }],
  ...extra,
});

const joiner = (extra = {}) => ({
  name: 'joiner',
  label: 'Combine conditions with',
  type: 'radio',
  options: [
    { value: 'and', label: 'AND — every condition must hold' },
    { value: 'or', label: 'OR — any condition is enough' },
  ],
  default: 'and',
  ...extra,
});

const includeExclude = (extra = {}) => ({
  name: 'action',
  label: 'Then',
  type: 'radio',
  options: [
    { value: 'include', label: 'Include the matching rows' },
    { value: 'exclude', label: 'Exclude the matching rows' },
  ],
  default: 'include',
  ...extra,
});

const stackDestination = () => ({
  name: 'destination',
  label: 'Store the result in',
  type: 'radio',
  options: [
    { value: 'new', label: 'A new worksheet' },
    { value: 'same', label: 'This worksheet (as extra columns)' },
  ],
  default: 'new',
});

const subscriptFields = (defaultName = 'Subscripts') => [
  { name: 'include_subscripts', label: 'Store subscripts', type: 'checkbox', default: true, group: 'Subscripts', hint: 'A column recording which source each stacked value came from.' },
  {
    name: 'subscript_name',
    label: 'Subscripts column name',
    type: 'text',
    default: defaultName,
    advanced: true,
    showIf: (v) => v.include_subscripts,
  },
  {
    name: 'index_subscripts',
    label: 'Number the subscripts',
    type: 'checkbox',
    default: false,
    advanced: true,
    showIf: (v) => v.include_subscripts,
  },
];

const recodeFields = (to, typeLabel) => [
  anyCols('columns', 'Columns to recode'),
  { name: 'to', label: 'New values are', type: 'text', default: to, omitFromForm: true },
  {
    name: 'mappings',
    label: `Old value → new ${typeLabel} value`,
    type: 'map-rows',
    max: 20,
    default: [{ from: '', to: '' }],
  },
  {
    name: 'ranges',
    label: 'Or recode a numeric range',
    type: 'range-rows',
    max: 10,
    default: [],
    hint: 'Ranges include both end points. Leave a bound empty for "anything below/above".',
  },
  {
    name: 'others',
    label: 'Values that match nothing',
    type: 'radio',
    options: [
      { value: 'keep', label: 'Keep as they are' },
      { value: 'missing', label: 'Become missing' },
      { value: 'value', label: 'Become a fixed value' },
    ],
    default: 'keep',
    advanced: true,
  },
  { name: 'other_value', label: 'That fixed value', type: 'text', advanced: true, showIf: (v) => v.others === 'value' },
  {
    name: 'destination',
    label: 'Write the result to',
    type: 'radio',
    options: [
      { value: 'same', label: 'The same columns (overwrite)' },
      { value: 'new', label: 'New columns' },
    ],
    default: 'new',
  },
  { name: 'suffix', label: 'Suffix for the new columns', type: 'text', default: '_recoded', advanced: true, showIf: (v) => v.destination === 'new' },
];

// ---------------------------------------------------------------------------
// the procedures
// ---------------------------------------------------------------------------

export const PROCEDURES = [
  // ----- Step 3: worksheet-level -----
  {
    id: 'subset',
    icon: 'subset',
    description: 'Copies the rows matching a condition, or a named list of rows, into a new worksheet. The original is left whole.',
    needs: 'A condition, a row list, or rows selected in the grid.',
    operation: 'subset',
    label: 'Subset Worksheet…',
    title: 'Subset Worksheet',
    submitLabel: 'Create subset worksheet',
    newName: (values, sheet) => `Subset of ${sheet}`,
    fields: [
      {
        name: 'by',
        label: 'Choose rows',
        type: 'radio',
        options: [
          { value: 'condition', label: 'That match a condition' },
          { value: 'rows', label: 'By row number' },
          { value: 'selection', label: 'That are selected in the worksheet', hint: 'Uses the range selected in the grid right now — select it before opening this dialog.' },
        ],
        default: 'condition',
      },
      conditionBuilder({ showIf: (v) => v.by === 'condition', required: true }),
      joiner({ showIf: (v) => v.by === 'condition' }),
      rowSpec('rows', 'Rows', { showIf: (v) => v.by === 'rows', required: true }),
      includeExclude(),
      newName(),
    ],
    note: 'The current worksheet is left exactly as it is — the subset opens as a new worksheet with its own tab.',
  },
  {
    id: 'split',
    icon: 'split-worksheet',
    description: 'Breaks the worksheet into one new worksheet per level of a grouping column — one per machine, one per region.',
    needs: 'A column with a manageable number of distinct values.',
    operation: 'split',
    label: 'Split Worksheet…',
    title: 'Split Worksheet',
    submitLabel: 'Split into worksheets',
    fields: [
      anyCol('by_column', 'By variable — one worksheet per value'),
      { name: 'drop_by_column', label: 'Omit the By column', type: 'checkbox', default: false, hint: 'Each new worksheet holds one value of it anyway.' },
      { name: 'include_missing', label: 'Include missing', type: 'checkbox', default: false, advanced: true, hint: 'Rows with no By value get a worksheet of their own.' },
      { name: 'max_worksheets', label: 'Maximum worksheets to create', type: 'number', min: 1, max: 200, step: 1, default: 30, advanced: true },
      { name: 'base_name', label: 'Name each worksheet', type: 'text', advanced: true, hint: 'The By value is appended. Leave blank to use this worksheet’s name.' },
    ],
  },
  { separator: true },
  {
    id: 'merge_match',
    icon: 'merge-match',
    description: 'Joins another worksheet onto this one by matching values in one or more key columns, the way a database join does. Rows finding no match keep missing values.',
    needs: 'Two open worksheets sharing a key column.',
    operation: 'merge_match',
    label: 'Match Values…',
    title: 'Merge Worksheets — Match Values',
    submitLabel: 'Merge worksheets',
    group: 'Merge Worksheets',
    newName: (values, sheet) => `Merge of ${sheet}`,
    fields: [
      { name: 'worksheet', label: 'Merge this worksheet with', type: 'worksheet', required: true },
      { name: 'keys', label: 'Key columns', type: 'pairs', rightFrom: 'worksheet', max: 3, required: true, default: [{ left: '', right: '' }] },
      {
        name: 'how',
        label: 'Keep',
        type: 'radio',
        options: [
          { value: 'inner', label: 'Only rows that match in both (inner join)' },
          { value: 'left', label: 'Every row of this worksheet (left join)' },
          { value: 'outer', label: 'Every row of both (outer join)' },
        ],
        default: 'inner',
      },
      { name: 'drop_duplicate_keys', label: 'Drop duplicate keys', type: 'checkbox', default: true, advanced: true, hint: 'The other worksheet’s copy of the key columns is left out of the result.' },
      newName(),
    ],
    note: 'Keys are matched on their text form, so a key stored as 3 in one worksheet still meets a key stored as "3" in the other.',
  },
  {
    id: 'merge_side_by_side',
    icon: 'merge-side-by-side',
    description: 'Sets other worksheets alongside this one column by column, pairing row 1 with row 1. Nothing is matched, so use Match Values when the row order does not already correspond.',
    needs: 'Two or more open worksheets.',
    operation: 'merge_side_by_side',
    label: 'Side-by-Side…',
    title: 'Merge Worksheets — Side by Side',
    submitLabel: 'Place side by side',
    group: 'Merge Worksheets',
    newName: (values, sheet) => `${sheet} + others`,
    fields: [
      { name: 'worksheets', label: 'Worksheets to place beside this one', type: 'worksheets', required: true },
      newName(),
    ],
    note: 'Columns are pasted next to each other by row position — row 1 meets row 1. A repeated column name gets a numeric suffix.',
  },
  {
    id: 'stack_worksheets',
    icon: 'stack-worksheets',
    description: 'Appends other worksheets underneath this one, lining columns up by name. The way to combine batches that share a layout.',
    needs: 'Two or more open worksheets with columns in common.',
    operation: 'stack_worksheets',
    label: 'Stack Worksheets…',
    title: 'Stack Worksheets',
    submitLabel: 'Stack worksheets',
    newName: () => 'Stacked worksheets',
    fields: [
      { name: 'worksheets', label: 'Worksheets to stack', type: 'worksheets', includeActive: true, required: true, minSelect: 2 },
      { name: 'include_source', label: 'Add a source column', type: 'checkbox', default: true, hint: 'Records which worksheet each row came from.' },
      { name: 'source_name', label: 'Source column name', type: 'text', default: 'Source', advanced: true, showIf: (v) => v.include_source },
      newName(),
    ],
    note: 'Columns are aligned by name; a column missing from one worksheet is left blank in its rows.',
  },
  { separator: true },

  // ----- Step 1: rows, order, basic column ops -----
  {
    id: 'sort',
    icon: 'sort',
    description: 'Reorders rows by one or more columns, each ascending or descending. Whole rows travel together, so values stay on their own record.',
    needs: 'At least one column to sort by.',
    operation: 'sort',
    label: 'Sort…',
    title: 'Sort',
    submitLabel: 'Sort worksheet',
    undoable: true,
    newName: (values, sheet) => `Sorted ${sheet}`,
    fields: [
      { name: 'by', label: 'Sort by', type: 'sort-by', max: 4, required: true, default: [{ column: '', direction: 'ascending' }] },
      {
        name: 'destination',
        label: 'Store the sorted data in',
        type: 'radio',
        options: [
          { value: 'in_place', label: 'This worksheet (sort in place)' },
          { value: 'new', label: 'A new worksheet' },
        ],
        default: 'in_place',
      },
      newName(),
    ],
    note: 'Every column moves together, so a row stays a row. Equal values keep the order they were already in, which is what lets a second sort refine the first.',
  },
  {
    id: 'rank',
    icon: 'rank',
    description: 'Writes each value\'s position within its column into a new column, 1 for the smallest, with ties sharing the average position. Rank labels values where Sort moves rows.',
    needs: 'One numeric column.',
    operation: 'rank',
    label: 'Rank…',
    title: 'Rank',
    submitLabel: 'Store ranks',
    undoable: true,
    fields: [
      numCol('column', 'Rank the values in'),
      { name: 'store_in', label: 'Store the ranks in', type: 'text', hint: 'A new column, or the name of an existing one to overwrite.' },
      {
        name: 'direction',
        label: 'Rank',
        type: 'radio',
        options: [
          { value: 'ascending', label: 'Smallest value gets rank 1' },
          { value: 'descending', label: 'Largest value gets rank 1' },
        ],
        default: 'ascending',
        advanced: true,
      },
    ],
    note: 'Tied values share the average of the ranks they span — the same rule Minitab uses.',
  },
  {
    id: 'delete_rows',
    icon: 'delete-rows',
    description: 'Removes rows entirely and closes the gap left behind.',
    needs: 'A row list, a condition, or rows selected in the grid.',
    operation: 'delete_rows',
    label: 'Delete Rows…',
    title: 'Delete Rows',
    submitLabel: 'Delete rows',
    undoable: true,
    danger: true,
    fields: [
      rowSpec('rows', 'Rows to delete', { required: true }),
      {
        name: 'scope',
        label: 'From',
        type: 'radio',
        options: [
          { value: 'all', label: 'All columns — the rows are removed entirely' },
          { value: 'some', label: 'Chosen columns — those cells go and the ones below shift up' },
        ],
        default: 'all',
      },
      anyCols('columns', 'Columns', { showIf: (v) => v.scope === 'some', required: true }),
    ],
  },
  {
    id: 'erase_variables',
    icon: 'erase-variables',
    description: 'Deletes whole columns and their contents from the worksheet.',
    needs: 'One or more columns.',
    operation: 'erase_variables',
    label: 'Erase Variables…',
    title: 'Erase Variables',
    submitLabel: 'Erase contents',
    undoable: true,
    danger: true,
    fields: [anyCols('columns', 'Columns to erase')],
    note: 'The columns stay in the worksheet — only their contents are cleared. Use Edit > Delete to remove the columns themselves.',
  },
  { separator: true },

  // ----- Step 4: copy -----
  {
    id: 'copy_columns',
    icon: 'copy-columns',
    description: 'Duplicates columns, into this worksheet or another, optionally only the rows meeting a condition.',
    needs: 'One or more columns.',
    operation: 'copy_columns',
    label: 'Columns to Columns…',
    title: 'Copy Columns to Columns',
    submitLabel: 'Copy columns',
    group: 'Copy',
    undoable: true,
    newName: (values, sheet) => `Columns from ${sheet}`,
    fields: [
      anyCols('columns', 'Columns to copy'),
      {
        name: 'destination',
        label: 'Copy them to',
        type: 'radio',
        options: [
          { value: 'same', label: 'New columns in this worksheet' },
          { value: 'other', label: 'Another open worksheet' },
          { value: 'new', label: 'A new worksheet' },
        ],
        default: 'same',
      },
      { name: 'worksheet', label: 'Which worksheet', type: 'worksheet', required: true, showIf: (v) => v.destination === 'other' },
      { name: 'new_names', label: 'Store in', type: 'names', from: 'columns', advanced: true, placeholder: 'new column name (optional)' },
      { name: 'use_condition', label: 'Use a condition', type: 'checkbox', default: false, hint: 'Copy only the rows that match.' },
      conditionBuilder({ showIf: (v) => v.use_condition, required: true }),
      joiner({ showIf: (v) => v.use_condition }),
      includeExclude({ showIf: (v) => v.use_condition }),
      newName(),
    ],
  },
  {
    id: 'copy_worksheet',
    icon: 'copy-worksheet',
    description: 'Duplicates the whole worksheet into a new tab, optionally narrowing it to some columns or to rows meeting a condition.',
    operation: 'copy_worksheet',
    label: 'Worksheet to Worksheet…',
    title: 'Copy Worksheet to Worksheet',
    submitLabel: 'Duplicate worksheet',
    group: 'Copy',
    newName: (values, sheet) => `Copy of ${sheet}`,
    fields: [
      { name: 'columns', label: 'Columns to include', type: 'columns', filter: 'any', required: false, hint: 'Leave everything unticked to copy the whole worksheet.' },
      { name: 'use_condition', label: 'Use a condition', type: 'checkbox', default: false, hint: 'Copy only the rows that match.' },
      conditionBuilder({ showIf: (v) => v.use_condition, required: true }),
      joiner({ showIf: (v) => v.use_condition }),
      includeExclude({ showIf: (v) => v.use_condition }),
      newName(),
    ],
  },
  {
    id: 'column_to_constants',
    icon: 'column-to-constants',
    description: 'Stores each value of a column as a numbered constant K1, K2, … so the Calculator and the dialogs can refer to them.',
    needs: 'One column, short enough to be worth holding as constants.',
    label: 'Column to Constants…',
    title: 'Copy Column to Constants',
    submitLabel: 'Store as constants',
    group: 'Copy',
    local: 'columnToConstants',
    fields: [
      anyCol('column', 'Column'),
      rowSpec('rows', 'Rows to copy', { required: false, hint: 'Leave blank to copy every non-empty value. Row numbers and a:b ranges.' }),
      { name: 'name_prefix', label: 'Name the constants', type: 'text', advanced: true, hint: 'Each constant is named "<prefix> 1", "<prefix> 2", … Leave blank for unnamed constants.' },
    ],
    note: 'Values become K1, K2, … in the constants store (Data > Constants). Constants are saved with the project.',
  },
  {
    id: 'constants_to_column',
    icon: 'constants-to-column',
    description: 'Writes stored constants into a worksheet column, one per row.',
    needs: 'At least one stored constant.',
    label: 'Constants to Column…',
    title: 'Copy Constants to Column',
    submitLabel: 'Write into the worksheet',
    group: 'Copy',
    local: 'constantsToColumn',
    undoable: true,
    fields: [
      { name: 'source_constants', label: 'Constants to copy', type: 'constants', required: true },
      { name: 'store_in', label: 'Store them in the column', type: 'text', default: 'Constants', required: true },
      { name: 'overwrite', label: 'Overwrite', type: 'checkbox', default: false, advanced: true, hint: 'Replace the column if that name is already in use, instead of adding another.' },
    ],
  },
  {
    id: 'constants_to_constants',
    icon: 'constants-to-constants',
    description: 'Duplicates stored constants into new K slots, keeping their values and names.',
    needs: 'At least one stored constant.',
    label: 'Constants to Constants…',
    title: 'Copy Constants to Constants',
    submitLabel: 'Copy constants',
    group: 'Copy',
    local: 'constantsToConstants',
    fields: [{ name: 'source_constants', label: 'Constants to copy', type: 'constants', required: true }],
    note: 'Each chosen constant is duplicated into a new K, keeping its value and name.',
  },
  // The matrix store arrived with the Calc menu, so these three are live now. They open the very
  // same dialogs as Calc > Matrices — Minitab reaches one operation from two places, and so does
  // this: one implementation, two menu entries.
  {
    id: 'matrices_to_matrices',
    icon: 'matrices-to-matrices',
    description: 'Duplicates stored matrices into new M slots, keeping their values and names.',
    needs: 'At least one stored matrix.',
    label: 'Matrices to Matrices…',
    title: 'Copy Matrices to Matrices',
    submitLabel: 'Copy matrices',
    group: 'Copy',
    local: 'matricesToMatrices',
    fields: [
      { name: 'source_matrices', label: 'Matrices to copy', type: 'matrices', required: true },
    ],
    note: 'Each chosen matrix is duplicated into a new M, keeping its values and name.',
  },
  {
    label: 'Matrix to Columns…',
    group: 'Copy',
    calc: 'matrix_to_columns',
    icon: 'matrix-to-columns',
    description: 'Writes a stored matrix out into worksheet columns, one column per matrix column.',
    needs: 'At least one stored matrix.',
  },
  {
    label: 'Columns to Matrix…',
    group: 'Copy',
    calc: 'matrix_from_columns',
    icon: 'columns-to-matrix',
    description: 'Reads worksheet columns into a stored matrix M1, M2, … so the matrix operations can work on them.',
    needs: 'Two or more numeric columns of equal length.',
  },
  { separator: true },

  // ----- Step 2: reshape -----
  {
    id: 'stack_columns',
    icon: 'stack-columns',
    description: 'Pours several columns into one tall column, with a second column recording which one each value came from. This is how wide data becomes the long layout most Stat dialogs expect.',
    needs: 'Two or more columns holding the same kind of measurement.',
    operation: 'stack_columns',
    label: 'Columns…',
    title: 'Stack Columns',
    submitLabel: 'Stack columns',
    group: 'Stack',
    newName: () => 'Stacked columns',
    fields: [
      anyCols('columns', 'Columns to stack', { minSelect: 2 }),
      { name: 'value_name', label: 'Name for the stacked column', type: 'text', default: 'Stacked' },
      ...subscriptFields('Subscripts'),
      { name: 'omit_missing', label: 'Omit empty cells', type: 'checkbox', default: false, advanced: true },
      stackDestination(),
      newName(),
    ],
  },
  {
    id: 'stack_blocks',
    icon: 'stack-blocks',
    description: 'Stacks groups of columns as units, so that several measurements per record stay side by side while the blocks are appended.',
    needs: 'Two or more blocks of columns with matching shapes.',
    operation: 'stack_blocks',
    label: 'Blocks of Columns…',
    title: 'Stack Blocks of Columns',
    submitLabel: 'Stack blocks',
    group: 'Stack',
    newName: () => 'Stacked blocks',
    fields: [
      { name: 'blocks', label: 'Blocks — each keeps its columns side by side', type: 'column-blocks', max: 6, required: true, minSelect: 2, default: [[], []] },
      ...subscriptFields('Subscripts'),
      stackDestination(),
      newName(),
    ],
    note: 'Every block must hold the same number of columns. The stacked columns take their names from block 1.',
  },
  {
    id: 'stack_rows',
    icon: 'stack-rows',
    description: 'Pours the values of several columns into one column, reading across each row before moving to the next. Stack Columns instead reads down each column in turn.',
    needs: 'Two or more columns.',
    operation: 'stack_rows',
    label: 'Rows…',
    title: 'Stack Rows',
    submitLabel: 'Stack rows',
    group: 'Stack',
    newName: () => 'Stacked rows',
    fields: [
      anyCols('columns', 'Columns whose rows are stacked'),
      rowSpec('rows', 'Rows', { required: false, hint: 'Leave blank for every row. Row numbers and a:b ranges.' }),
      { name: 'value_name', label: 'Name for the stacked column', type: 'text', default: 'Stacked' },
      ...subscriptFields('Row'),
      { name: 'omit_missing', label: 'Omit empty cells', type: 'checkbox', default: false, advanced: true },
      stackDestination(),
      newName(),
    ],
  },
  {
    id: 'unstack_columns',
    icon: 'unstack-columns',
    description: 'Splits one column into several, one per level of a grouping column. The reverse of Stack Columns, turning long data back into wide.',
    needs: 'A value column and a grouping column.',
    operation: 'unstack_columns',
    label: 'Unstack Columns…',
    title: 'Unstack Columns',
    submitLabel: 'Unstack columns',
    newName: () => 'Unstacked',
    fields: [
      anyCols('columns', 'Columns to unstack'),
      anyCol('subscript_column', 'Using subscripts in'),
      { name: 'sort_groups', label: 'Sort the new columns', type: 'checkbox', default: true, advanced: true, hint: 'By group value, rather than by first appearance.' },
      { name: 'include_missing', label: 'Include missing', type: 'checkbox', default: false, advanced: true, hint: 'Values with no subscript get a column of their own.' },
      stackDestination(),
      newName(),
    ],
    note: 'The new columns are named after the values of the subscripts column — the exact inverse of Stack Columns.',
  },
  {
    id: 'transpose',
    icon: 'transpose',
    description: 'Rotates the block, turning each column into a row and each row into a column.',
    needs: 'The columns to rotate. A text column can supply the new column names.',
    operation: 'transpose',
    label: 'Transpose Columns…',
    title: 'Transpose Columns',
    submitLabel: 'Transpose into a new worksheet',
    newName: (values, sheet) => `Transposed ${sheet}`,
    fields: [
      anyCols('columns', 'Columns to transpose'),
      { name: 'name_column', label: 'Use the values in this column as the new column names', type: 'column', filter: 'any', required: false },
      newName(),
    ],
    note: 'Each chosen column becomes a row of the new worksheet, with its original name in a leading "Variable" column.',
  },
  { separator: true },

  // ----- Step 5: values & types -----
  {
    id: 'recode_numeric',
    icon: 'recode-numeric',
    description: 'Replaces numeric values with other numbers, one value or one range at a time — grouping 1–5 into 1 and 6–10 into 2, for instance.',
    needs: 'One or more numeric columns.',
    operation: 'recode',
    label: 'To Numeric…',
    title: 'Recode to Numeric',
    submitLabel: 'Recode values',
    group: 'Recode',
    undoable: true,
    fields: recodeFields('numeric', 'numeric'),
  },
  {
    id: 'recode_text',
    icon: 'recode-text',
    description: 'Replaces text values with other text, so that \'N\', \'no\' and \'No\' can all become one label.',
    needs: 'One or more text columns.',
    operation: 'recode',
    label: 'To Text…',
    title: 'Recode to Text',
    submitLabel: 'Recode values',
    group: 'Recode',
    undoable: true,
    fields: recodeFields('text', 'text'),
  },
  {
    id: 'recode_datetime',
    icon: 'recode-datetime',
    description: 'Replaces dates or times with other date/time values, one value or one range at a time.',
    needs: 'One or more date/time columns.',
    operation: 'recode',
    label: 'To Date/Time…',
    title: 'Recode to Date/Time',
    submitLabel: 'Recode values',
    group: 'Recode',
    undoable: true,
    fields: recodeFields('datetime', 'date/time'),
  },
  {
    id: 'recode_conversion_table',
    icon: 'recode-conversion-table',
    description: 'Recodes from a two-column lookup table held in another worksheet, so a long mapping stays data rather than something typed into a dialog.',
    needs: 'A second worksheet with the old and new values in two columns.',
    operation: 'recode_conversion_table',
    label: 'Use Conversion Table…',
    title: 'Recode Using a Conversion Table',
    submitLabel: 'Apply conversion table',
    group: 'Recode',
    undoable: true,
    fields: [
      anyCols('columns', 'Columns to recode'),
      { name: 'table_worksheet', label: 'Conversion table is on', type: 'worksheet', includeActive: true, required: true },
      { name: 'old_column', label: 'Old values in', type: 'other-column', from: 'table_worksheet', required: true },
      { name: 'new_column', label: 'New values in', type: 'other-column', from: 'table_worksheet', required: true },
      {
        name: 'to',
        label: 'New values are',
        type: 'select',
        options: [
          { value: 'text', label: 'Text' },
          { value: 'numeric', label: 'Numeric' },
          { value: 'datetime', label: 'Date/Time' },
        ],
        default: 'text',
      },
      {
        name: 'others',
        label: 'Values not in the table',
        type: 'radio',
        options: [
          { value: 'keep', label: 'Keep as they are' },
          { value: 'missing', label: 'Become missing' },
        ],
        default: 'keep',
        advanced: true,
      },
      {
        name: 'destination',
        label: 'Write the result to',
        type: 'radio',
        options: [
          { value: 'same', label: 'The same columns (overwrite)' },
          { value: 'new', label: 'New columns' },
        ],
        default: 'new',
      },
      { name: 'suffix', label: 'Suffix for the new columns', type: 'text', default: '_recoded', advanced: true, showIf: (v) => v.destination === 'new' },
    ],
  },
  {
    id: 'change_type',
    icon: 'change-type',
    description: 'Converts a column between numeric, text and date/time. Values that cannot be converted become missing, and the dialog reports how many that would be before anything changes.',
    needs: 'One or more columns.',
    operation: 'change_type',
    label: 'Change Data Type…',
    title: 'Change Data Type',
    submitLabel: 'Convert columns',
    undoable: true,
    previewLabel: 'Preview conversion',
    fields: [
      anyCols('columns', 'Columns to convert'),
      {
        name: 'to',
        label: 'Convert to',
        type: 'radio',
        options: [
          { value: 'numeric', label: 'Numeric' },
          { value: 'text', label: 'Text' },
          { value: 'datetime', label: 'Date/Time' },
        ],
        default: 'numeric',
      },
      {
        name: 'date_format',
        label: 'Date format (optional)',
        type: 'text',
        mono: true,
        placeholder: '%d/%m/%Y',
        advanced: true,
        showIf: (v) => v.to === 'datetime',
        hint: 'Leave blank to let the parser work it out. Give a format when day and month could be read either way.',
      },
    ],
    note: 'Preview first: it counts how many values would parse and how many would become missing, and shows examples of the ones that fail.',
  },
  {
    id: 'date_extract_numeric',
    icon: 'date-extract-numeric',
    description: 'Pulls one part of a date out as a number — the year, the month as 1–12, the weekday as 1–7 — so it can be sorted on or used as a covariate.',
    needs: 'One date/time column.',
    operation: 'date_extract',
    label: 'Extract to Numeric…',
    title: 'Extract Date/Time to Numeric',
    submitLabel: 'Extract components',
    group: 'Date/Time',
    undoable: true,
    fields: [
      anyCol('column', 'Date/time column'),
      {
        name: 'components',
        label: 'Components to extract',
        type: 'checkbox-grid',
        required: true,
        items: [
          { key: 'year', label: 'Year' },
          { key: 'quarter', label: 'Quarter' },
          { key: 'month', label: 'Month' },
          { key: 'month name', label: 'Month name' },
          { key: 'week of year', label: 'Week of year' },
          { key: 'day of year', label: 'Day of year' },
          { key: 'day of month', label: 'Day of month' },
          { key: 'weekday', label: 'Weekday (1 = Monday)' },
          { key: 'weekday name', label: 'Weekday name' },
          { key: 'hour', label: 'Hour' },
          { key: 'minute', label: 'Minute' },
          { key: 'second', label: 'Second' },
        ],
        default: ['year', 'month'],
      },
      { name: 'as', label: 'Store as', type: 'text', default: 'numeric', omitFromForm: true },
      { name: 'date_format', label: 'Date format (optional)', type: 'text', mono: true, placeholder: '%d/%m/%Y', advanced: true },
    ],
    note: 'A name component (month name, weekday name) is always stored as text — there is no number to store.',
  },
  {
    id: 'date_extract_text',
    icon: 'date-extract-text',
    description: 'Pulls one part of a date out as text — \'March\', \'Tuesday\' — so it can be a grouping factor with readable labels.',
    needs: 'One date/time column.',
    operation: 'date_extract',
    label: 'Extract to Text…',
    title: 'Extract Date/Time to Text',
    submitLabel: 'Extract components',
    group: 'Date/Time',
    undoable: true,
    fields: [
      anyCol('column', 'Date/time column'),
      {
        name: 'components',
        label: 'Components to extract',
        type: 'checkbox-grid',
        required: true,
        items: [
          { key: 'year', label: 'Year' },
          { key: 'quarter', label: 'Quarter' },
          { key: 'month', label: 'Month' },
          { key: 'month name', label: 'Month name' },
          { key: 'week of year', label: 'Week of year' },
          { key: 'day of year', label: 'Day of year' },
          { key: 'day of month', label: 'Day of month' },
          { key: 'weekday', label: 'Weekday (1 = Monday)' },
          { key: 'weekday name', label: 'Weekday name' },
          { key: 'hour', label: 'Hour' },
          { key: 'minute', label: 'Minute' },
          { key: 'second', label: 'Second' },
        ],
        default: ['month name'],
      },
      { name: 'as', label: 'Store as', type: 'text', default: 'text', omitFromForm: true },
      { name: 'date_format', label: 'Date format (optional)', type: 'text', mono: true, placeholder: '%d/%m/%Y', advanced: true },
    ],
  },
  {
    id: 'date_round',
    icon: 'date-round',
    description: 'Snaps each date/time back to the start of its hour, day, month or year. This is how daily records get collapsed into monthly ones.',
    needs: 'One date/time column.',
    operation: 'date_round',
    label: 'Round Date/Time…',
    title: 'Round Date/Time',
    submitLabel: 'Round dates',
    group: 'Date/Time',
    undoable: true,
    fields: [
      anyCol('column', 'Date/time column'),
      {
        name: 'unit',
        label: 'Round to the nearest',
        type: 'select',
        options: [
          { value: 'year', label: 'Year' },
          { value: 'quarter', label: 'Quarter' },
          { value: 'month', label: 'Month' },
          { value: 'week', label: 'Week (starting Monday)' },
          { value: 'day', label: 'Day' },
          { value: 'hour', label: 'Hour' },
          { value: 'minute', label: 'Minute' },
          { value: 'second', label: 'Second' },
        ],
        default: 'day',
      },
      {
        name: 'how',
        label: 'Direction',
        type: 'radio',
        options: [
          { value: 'floor', label: 'Down — the start of the period' },
          { value: 'ceiling', label: 'Up — the start of the next period' },
          { value: 'round', label: 'To whichever is nearer' },
        ],
        default: 'floor',
      },
      {
        name: 'destination',
        label: 'Write the result to',
        type: 'radio',
        options: [
          { value: 'new', label: 'A new column' },
          { value: 'same', label: 'The same column (overwrite)' },
        ],
        default: 'new',
      },
      { name: 'date_format', label: 'Date format (optional)', type: 'text', mono: true, placeholder: '%d/%m/%Y', advanced: true },
    ],
  },
  {
    id: 'concatenate',
    icon: 'concatenate',
    description: 'Joins the values of several columns into one text column, separated by a string of choice.',
    needs: 'Two or more columns.',
    operation: 'concatenate',
    label: 'Concatenate…',
    title: 'Concatenate',
    submitLabel: 'Combine columns',
    undoable: true,
    fields: [
      anyCols('columns', 'Columns to combine', { minSelect: 2 }),
      { name: 'new_column', label: 'Store the result in', type: 'text', default: 'Concatenated', required: true },
      { name: 'separator', label: 'Separator', type: 'text', default: ' ', hint: 'Put between each pair of values. Leave blank to join them with nothing in between.' },
      { name: 'skip_missing', label: 'Skip empty cells', type: 'checkbox', default: true, advanced: true, hint: 'Otherwise an empty cell leaves an extra separator in the result.' },
    ],
  },
  { separator: true },

  // ----- reporting -----
  {
    id: 'display_data',
    icon: 'display-data',
    description: 'Prints the chosen columns into the Session Window as text, so a slice of the data can be read next to the results it produced.',
    needs: 'One or more columns.',
    operation: 'display_data',
    label: 'Display Data…',
    title: 'Display Data',
    submitLabel: 'Print to the Session Window',
    fields: [
      { name: 'columns', label: 'Columns to display', type: 'columns', filter: 'any', required: false, hint: 'Leave everything unticked to display every column.' },
      rowSpec('rows', 'Rows', { required: false, hint: 'Leave blank for every row. Row numbers and a:b ranges.' }),
      { name: 'max_rows', label: 'Maximum rows to print', type: 'number', min: 1, max: 5000, step: 1, default: 500, advanced: true },
    ],
    note: 'The values are printed as text in the Session Window, exactly as Minitab’s Display Data does.',
  },
  {
    id: 'worksheet_info',
    icon: 'worksheet-info',
    description: 'Lists every column with its data type, how many values it holds and how many are missing. The first place to look when a dialog will not accept a column.',
    operation: 'worksheet_info',
    label: 'Worksheet Information',
    title: 'Worksheet Information',
    submitLabel: 'Show worksheet information',
    immediate: true,
    fields: [],
  },
];

export const PROCEDURE_BY_ID = Object.fromEntries(PROCEDURES.filter((p) => p.id).map((p) => [p.id, p]));

// ---------------------------------------------------------------------------
// the Data dropdown, mirroring Minitab's own structure and order
// ---------------------------------------------------------------------------

const itemsInGroup = (group) =>
  PROCEDURES.filter((p) => p.group === group).map((p) => {
    // An entry can hand off to the Calc menu's implementation instead of owning one here.
    const help = { icon: p.icon, description: p.description, needs: p.needs };
    if (p.calc) return { label: p.label, calc: p.calc, ...help };
    return p.id ? { label: p.label, data: p.id, ...help } : { label: p.label, disabled: true, title: p.title, ...help };
  });

const ungrouped = (id) => {
  const config = PROCEDURE_BY_ID[id];
  return config ? { label: config.label, data: id, icon: config.icon, description: config.description, needs: config.needs } : null;
};

export function dataMenuConfig() {
  return [
    ungrouped('subset'),
    ungrouped('split'),
    { label: 'Merge Worksheets', items: itemsInGroup('Merge Worksheets') },
    ungrouped('stack_worksheets'),
    { separator: true },
    ungrouped('sort'),
    ungrouped('rank'),
    ungrouped('delete_rows'),
    ungrouped('erase_variables'),
    { separator: true },
    { label: 'Copy', items: itemsInGroup('Copy') },
    { separator: true },
    { label: 'Stack', items: itemsInGroup('Stack') },
    ungrouped('unstack_columns'),
    ungrouped('transpose'),
    { separator: true },
    { label: 'Recode', items: itemsInGroup('Recode') },
    ungrouped('change_type'),
    { label: 'Date/Time', items: itemsInGroup('Date/Time') },
    ungrouped('concatenate'),
    { separator: true },
    { label: 'Conditional Formatting', items: conditionalFormattingMenu() },
    { separator: true },
    ungrouped('display_data'),
    ungrouped('worksheet_info'),
    {
      label: 'Constants…',
      action: 'constants',
      icon: 'constants',
      description: 'Opens the window listing the stored constants K1, K2, … with their values and names, where they can be edited or cleared.',
    },
    { separator: true },
    {
      label: 'Import file…',
      action: 'import',
      icon: 'import-file',
      description: 'Loads a CSV, Excel, JSON file or Google Sheets link into the active worksheet, replacing what is there.',
    },
    {
      label: 'Dataset summary',
      action: 'summary',
      icon: 'dataset-summary',
      description: 'Shows the worksheet\u2019s columns with their data types alongside its first few rows \u2014 a quick look at shape rather than a full analysis.',
    },
    {
      label: 'Reload worksheet',
      action: 'reload-worksheet',
      icon: 'reload-worksheet',
      description: 'Redraws the grid from the server\u2019s copy of the data. Use it if the display and the results ever look out of step.',
    },
  ].filter(Boolean);
}

// ---------------------------------------------------------------------------
// values -> request
// ---------------------------------------------------------------------------

// Fields never shown in the form but still sent (the fixed `to`/`as` a menu item is defined by).
export function formFields(config) {
  return config.fields.filter((f) => !f.omitFromForm);
}

export function buildRequest(config, values, { worksheetName = 'this worksheet', extra = {} } = {}) {
  const options = {};
  for (const field of visible(config, values)) {
    let value = values[field.name];
    if (ARRAY_FIELDS.has(field.type)) {
      value = liveRows(field, value);
      if (!value.length) continue;
    } else if (field.type === 'checkbox') {
      options[field.name] = !!value; // false is meaningful — 'do not store subscripts'
      continue;
    } else if (field.type === 'number') {
      if (value === '' || value === null || value === undefined) continue;
      value = Number(value);
    }
    if (value === '' || value === null || value === undefined) continue;
    options[field.name] = value;
  }
  // Fields that never reach the form still carry the menu item's fixed choice.
  for (const field of config.fields) {
    if (field.omitFromForm && field.default !== undefined && options[field.name] === undefined) options[field.name] = field.default;
  }
  if (config.newName && !options.new_name) options.new_name = config.newName(values, worksheetName);
  if (config.id === 'split' && !options.base_name) options.base_name = worksheetName;
  return { operation: config.operation, options: { ...options, ...extra } };
}

/** One-line description for the window title and the Session Window entry. */
export function describe(config, values) {
  const parts = [];
  for (const field of visible(config, values)) {
    if (field.type === 'column' && values[field.name]) parts.push(values[field.name]);
    else if (field.type === 'columns' && (values[field.name] || []).length) parts.push(values[field.name].join(', '));
  }
  const name = config.title || config.label.replace(/…$/, '');
  return parts.length ? `${name} (${parts.join('; ')})` : name;
}

export { visibleFields, defaultValues, validate } from './procedureDialog.js';
