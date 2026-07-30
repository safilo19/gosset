// Single place that wraps every call to the backend REST API.
// The backend serves this page itself, so every request is same-origin —
// no base URL, no CORS, nothing to configure or break.

// A "Failed to fetch" TypeError means the request never reached the server at all (as opposed
// to the server responding with an error status) — that's almost always a transient hiccup
// right after the backend starts up, so one silent retry papers over it. If it fails twice in a
// row, surface a message that actually tells the user what to check instead of the raw browser text.
async function fetchWithRetry(url, options) {
  try {
    return await fetch(url, options);
  } catch (err) {
    if (!(err instanceof TypeError)) throw err;
    await new Promise((r) => setTimeout(r, 700));
    try {
      return await fetch(url, options);
    } catch {
      throw new Error('Could not reach the backend server. Make sure the LaunchBackend window is still open and running, then try again.');
    }
  }
}

async function handleResponse(res) {
  if (!res.ok) {
    let detail = res.statusText;
    let swap = null;
    try {
      const body = await res.json();
      // A degenerate-group refusal names the two fields to exchange (backend check_group_column). It
      // travels on the Error so the dialog can offer the swap as a button.
      if (Array.isArray(body.swap) && body.swap.length === 2) swap = body.swap;
      // A 400 from our own code carries a sentence meant for the user. A 422 from FastAPI's request
      // validation carries an ARRAY of {loc, msg} objects — passed to Error() unchanged that shows
      // as "[object Object],[object Object]", which says nothing about what was wrong.
      if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((item) => {
            const field = (item.loc || []).filter((part) => part !== 'body').join('.');
            return field ? `${field}: ${item.msg}` : item.msg;
          })
          .join('; ');
      } else {
        detail = body.detail || JSON.stringify(body);
      }
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    const error = new Error(detail || `Request failed (${res.status}).`);
    if (swap) error.swap = swap;
    throw error;
  }
  return res.json();
}

async function post(path, body) {
  const res = await fetchWithRetry(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

async function patch(path, body) {
  const res = await fetchWithRetry(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

async function put(path, body) {
  const res = await fetchWithRetry(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

// DELETE with a JSON body — the row/column lists to remove.
async function del(path, body) {
  const res = await fetchWithRetry(path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export const apiClient = {
  async uploadFile(file, sourceType) {
    const form = new FormData();
    form.append('file', file);
    form.append('source_type', sourceType);
    const res = await fetchWithRetry('/datasets', { method: 'POST', body: form });
    return handleResponse(res);
  },

  async loadGSheet(source, sheetName) {
    return post('/datasets', { source, sheet_name: sheetName || null });
  },

  async listDatasets() {
    const res = await fetchWithRetry('/datasets');
    return handleResponse(res);
  },

  async describe(datasetId, columns) {
    const qs = columns && columns.length ? `?${columns.map((c) => `columns=${encodeURIComponent(c)}`).join('&')}` : '';
    const res = await fetchWithRetry(`/datasets/${datasetId}/describe${qs}`);
    return handleResponse(res);
  },

  async getRows(datasetId) {
    const res = await fetchWithRetry(`/datasets/${datasetId}/rows`);
    return handleResponse(res);
  },

  async createBlankDataset(name) {
    const qs = name ? `?name=${encodeURIComponent(name)}` : '';
    const res = await fetchWithRetry(`/datasets/blank${qs}`, { method: 'POST' });
    return handleResponse(res);
  },

  // Whole-worksheet read/write: /full for File > Save Project, the /values pair for opening a
  // saved project and for undoing a delete or a grid-growing paste.
  async getFull(datasetId) {
    const res = await fetchWithRetry(`/datasets/${datasetId}/full`);
    return handleResponse(res);
  },

  createFromValues: (columns, rows, source) => post('/datasets/values', { columns, rows, source }),
  replaceValues: (datasetId, columns, rows) => put(`/datasets/${datasetId}/values`, { columns, rows }),
  deleteRows: (datasetId, rowIndices) => del(`/datasets/${datasetId}/rows`, { row_indices: rowIndices }),
  deleteColumns: (datasetId, columns) => del(`/datasets/${datasetId}/columns`, { columns }),

  updateCell: (datasetId, rowIndex, column, value) => patch(`/datasets/${datasetId}/cell`, { row_index: rowIndex, column, value }),
  pasteCells: (datasetId, startRow, startColumn, values) => patch(`/datasets/${datasetId}/paste`, { start_row: startRow, start_column: startColumn, values }),
  renameColumn: (datasetId, column, newName) => patch(`/datasets/${datasetId}/column-name`, { column, new_name: newName }),
  // The worksheet TAB's label (distinct from renameColumn above, which renames a column inside it).
  renameWorksheet: (datasetId, name) => patch(`/datasets/${datasetId}/name`, { name }),

  // Every Data menu operation comes through here; the body names the operation. The reply says
  // what changed — `mode`, plus the worksheets it created and the ones it rewrote in place.
  dataOp: (datasetId, body) => post(`/datasets/${datasetId}/data-op`, body),

  // All 18 Stat > Basic Statistics procedures come through here; the body names the procedure.
  basicStats: (datasetId, body) => post(`/datasets/${datasetId}/basic-stats`, body),
  // Stat > Regression's 13 dialogs and its Predict panel, same contract. Deliberately NOT named
  // `regression`: that key is already the old single-model endpoint below, and a duplicate key in
  // this object literal would silently shadow one of them.
  regressionModel: (datasetId, body) => post(`/datasets/${datasetId}/regression-model`, body),
  // Stat > ANOVA: one-way through GLM, mixed effects, MANOVA and ANOM, same contract again. The
  // dialogs downstream of a fit send the stored model_spec back in `options`.
  anova: (datasetId, body) => post(`/datasets/${datasetId}/anova`, body),
  // Calc: the Calculator, data generation, random data, probability, resampling and matrices.
  calc: (datasetId, body) => post(`/datasets/${datasetId}/calc`, body),

  correlation: (datasetId, body) => post(`/datasets/${datasetId}/correlation`, body),
  hypothesisTest: (datasetId, body) => post(`/datasets/${datasetId}/hypothesis-test`, body),
  regression: (datasetId, body) => post(`/datasets/${datasetId}/regression`, body),
  forecast: (datasetId, body) => post(`/datasets/${datasetId}/forecast`, body),
  segmentation: (datasetId, body) => post(`/datasets/${datasetId}/segmentation`, body),
  chart: (datasetId, body) => post(`/datasets/${datasetId}/chart`, body),
  // Every Graph menu item's series comes from here — binning, five-number stats, quantiles,
  // density curves and interpolated grids are all computed server-side.
  graphData: (datasetId, body) => post(`/datasets/${datasetId}/graph-data`, body),
  decisionTree: (datasetId, body) => post(`/datasets/${datasetId}/decision-tree`, body),
  randomForest: (datasetId, body) => post(`/datasets/${datasetId}/random-forest`, body),
  gradientBoosting: (datasetId, body) => post(`/datasets/${datasetId}/gradient-boosting`, body),
  automl: (datasetId, body) => post(`/datasets/${datasetId}/automl`, body),
  exportReport: (body) => post('/reports', body),

  // Report files come back from the API as absolute server-side paths (same contract the MCP
  // tool uses); the API also serves backend/output/ as static files, so the browser just needs
  // the filename appended to that route.
  downloadUrl(filePath) {
    const filename = filePath.split(/[\\/]/).pop();
    return `/output/${encodeURIComponent(filename)}`;
  },
};
