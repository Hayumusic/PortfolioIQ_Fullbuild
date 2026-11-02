from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import AppServices
from app.api.routes_analysis import router as analysis_router
from app.api.routes_health import router as health_router
from app.api.routes_uploads import router as uploads_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.analysis_service import AnalysisService
from app.services.cmdb_parser_service import CMDBParseError, CMDBParserService
from app.services.cmdb_service import (
    CMDBNotUploadedError,
    CMDBService,
    CMDBValidationResultNotFoundError,
)
from app.services.cmdb_similarity_service import (
    CMDBSimilarityService,
    SimilarityPrerequisiteError,
    SimilarityResultNotFoundError,
)
from app.services.cmdb_validation_service import CMDBValidationService
from app.services.dashboard_metrics_service import (
    DashboardMetricsPrerequisiteError,
    DashboardMetricsResultNotFoundError,
    DashboardMetricsService,
)
from app.services.file_service import FileService, UploadValidationError
from app.services.job_service import JobNotFoundError, JobService
from app.services.mandatory_field_config_service import (
    MandatoryFieldConfigError,
    MandatoryFieldConfigService,
)
from app.services.openai_service import OpenAIService
from app.services.output_family_analysis_service import (
    OutputFamilyAnalysisPrerequisiteError,
    OutputFamilyAnalysisResultNotFoundError,
    OutputFamilyAnalysisService,
    OutputFamilyNotFoundError,
)
from app.services.portfolio_insights_service import (
    PortfolioInsightsApplicationNotFoundError,
    PortfolioInsightsPrerequisiteError,
    PortfolioInsightsResultNotFoundError,
    PortfolioInsightsService,
)
from app.services.result_helpers import InvalidLimitError
from app.services.team_validation_service import TeamValidationService
from app.services.technology_analysis_service import (
    TechnologyAnalysisPrerequisiteError,
    TechnologyAnalysisResultNotFoundError,
    TechnologyAnalysisService,
)
from app.services.upload_config_service import UploadConfigParseError, UploadConfigService
from app.storage.factory import create_storage_provider


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    storage = create_storage_provider(app_settings)
    job_service = JobService(storage)
    openai_service = OpenAIService(
        api_key=app_settings.openai_api_key,
        model=app_settings.openai_model,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        file_service = FileService(
            storage=storage,
            job_service=job_service,
            max_upload_bytes=app_settings.max_upload_bytes,
        )
        similarity_service = CMDBSimilarityService(storage, job_service)
        dashboard_metrics_service = DashboardMetricsService(storage, job_service)
        technology_analysis_service = TechnologyAnalysisService(storage, job_service)
        config_service = MandatoryFieldConfigService(storage)
        upload_config_service = UploadConfigService(
            storage=storage,
            job_service=job_service,
            file_service=file_service,
            mandatory_config_service=config_service,
        )
        output_family_analysis_service = OutputFamilyAnalysisService(
            storage, job_service, upload_config_service
        )
        portfolio_insights_service = PortfolioInsightsService(storage, job_service)
        analysis_service = AnalysisService(
            job_service=job_service,
            openai_service=openai_service,
            storage=storage,
            settings=app_settings,
            similarity_service=similarity_service,
            dashboard_metrics_service=dashboard_metrics_service,
            technology_analysis_service=technology_analysis_service,
            output_family_analysis_service=output_family_analysis_service,
            portfolio_insights_service=portfolio_insights_service,
        )
        team_validation_service = TeamValidationService(
            storage=storage,
            job_service=job_service,
            file_service=file_service,
        )
        cmdb_service = CMDBService(
            storage=storage,
            job_service=job_service,
            file_service=file_service,
            parser_service=CMDBParserService(app_settings.max_cmdb_rows),
            validation_service=CMDBValidationService(),
            config_service=config_service,
            team_validation_service=team_validation_service,
        )
        application.state.services = AppServices(
            settings=app_settings,
            job_service=job_service,
            file_service=file_service,
            analysis_service=analysis_service,
            cmdb_service=cmdb_service,
            similarity_service=similarity_service,
            dashboard_metrics_service=dashboard_metrics_service,
            technology_analysis_service=technology_analysis_service,
            output_family_analysis_service=output_family_analysis_service,
            portfolio_insights_service=portfolio_insights_service,
            mandatory_field_config_service=config_service,
            upload_config_service=upload_config_service,
        )
        yield

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description=(
            "Upload-based Portfolio IQ backend with deterministic CMDB validation, "
            "similarity analysis, dashboard metrics, technology/integration analysis, "
            "output-family analysis, and deterministic cross-module portfolio insights."
        ),
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(uploads_router, prefix=app_settings.api_prefix)
    application.include_router(analysis_router, prefix=app_settings.api_prefix)

    @application.exception_handler(JobNotFoundError)
    async def job_not_found_handler(request: Request, error: JobNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})

    @application.exception_handler(UploadValidationError)
    async def invalid_upload_handler(
        request: Request, error: UploadValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": str(error)},
        )

    async def cmdb_validation_error_handler(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": str(error)},
        )

    for error_type in (
        CMDBParseError,
        MandatoryFieldConfigError,
        CMDBNotUploadedError,
        UploadConfigParseError,
        SimilarityPrerequisiteError,
        DashboardMetricsPrerequisiteError,
        TechnologyAnalysisPrerequisiteError,
        OutputFamilyAnalysisPrerequisiteError,
        PortfolioInsightsPrerequisiteError,
        InvalidLimitError,
    ):
        application.add_exception_handler(error_type, cmdb_validation_error_handler)

    async def result_not_found_handler(
        request: Request, error: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(error)},
        )

    for error_type in (
        CMDBValidationResultNotFoundError,
        SimilarityResultNotFoundError,
        DashboardMetricsResultNotFoundError,
        TechnologyAnalysisResultNotFoundError,
        OutputFamilyAnalysisResultNotFoundError,
        OutputFamilyNotFoundError,
        PortfolioInsightsResultNotFoundError,
        PortfolioInsightsApplicationNotFoundError,
    ):
        application.add_exception_handler(error_type, result_not_found_handler)

    return application


app = create_app()
