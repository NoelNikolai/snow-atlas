from __future__ import annotations

from typing import Literal

from pydantic import BaseModel




class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    credentials_configured: bool
    processed_data_available: bool
