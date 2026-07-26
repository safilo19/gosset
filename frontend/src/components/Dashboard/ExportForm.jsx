import { useState } from 'react';
import { apiClient } from '../../api/client';

export function ExportForm({ results, datasetId, onResult }) {
  const [selected, setSelected] = useState(new Set());
  const [format, setFormat] = useState('both');
  const [reportName, setReportName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (selected.size === 0) {
      setError('Select at least one prior result to include.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const analyses = results
        .filter((r) => selected.has(r.id))
        .map((r) => ({ title: r.label, data: r.data, chart_path: r.data?.chart_path || null }));
      const data = await apiClient.exportReport({
        dataset_id: datasetId,
        format,
        analyses,
        report_name: reportName || null,
      });
      onResult(`Export (${format})`, data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const exportable = results.filter((r) => r.analysisId !== 'export');

  if (exportable.length === 0) {
    return <p className="muted">Run at least one other analysis first, then come back here to export it.</p>;
  }

  return (
    <form className="analysis-form" onSubmit={handleSubmit}>
      <div className="field">
        <label>Include:</label>
        <div className="checkbox-list">
          {exportable.map((r) => (
            <label key={r.id} className="checkbox-item">
              <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
              {r.label}
            </label>
          ))}
        </div>
      </div>
      <div className="field">
        <label>Format</label>
        <select value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="both">both</option>
          <option value="xlsx">xlsx</option>
          <option value="markdown">markdown</option>
        </select>
      </div>
      <div className="field">
        <label>Report name (optional)</label>
        <input
          type="text"
          value={reportName}
          onChange={(e) => setReportName(e.target.value)}
          placeholder="auto-generated if empty"
        />
      </div>
      <button type="submit" disabled={busy}>
        {busy ? 'Exporting…' : 'Export'}
      </button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
