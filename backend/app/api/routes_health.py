from fastapi import APIRouter

from app.api.dependencies import SettingsDependency
from app.schemas.common import HealthResponse, ResponseStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDependency) -> HealthResponse:
    return HealthResponse(
        status=ResponseStatus.HEALTHY,
        service=settings.app_name,
        environment=settings.app_env,
    )
