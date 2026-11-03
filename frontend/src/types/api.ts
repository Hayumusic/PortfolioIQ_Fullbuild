export interface HealthResponse {
  status: "healthy" | string;
  service: string;
  environment: string;
}

export interface JobResponse {
  status: string;
  job_id: string;
  created_at: string;
  uploads: Record<string, string[]>;
  message: string;
}

export interface UploadResult {
  status: string;
  module_name: string;
  job_id?: string | null;
  message: string;
  file_names?: string[];
  upload_id?: string;
  file_count?: number;
  row_count?: number | null;
  column_count?: number | null;
  warnings?: string[];
  files?: UploadedFileMetadata[];
}

export interface UploadedFileMetadata {
  upload_id: string;
  filename: string;
  stored_filename: string;
  processed: boolean;
  row_count?: number | null;
  column_count?: number | null;
  warnings: string[];
}

export interface UploadSourceStatus {
  required: boolean;
  uploaded: boolean;
  processed: boolean;
  upload_count: number;
  latest_upload_id: string | null;
  latest_filename: string | null;
  accepted_file_types: string[];
  warnings: string[];
}

export type UploadSourceKey =
  | "cmdb"
  | "mandatory_fields_config"
  | "output_family_config"
  | "confluence"
  | "team_validation"
  | "cloudwatch";

export interface UploadStatusResponse {
  [key: string]: unknown;
  job_id: string;
  sources: Record<UploadSourceKey, UploadSourceStatus>;
  cmdb_ready: boolean;
  mandatory_fields_config_ready: boolean;
  output_family_config_ready: boolean;
  optional_inputs_available: boolean;
  can_run_validation: boolean;
  can_run_outputs_analysis: boolean;
  missing_required_inputs: string[];
  warnings: string[];
}

export interface OutputFamilyFilterOptions {
  portfolios: string[];
  output_families: string[];
  confidences: OutputConfidence[];
  classification_statuses: OutputClassificationStatus[];
}

export interface OutputFamilyAnalysisRow {
  output_family: string;
  application_count: number;
  portfolio_count: number;
  multiple_family_count: number;
}

export interface OutputFamilyCoverageRow {
  portfolio: string;
  output_family: string;
  application_count: number;
}

export interface OutputFamilyOverlapRow {
  output_family: string;
  number_of_applications: number;
  number_of_portfolios: number;
  potential_overlap: boolean;
}

export interface OutputFamilyAnalysisViewResponse {
  options: OutputFamilyFilterOptions;
  filtered_application_count: number;
  insufficient_evidence_application_count: number;
  multiple_family_application_count: number;
  families: OutputFamilyAnalysisRow[];
  coverage: OutputFamilyCoverageRow[];
  potential_overlaps: OutputFamilyOverlapRow[];
}

export type OutputConfidence = "High" | "Medium" | "Low" | "Insufficient Evidence";
export type OutputClassificationStatus = "Classified" | "Multiple Families" | "Insufficient Evidence";
export type OutputMappingDisplaySize = "50" | "100" | "200" | "all";

export interface OutputAssignment {
  output_family: string;
  output_cluster: string;
  evidence: string[];
}

export interface ApplicationOutputMappingRow {
  application_name: string;
  application_code: string | null;
  portfolio: string | null;
  business_criticality: string | null;
  assignments: OutputAssignment[];
  output_families: string[];
  output_clusters: string[];
  output_family_count: number;
  assigned_output_family: string;
  assigned_output_cluster: string;
  confidence: OutputConfidence;
  classification_status: OutputClassificationStatus;
  fields_used: string[];
  matched_evidence: string[];
  classification_rationale: string;
  comment: string;
  warnings: string[];
}

export interface ApplicationOutputMappingResponse {
  options: OutputFamilyFilterOptions;
  display_size: OutputMappingDisplaySize;
  total_application_count: number;
  returned_application_count: number;
  insufficient_evidence_application_count: number;
  multiple_family_application_count: number;
  applications: ApplicationOutputMappingRow[];
}

export interface OutputFamilyCluster {
  output_family_name: string;
  applications_producing_this_output_family: string;
  application_count: number;
  specific_outputs_identified: string;
  similarity_notes: string;
  confidence_level: string;
  evidence_type: string;
  source_of_truth_labels_in_cluster: string;
  reliability_labels_in_cluster: string;
}

export interface OutputFamilyMatrixRow {
  application_key: string;
  application_name: string;
  values: Record<string, "Yes" | "No">;
}

export interface OutputRedundancyAlert {
  applications_involved: string;
  shared_output_family: string;
  similar_or_duplicated_outputs: string;
  business_impact: string;
  redundancy_severity: "Low" | "Medium" | "High";
  recommendation: string;
  evidence_type: string;
  source_of_truth_label: string;
  reliability_label: string;
}

export interface OutputDetail {
  application_key: string;
  application_name: string;
  output_summary: string;
  output_family_classification: string;
  key_evidence_or_keywords_found: string;
  consumers_or_downstream_users: string;
  confidence_level: string;
  why_classified: string;
  comment: string;
  direct_or_inferred: string;
  evidence_type: string;
  missing_data_warnings: string;
  source_of_truth_label: string;
  reliability_label: string;
}

export interface OutputException {
  application_name: string;
  output_description: string;
  reason: string;
  comment?: string;
  confidence_level: string;
  evidence_type: string;
  missing_data_warnings: string;
}

export interface OutputMvpResults {
  output_family_clusters: OutputFamilyCluster[];
  family_matrix: {
    output_families: string[];
    configured_families: string[];
    other_clusters: string[];
    rows: OutputFamilyMatrixRow[];
  };
  redundancy_alerts: OutputRedundancyAlert[];
  output_details: OutputDetail[];
  exceptions: OutputException[];
  downloads: { details: string; clusters: string; alerts: string };
}

export interface MandatoryFieldMapping {
  configured_field: string;
  cmdb_column: string | null;
  matched: boolean;
  match_type: string;
}

export interface MandatoryFieldsConfigResponse {
  job_id: string;
  upload_id: string | null;
  mandatory_fields: string[];
  row_count: number;
  warnings: string[];
  usable: boolean;
}

export interface OutputFamilyDefinition {
  key: string | null;
  name: string;
  keywords: string[];
  description: string | null;
  members: Array<Record<string, string | null>>;
}

export interface OutputFamiliesConfigResponse {
  job_id: string;
  upload_id: string | null;
  family_count: number;
  families: OutputFamilyDefinition[];
  row_count: number;
  warnings: string[];
  usable: boolean;
}

export interface CmdbColumnsResponse {
  job_id: string;
  upload_id: string;
  total_column_count: number;
  columns: string[];
  application_code_column: string | null;
  application_id_column: string | null;
  application_name_column: string | null;
}

export interface CmdbApplication {
  internal_row_number: number;
  application_code: string | null;
  application_name: string | null;
}

export interface CmdbApplicationsResponse {
  job_id: string;
  upload_id: string;
  total_records: number;
  applications: CmdbApplication[];
}

export interface ValidationSummaryResponse {
  status: string;
  module_name: "validation";
  job_id: string;
  upload_id: string;
  validation_status: "validated" | "completed_with_warnings";
  analysis_status: "completed" | "completed_with_warnings";
  summary: ValidationSummary;
  warnings: string[];
  details_endpoint: string;
  duplicates_endpoint: string;
  completeness_csv_endpoint: string;
  detail_endpoints: Record<string, string>;
}

export interface ValidationSummary {
  total_row_count: number;
  total_column_count: number;
  overall_completeness: number;
  matched_mandatory_columns: Array<{
    configured_field: string;
    cmdb_column: string;
  }>;
  missing_mandatory_columns: string[];
  mandatory_field_mappings: MandatoryFieldMapping[];
  mandatory_fields_config_source: "job_upload" | "global_config" | "default_or_missing";
  mandatory_fields_config_upload_id: string | null;
  application_code_column: string | null;
  application_id_column: string | null;
  duplicate_application_code_group_count: number;
  duplicate_application_id_group_count: number;
  duplicate_application_name_group_count: number;
  warning_count: number;
  missing_data_warnings: string[];
  source_of_truth_label: string | null;
  reliability_label: string | null;
  reliability_reason: string | null;
  team_validation_summary: TeamValidationSummary | null;
  optional_input_summary: OptionalInputSummary | null;
}

export interface TeamValidationSummary {
  team_validation_available: boolean;
  upload_id: string | null;
  row_count: number;
  column_count: number;
  columns: string[];
  application_code_column: string | null;
  rows_with_application_code: number;
  rows_missing_application_code: number;
  unmatched_team_validation_records: number;
  cmdb_applications_missing_team_validation_record: number;
  yes_no_column: string | null;
  invalid_yes_no_value_count: number;
}

export interface OptionalInputSummary {
  confluence_available: boolean;
  confluence_file_count: number;
  team_validation_available: boolean;
  team_validation_upload_id: string | null;
  cloudwatch_available: boolean;
  cloudwatch_upload_id: string | null;
  source_of_truth_inputs_used: string[];
}

export interface ValidationDetailRow {
  internal_row_number: number;
  application_key: string;
  application_code: string | null;
  application_name: string;
  completeness_percentage: number;
  missing_mandatory_fields: string[];
  evidence_type: string;
  source_of_truth_label: string;
  reliability_label: string;
  missing_data_warnings: string[];
  source_data: Record<string, unknown>;
}

export interface ValidationDetailsResponse {
  job_id: string;
  upload_id: string;
  page: number;
  page_size: number;
  total_records: number;
  total_pages: number;
  records: ValidationDetailRow[];
}

export interface DuplicateValue {
  value: string;
  row_numbers: number[];
}

export interface ValidationDuplicatesResponse {
  job_id: string;
  upload_id: string;
  duplicate_application_code_group_count: number;
  duplicate_application_id_group_count: number;
  duplicate_application_name_group_count: number;
  duplicate_application_codes: DuplicateValue[];
  duplicate_application_ids: DuplicateValue[];
  duplicate_application_names: DuplicateValue[];
}

export interface DashboardCardResult {
  key: string;
  label: string;
  value: string | number | null;
  severity: "info" | "success" | "warning" | "critical";
  description: string;
}

export interface DashboardMetricsResponse {
  status: string;
  module_name: "dashboard_metrics";
  job_id: string;
  upload_id: string;
  analysis_status: "completed" | "completed_with_warnings";
  overview: {
    total_applications: number;
    total_columns: number;
    source_of_truth_label: string;
    reliability_label: string;
    overall_completeness: number | null;
    warning_count: number;
  };
  cards: DashboardCardResult[];
  distributions: {
    portfolio: {
      counts: Record<string, number>;
      top_portfolios: Array<{ value: string; count: number }>;
      missing_portfolio_count: number;
    };
    [key: string]: unknown;
  };
  data_quality: {
    overall_completeness: number | null;
    matched_mandatory_columns: Array<{ configured_field: string; cmdb_column: string }> | null;
    missing_mandatory_columns: string[] | null;
    duplicate_application_code_group_count: number | null;
    duplicate_application_name_group_count: number | null;
    warning_count: number | null;
  };
  similarity_summary: {
    similar_pair_count: number | null;
    possible_duplicate_count: number | null;
    similar_pair_threshold: number | null;
    possible_duplicate_threshold: number | null;
    top_possible_duplicates: unknown[];
  };
  warnings: string[];
  generated_from: {
    cmdb_preview_available: boolean;
    validation_result_available: boolean;
    similarity_result_available: boolean;
  };
  summary_endpoint: string;
}

export interface PortfolioInsightsResponse {
  job_id: string;
  analysis_status: "completed" | "completed_with_warnings";
  summary: PortfolioInsightsSummary;
  executive_summary: PortfolioExecutiveSummary;
  module_status: PortfolioModuleStatus[];
  top_portfolio_scorecards: PortfolioScorecard[];
  risk_sample: PortfolioRisk[];
  action_item_sample: PortfolioActionItem[];
  warnings: string[];
  detail_endpoints: {
    risks_csv_endpoint: string;
    action_items_csv_endpoint: string;
    portfolio_scorecard_csv_endpoint: string;
  };
}

export interface PortfolioInsightsSummary {
  total_applications: number;
  total_portfolios: number;
  available_module_count: number;
  missing_module_count: number;
  total_risk_count: number;
  critical_risk_count: number;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  action_item_count: number;
  source_of_truth_label: string;
  reliability_label: string;
  warning_count: number;
}

export interface PortfolioExecutiveSummary {
  total_applications: number;
  cmdb_completeness_percent: number | null;
  source_of_truth_label: string;
  reliability_label: string;
  high_priority_risk_count: number;
  medium_priority_risk_count: number;
  low_priority_risk_count: number;
  possible_duplicate_count: number | null;
  technology_obsolete_indicator_count: number | null;
  explicit_integration_count: number | null;
  output_family_warning_count: number | null;
  unmapped_output_family_application_count: number | null;
  key_findings: string[];
  limitations: string[];
}

export interface PortfolioModuleStatus {
  module_name: string;
  status: "available" | "missing" | "error";
  analysis_status: string | null;
  source_result_available: boolean;
  key_metrics: Record<string, string | number | boolean | null>;
  warnings: string[];
}

export interface PortfolioScorecard {
  portfolio: string;
  application_count: number;
  completeness_percent: number | null;
  critical_application_count: number;
  high_business_criticality_count: number;
  possible_duplicate_count: number | null;
  obsolete_indicator_count: number | null;
  explicit_integration_count: number | null;
  unmapped_output_family_application_count: number | null;
  risk_count: number;
  highest_risk_severity: string | null;
  warnings: string[];
}

export interface PortfolioRisk {
  risk_id: string;
  risk_type: string;
  severity: "low" | "medium" | "high" | "critical";
  application_code: string | null;
  application_name: string | null;
  portfolio: string | null;
  evidence_module: string;
  evidence: string;
  recommended_action: string;
  confidence: "low" | "medium" | "high";
}

export interface PortfolioActionItem {
  action_id: string;
  priority: "low" | "medium" | "high" | "critical";
  action_type: string;
  application_code: string | null;
  application_name: string | null;
  portfolio: string | null;
  description: string;
  source_risk_id: string;
  owner_hint: string | null;
  evidence_module: string;
}

export interface SimilarityAnalysisRequest {
  selected_fields: string[];
  field_weights: Record<string, number>;
  dimension_fields: Record<string, string>;
  dimension_weights: Record<string, number>;
}

export interface SimilarityAnalysisResponse {
  status: string;
  module_name: "similarity";
  analysis_status: "completed" | "completed_with_warnings";
  summary: {
    total_applications_analyzed: number;
    total_candidate_pairs_evaluated: number;
    analysis_elapsed_seconds: number;
    similar_pair_count: number;
    possible_duplicate_count: number;
    similar_pair_threshold: number;
    possible_duplicate_threshold: number;
    source_of_truth_label: string;
    reliability_label: string;
    warning_count: number;
  };
  selected_fields_used: string[];
  field_weights_used: Record<string, number>;
  unsupported_fields: string[];
  rules_config: {
    selected_fields_used: string[];
    field_weights_used: Record<string, number>;
    dimension_fields_used: Record<string, string>;
    [key: string]: unknown;
  };
  warnings: string[];
}

export interface SimilaritySummaryResponse {
  analysis_status: "completed" | "completed_with_warnings";
  summary: SimilarityAnalysisResponse["summary"];
  warnings: string[];
}

export interface SimilarApplicationResult {
  application_code: string;
  application_name: string;
  similarity_score: number;
  possible_duplicate: boolean;
  evidence: string[];
  matched_fields: string[];
  component_scores: Record<string, number | null>;
  component_details: Record<string, {
    score: number | null;
    comparable: boolean;
    reason: string;
    evidence: string[];
  }>;
  similarity_reason: string;
}

export interface SimilarAppsGroup {
  application_code: string;
  application_name: string;
  similar_applications: SimilarApplicationResult[];
  highest_similarity_score: number | null;
  possible_duplicate_count: number;
  warning_count: number;
}

export interface SimilarityAppsResponse {
  per_application_limit: number;
  applications: SimilarAppsGroup[];
}

export interface SimilarityRulesResponse {
  rules_config: {
    selected_fields_used: string[];
    field_weights_used: Record<string, number>;
    dimension_fields_used: Record<string, string>;
  };
  applications: HeatmapApplication[];
  portfolio_options: string[];
}

export interface HeatmapApplication {
  application_key: string;
  application_code: string;
  application_name: string;
  portfolio: string;
  strongest_similarity_score: number | null;
}

export interface HeatmapCell {
  anchor_application_key: string;
  anchor_application_code: string;
  anchor_application_name: string;
  candidate_application_key: string;
  candidate_application_code: string;
  candidate_application_name: string;
  candidate_portfolio: string;
  similarity_score: number;
  possible_duplicate: boolean;
}

export interface SimilarityHeatmapResponse {
  limit: number;
  matched_anchor_count: number;
  candidate_count: number;
  no_comparable_data: boolean;
  portfolio_options: string[];
  anchor_applications: HeatmapApplication[];
  candidate_applications: HeatmapApplication[];
  matrix: HeatmapCell[];
  warnings: string[];
  score_range: string;
  score_range_note: string;
}

export interface SimilarityCluster {
  cluster: string;
  application_count: number;
  applications: HeatmapApplication[];
  average_similarity: number;
  common_cluster_function: string;
  evidence_used_for_analysis: string;
  cluster_reason: string;
  comparable_dimension_count: number;
  average_calculation: string;
}

export interface SimilarityClustersResponse {
  clusters: SimilarityCluster[];
  warnings: string[];
}

export interface RedundancyAlert {
  application_code_a: string;
  application_name_a: string;
  application_code_b: string;
  application_name_b: string;
  application_key_a: string;
  application_key_b: string;
  portfolio_a: string;
  portfolio_b: string;
  similarity_score: number;
  evidence: string[];
  matched_fields: string[];
  recommendation: string;
  redundancy_reason: string;
  component_details: SimilarApplicationResult["component_details"];
}

export interface SimilarityAlertsResponse {
  total_alert_count: number;
  alerts: RedundancyAlert[];
  warnings: string[];
}

export type TechnologyPageSize = 25 | 50 | 100 | 200 | "all";

export interface TechnologyOptionApplication {
  application_code: string | null;
  application_name: string;
  portfolio: string | null;
}

export interface TechnologyOptionsResponse {
  dimensions: Array<{ key: string; label: string }>;
  portfolios: string[];
  business_criticalities: string[];
  applications: TechnologyOptionApplication[];
  integration_types: string[];
  confidence_options: Array<"high" | "medium" | "low">;
  indicator_options: string[];
}

export interface TechnologyCluster {
  cluster_key: string;
  label: string;
  technology_type: string;
  application_count: number;
  risky_application_count: number;
  lifecycle_status: string;
  shortcomings: string[];
  applications: Array<{
    application_code: string | null;
    application_name: string;
    portfolio: string | null;
    business_criticality: string | null;
  }>;
  concern_evidence: Array<{
    application_code: string | null;
    application_name: string;
    source_field: string;
    evidence_value: string;
    reason: string;
  }>;
  cluster_reason: string;
}

export interface TechnologyClustersResponse {
  limit: number;
  portfolio: string | null;
  scope_application_count: number;
  total_cluster_count: number;
  clusters: TechnologyCluster[];
  warnings: string[];
}

export interface TechnologyLandscapeResponse {
  dimension: string;
  dimension_label: string;
  groupings: Array<{ label: string; application_count: number }>;
  portfolio_groupings: Array<{ portfolio: string; technology_value: string; application_count: number }>;
  selected_technology_value: string | null;
  total_application_count: number;
  page: number;
  page_size: TechnologyPageSize;
  applications: Array<{
    application_name: string;
    application_code: string | null;
    portfolio: string | null;
    business_criticality: string | null;
    technology_dimension: string;
    technology_value: string;
  }>;
}

export interface TechnologyIntegration {
  source_application_code: string | null;
  source_application_name: string;
  target_application_code: string | null;
  target_application_name: string | null;
  integration_type: string;
  evidence_field: string;
  evidence_value: string;
  confidence: "low" | "medium" | "high";
  warning: string | null;
  direction: "incoming" | "outgoing" | "unknown" | "directed";
}

export interface TechnologyIntegrationsResponse {
  limit: number;
  total_integration_count: number;
  integration_data_available: boolean;
  integrations: TechnologyIntegration[];
  warnings: string[];
}

export interface IntegrationNeighborhoodResponse {
  selected_application: TechnologyGraphNode;
  total_integration_count: number;
  page: number;
  page_size: TechnologyPageSize;
  integrations: TechnologyIntegration[];
  nodes: TechnologyGraphNode[];
  edges: Array<{
    source_application_code: string;
    target_application_code: string;
    integration_type: string;
    confidence: "low" | "medium" | "high";
    direction: "incoming" | "outgoing" | "unknown" | "directed";
    evidence_field: string;
  }>;
  graph_truncated: boolean;
  graph_edge_limit: number;
  portfolio_dependencies: PortfolioDependency[];
  integration_hubs: IntegrationHub[];
}

export interface TechnologyGraphNode {
  application_code: string;
  application_name: string;
  portfolio: string | null;
  business_criticality: string | null;
  anchor: boolean;
}

export interface PortfolioDependency {
  source_portfolio: string;
  target_portfolio: string;
  integration_count: number;
}

export interface IntegrationHub {
  application_name: string;
  application_code: string | null;
  portfolio: string | null;
  business_criticality: string | null;
  total_connections: number;
  incoming_connections: number;
  outgoing_related_connections: number;
}

export interface TechnologyInventoryResponse {
  total_application_count: number;
  filtered_application_count: number;
  page: number;
  page_size: TechnologyPageSize;
  applications: Array<{
    application_name: string;
    application_code: string | null;
    portfolio: string | null;
    business_criticality: string | null;
    hosting_type: string | null;
    hosting_provider: string | null;
    technology_stack: string | null;
    database_technology: string | null;
    integration_count: number;
    incoming_integration_count: number;
    outgoing_related_integration_count: number;
    integration_types: string[];
    potential_legacy_indicator: boolean;
  }>;
}

export interface ObsoleteTechnologyResponse {
  obsolete_indicator_count: number;
  page: number;
  page_size: TechnologyPageSize;
  indicators: Array<{
    application_code: string | null;
    application_name: string;
    portfolio: string | null;
    business_criticality: string | null;
    field: string;
    value: string;
    indicator: string;
    reason: string;
    severity: "info" | "warning" | "critical";
  }>;
  warnings: string[];
}
