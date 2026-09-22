from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.models.snow import SnowDataStatus, SnowProduct
from app.services.snow_service import SnowService


router = APIRouter(prefix="/snow", tags=["snow"])


def snow_service(settings: Settings = Depends(get_settings)) -> SnowService:
    return SnowService(settings)


@router.get("/cells", response_class=JSONResponse)
def cells(
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    product: list[SnowProduct] | None = Query(default=None),
    service: SnowService = Depends(snow_service),
) -> JSONResponse:
    values = [west, south, east, north]
    if any(value is not None for value in values) and not all(value is not None for value in values):
        raise HTTPException(status_code=422, detail="west, south, east and north must be supplied together")
    bbox = [float(value) for value in values] if all(value is not None for value in values) else None
    products = {value.upper() for value in product} if product else None
    return JSONResponse(service.feature_collection(bbox=bbox, products=products))


@router.get("/status", response_model=SnowDataStatus)
def status(service: SnowService = Depends(snow_service)) -> SnowDataStatus:
    return SnowDataStatus(**service.status())
