from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


SnowProduct = Literal["FSC", "GFSC"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    credentials_configured: bool
    processed_data_available: bool


class SnowDataStatus(BaseModel):
    mode: Literal["processed", "demo"]
    generated_at: datetime | None = None
    feature_count: int
    products: list[SnowProduct]
