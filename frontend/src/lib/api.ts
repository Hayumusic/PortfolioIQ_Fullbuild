import type {
  ApplicationOutputMappingResponse,
  CmdbApplicationsResponse,
  CmdbColumnsResponse,
  DashboardMetricsResponse,
  SimilarityAnalysisRequest,
  SimilarityAnalysisResponse,
  SimilarityAlertsResponse,
  SimilarityAppsResponse,
  SimilarityClustersResponse,
  SimilarityHeatmapResponse,
  SimilarityRulesResponse,
  SimilaritySummaryResponse,
  IntegrationNeighborhoodResponse,
  ObsoleteTechnologyResponse,
  OutputFamilyAnalysisViewResponse,
  OutputMappingDisplaySize,
  OutputMvpResults,
  PortfolioInsightsResponse,
  TechnologyLandscapeResponse,
  TechnologyInventoryResponse,
  TechnologyClustersResponse,
  TechnologyOptionsResponse,
  TechnologyIntegrationsResponse,
  TechnologyPageSize,
  UploadStatusResponse,
  ValidationDetailsResponse,
  ValidationDuplicatesResponse,
  ValidationSummaryResponse,
} from "@/types/api";

const configuredBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export const API_BASE_URL = configuredBaseUrl.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;

  const record = payload as Record<string, unknown>;
  const detail = record.detail ?? record.message ?? record.error;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String(item.msg);
        }
        return String(item);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String(detail.message);
  }
  return fallback;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      `Could not reach the Portfolio IQ backend at ${API_BASE_URL}.`,
      0,
    );
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      getErrorMessage(payload, `Request failed with status ${response.status}.`),
      response.status,
    );
  }
  return payload as T;
}

export function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: "GET" });
}

export function postJson<TResponse, TBody = unknown>(
  path: string,
  body?: TBody,
): Promise<TResponse> {
  return requestJson<TResponse>(path, {
    method: "POST",
    ...(body === undefined
      ? {}
      : {
          body: JSON.stringify(body),
          headers: { "Content-Type": "application/json" },
        }),
  });
}

export type MultipartFieldName = "file" | "files";

export function uploadFiles<T>(
  path: string,
  fieldName: MultipartFieldName,
  files: readonly File[],
): Promise<T> {
  const formData = new FormData();
  files.forEach((file) => formData.append(fieldName, file));
  return requestJson<T>(path, { method: "POST", body: formData });
}

export function csvDownloadUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

function jobPath(jobId: string, suffix: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}${suffix}`;
}

export function getUploadStatus(jobId: string): Promise<UploadStatusResponse> {
  return getJson(jobPath(jobId, "/uploads/status"));
}

export function getCmdbColumns(jobId: string): Promise<CmdbColumnsResponse> {
  return getJson(jobPath(jobId, "/cmdb/columns"));
}

export function getCmdbApplications(jobId: string): Promise<CmdbApplicationsResponse> {
  return getJson(jobPath(jobId, "/cmdb/applications"));
}

export function runSimilarityAnalysis(
  jobId: string,
  request: SimilarityAnalysisRequest,
): Promise<SimilarityAnalysisResponse> {
  return postJson(jobPath(jobId, "/analysis/similarity"), request);
}

export function getSimilarityApps(jobId: string, applicationKey: string, limit: 5 | 10 | 25 | 50, portfolio = "", excludedApplicationKeys: string[] = []): Promise<SimilarityAppsResponse> {
  const query = new URLSearchParams({ application_key: applicationKey, limit: String(limit), portfolio });
  for (const key of excludedApplicationKeys) query.append("excluded_application_keys", key);
  return getJson(jobPath(jobId, `/analysis/similarity/apps?${query.toString()}`));
}

export function getSimilarityHeatmap(
  jobId: string,
  limit: number,
  search = "",
  portfolio = "",
  applicationKey = "",
  scoreRange = "20-100",
  excludedApplicationKeys: string[] = [],
): Promise<SimilarityHeatmapResponse> {
  const query = new URLSearchParams({ limit: String(limit), search, portfolio, application_key: applicationKey, score_range: scoreRange });
  for (const key of excludedApplicationKeys) query.append("excluded_application_keys", key);
  return getJson(jobPath(jobId, `/analysis/similarity/heatmap?${query.toString()}`));
}

export function getSimilarityClusters(jobId: string): Promise<SimilarityClustersResponse> {
  return getJson(jobPath(jobId, "/analysis/similarity/clusters"));
}

export function getSimilarityAlerts(jobId: string, limit: 25 | 50 | 100 | 200, scoreRange = "20-100", portfolio = "", excludedApplicationKeys: string[] = []): Promise<SimilarityAlertsResponse> {
  const query = new URLSearchParams({ limit: String(limit), score_range: scoreRange, portfolio });
  for (const key of excludedApplicationKeys) query.append("excluded_application_keys", key);
  return getJson(jobPath(jobId, `/analysis/similarity/alerts?${query.toString()}`));
}

export function getSimilarityRules(jobId: string): Promise<SimilarityRulesResponse> {
  return getJson(jobPath(jobId, "/analysis/similarity/rules"));
}

export function getSimilaritySummary(jobId: string): Promise<SimilaritySummaryResponse> {
  return getJson(jobPath(jobId, "/analysis/similarity/summary"));
}

export function runDashboardMetrics(jobId: string): Promise<DashboardMetricsResponse> {
  return postJson(jobPath(jobId, "/analysis/dashboard-metrics"));
}

export function getDashboardMetrics(jobId: string): Promise<DashboardMetricsResponse> {
  return getJson(jobPath(jobId, "/analysis/dashboard-metrics/summary"));
}

export function runPortfolioInsights(jobId: string): Promise<PortfolioInsightsResponse> {
  return postJson<PortfolioInsightsResponse>(jobPath(jobId, "/analysis/portfolio-insights"));
}

export function runValidation(jobId: string): Promise<ValidationSummaryResponse> {
  return postJson(jobPath(jobId, "/analysis/validation"));
}

export function getValidationSummary(jobId: string): Promise<ValidationSummaryResponse> {
  return getJson(jobPath(jobId, "/analysis/validation/summary"));
}

export function getValidationDetails(
  jobId: string,
  page = 1,
  pageSize = 50,
): Promise<ValidationDetailsResponse> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return getJson(`${jobPath(jobId, "/analysis/validation/details")}?${query}`);
}

export function getValidationDuplicates(jobId: string): Promise<ValidationDuplicatesResponse> {
  return getJson(jobPath(jobId, "/analysis/validation/duplicates"));
}

export function validationCompletenessCsvUrl(jobId: string): string {
  return csvDownloadUrl(jobPath(jobId, "/analysis/validation/completeness.csv"));
}

export function runTechnologyAnalysis(jobId: string): Promise<unknown> {
  return postJson(jobPath(jobId, "/analysis/technology"));
}

export function runOutputFamilyAnalysis(jobId: string): Promise<unknown> {
  return postJson(jobPath(jobId, "/analysis/output-families"));
}

export function getOutputMvpResults(jobId: string): Promise<OutputMvpResults> {
  return getJson(jobPath(jobId, "/analysis/output-families/mvp"));
}

export async function downloadOutputWorkbook(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${jobPath(jobId, "/analysis/output-families/export.xlsx")}`);
  if (!response.ok) throw new ApiError("Could not download the Application Outputs workbook.", response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${jobId}-application-outputs.xlsx`;
  link.click();
  URL.revokeObjectURL(url);
}

export function getOutputFamilyAnalysisView(
  jobId: string,
  filters: { portfolio: string; outputFamily: string; search: string },
): Promise<OutputFamilyAnalysisViewResponse> {
  const query = new URLSearchParams({
    portfolio: filters.portfolio,
    output_family: filters.outputFamily,
    search: filters.search,
  });
  return getJson(jobPath(jobId, `/analysis/output-families/analysis-view?${query}`));
}

export function getApplicationOutputMapping(
  jobId: string,
  filters: { portfolio: string; outputFamily: string; confidence: string; classificationStatus: string; search: string; displaySize: OutputMappingDisplaySize },
): Promise<ApplicationOutputMappingResponse> {
  const query = new URLSearchParams({
    portfolio: filters.portfolio,
    output_family: filters.outputFamily,
    confidence: filters.confidence,
    classification_status: filters.classificationStatus,
    search: filters.search,
    display_size: filters.displaySize,
  });
  return getJson(jobPath(jobId, `/analysis/output-families/application-mapping?${query}`));
}

export function getTechnologyOptions(jobId: string): Promise<TechnologyOptionsResponse> {
  return getJson(jobPath(jobId, "/analysis/technology/options"));
}

export function getTechnologyClusters(
  jobId: string,
  portfolio: string,
): Promise<TechnologyClustersResponse> {
  const query = new URLSearchParams({ limit: "500", portfolio });
  return getJson(jobPath(jobId, `/analysis/technology/clusters?${query}`));
}

export function getTechnologyInventory(
  jobId: string,
  filters: { search: string; portfolio: string; businessCriticality: string; page: number; pageSize: TechnologyPageSize },
): Promise<TechnologyInventoryResponse> {
  const query = new URLSearchParams({
    search: filters.search,
    portfolio: filters.portfolio,
    business_criticality: filters.businessCriticality,
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  return getJson(jobPath(jobId, `/analysis/technology/inventory?${query}`));
}

export function getTechnologyLandscape(
  jobId: string,
  filters: { dimension: string; portfolio: string; businessCriticality: string; search: string; technologyValue: string; page: number; pageSize: TechnologyPageSize },
): Promise<TechnologyLandscapeResponse> {
  const query = new URLSearchParams({
    dimension: filters.dimension,
    portfolio: filters.portfolio,
    business_criticality: filters.businessCriticality,
    search: filters.search,
    technology_value: filters.technologyValue,
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  return getJson(jobPath(jobId, `/analysis/technology/landscape?${query}`));
}

export function getIntegrationNeighborhood(
  jobId: string,
  filters: { applicationCode: string; portfolio: string; integrationType: string; confidence: string; page: number; pageSize: TechnologyPageSize },
): Promise<IntegrationNeighborhoodResponse> {
  const query = new URLSearchParams({
    application_code: filters.applicationCode,
    portfolio: filters.portfolio,
    integration_type: filters.integrationType,
    confidence: filters.confidence,
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  return getJson(jobPath(jobId, `/analysis/technology/integration-neighborhood?${query}`));
}

export function getTechnologyIntegrations(jobId: string, limit = 1000): Promise<TechnologyIntegrationsResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  return getJson(jobPath(jobId, `/analysis/technology/integrations?${query}`));
}

export function getObsoleteTechnology(
  jobId: string,
  filters: { portfolio: string; indicator: string; businessCriticality: string; search: string; page: number; pageSize: TechnologyPageSize },
): Promise<ObsoleteTechnologyResponse> {
  const query = new URLSearchParams({
    portfolio: filters.portfolio,
    indicator: filters.indicator,
    business_criticality: filters.businessCriticality,
    search: filters.search,
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  return getJson(jobPath(jobId, `/analysis/technology/obsolete?${query}`));
}
