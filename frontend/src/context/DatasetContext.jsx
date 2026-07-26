import { createContext, useContext, useRef, useState } from 'react';

const DatasetContext = createContext(null);

export function DatasetProvider({ children }) {
  const [dataset, setDatasetState] = useState(null);
  const [results, setResults] = useState([]);
  const nextId = useRef(1);

  function setDataset(loadResponse) {
    setDatasetState(loadResponse);
    setResults([]); // a freshly loaded dataset starts with a clean results history
  }

  function addResult(analysisId, label, data) {
    const id = nextId.current++;
    setResults((prev) => [{ id, analysisId, label, data }, ...prev]);
    return id;
  }

  return (
    <DatasetContext.Provider value={{ dataset, setDataset, results, addResult }}>{children}</DatasetContext.Provider>
  );
}

export function useDataset() {
  const ctx = useContext(DatasetContext);
  if (!ctx) throw new Error('useDataset must be used within a DatasetProvider');
  return ctx;
}
