from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.models.snow import HealthResponse


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        service=settings.app_name,
        environment=settings.app_environment,
        credentials_configured=settings.credentials_configured,
        processed_data_available=settings.processed_geojson.is_file(),
    )
