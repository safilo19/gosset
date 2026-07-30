// Plain regex/keyword command parser — no external API calls.
//
// This module is deliberately STATELESS: it never holds a dataset, a dataset_id or a schema of
// its own. Every entry point takes the dataset the caller considers active right now, so a
// message typed after a new file loads is parsed against the new file's columns. Anything the
// assistant "knows" about the data therefore comes from the caller's shared active-dataset state
// (the same state the Dashboard and the Worksheet read), resolved per message.
//
// Column names in free text are matched against the ACTIVE schema: case- and
// space/underscore-insensitive, accepting either the descriptive name ("yield_kg") or the
// worksheet's system label ("C3"), with a unique-substring fallback. A name that matches nothing —
// or matches ambiguously — is reported back with the real column list rather than guessed at, so
// a question is never silently answered against the wrong column.

const NUMERIC_DTYPE_RE = /int|float|double|decimal|number/i;
const DATE_KEYWORDS = ['date', 'month', 'year', 'time', 'day', 'period', 'week', 'quarter'];
const SYSTEM_NAME_RE = /^c(\d+)$/i;
// Words that carry no identity when naming a dataset out loud ("switch to the sales file").
const DATASET_FILLER = new Set(['the', 'a', 'my', 'file', 'files', 'data', 'dataset', 'datasets', 'worksheet', 'sheet', 'csv', 'xlsx', 'one']);

// Help shown before any worksheet exists — every other help string is built from real columns.
export const GENERIC_HELP = `I don't have a worksheet yet. Open a file from the File menu, or type data into the worksheet, then ask me things like "describe the data" or "correlation between <column> and <column>".`;

function normalize(s) {
  return String(s)
    .trim()
    .toLowerCase()
    .replace(/[_\s]+/g, ' ');
}

// ---------------------------------------------------------------------------
// reading the active schema
// ---------------------------------------------------------------------------

export function columnNames(dataset) {
  if (!dataset || !dataset.columns) return [];
  return dataset.columns.map((c) => (typeof c === 'string' ? c : c.name));
}

function columnDtype(dataset, name) {
  const col = (dataset.columns || []).find((c) => typeof c !== 'string' && c.name === name);
  return col ? col.dtype : '';
}

export function numericColumns(dataset) {
  return columnNames(dataset).filter((n) => NUMERIC_DTYPE_RE.test(columnDtype(dataset, n)));
}

// A brand-new worksheet's columns are still called C1..Cn — nothing worth quoting back at the
// user as an example, so the welcome text says "type some data in" instead.
export function isPlaceholderSchema(dataset) {
  const names = columnNames(dataset);
  return names.length > 0 && names.every((n) => SYSTEM_NAME_RE.test(n));
}

export function datasetLabel(dataset) {
  if (!dataset) return 'no worksheet';
  const cols = columnNames(dataset).length;
  return `${dataset.source} (${dataset.row_count} rows × ${cols} cols)`;
}

function guessDateColumn(dataset) {
  const byDtype = columnNames(dataset).find((n) => {
    const d = (columnDtype(dataset, n) || '').toLowerCase();
    return d.includes('date') || d.includes('time');
  });
  if (byDtype) return byDtype;
  return columnNames(dataset).find((n) => DATE_KEYWORDS.some((k) => n.toLowerCase().includes(k))) || null;
}

// ---------------------------------------------------------------------------
// column resolution against the active schema
// ---------------------------------------------------------------------------

function cleanToken(token) {
  return String(token || '')
    .trim()
    .replace(/^["'`]+|["'`]+$/g, '')
    .replace(/[.?!,;:]+$/, '')
    .replace(/^(?:the|column|col)\s+/i, '')
    .replace(/\s+column$/i, '')
    .trim();
}

// Returns {column} on a confident match, {ambiguous:[names]} when the token could mean more than
// one column, or {} when nothing matched. Ambiguity is never resolved by picking the first hit.
export function matchColumn(token, columns) {
  const cleaned = cleanToken(token);
  const norm = normalize(cleaned);
  if (!norm) return {};

  const exact = columns.find((c) => normalize(c) === norm);
  if (exact) return { column: exact };

  // "C3" means the third column of the worksheet, the way the grid labels it. (On a blank
  // worksheet the real name is also C3, so the exact match above already caught it.)
  const sys = cleaned.match(SYSTEM_NAME_RE);
  if (sys) {
    const index = parseInt(sys[1], 10) - 1;
    if (index >= 0 && index < columns.length) return { column: columns[index] };
    return {};
  }

  const prefix = columns.filter((c) => normalize(c).startsWith(norm));
  if (prefix.length === 1) return { column: prefix[0] };
  if (prefix.length > 1) return { ambiguous: prefix };

  const loose = columns.filter((c) => normalize(c).includes(norm) || norm.includes(normalize(c)));
  if (loose.length === 1) return { column: loose[0] };
  if (loose.length > 1) return { ambiguous: loose };
  return {};
}

export function resolveColumn(token, columns) {
  const hit = matchColumn(token, columns);
  return hit.column || null;
}

// The one reply the whole "never answer against the wrong column" rule hangs on: name what
// didn't match, then list what this worksheet actually has.
function columnError(tokens, dataset) {
  const columns = columnNames(dataset);
  const named = tokens.map((t) => `"${cleanToken(t)}"`).join(' and ');
  const ambiguous = tokens.map((t) => matchColumn(t, columns)).find((hit) => hit.ambiguous);
  const lead = ambiguous
    ? `${named} could mean ${ambiguous.ambiguous.join(' or ')} in ${dataset.source}.`
    : `I don't see ${named} in ${dataset.source}.`;
  return {
    action: 'error',
    message: `${lead}\nThis worksheet has: ${columns.join(', ')}. Which did you mean?`,
  };
}

function splitList(text) {
  return String(text)
    .replace(/[.?!]+$/, '')
    .split(/,|\band\b/i)
    .map((s) => s.trim())
    .filter(Boolean);
}

// Collects the tokens that failed to resolve, so a two-column request names both problems at once.
function unmatched(pairs) {
  return pairs.filter(([, hit]) => !hit.column).map(([token]) => token);
}

// Resolves a list of column tokens, failing on the first one that doesn't match so the error
// names the token the user actually typed.
function resolveAll(tokens, dataset) {
  const columns = columnNames(dataset);
  const resolved = [];
  for (const token of tokens) {
    const hit = matchColumn(token, columns);
    if (!hit.column) return { error: columnError([token], dataset) };
    if (!resolved.includes(hit.column)) resolved.push(hit.column);
  }
  return { columns: resolved };
}

// ---------------------------------------------------------------------------
// dynamic help + welcome, written in the active dataset's own column names
// ---------------------------------------------------------------------------

// Picks the columns the examples are written in. A spreadsheet usually reads inputs-left,
// result-right, and a measured outcome is usually continuous while counts and ids are integers —
// so the rightmost decimal column makes the best example outcome (yield_kg over plants,
// revenue over units), with the leftmost other numeric column as its predictor.
function examplePair(dataset) {
  const nums = numericColumns(dataset);
  const names = columnNames(dataset);
  const pool = nums.length >= 2 ? nums : names;
  if (pool.length < 2) return { x: pool[0] || null, y: null, nums };
  const decimals = nums.filter((n) => /float|double|decimal/i.test(columnDtype(dataset, n)));
  const y = decimals.length ? decimals[decimals.length - 1] : pool[pool.length - 1];
  const x = pool.find((n) => n !== y) || pool[0];
  return { x, y, nums };
}

function exampleLines(dataset) {
  const { x, y, nums } = examplePair(dataset);
  const lines = ['- "describe the data"'];
  if (x && y) {
    lines.push(`- "correlation between ${x} and ${y}"`);
    lines.push(`- "regression on ${y} using ${x}"`);
  }
  if (nums.length >= 2) lines.push(`- "segment by ${nums.slice(0, 3).join(', ')}"`);
  const dateCol = guessDateColumn(dataset);
  if (dateCol && y && y !== dateCol) lines.push(`- "forecast ${y} for 6 periods"`);
  if (x && y) lines.push(`- "plot ${x} vs ${y}"`);
  else if (x) lines.push(`- "chart of ${x}"`);
  return lines;
}

// `otherNames` are the other datasets loaded in this session — the switching commands are only
// advertised when there is somewhere to switch to.
function switchLines(otherNames = []) {
  if (!otherNames.length) return [];
  return ['- "list datasets"', `- "use ${otherNames[0]}"`];
}

export function buildHelpText(dataset, otherNames = []) {
  if (!dataset) return GENERIC_HELP;
  if (isPlaceholderSchema(dataset)) {
    return [
      `I'm looking at ${datasetLabel(dataset)}, and its columns are still unnamed (C1…C${columnNames(dataset).length}).`,
      'Type or paste data into the worksheet, or open a file from the File menu, then ask me for a describe, a correlation, a regression, a segmentation, a forecast or a chart.',
      ...switchLines(otherNames),
    ].join('\n');
  }
  return [`I didn't understand that. With ${datasetLabel(dataset)} loaded, try:`, ...exampleLines(dataset), ...switchLines(otherNames)].join('\n');
}

export function buildWelcome(dataset, otherNames = []) {
  if (!dataset) return GENERIC_HELP;
  if (isPlaceholderSchema(dataset)) {
    return [
      `Working with ${datasetLabel(dataset)} — an empty worksheet, so there is nothing to analyse yet.`,
      'Type or paste data into the worksheet, or open a file from the File menu, and ask me again.',
      ...switchLines(otherNames),
    ].join('\n');
  }
  return [`Working with ${datasetLabel(dataset)}. Ask me things like:`, ...exampleLines(dataset), ...switchLines(otherNames)].join('\n');
}

export function columnListReply(dataset) {
  const names = columnNames(dataset);
  if (!names.length) return `${dataset.source} has no columns.`;
  const nums = numericColumns(dataset);
  const numLine = nums.length ? `\nNumeric: ${nums.join(', ')}.` : '';
  return `${datasetLabel(dataset)} has: ${names.join(', ')}.${numLine}`;
}

// ---------------------------------------------------------------------------
// picking a dataset out of the session by name
// ---------------------------------------------------------------------------

// Matches a spoken name against the loaded datasets: exact id, exact source, source without its
// extension, then unique substring. Returns {dataset} / {ambiguous:[records]} / {}.
export function matchDataset(query, records) {
  const cleaned = cleanToken(query).replace(/^(?:dataset|worksheet|file|data)\s+/i, '');
  const norm = normalize(cleaned);
  if (!norm) return {};

  const byId = records.find((r) => r.dataset_id.toLowerCase() === cleaned.toLowerCase());
  if (byId) return { dataset: byId };

  const exact = records.filter((r) => normalize(r.source) === norm);
  if (exact.length === 1) return { dataset: exact[0] };

  const stem = (name) => normalize(String(name).replace(/\.[^.]+$/, ''));
  const byStem = records.filter((r) => stem(r.source) === norm);
  if (byStem.length === 1) return { dataset: byStem[0] };

  const loose = records.filter((r) => normalize(r.source).includes(norm) || r.dataset_id.toLowerCase().includes(cleaned.toLowerCase()));
  if (loose.length === 1) return { dataset: loose[0] };
  if (loose.length > 1) return { ambiguous: loose };

  // Last pass, for "switch to the sales file": drop the filler words and require every remaining
  // word to appear in the name, so one distinctive word is enough but a wrong word still fails.
  const words = norm.split(' ').filter((w) => w && !DATASET_FILLER.has(w));
  if (words.length) {
    const byWords = records.filter((r) => words.every((w) => normalize(r.source).includes(w)));
    if (byWords.length === 1) return { dataset: byWords[0] };
    if (byWords.length > 1) return { ambiguous: byWords };
  }
  return {};
}

// ---------------------------------------------------------------------------
// the parser
// ---------------------------------------------------------------------------

// `dataset` is the active dataset AT THE MOMENT THE MESSAGE WAS SENT — the caller must resolve it
// per message rather than passing one it captured earlier.
export function parseCommand(text, dataset) {
  const t = text.trim();

  // Session-level commands come first: they must work even when the active worksheet is blank.
  if (/^(?:list|show|which)\s+(?:the\s+)?(?:datasets?|worksheets?|files?|data\s*sets?)\b/i.test(t) || /^what\s+data(?:sets?)?\s+(?:do\s+i\s+have|is\s+loaded|are\s+loaded)/i.test(t) || /^what(?:'s|\s+is)\s+loaded\b/i.test(t)) {
    return { action: 'list-datasets' };
  }

  let m = t.match(/^(?:use|switch\s+to|switch|work\s+(?:with|on)|open)\s+(.+)$/i);
  if (m) return { action: 'switch-dataset', params: { name: m[1] } };

  if (/^(?:help|what\s+can\s+you\s+do|commands?)\b/i.test(t)) return { action: 'help' };

  if (/^(?:what\s+)?columns\b/i.test(t) || /^(?:list|show)\s+(?:the\s+)?columns\b/i.test(t) || /^what\s+columns\s+/i.test(t) || /^(?:what|which)\s+fields\b/i.test(t)) {
    return { action: 'columns' };
  }

  if (!dataset) return { action: 'no-dataset' };
  const columns = columnNames(dataset);

  if (/\bdescribe\b/i.test(t) || /^summar(y|ize|ise)\b/i.test(t) || /^(?:what|tell me)\b.*\bdata\b/i.test(t)) {
    return { action: 'describe', params: { columns: undefined } };
  }

  m = t.match(/correlat\w*\s+(?:between\s+)?(.+?)\s+(?:and|vs\.?|with)\s+(.+)/i);
  if (m) {
    const a = matchColumn(m[1], columns);
    const b = matchColumn(m[2], columns);
    const missing = unmatched([[m[1], a], [m[2], b]]);
    if (missing.length) return columnError(missing, dataset);
    return { action: 'correlation', params: { columns: [a.column, b.column], method: 'pearson' } };
  }

  m = t.match(/regression\s+(?:on|for)\s+(.+?)\s+(?:using|from|with|on)\s+(.+)/i) || t.match(/predict\s+(.+?)\s+(?:from|using|with)\s+(.+)/i);
  if (m) {
    const target = matchColumn(m[1], columns);
    if (!target.column) return columnError([m[1]], dataset);
    const features = resolveAll(splitList(m[2]), dataset);
    if (features.error) return features.error;
    return { action: 'regression', params: { target: target.column, features: features.columns, model_type: 'linear' } };
  }

  m = t.match(/(?:segment|cluster|group)\s+(?:by|on)\s+(.+)/i);
  if (m) {
    const cols = resolveAll(splitList(m[1]), dataset);
    if (cols.error) return cols.error;
    return { action: 'segmentation', params: { columns: cols.columns, method: 'auto', n_clusters: 3 } };
  }

  m = t.match(/forecast\s+(.+?)\s+for\s+(\d+)\s+periods?/i) || t.match(/forecast\s+(.+?)\s+(\d+)\s+periods?\s+(?:ahead|out)/i);
  if (m) {
    const value = matchColumn(m[1], columns);
    if (!value.column) return columnError([m[1]], dataset);
    const dateCol = guessDateColumn(dataset);
    if (!dateCol) {
      return {
        action: 'error',
        message: `I couldn't find a date-like column in ${dataset.source} to forecast against.\nThis worksheet has: ${columns.join(', ')}.`,
      };
    }
    return { action: 'forecast', params: { date_column: dateCol, value_column: value.column, periods: parseInt(m[2], 10), method: 'auto' } };
  }

  m = t.match(/(?:plot|chart|graph|scatter(?:\s*plot)?(?:\s+of)?)\s+(.+?)\s+(?:vs\.?|against|versus)\s+(.+)/i);
  if (m) {
    const x = matchColumn(m[1], columns);
    const y = matchColumn(m[2], columns);
    const missing = unmatched([[m[1], x], [m[2], y]]);
    if (missing.length) return columnError(missing, dataset);
    return { action: 'chart', params: { chart_type: 'scatter', columns: [x.column, y.column] } };
  }

  m = t.match(/(?:chart|plot|graph|histogram)\s+(?:of\s+)?(.+)/i);
  if (m) {
    const col = matchColumn(m[1], columns);
    if (!col.column) return columnError([m[1]], dataset);
    return { action: 'chart', params: { chart_type: 'histogram', columns: [col.column] } };
  }

  return { action: 'unknown' };
}
