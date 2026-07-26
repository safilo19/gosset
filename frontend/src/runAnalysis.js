// Single dispatch used by both the Dashboard forms and the Chat panel, so both interfaces
// call the backend exactly the same way and can never drift apart.
import { apiClient } from './api/client';

export async function runAnalysis(analysisId, datasetId, params) {
  switch (analysisId) {
    case 'describe':
      return apiClient.describe(datasetId, params.columns);
    case 'correlation':
      return apiClient.correlation(datasetId, params);
    case 'hypothesis':
      return apiClient.hypothesisTest(datasetId, params);
    case 'regression':
      return apiClient.regression(datasetId, params);
    case 'forecast':
      return apiClient.forecast(datasetId, params);
    case 'segmentation':
      return apiClient.segmentation(datasetId, params);
    case 'chart':
      return apiClient.chart(datasetId, params);
    default:
      throw new Error(`Unknown analysis: ${analysisId}`);
  }
}
