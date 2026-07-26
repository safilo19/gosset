import { useState } from 'react';
import { ANALYSES } from '../../analysisConfig';
import { useDataset } from '../../context/DatasetContext';
import { AnalysisForm } from './AnalysisForm';
import { ExportForm } from './ExportForm';

export function AnalysisSection() {
  const { dataset, addResult, results } = useDataset();
  const [activeId, setActiveId] = useState(null);

  const columns = dataset.columns.map((c) => c.name);
  const activeConfig = ANALYSES.find((a) => a.id === activeId);

  return (
    <div className="analysis-section">
      <div className="analysis-buttons">
        {ANALYSES.map((a) => (
          <button
            key={a.id}
            type="button"
            className={activeId === a.id ? 'chip chip-active' : 'chip'}
            onClick={() => setActiveId(activeId === a.id ? null : a.id)}
          >
            {a.label}
          </button>
        ))}
      </div>

      {activeConfig && !activeConfig.special && (
        <AnalysisForm
          key={activeConfig.id}
          config={activeConfig}
          columns={columns}
          onResult={(label, data) => addResult(activeConfig.id, label, data)}
        />
      )}
      {activeConfig && activeConfig.special && (
        <ExportForm
          results={results}
          datasetId={dataset.dataset_id}
          onResult={(label, data) => addResult('export', label, data)}
        />
      )}
    </div>
  );
}
