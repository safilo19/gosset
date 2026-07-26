// Single place that wraps every call to the backend REST API.
// Base URL comes from VITE_API_URL so deployment only needs an env var change.

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');

async function handleResponse(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new Error(detail);
  }
  return res.json();
}

async function post(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export const apiClient = {
  baseUrl: API_BASE,

  async uploadFile(file, sourceType) {
    const form = new FormData();
    form.append('file', file);
    form.append('source_type', sourceType);
    const res = await fetch(`${API_BASE}/datasets`, { method: 'POST', body: form });
    return handleResponse(res);
  },

  async loadGSheet(source, sheetName) {
    return post('/datasets', { source, sheet_name: sheetName || null });
  },

  async listDatasets() {
    const res = await fetch(`${API_BASE}/datasets`);
    return handleResponse(res);
  },

  async describe(datasetId, columns) {
    const qs = columns && columns.length ? `?${columns.map((c) => `columns=${encodeURIComponent(c)}`).join('&')}` : '';
    const res = await fetch(`${API_BASE}/datasets/${datasetId}/describe${qs}`);
    return handleResponse(res);
  },

  correlation: (datasetId, body) => post(`/datasets/${datasetId}/correlation`, body),
  hypothesisTest: (datasetId, body) => post(`/datasets/${datasetId}/hypothesis-test`, body),
  regression: (datasetId, body) => post(`/datasets/${datasetId}/regression`, body),
  forecast: (datasetId, body) => post(`/datasets/${datasetId}/forecast`, body),
  segmentation: (datasetId, body) => post(`/datasets/${datasetId}/segmentation`, body),
  chart: (datasetId, body) => post(`/datasets/${datasetId}/chart`, body),
  exportReport: (body) => post('/reports', body),

  // Report files come back from the API as absolute server-side paths (same contract the MCP
  // tool uses); the API also serves backend/output/ as static files, so the browser just needs
  // the filename appended to that route.
  downloadUrl(filePath) {
    const filename = filePath.split(/[\\/]/).pop();
    return `${API_BASE}/output/${encodeURIComponent(filename)}`;
  },
};
