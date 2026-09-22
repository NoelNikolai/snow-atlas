from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.services.area_jobs import area_jobs
from app.services.snow_service import SnowMode, SnowService


router = APIRouter(prefix="/snow", tags=["snow"])


def snow_service(settings: Settings = Depends(get_settings)) -> SnowService:
    return SnowService(settings)


class AreaRequest(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


@router.get("/tiles/{mode}/{z}/{x}/{y}.png", response_class=Response)
def tile(
    mode: SnowMode,
    z: int = Path(ge=0, le=18),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
    clouds: bool = True,
    service: SnowService = Depends(snow_service),
) -> Response:
    if x >= 2**z or y >= 2**z:
        raise HTTPException(status_code=404, detail="Tile outside the grid")
    return Response(
        content=service.tile(mode, z, x, y, clouds),
        media_type="image/png",
        # Tile URLs carry the data version, so a new import never serves stale tiles.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/summary")
def summary(
    west: float = Query(ge=-180, le=180),
    south: float = Query(ge=-85, le=85),
    east: float = Query(ge=-180, le=180),
    north: float = Query(ge=-85, le=85),
    mode: SnowMode = "combined",
    service: SnowService = Depends(snow_service),
) -> JSONResponse:
    if west >= east or south >= north:
        raise HTTPException(status_code=422, detail="bbox must have a positive width and height")
    return JSONResponse(service.summary(mode, [west, south, east, north]))


@router.get("/point")
def point(
    lon: float = Query(ge=-180, le=180),
    lat: float = Query(ge=-90, le=90),
    service: SnowService = Depends(snow_service),
) -> JSONResponse:
    return JSONResponse(service.point(lon, lat))


@router.get("/coverage")
def coverage(service: SnowService = Depends(snow_service)) -> JSONResponse:
    return JSONResponse(service.coverage())


@router.get("/status")
def status(service: SnowService = Depends(snow_service)) -> JSONResponse:
    return JSONResponse(service.status())


@router.post("/areas", status_code=202)
def prepare_area(request: AreaRequest, settings: Settings = Depends(get_settings)) -> JSONResponse:
    try:
        job = area_jobs.start(settings, request.longitude, request.latitude)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JSONResponse(job.as_dict(), status_code=202)


@router.get("/areas/{job_id}")
def area_job(job_id: str) -> JSONResponse:
    job = area_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return JSONResponse(job.as_dict())
