import { useDataset } from '../../context/DatasetContext';

export function DatasetSummary() {
  const { dataset } = useDataset();
  if (!dataset) return null;

  return (
    <div className="dataset-summary">
      <h2>
        Dataset <code>{dataset.dataset_id}</code>
      </h2>
      <p className="muted">
        {dataset.source} · {dataset.row_count} rows · {dataset.columns.length} columns
      </p>

      <div className="table-scroll">
        <table className="schema-table">
          <thead>
            <tr>
              <th>Column</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {dataset.columns.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>{c.dtype}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Preview</h3>
      <div className="table-scroll">
        <table className="preview-table">
          <thead>
            <tr>
              {dataset.columns.map((c) => (
                <th key={c.name}>{c.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataset.preview.map((row, i) => (
              <tr key={i}>
                {dataset.columns.map((c) => (
                  <td key={c.name}>{row[c.name] === null || row[c.name] === undefined ? '' : String(row[c.name])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
