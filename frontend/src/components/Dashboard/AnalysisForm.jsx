import { useEffect, useState } from 'react';
import { buildParams, defaultValues, summarizeParams, validateValues } from '../../analysisConfig';
import { useDataset } from '../../context/DatasetContext';
import { runAnalysis } from '../../runAnalysis';

export function AnalysisForm({ config, columns, onResult }) {
  const { dataset } = useDataset();
  const [values, setValues] = useState(() => defaultValues(config));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setValues(defaultValues(config));
    setError(null);
  }, [config]);

  function updateField(name, value) {
    setValues((v) => ({ ...v, [name]: value }));
  }

  function toggleColumn(name, col) {
    setValues((v) => {
      const list = v[name] || [];
      const next = list.includes(col) ? list.filter((c) => c !== col) : [...list, col];
      return { ...v, [name]: next };
    });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const validationError = validateValues(config, values);
    if (validationError) {
      setError(validationError);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const params = buildParams(config, values);
      const data = await runAnalysis(config.id, dataset.dataset_id, params);
      onResult(summarizeParams(config, values), data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="analysis-form" onSubmit={handleSubmit}>
      {config.fields.map((f) => (
        <div className="field" key={f.name}>
          <label>{f.label}</label>
          {f.type === 'column' && (
            <select value={values[f.name]} onChange={(e) => updateField(f.name, e.target.value)}>
              <option value="">-- choose --</option>
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          )}
          {f.type === 'columns' && (
            <div className="checkbox-list">
              {columns.map((c) => (
                <label key={c} className="checkbox-item">
                  <input
                    type="checkbox"
                    checked={(values[f.name] || []).includes(c)}
                    onChange={() => toggleColumn(f.name, c)}
                  />
                  {c}
                </label>
              ))}
            </div>
          )}
          {f.type === 'select' && (
            <select value={values[f.name]} onChange={(e) => updateField(f.name, e.target.value)}>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          )}
          {f.type === 'number' && (
            <input
              type="number"
              value={values[f.name]}
              step={f.step || 1}
              min={f.min}
              max={f.max}
              onChange={(e) => updateField(f.name, e.target.value)}
            />
          )}
        </div>
      ))}
      <button type="submit" disabled={busy}>
        {busy ? 'Running…' : 'Run'}
      </button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
