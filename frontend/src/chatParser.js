// Plain regex/keyword command parser — no external API calls. Column names in free text are
// resolved against the active dataset's real schema (case/space/underscore-insensitive, with a
// substring fallback) so "units" matches a column literally named "Units" or "unit_count".

export const HELP_TEXT = `I didn't understand that. Try things like:
- "describe the data"
- "correlation between units and revenue"
- "regression on revenue using units, discount_pct" (or "predict revenue from units and discount_pct")
- "segment by recency, frequency, monetary" (or "cluster by units, revenue")
- "forecast revenue for 6 periods"
- "chart of revenue" (or "plot units vs revenue")`;

function normalize(s) {
  return s
    .trim()
    .toLowerCase()
    .replace(/[_\s]+/g, ' ');
}

export function resolveColumn(token, columns) {
  if (!token) return null;
  const cleaned = token.trim().replace(/^["'`]+|["'`]+$/g, '').replace(/[.?!]+$/, '');
  const norm = normalize(cleaned);
  if (!norm) return null;

  let match = columns.find((c) => normalize(c) === norm);
  if (match) return match;

  match = columns.find((c) => normalize(c).includes(norm) || norm.includes(normalize(c)));
  return match || null;
}

function splitList(text) {
  return text
    .replace(/[.?!]+$/, '')
    .split(/,|\band\b/i)
    .map((s) => s.trim())
    .filter(Boolean);
}

function guessDateColumn(dataset) {
  const keywords = ['date', 'month', 'year', 'time', 'day', 'period'];
  const byDtype = dataset.columns.find((c) => c.dtype.toLowerCase().includes('date') || c.dtype.toLowerCase().includes('time'));
  if (byDtype) return byDtype.name;
  const byName = dataset.columns.find((c) => keywords.some((k) => c.name.toLowerCase().includes(k)));
  return byName ? byName.name : null;
}

function unresolvedError(labels, columns) {
  return {
    action: 'error',
    message: `I couldn't match ${labels} to column(s) in this dataset. Available columns: ${columns.join(', ')}`,
  };
}

export function parseCommand(text, dataset) {
  const columns = dataset.columns.map((c) => c.name);
  const t = text.trim();

  if (/\bdescribe\b/i.test(t) || /^summar(y|ize)\b/i.test(t)) {
    return { action: 'describe', params: { columns: undefined } };
  }

  let m = t.match(/correlat\w*\s+between\s+(.+?)\s+and\s+(.+)/i);
  if (m) {
    const a = resolveColumn(m[1], columns);
    const b = resolveColumn(m[2], columns);
    if (!a || !b) return unresolvedError(`"${m[1].trim()}" and/or "${m[2].trim()}"`, columns);
    return { action: 'correlation', params: { columns: [a, b], method: 'pearson' } };
  }

  m = t.match(/regression\s+on\s+(.+?)\s+using\s+(.+)/i) || t.match(/predict\s+(.+?)\s+from\s+(.+)/i);
  if (m) {
    const target = resolveColumn(m[1], columns);
    const features = splitList(m[2])
      .map((f) => resolveColumn(f, columns))
      .filter(Boolean);
    if (!target || !features.length) return unresolvedError(`a target/features in "${text}"`, columns);
    return { action: 'regression', params: { target, features, model_type: 'linear' } };
  }

  m = t.match(/(?:segment|cluster)\s+by\s+(.+)/i);
  if (m) {
    const cols = splitList(m[1])
      .map((c) => resolveColumn(c, columns))
      .filter(Boolean);
    if (!cols.length) return unresolvedError(`any columns in "${m[1].trim()}"`, columns);
    return { action: 'segmentation', params: { columns: cols, method: 'auto', n_clusters: 3 } };
  }

  m = t.match(/forecast\s+(.+?)\s+for\s+(\d+)\s+periods?/i);
  if (m) {
    const value = resolveColumn(m[1], columns);
    const periods = parseInt(m[2], 10);
    if (!value) return unresolvedError(`"${m[1].trim()}"`, columns);
    const dateCol = guessDateColumn(dataset);
    if (!dateCol) {
      return { action: 'error', message: "I couldn't find a date-like column in this dataset to forecast against." };
    }
    return { action: 'forecast', params: { date_column: dateCol, value_column: value, periods, method: 'auto' } };
  }

  m = t.match(/plot\s+(.+?)\s+vs\.?\s+(.+)/i);
  if (m) {
    const x = resolveColumn(m[1], columns);
    const y = resolveColumn(m[2], columns);
    if (!x || !y) return unresolvedError(`"${m[1].trim()}" and/or "${m[2].trim()}"`, columns);
    return { action: 'chart', params: { chart_type: 'scatter', columns: [x, y] } };
  }

  m = t.match(/(?:chart|plot)\s+of\s+(.+)/i);
  if (m) {
    const col = resolveColumn(m[1], columns);
    if (!col) return unresolvedError(`"${m[1].trim()}"`, columns);
    return { action: 'chart', params: { chart_type: 'histogram', columns: [col] } };
  }

  return { action: 'unknown', message: HELP_TEXT };
}
