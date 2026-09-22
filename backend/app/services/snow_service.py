from __future__ import annotations

from typing import Any, Literal

import numpy as np

from app.core.config import Settings
from app.processing.snow_raster import (
    TILE_SIZE,
    area_statistics,
    cell_statistics,
    colorize,
    composite,
    encode_png,
    mercator_bounds,
    merge_products,
    nodata_png,
    tile_bounds,
    wgs84_bounds,
)
from app.storage.scene_catalog import SceneCatalog


SnowMode = Literal["FSC", "GFSC", "combined"]


class SnowService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalog = SceneCatalog(settings.scenes_dir)

    # --- Raster -------------------------------------------------------------

    def tile(self, mode: SnowMode, z: int, x: int, y: int, show_clouds: bool) -> bytes:
        bounds = tile_bounds(z, x, y)
        values = self._values(mode, bounds, TILE_SIZE, TILE_SIZE)
        if values is None:
            return nodata_png()
        return encode_png(colorize(values, show_clouds, pixel_origin=(x * TILE_SIZE, y * TILE_SIZE)))

    def summary(self, mode: SnowMode, bbox: list[float]) -> dict[str, Any]:
        bounds = mercator_bounds(bbox)
        aspect = (bounds[3] - bounds[1]) / max(bounds[2] - bounds[0], 1)
        width = TILE_SIZE if aspect <= 1 else max(16, round(TILE_SIZE / aspect))
        height = TILE_SIZE if aspect > 1 else max(16, round(TILE_SIZE * aspect))
        values = self._values(mode, bounds, width, height)
        if values is None:
            values = np.full((height, width), 255, dtype=np.uint8)
        return {"mode": mode, "bbox": bbox, **area_statistics(values)}

    def _values(self, mode: SnowMode, bounds: tuple[float, float, float, float], width: int, height: int):
        bbox = wgs84_bounds(bounds)
        root = self.catalog.root
        products = ["FSC", "GFSC"] if mode == "combined" else [mode]
        layers = {}
        for product in products:
            scenes = self.catalog.active(product, bbox)
            if scenes:
                layers[product] = composite(scenes, root, bounds, width, height)
        if not layers:
            return None
        if mode == "combined" and len(layers) == 2:
            return merge_products(layers["FSC"], layers["GFSC"])
        return next(iter(layers.values()))

    # --- Point & coverage ---------------------------------------------------

    def point(self, longitude: float, latitude: float) -> dict[str, Any]:
        """Cell statistics for each product at a point (newest scene that has data there)."""

        bbox = [longitude, latitude, longitude, latitude]
        cells: dict[str, Any] = {}
        for product, cell_size in (("FSC", self.settings.fsc_cell_m), ("GFSC", self.settings.gfsc_cell_m)):
            for scene in reversed(self.catalog.active(product, bbox)):
                cell = cell_statistics(scene, self.catalog.root, longitude, latitude, cell_size)
                if cell:
                    cells[product] = cell
                    break
        return {
            "longitude": longitude,
            "latitude": latitude,
            "covered": bool(cells),
            "cells": cells,
            "data_version": self.catalog.version(),
        }

    def coverage(self) -> dict[str, Any]:
        features = []
        for product in ("FSC", "GFSC"):
            for scene in self.catalog.active(product):
                features.append(
                    {
                        "type": "Feature",
                        "id": scene.product_id,
                        "properties": {
                            "product": scene.product,
                            "tile_id": scene.tile_id,
                            "observed_at": scene.observed_at,
                            "product_id": scene.product_id,
                        },
                        "geometry": {"type": "Polygon", "coordinates": [scene.footprint]},
                    }
                )
        return {"type": "FeatureCollection", "features": features, "data_version": self.catalog.version()}

    def status(self) -> dict[str, Any]:
        scenes = self.catalog.scenes()
        active = [scene for product in ("FSC", "GFSC") for scene in self.catalog.active(product)]
        return {
            "mode": "processed" if scenes else "empty",
            "data_version": self.catalog.version(),
            "scene_count": len(scenes),
            "products": sorted({scene.product for scene in scenes}),
            "active_scenes": [
                {"product": scene.product, "tile_id": scene.tile_id, "observed_at": scene.observed_at, "product_id": scene.product_id}
                for scene in active
            ],
            "credentials_configured": self.settings.credentials_configured,
        }
