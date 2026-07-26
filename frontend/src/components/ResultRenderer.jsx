import { apiClient } from '../api/client';

// Mirrors backend/core/reports.py's _extract_table heuristic: pull the first known
// list-of-dicts (or matrix-like dict) out as the main table; everything else is a scalar.
const TABLE_KEYS_PRIORITY = [
  'coefficients',
  'forecast',
  'segments',
  'strongest_pairs',
  'stats',
  'groups',
  'datasets',
  'preview',
  'row_assignments',
];
const NARRATIVE_KEYS = ['conclusion', 'interpretation', 'summary', 'method_reason'];
const HIDE_SCALAR_KEYS = new Set(['image_base64', 'chart_path', ...NARRATIVE_KEYS]);

function extractTable(data) {
  for (const key of TABLE_KEYS_PRIORITY) {
    const value = data[key];
    if (Array.isArray(value) && value.length && value.every((v) => v && typeof v === 'object')) {
      return { key, rows: value };
    }
  }
  if (data.matrix && typeof data.matrix === 'object' && Object.keys(data.matrix).length) {
    const rows = Object.entries(data.matrix).map(([k, v]) => ({ column: k, ...v }));
    return { key: 'matrix', rows };
  }
  if (data.contingency_table && typeof data.contingency_table === 'object' && Object.keys(data.contingency_table).length) {
    const rows = Object.entries(data.contingency_table).map(([k, v]) => ({ '(row)': k, ...v }));
    return { key: 'contingency_table', rows };
  }
  return { key: null, rows: [] };
}

function formatCell(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function DataTable({ rows }) {
  if (!rows.length) return null;
  const headers = Object.keys(rows[0]);
  return (
    <div className="table-scroll">
      <table className="result-table">
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {headers.map((h) => (
                <td key={h}>{formatCell(row[h])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ResultRenderer({ data, hideNarrative = false }) {
  if (!data) return null;

  if (data.files) {
    return (
      <div className="result-export">
        {!hideNarrative && data.summary && <p className="narrative">{data.summary}</p>}
        <ul className="download-list">
          {data.files.map((f) => (
            <li key={f}>
              <a href={apiClient.downloadUrl(f)} target="_blank" rel="noreferrer" download>
                {f.split(/[\\/]/).pop()}
              </a>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const narrative = hideNarrative ? null : NARRATIVE_KEYS.map((k) => data[k]).find(Boolean);
  const { key: tableKey, rows } = extractTable(data);
  const scalars = Object.entries(data).filter(
    ([k, v]) => k !== tableKey && !HIDE_SCALAR_KEYS.has(k) && (typeof v !== 'object' || v === null),
  );

  return (
    <div className="result-content">
      {data.image_base64 && (
        <img className="result-image" src={`data:image/png;base64,${data.image_base64}`} alt={data.title || 'chart'} />
      )}
      {narrative && <p className="narrative">{narrative}</p>}
      {scalars.length > 0 && (
        <table className="scalar-table">
          <tbody>
            {scalars.map(([k, v]) => (
              <tr key={k}>
                <th>{k}</th>
                <td>{formatCell(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rows.length > 0 && <DataTable rows={rows} />}
    </div>
  );
}
