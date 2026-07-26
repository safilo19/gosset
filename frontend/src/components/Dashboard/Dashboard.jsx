import { useDataset } from '../../context/DatasetContext';
import { ResultRenderer } from '../ResultRenderer';
import { AnalysisSection } from './AnalysisSection';
import { DatasetSummary } from './DatasetSummary';
import { UploadArea } from './UploadArea';

export function Dashboard() {
  const { dataset, results } = useDataset();

  return (
    <div className="dashboard">
      <UploadArea />
      {dataset && (
        <>
          <DatasetSummary />
          <AnalysisSection />
          <div className="results-list">
            {results.map((r) => (
              <div key={r.id} className="result-block">
                <h3>{r.label}</h3>
                <ResultRenderer data={r.data} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
