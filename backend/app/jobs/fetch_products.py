from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.providers.base import ProductMatch
from app.providers.wekeo import WekeoProvider


def fetch_latest_product(
    settings: Settings,
    product: str,
    bbox: list[float],
    lookback_days: int,
) -> tuple[Path, ProductMatch]:
    provider = WekeoProvider(settings)
    now = datetime.now(UTC)
    results, matches = provider.search(
        product=product,
        bbox=bbox,
        start=now - timedelta(days=lookback_days),
        end=now,
        limit=3,
    )
    if not matches:
        raise LookupError(f"No {product} product found in the last {lookback_days} days")
    destination = settings.data_dir / "raw" / product.lower()
    archive = provider.download_first(results, destination)
    return archive, matches[0]
