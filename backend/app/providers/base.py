from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ProductMatch:
    product: str
    dataset_id: str
    product_id: str
    observed_at: datetime | None
    size_bytes: int | None
    raw: dict[str, Any]
    index: int = 0

    def covers(self, longitude: float, latitude: float) -> bool:
        bbox = self.raw.get("bbox")
        if not bbox or len(bbox) != 4:
            return True
        west, south, east, north = bbox
        return west <= longitude <= east and south <= latitude <= north


class SnowArchiveProvider(Protocol):
    def search(
        self,
        product: str,
        bbox: list[float],
        start: datetime,
        end: datetime,
        limit: int = 3,
    ) -> tuple[Any, list[ProductMatch]]: ...

    def download(self, search_results: Any, match: ProductMatch, destination: Path) -> Path: ...
