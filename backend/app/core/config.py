from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Snow Atlas API"
    app_environment: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    hda_user: str | None = None
    hda_password: str | None = None
    fsc_dataset_id: str = "EO:CLMS:DAT:FSC_EUROPE_20M_DAILY_V2"
    gfsc_dataset_id: str = "EO:CLMS:DAT:GFSC_EUROPE_60M_DAILY_V1"

    data_dir: Path = Field(default=BACKEND_ROOT / "data")
    snow_cell_size_m: int = 5_040
    snow_min_percent: float = 2.0
    refresh_lookback_days: int = 14
    default_bbox: str = "5.7,45.5,16.0,48.5"

    @property
    def credentials_configured(self) -> bool:
        return bool(self.hda_user and self.hda_password)

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def default_bbox_values(self) -> list[float]:
        values = [float(value.strip()) for value in self.default_bbox.split(",")]
        if len(values) != 4:
            raise ValueError("DEFAULT_BBOX must contain west,south,east,north")
        return values

    @property
    def processed_geojson(self) -> Path:
        return self.data_dir / "processed" / "snow_cells.geojson"

    def dataset_id(self, product: str) -> str:
        if product.upper() == "FSC":
            return self.fsc_dataset_id
        if product.upper() == "GFSC":
            return self.gfsc_dataset_id
        raise ValueError(f"Unsupported snow product: {product}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
