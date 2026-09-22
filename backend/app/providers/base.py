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


class SnowArchiveProvider(Protocol):
    def search(
        self,
        product: str,
        bbox: list[float],
        start: datetime,
        end: datetime,
        limit: int = 3,
    ) -> tuple[Any, list[ProductMatch]]: ...

    def download_first(self, search_results: Any, destination: Path) -> Path: ...
