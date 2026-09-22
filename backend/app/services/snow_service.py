from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.config import Settings
from app.providers.demo import demo_feature_collection
from app.storage.local_store import LocalGeoJsonStore


class SnowService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = LocalGeoJsonStore(settings.processed_geojson)

    def feature_collection(
        self,
        bbox: list[float] | None = None,
        products: set[str] | None = None,
    ) -> dict[str, Any]:
        collection = self.store.read() if self.store.exists() else demo_feature_collection()
        if bbox is None and not products:
            return collection

        filtered = deepcopy(collection)
        filtered["features"] = [
            feature
            for feature in collection.get("features", [])
            if self._matches(feature, bbox, products)
        ]
        return filtered

    def status(self) -> dict[str, Any]:
        collection = self.store.read() if self.store.exists() else demo_feature_collection()
        metadata = collection.get("metadata", {})
        products = sorted(
            {feature.get("properties", {}).get("product") for feature in collection.get("features", [])}
            - {None}
        )
        return {
            "mode": "processed" if self.store.exists() else "demo",
            "generated_at": metadata.get("generated_at"),
            "feature_count": len(collection.get("features", [])),
            "products": products,
        }

    @staticmethod
    def _matches(
        feature: dict[str, Any],
        bbox: list[float] | None,
        products: set[str] | None,
    ) -> bool:
        properties = feature.get("properties", {})
        if products and str(properties.get("product", "")).upper() not in products:
            return False
        if not bbox:
            return True
        coordinates = feature.get("geometry", {}).get("coordinates", [[]])[0]
        if not coordinates:
            return False
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        west, south, east, north = bbox
        return not (max(xs) < west or min(xs) > east or max(ys) < south or min(ys) > north)
