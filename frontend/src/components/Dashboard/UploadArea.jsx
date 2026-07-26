import { useState } from 'react';
import { apiClient } from '../../api/client';
import { useDataset } from '../../context/DatasetContext';

export function UploadArea() {
  const { setDataset } = useDataset();
  const [dragOver, setDragOver] = useState(false);
  const [gsheetUrl, setGsheetUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleFile(file) {
    setBusy(true);
    setError(null);
    try {
      const ext = file.name.split('.').pop().toLowerCase();
      const sourceType = ext === 'xlsx' ? 'xlsx' : 'csv';
      const data = await apiClient.uploadFile(file, sourceType);
      setDataset(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleGSheetSubmit(e) {
    e.preventDefault();
    if (!gsheetUrl.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiClient.loadGSheet(gsheetUrl.trim());
      setDataset(data);
      setGsheetUrl('');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  return (
    <div className="upload-area">
      <div
        className={`dropzone${dragOver ? ' dropzone-active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => document.getElementById('file-input').click()}
        role="button"
        tabIndex={0}
      >
        <input
          id="file-input"
          type="file"
          accept=".csv,.xlsx"
          style={{ display: 'none' }}
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />
        <p>Drag &amp; drop a CSV or .xlsx file here, or click to choose one.</p>
      </div>
      <form className="gsheet-form" onSubmit={handleGSheetSubmit}>
        <input
          type="text"
          placeholder="...or paste a public Google Sheets link"
          value={gsheetUrl}
          onChange={(e) => setGsheetUrl(e.target.value)}
        />
        <button type="submit" disabled={busy}>
          Load
        </button>
      </form>
      {busy && <p className="status">Loading…</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
