from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.analysis_service import AnalysisService
from app.services.cmdb_service import CMDBService
from app.services.cmdb_similarity_service import CMDBSimilarityService
from app.services.dashboard_metrics_service import DashboardMetricsService
from app.services.file_service import FileService
from app.services.job_service import JobService
from app.services.mandatory_field_config_service import MandatoryFieldConfigService
from app.services.output_family_analysis_service import OutputFamilyAnalysisService
from app.services.portfolio_insights_service import PortfolioInsightsService
from app.services.technology_analysis_service import TechnologyAnalysisService
from app.services.upload_config_service import UploadConfigService


@dataclass(frozen=True, slots=True)
class AppServices:
    settings: Settings
    job_service: JobService
    file_service: FileService
    analysis_service: AnalysisService
    cmdb_service: CMDBService
    similarity_service: CMDBSimilarityService
    dashboard_metrics_service: DashboardMetricsService
    technology_analysis_service: TechnologyAnalysisService
    output_family_analysis_service: OutputFamilyAnalysisService
    portfolio_insights_service: PortfolioInsightsService
    mandatory_field_config_service: MandatoryFieldConfigService
    upload_config_service: UploadConfigService


def get_app_services(request: Request) -> AppServices:
    return request.app.state.services


def get_settings(services: Annotated[AppServices, Depends(get_app_services)]) -> Settings:
    return services.settings


def get_job_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> JobService:
    return services.job_service


def get_file_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> FileService:
    return services.file_service


def get_analysis_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> AnalysisService:
    return services.analysis_service


def get_cmdb_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> CMDBService:
    return services.cmdb_service


def get_similarity_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> CMDBSimilarityService:
    return services.similarity_service


def get_dashboard_metrics_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> DashboardMetricsService:
    return services.dashboard_metrics_service


def get_technology_analysis_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TechnologyAnalysisService:
    return services.technology_analysis_service


def get_output_family_analysis_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> OutputFamilyAnalysisService:
    return services.output_family_analysis_service


def get_portfolio_insights_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> PortfolioInsightsService:
    return services.portfolio_insights_service


def get_mandatory_field_config_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> MandatoryFieldConfigService:
    return services.mandatory_field_config_service


def get_upload_config_service(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> UploadConfigService:
    return services.upload_config_service


SettingsDependency = Annotated[Settings, Depends(get_settings)]
JobServiceDependency = Annotated[JobService, Depends(get_job_service)]
FileServiceDependency = Annotated[FileService, Depends(get_file_service)]
AnalysisServiceDependency = Annotated[AnalysisService, Depends(get_analysis_service)]
CMDBServiceDependency = Annotated[CMDBService, Depends(get_cmdb_service)]
SimilarityServiceDependency = Annotated[
    CMDBSimilarityService, Depends(get_similarity_service)
]
DashboardMetricsServiceDependency = Annotated[
    DashboardMetricsService, Depends(get_dashboard_metrics_service)
]
TechnologyAnalysisServiceDependency = Annotated[
    TechnologyAnalysisService, Depends(get_technology_analysis_service)
]
OutputFamilyAnalysisServiceDependency = Annotated[
    OutputFamilyAnalysisService, Depends(get_output_family_analysis_service)
]
PortfolioInsightsServiceDependency = Annotated[
    PortfolioInsightsService, Depends(get_portfolio_insights_service)
]
MandatoryFieldConfigServiceDependency = Annotated[
    MandatoryFieldConfigService, Depends(get_mandatory_field_config_service)
]
UploadConfigServiceDependency = Annotated[
    UploadConfigService, Depends(get_upload_config_service)
]
