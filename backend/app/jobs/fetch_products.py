from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.processing.scenes import TILE_PATTERN, import_archive
from app.providers.base import ProductMatch
from app.providers.wekeo import WekeoProvider
from app.storage.scene_catalog import Scene, SceneCatalog


def fetch_newest_scenes(
    settings: Settings,
    bbox: list[float],
    products: list[str],
    lookback_days: int,
    progress: Callable[[str], None] = print,
) -> list[Scene]:
    """Download and import the newest FSC/GFSC product per Sentinel-2 tile touching ``bbox``.

    Already imported products are not downloaded again.
    """

    catalog = SceneCatalog(settings.scenes_dir)
    provider = WekeoProvider(settings)
    now = datetime.now(UTC)
    center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    imported: list[Scene] = []
    for product in products:
        progress(f"{product}: suche Aufnahmen bei WEkEO …")
        results, matches = provider.search(
            product=product,
            bbox=bbox,
            start=now - timedelta(days=lookback_days),
            end=now,
            limit=40,
        )
        newest = _newest_per_tile(matches, center)
        if not newest:
            progress(f"{product}: keine Aufnahme in den letzten {lookback_days} Tagen")
            continue
        for match in newest:
            existing = catalog.get(match.product_id)
            if existing:
                imported.append(existing)
                continue
            size = f" ({match.size_bytes / 1_000_000:.0f} MB)" if match.size_bytes else ""
            progress(f"{product}: lade {match.product_id}{size} …")
            archive = provider.download(results, match, settings.data_dir / "raw" / product.lower())
            progress(f"{product}: bereite {match.product_id} auf …")
            imported.append(import_archive(archive, catalog))
    return imported


def _newest_per_tile(matches: list[ProductMatch], center: tuple[float, float]) -> list[ProductMatch]:
    """Matches arrive newest first; keep the first per tile, preferring tiles that contain the center."""

    per_tile: dict[str, ProductMatch] = {}
    for match in matches:
        tile = TILE_PATTERN.search(match.product_id)
        per_tile.setdefault(tile.group(1) if tile else match.product_id, match)
    covering = [match for match in per_tile.values() if match.covers(*center)]
    return covering or list(per_tile.values())[:1]
