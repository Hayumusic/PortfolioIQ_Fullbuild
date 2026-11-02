from typing import Annotated

from fastapi import APIRouter, Body, Query, Response

from app.api.dependencies import (
    AnalysisServiceDependency,
    CMDBServiceDependency,
    DashboardMetricsServiceDependency,
    OutputFamilyAnalysisServiceDependency,
    PortfolioInsightsServiceDependency,
    SimilarityServiceDependency,
    TechnologyAnalysisServiceDependency,
)
from app.domain.models import AnalysisInput, AnalysisResult
from app.schemas.analysis import AnalysisRequest, AnalysisResponse
from app.schemas.cmdb import (
    CMDBValidationDetailsResponse,
    CMDBValidationDuplicatesResponse,
    CMDBValidationOverviewResponse,
)
from app.schemas.common import ResponseStatus
from app.schemas.dashboard_metrics import (
    DashboardMetricsRequest,
    DashboardMetricsResponse,
)
from app.schemas.output_families import (
    ApplicationOutputMappingResponse,
    OutputFamiliesResponse,
    OutputFamilyAnalysisRequest,
    OutputFamilyAnalysisResponse,
    OutputFamilyAnalysisViewResponse,
    OutputFamilyApplicationMatrixResponse,
    OutputFamilyDetailResponse,
    OutputFamilyGapsResponse,
    OutputFamilyMembersResponse,
    OutputFamilySummaryResponse,
)
from app.schemas.portfolio_insights import (
    ActionItemsResponse,
    ApplicationInsightResponse,
    ExecutiveSummaryResponse,
    ModuleStatusResponse,
    PortfolioInsightsRequest,
    PortfolioInsightsResponse,
    PortfolioInsightsSummaryResponse,
    PortfolioScorecardResponse,
    RiskRegisterResponse,
)
from app.schemas.similarity import (
    SimilarityAnalysisRequest,
    SimilarityAlertsResponse,
    SimilarityAppsResponse,
    SimilarityComparisonResponse,
    SimilarityClustersResponse,
    SimilarityHeatmapResponse,
    SimilarityOverviewResponse,
    SimilarityPairsResponse,
    SimilarityRulesResponse,
    SimilaritySummaryResponse,
)
from app.schemas.technology import (
    ApplicationMapResponse,
    IntegrationNeighborhoodResponse,
    ObsoleteTechnologyResponse,
    PortfolioMapResponse,
    TechnologyAnalysisRequest,
    TechnologyAnalysisResponse,
    TechnologyClustersResponse,
    TechnologyIntegrationsResponse,
    TechnologyInventoryResponse,
    TechnologyLandscapeResponse,
    TechnologyOptionsResponse,
    TechnologySummaryResponse,
)

router = APIRouter(prefix="/jobs/{job_id}/analysis", tags=["analysis"])


def _to_response(result: AnalysisResult) -> AnalysisResponse:
    return AnalysisResponse(
        status=ResponseStatus.PLACEHOLDER,
        module_name=result.module_name,
        job_id=result.job_id,
        message=result.message,
        next_implementation_note=result.next_implementation_note,
        result=result.result,
    )


async def _run(
    module_name: str,
    job_id: str,
    payload: AnalysisRequest,
    analysis_service: AnalysisServiceDependency,
) -> AnalysisResponse:
    result = await analysis_service.run_module(
        module_name,
        job_id,
        AnalysisInput(force=payload.force, options=payload.options),
    )
    return _to_response(result)


@router.post("/validation", response_model=CMDBValidationOverviewResponse)
def run_validation(
    job_id: str,
    cmdb_service: CMDBServiceDependency,
    payload: Annotated[AnalysisRequest | None, Body()] = None,
) -> CMDBValidationOverviewResponse:
    del payload  # Reserved for force/options compatibility with the existing route.
    return CMDBValidationOverviewResponse.model_validate(
        cmdb_service.run_validation_overview(job_id)
    )


@router.get("/validation", response_model=CMDBValidationOverviewResponse)
def get_validation(
    job_id: str, cmdb_service: CMDBServiceDependency
) -> CMDBValidationOverviewResponse:
    return CMDBValidationOverviewResponse.model_validate(
        cmdb_service.get_validation_overview(job_id)
    )


@router.get("/validation/summary", response_model=CMDBValidationOverviewResponse)
def get_validation_summary(
    job_id: str, cmdb_service: CMDBServiceDependency
) -> CMDBValidationOverviewResponse:
    return CMDBValidationOverviewResponse.model_validate(
        cmdb_service.get_validation_summary(job_id)
    )


@router.get("/validation/details", response_model=CMDBValidationDetailsResponse)
def get_validation_details(
    job_id: str,
    cmdb_service: CMDBServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CMDBValidationDetailsResponse:
    return CMDBValidationDetailsResponse.model_validate(
        cmdb_service.get_validation_details(job_id, page, page_size)
    )


@router.get("/validation/duplicates", response_model=CMDBValidationDuplicatesResponse)
def get_validation_duplicates(
    job_id: str, cmdb_service: CMDBServiceDependency
) -> CMDBValidationDuplicatesResponse:
    return CMDBValidationDuplicatesResponse.model_validate(
        cmdb_service.get_validation_duplicates(job_id)
    )


@router.get("/validation/completeness.csv", response_class=Response)
def get_validation_completeness_csv(
    job_id: str, cmdb_service: CMDBServiceDependency
) -> Response:
    return Response(
        content=cmdb_service.get_validation_completeness_csv(job_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job_id}-cmdb-completeness.csv"'
            )
        },
    )


@router.post("/similarity", response_model=SimilarityOverviewResponse)
async def run_similarity(
    job_id: str,
    analysis_service: AnalysisServiceDependency,
    similarity_service: SimilarityServiceDependency,
    payload: Annotated[SimilarityAnalysisRequest | None, Body()] = None,
) -> SimilarityOverviewResponse:
    request = payload or SimilarityAnalysisRequest()
    await analysis_service.run_module(
        "similarity", job_id, AnalysisInput(options=request.model_dump())
    )
    return SimilarityOverviewResponse.model_validate(
        similarity_service.get_overview(job_id)
    )


@router.get("/similarity/summary", response_model=SimilaritySummaryResponse)
def get_similarity_summary(
    job_id: str, similarity_service: SimilarityServiceDependency
) -> SimilaritySummaryResponse:
    return SimilaritySummaryResponse.model_validate(
        similarity_service.get_summary(job_id)
    )


@router.get("/similarity/pairs", response_model=SimilarityPairsResponse)
def get_similarity_pairs(
    job_id: str,
    similarity_service: SimilarityServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SimilarityPairsResponse:
    return SimilarityPairsResponse.model_validate(
        similarity_service.get_pairs(job_id, page, page_size)
    )


@router.get("/similarity/apps", response_model=SimilarityAppsResponse)
def get_similarity_apps(
    job_id: str,
    similarity_service: SimilarityServiceDependency,
    application_key: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    portfolio: str = "",
    excluded_application_keys: Annotated[list[str] | None, Query()] = None,
) -> SimilarityAppsResponse:
    return SimilarityAppsResponse.model_validate(
        similarity_service.get_apps(
            job_id, application_key, limit, portfolio, excluded_application_keys or []
        )
    )


@router.get("/similarity/rules", response_model=SimilarityRulesResponse)
def get_similarity_rules(
    job_id: str, similarity_service: SimilarityServiceDependency
) -> SimilarityRulesResponse:
    return SimilarityRulesResponse.model_validate(
        similarity_service.get_rules(job_id)
    )


@router.get("/similarity/heatmap", response_model=SimilarityHeatmapResponse)
def get_similarity_heatmap(
    job_id: str,
    similarity_service: SimilarityServiceDependency,
    limit: Annotated[int, Query(ge=1)] = 50,
    search: str = "",
    portfolio: str = "",
    application_key: str = "",
    score_range: str = "20-100",
    excluded_application_keys: Annotated[list[str] | None, Query()] = None,
) -> SimilarityHeatmapResponse:
    return SimilarityHeatmapResponse.model_validate(
        similarity_service.get_heatmap(
            job_id,
            limit,
            search,
            portfolio,
            application_key,
            score_range,
            excluded_application_keys or [],
        )
    )


@router.get("/similarity/clusters", response_model=SimilarityClustersResponse)
def get_similarity_clusters(
    job_id: str, similarity_service: SimilarityServiceDependency
) -> SimilarityClustersResponse:
    return SimilarityClustersResponse.model_validate(
        similarity_service.get_clusters(job_id)
    )


@router.get("/similarity/alerts", response_model=SimilarityAlertsResponse)
def get_similarity_alerts(
    job_id: str,
    similarity_service: SimilarityServiceDependency,
    limit: Annotated[int, Query(ge=1)] = 25,
    score_range: str = "20-100",
    portfolio: str = "",
    excluded_application_keys: Annotated[list[str] | None, Query()] = None,
) -> SimilarityAlertsResponse:
    return SimilarityAlertsResponse.model_validate(
        similarity_service.get_alerts(
            job_id, limit, score_range, portfolio, excluded_application_keys or []
        )
    )


@router.get("/similarity/compare", response_model=SimilarityComparisonResponse)
def compare_similarity_applications(
    job_id: str,
    similarity_service: SimilarityServiceDependency,
    application_code_a: str,
    application_code_b: str,
) -> SimilarityComparisonResponse:
    return SimilarityComparisonResponse.model_validate(
        similarity_service.compare(
            job_id, application_code_a, application_code_b
        )
    )


@router.get("/similarity/results.csv", response_class=Response)
def get_similarity_results_csv(
    job_id: str, similarity_service: SimilarityServiceDependency
) -> Response:
    return Response(
        content=similarity_service.get_results_csv(job_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job_id}-similarity-results.csv"'
            )
        },
    )


@router.post("/dashboard-metrics", response_model=DashboardMetricsResponse)
async def run_dashboard_metrics(
    job_id: str,
    analysis_service: AnalysisServiceDependency,
    payload: Annotated[DashboardMetricsRequest | None, Body()] = None,
) -> DashboardMetricsResponse:
    request = payload or DashboardMetricsRequest()
    result = await analysis_service.run_module(
        "dashboard_metrics", job_id, AnalysisInput(options=request.model_dump())
    )
    return DashboardMetricsResponse.model_validate(result.result)


@router.get(
    "/dashboard-metrics/summary", response_model=DashboardMetricsResponse
)
def get_dashboard_metrics_summary(
    job_id: str,
    dashboard_service: DashboardMetricsServiceDependency,
) -> DashboardMetricsResponse:
    return DashboardMetricsResponse.model_validate(
        dashboard_service.get_summary(job_id)
    )


@router.post("/technology", response_model=TechnologyAnalysisResponse)
async def run_technology_analysis(
    job_id: str,
    analysis_service: AnalysisServiceDependency,
    technology_service: TechnologyAnalysisServiceDependency,
    payload: Annotated[TechnologyAnalysisRequest | None, Body()] = None,
) -> TechnologyAnalysisResponse:
    request = payload or TechnologyAnalysisRequest()
    await analysis_service.run_module(
        "technology", job_id, AnalysisInput(options=request.model_dump())
    )
    return TechnologyAnalysisResponse.model_validate(
        technology_service.get_overview(job_id)
    )


@router.get("/technology/summary", response_model=TechnologySummaryResponse)
def get_technology_summary(
    job_id: str, technology_service: TechnologyAnalysisServiceDependency
) -> TechnologySummaryResponse:
    return TechnologySummaryResponse.model_validate(
        technology_service.get_summary(job_id)
    )


@router.get("/technology/options", response_model=TechnologyOptionsResponse)
def get_technology_options(
    job_id: str, technology_service: TechnologyAnalysisServiceDependency
) -> TechnologyOptionsResponse:
    return TechnologyOptionsResponse.model_validate(technology_service.get_options(job_id))


@router.get("/technology/inventory", response_model=TechnologyInventoryResponse)
def get_technology_inventory(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    search: str = "",
    portfolio: str = "",
    business_criticality: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: str = "50",
) -> TechnologyInventoryResponse:
    return TechnologyInventoryResponse.model_validate(
        technology_service.get_inventory(
            job_id,
            search,
            portfolio,
            business_criticality,
            page,
            page_size,
        )
    )


@router.get("/technology/landscape", response_model=TechnologyLandscapeResponse)
def get_technology_landscape(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    dimension: str,
    portfolio: str = "",
    business_criticality: str = "",
    search: str = "",
    technology_value: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: str = "25",
) -> TechnologyLandscapeResponse:
    return TechnologyLandscapeResponse.model_validate(
        technology_service.get_landscape(
            job_id,
            dimension,
            portfolio,
            business_criticality,
            search,
            technology_value,
            page,
            page_size,
        )
    )


@router.get(
    "/technology/integration-neighborhood",
    response_model=IntegrationNeighborhoodResponse,
)
def get_technology_integration_neighborhood(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    application_code: str,
    portfolio: str = "",
    integration_type: str = "",
    confidence: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: str = "25",
) -> IntegrationNeighborhoodResponse:
    return IntegrationNeighborhoodResponse.model_validate(
        technology_service.get_integration_neighborhood(
            job_id,
            application_code,
            portfolio,
            integration_type,
            confidence,
            page,
            page_size,
        )
    )


@router.get("/technology/clusters", response_model=TechnologyClustersResponse)
def get_technology_clusters(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 500.")] = 50,
    portfolio: str = "",
) -> TechnologyClustersResponse:
    return TechnologyClustersResponse.model_validate(
        technology_service.get_clusters(job_id, limit, portfolio)
    )


@router.get(
    "/technology/integrations", response_model=TechnologyIntegrationsResponse
)
def get_technology_integrations(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 1000.")] = 100,
) -> TechnologyIntegrationsResponse:
    return TechnologyIntegrationsResponse.model_validate(
        technology_service.get_integrations(job_id, limit)
    )


@router.get("/technology/application-map", response_model=ApplicationMapResponse)
def get_technology_application_map(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 1000.")] = 100,
) -> ApplicationMapResponse:
    return ApplicationMapResponse.model_validate(
        technology_service.get_application_map(job_id, limit)
    )


@router.get("/technology/portfolio-map", response_model=PortfolioMapResponse)
def get_technology_portfolio_map(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 1000.")] = 100,
) -> PortfolioMapResponse:
    return PortfolioMapResponse.model_validate(
        technology_service.get_portfolio_map(job_id, limit)
    )


@router.get("/technology/obsolete", response_model=ObsoleteTechnologyResponse)
def get_obsolete_technology(
    job_id: str,
    technology_service: TechnologyAnalysisServiceDependency,
    portfolio: str = "",
    indicator: str = "",
    business_criticality: str = "",
    search: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: str = "25",
) -> ObsoleteTechnologyResponse:
    return ObsoleteTechnologyResponse.model_validate(
        technology_service.get_obsolete(
            job_id,
            portfolio,
            indicator,
            business_criticality,
            search,
            page,
            page_size,
        )
    )


@router.get("/technology/clusters.csv", response_class=Response)
def get_technology_clusters_csv(
    job_id: str, technology_service: TechnologyAnalysisServiceDependency
) -> Response:
    return Response(
        content=technology_service.get_clusters_csv(job_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job_id}-technology-clusters.csv"'
            )
        },
    )


@router.get("/technology/integrations.csv", response_class=Response)
def get_technology_integrations_csv(
    job_id: str, technology_service: TechnologyAnalysisServiceDependency
) -> Response:
    return Response(
        content=technology_service.get_integrations_csv(job_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job_id}-technology-integrations.csv"'
            )
        },
    )


@router.post("/output-families", response_model=OutputFamilyAnalysisResponse)
async def run_output_family_analysis(
    job_id: str,
    analysis_service: AnalysisServiceDependency,
    output_family_service: OutputFamilyAnalysisServiceDependency,
    payload: Annotated[OutputFamilyAnalysisRequest | None, Body()] = None,
) -> OutputFamilyAnalysisResponse:
    request = payload or OutputFamilyAnalysisRequest()
    await analysis_service.run_module(
        "output_families", job_id, AnalysisInput(options=request.model_dump())
    )
    return OutputFamilyAnalysisResponse.model_validate(
        output_family_service.get_overview(job_id)
    )


@router.get(
    "/output-families/summary", response_model=OutputFamilySummaryResponse
)
def get_output_family_summary(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> OutputFamilySummaryResponse:
    return OutputFamilySummaryResponse.model_validate(
        output_family_service.get_summary(job_id)
    )


@router.get("/output-families/families", response_model=OutputFamiliesResponse)
def get_output_families(
    job_id: str,
    output_family_service: OutputFamilyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 500.")] = 50,
) -> OutputFamiliesResponse:
    return OutputFamiliesResponse.model_validate(
        output_family_service.get_families(job_id, limit)
    )


@router.get(
    "/output-families/families/{family_key}",
    response_model=OutputFamilyDetailResponse,
)
def get_output_family_detail(
    job_id: str,
    family_key: str,
    output_family_service: OutputFamilyAnalysisServiceDependency,
) -> OutputFamilyDetailResponse:
    return OutputFamilyDetailResponse.model_validate(
        output_family_service.get_family(job_id, family_key)
    )


@router.get(
    "/output-families/members", response_model=OutputFamilyMembersResponse
)
def get_output_family_members(
    job_id: str,
    output_family_service: OutputFamilyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 5000.")] = 200,
) -> OutputFamilyMembersResponse:
    return OutputFamilyMembersResponse.model_validate(
        output_family_service.get_members(job_id, limit)
    )


@router.get("/output-families/gaps", response_model=OutputFamilyGapsResponse)
def get_output_family_gaps(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> OutputFamilyGapsResponse:
    return OutputFamilyGapsResponse.model_validate(
        output_family_service.get_gaps(job_id)
    )


@router.get(
    "/output-families/application-matrix",
    response_model=OutputFamilyApplicationMatrixResponse,
)
def get_output_family_application_matrix(
    job_id: str,
    output_family_service: OutputFamilyAnalysisServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 5000.")] = 200,
) -> OutputFamilyApplicationMatrixResponse:
    return OutputFamilyApplicationMatrixResponse.model_validate(
        output_family_service.get_application_matrix(job_id, limit)
    )


@router.get(
    "/output-families/analysis-view",
    response_model=OutputFamilyAnalysisViewResponse,
)
def get_output_family_analysis_view(
    job_id: str,
    output_family_service: OutputFamilyAnalysisServiceDependency,
    portfolio: str = "",
    output_family: str = "",
    search: str = "",
) -> OutputFamilyAnalysisViewResponse:
    return OutputFamilyAnalysisViewResponse.model_validate(
        output_family_service.get_analysis_view(
            job_id,
            portfolio=portfolio,
            output_family=output_family,
            search=search,
        )
    )


@router.get(
    "/output-families/application-mapping",
    response_model=ApplicationOutputMappingResponse,
)
def get_application_output_mapping(
    job_id: str,
    output_family_service: OutputFamilyAnalysisServiceDependency,
    portfolio: str = "",
    output_family: str = "",
    confidence: Annotated[str, Query(pattern="^(|High|Medium|Low|Insufficient Evidence)$")] = "",
    classification_status: Annotated[
        str,
        Query(pattern="^(|Classified|Multiple Families|Insufficient Evidence)$"),
    ] = "",
    search: str = "",
    display_size: Annotated[str, Query(pattern="^(50|100|200|all)$")] = "50",
) -> ApplicationOutputMappingResponse:
    return ApplicationOutputMappingResponse.model_validate(
        output_family_service.get_application_mapping(
            job_id,
            portfolio=portfolio,
            output_family=output_family,
            confidence=confidence,
            classification_status=classification_status,
            search=search,
            display_size=display_size,
        )
    )


@router.get("/output-families/mvp")
def get_output_family_mvp_results(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> dict:
    return output_family_service.get_mvp_results(job_id)


@router.get("/output-families/export.xlsx", response_class=Response)
def export_output_family_workbook(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return Response(
        content=output_family_service.get_excel_export(job_id),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{job_id}-application-outputs.xlsx"'},
    )


def _output_family_csv_response(content: str, job_id: str, suffix: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job_id}-output-families-{suffix}.csv"'
            )
        },
    )


@router.get("/output-families/families.csv", response_class=Response)
def get_output_families_csv(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return _output_family_csv_response(
        output_family_service.get_families_csv(job_id), job_id, "families"
    )


@router.get("/output-families/members.csv", response_class=Response)
def get_output_family_members_csv(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return _output_family_csv_response(
        output_family_service.get_members_csv(job_id), job_id, "members"
    )


@router.get("/output-families/gaps.csv", response_class=Response)
def get_output_family_gaps_csv(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return _output_family_csv_response(
        output_family_service.get_gaps_csv(job_id), job_id, "gaps"
    )


@router.get("/output-families/output-details.csv", response_class=Response)
def get_output_details_csv(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return _output_family_csv_response(
        output_family_service.get_output_details_csv(job_id), job_id, "details"
    )


@router.get("/output-families/output-clusters.csv", response_class=Response)
def get_output_clusters_csv(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return _output_family_csv_response(
        output_family_service.get_output_clusters_csv(job_id), job_id, "clusters"
    )


@router.get("/output-families/output-alerts.csv", response_class=Response)
def get_output_alerts_csv(
    job_id: str, output_family_service: OutputFamilyAnalysisServiceDependency
) -> Response:
    return _output_family_csv_response(
        output_family_service.get_output_alerts_csv(job_id), job_id, "alerts"
    )


@router.post("/portfolio-insights", response_model=PortfolioInsightsResponse)
async def run_portfolio_insights(
    job_id: str,
    analysis_service: AnalysisServiceDependency,
    payload: Annotated[PortfolioInsightsRequest | None, Body()] = None,
) -> PortfolioInsightsResponse:
    request = payload or PortfolioInsightsRequest()
    result = await analysis_service.run_module(
        "portfolio_insights", job_id, AnalysisInput(options=request.model_dump())
    )
    return PortfolioInsightsResponse.model_validate(result.result)


@router.get(
    "/portfolio-insights/summary", response_model=PortfolioInsightsSummaryResponse
)
def get_portfolio_insights_summary(
    job_id: str, portfolio_insights_service: PortfolioInsightsServiceDependency
) -> PortfolioInsightsSummaryResponse:
    return PortfolioInsightsSummaryResponse.model_validate(
        portfolio_insights_service.get_summary(job_id)
    )


@router.get(
    "/portfolio-insights/executive-summary",
    response_model=ExecutiveSummaryResponse,
)
def get_portfolio_insights_executive_summary(
    job_id: str, portfolio_insights_service: PortfolioInsightsServiceDependency
) -> ExecutiveSummaryResponse:
    return ExecutiveSummaryResponse.model_validate(
        portfolio_insights_service.get_executive_summary(job_id)
    )


@router.get(
    "/portfolio-insights/module-status", response_model=ModuleStatusResponse
)
def get_portfolio_insights_module_status(
    job_id: str, portfolio_insights_service: PortfolioInsightsServiceDependency
) -> ModuleStatusResponse:
    return ModuleStatusResponse.model_validate(
        portfolio_insights_service.get_module_status(job_id)
    )


@router.get(
    "/portfolio-insights/portfolio-scorecard",
    response_model=PortfolioScorecardResponse,
)
def get_portfolio_insights_portfolio_scorecard(
    job_id: str,
    portfolio_insights_service: PortfolioInsightsServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 500.")] = 100,
) -> PortfolioScorecardResponse:
    return PortfolioScorecardResponse.model_validate(
        portfolio_insights_service.get_portfolio_scorecard(job_id, limit)
    )


@router.get("/portfolio-insights/risks", response_model=RiskRegisterResponse)
def get_portfolio_insights_risks(
    job_id: str,
    portfolio_insights_service: PortfolioInsightsServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 5000.")] = 100,
    include_low_severity: bool = True,
) -> RiskRegisterResponse:
    return RiskRegisterResponse.model_validate(
        portfolio_insights_service.get_risks(
            job_id, limit, include_low_severity
        )
    )


@router.get("/portfolio-insights/action-items", response_model=ActionItemsResponse)
def get_portfolio_insights_action_items(
    job_id: str,
    portfolio_insights_service: PortfolioInsightsServiceDependency,
    limit: Annotated[int, Query(ge=1, description="Capped at 5000.")] = 100,
) -> ActionItemsResponse:
    return ActionItemsResponse.model_validate(
        portfolio_insights_service.get_action_items(job_id, limit)
    )


@router.get(
    "/portfolio-insights/applications/{application_code}",
    response_model=ApplicationInsightResponse,
)
def get_portfolio_insights_application(
    job_id: str,
    application_code: str,
    portfolio_insights_service: PortfolioInsightsServiceDependency,
) -> ApplicationInsightResponse:
    return ApplicationInsightResponse.model_validate(
        portfolio_insights_service.get_application_insight(
            job_id, application_code
        )
    )


def _portfolio_insights_csv_response(
    content: str, job_id: str, suffix: str
) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job_id}-portfolio-insights-{suffix}.csv"'
            )
        },
    )


@router.get("/portfolio-insights/risks.csv", response_class=Response)
def get_portfolio_insights_risks_csv(
    job_id: str, portfolio_insights_service: PortfolioInsightsServiceDependency
) -> Response:
    return _portfolio_insights_csv_response(
        portfolio_insights_service.get_risks_csv(job_id), job_id, "risks"
    )


@router.get("/portfolio-insights/action-items.csv", response_class=Response)
def get_portfolio_insights_action_items_csv(
    job_id: str, portfolio_insights_service: PortfolioInsightsServiceDependency
) -> Response:
    return _portfolio_insights_csv_response(
        portfolio_insights_service.get_action_items_csv(job_id),
        job_id,
        "action-items",
    )


@router.get("/portfolio-insights/portfolio-scorecard.csv", response_class=Response)
def get_portfolio_insights_portfolio_scorecard_csv(
    job_id: str, portfolio_insights_service: PortfolioInsightsServiceDependency
) -> Response:
    return _portfolio_insights_csv_response(
        portfolio_insights_service.get_portfolio_scorecard_csv(job_id),
        job_id,
        "portfolio-scorecard",
    )


@router.post("/technology-integrations", response_model=AnalysisResponse)
async def run_technology_integrations(
    job_id: str, payload: AnalysisRequest, analysis_service: AnalysisServiceDependency
) -> AnalysisResponse:
    return await _run("technology-integrations", job_id, payload, analysis_service)


@router.post("/outputs", response_model=AnalysisResponse)
async def run_outputs(
    job_id: str, payload: AnalysisRequest, analysis_service: AnalysisServiceDependency
) -> AnalysisResponse:
    return await _run("outputs", job_id, payload, analysis_service)


@router.post("/uncertain-items", response_model=AnalysisResponse)
async def run_uncertain_items(
    job_id: str, payload: AnalysisRequest, analysis_service: AnalysisServiceDependency
) -> AnalysisResponse:
    return await _run("uncertain-items", job_id, payload, analysis_service)
