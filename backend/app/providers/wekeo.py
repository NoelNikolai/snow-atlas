from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hda import Client, Configuration

from app.core.config import Settings
from app.providers.base import ProductMatch


OBSERVATION_PATTERNS = [
    re.compile(r"_(\d{8}T\d{6})_"),
    re.compile(r"_(\d{8})P\d+D_"),
]


def parse_observed_at(product_id: str) -> datetime | None:
    for pattern in OBSERVATION_PATTERNS:
        match = pattern.search(product_id)
        if not match:
            continue
        value = match.group(1)
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S" if "T" in value else "%Y%m%d")
        return parsed.replace(tzinfo=UTC)
    return None


class WekeoProvider:
    def __init__(self, settings: Settings):
        if not settings.credentials_configured:
            raise RuntimeError("HDA_USER and HDA_PASSWORD must be configured")
        self.settings = settings
        self.client = Client(
            config=Configuration(user=settings.hda_user, password=settings.hda_password),
            timeout=60,
            retry_max=2,
            sleep_max=5,
            progress=True,
            max_workers=1,
        )

    def search(
        self,
        product: str,
        bbox: list[float],
        start: datetime,
        end: datetime,
        limit: int = 3,
    ) -> tuple[Any, list[ProductMatch]]:
        product = product.upper()
        dataset_id = self.settings.dataset_id(product)
        query = {
            "dataset_id": dataset_id,
            "bbox": bbox,
            "startdate": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "enddate": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.999Z"),
        }
        results = self.client.search(query, limit=limit)
        matches = [self._to_match(product, dataset_id, raw) for raw in results.results]
        matches.sort(key=lambda item: item.observed_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return results, matches

    def download_first(self, search_results: Any, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        before = set(destination.glob("*.zip"))
        search_results[:1].download(download_dir=str(destination))
        after = set(destination.glob("*.zip"))
        created = sorted(after - before, key=lambda path: path.stat().st_mtime, reverse=True)
        if created:
            return created[0]
        existing = sorted(after, key=lambda path: path.stat().st_mtime, reverse=True)
        if not existing:
            raise FileNotFoundError("WEkEO download completed without a ZIP product")
        return existing[0]

    @staticmethod
    def _to_match(product: str, dataset_id: str, raw: dict[str, Any]) -> ProductMatch:
        properties = raw.get("properties", {})
        size = properties.get("size")
        return ProductMatch(
            product=product,
            dataset_id=dataset_id,
            product_id=str(raw.get("id", "")),
            observed_at=parse_observed_at(str(raw.get("id", ""))),
            size_bytes=int(size) if isinstance(size, (int, float)) else None,
            raw=raw,
        )
