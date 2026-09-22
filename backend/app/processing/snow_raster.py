from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from rasterio.warp import transform as transform_coordinates
from rasterio.windows import Window

from app.storage.scene_catalog import Scene


WEB_MERCATOR = "EPSG:3857"
EARTH_HALF = 20_037_508.342789244
TILE_SIZE = 256
CLOUD = 205
WATER = 210
NODATA = 255
MINIMUM_VALID_AT = 946_684_800  # 2000-01-01T00:00:00Z; AT nodata is 0.

# Ordinal blue ramp (light -> dark = little -> much snow). Validated sequential
# steps; the dark end stays readable on bright limestone and on snow in the basemap.
SNOW_CLASSES = [
    (1, 25, (0x86, 0xB6, 0xEF)),
    (26, 50, (0x39, 0x87, 0xE5)),
    (51, 75, (0x1C, 0x5C, 0xAB)),
    (76, 100, (0x0D, 0x36, 0x6B)),
]
SNOW_ALPHA = 220
CLOUD_RGBA = (0xD4, 0xD8, 0xDD, 190)
NODATA_RGBA = (0x10, 0x1A, 0x1E, 70)


# --- Web-Mercator geometry ---------------------------------------------------

def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    size = 2 * EARTH_HALF / 2**z
    west = -EARTH_HALF + x * size
    north = EARTH_HALF - y * size
    return west, north - size, west + size, north


def mercator_bounds(bbox_wgs84: list[float]) -> tuple[float, float, float, float]:
    west, south, east, north = bbox_wgs84
    xs, ys = transform_coordinates("EPSG:4326", WEB_MERCATOR, [west, east], [south, north])
    return xs[0], ys[0], xs[1], ys[1]


def wgs84_bounds(bounds_3857: tuple[float, float, float, float]) -> list[float]:
    left, bottom, right, top = bounds_3857
    xs, ys = transform_coordinates(WEB_MERCATOR, "EPSG:4326", [left, right], [bottom, top])
    return [xs[0], ys[0], xs[1], ys[1]]


# --- Compositing -------------------------------------------------------------

def composite(
    scenes: list[Scene],
    root: Path,
    bounds_3857: tuple[float, float, float, float],
    width: int,
    height: int,
) -> np.ndarray:
    """Warp the scenes' snow codes into one Web-Mercator grid.

    Scenes are passed oldest first; a newer observation (snow value or water)
    replaces older data, a cloud only fills pixels that have nothing yet.
    """

    result = np.full((height, width), NODATA, dtype=np.uint8)
    destination_transform = from_bounds(*bounds_3857, width, height)
    target_resolution = (bounds_3857[2] - bounds_3857[0]) / width
    for scene in scenes:
        path = root / scene.directory / scene.snow_file
        warped = np.full((height, width), NODATA, dtype=np.uint8)
        with _open_for_resolution(path, scene.resolution_m, target_resolution) as source:
            reproject(
                source=rasterio.band(source, 1),
                destination=warped,
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=NODATA,
                dst_transform=destination_transform,
                dst_crs=WEB_MERCATOR,
                dst_nodata=NODATA,
                resampling=Resampling.nearest,
            )
        observed = (warped <= 100) | (warped == WATER)
        fills_gap = (result == NODATA) & (warped == CLOUD)
        result = np.where(observed | fills_gap, warped, result)
    return result


def merge_products(fsc: np.ndarray, gfsc: np.ndarray) -> np.ndarray:
    """Prefer the daily FSC observation; GFSC fills clouds and swath gaps."""

    fsc_observed = (fsc <= 100) | (fsc == WATER)
    return np.where(fsc_observed, fsc, np.where(gfsc != NODATA, gfsc, fsc))


def _open_for_resolution(path: Path, native_m: float, target_m: float):
    factors = _overview_factors(path)
    level = None
    for index, factor in enumerate(factors):
        if native_m * factor <= target_m:
            level = index
    return rasterio.open(path, overview_level=level) if level is not None else rasterio.open(path)


@lru_cache(maxsize=256)
def _overview_factors(path: Path) -> tuple[int, ...]:
    with rasterio.open(path) as source:
        return tuple(source.overviews(1))


# --- Rendering ---------------------------------------------------------------

def colorize(values: np.ndarray, show_clouds: bool, pixel_origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    height, width = values.shape
    rgba = np.zeros((4, height, width), dtype=np.uint8)
    for low, high, color in SNOW_CLASSES:
        mask = (values >= low) & (values <= high)
        for band, channel in enumerate(color):
            rgba[band][mask] = channel
        rgba[3][mask] = SNOW_ALPHA

    if show_clouds:
        rows, columns = np.indices(values.shape)
        stripes = ((rows + pixel_origin[1] + columns + pixel_origin[0]) % 9) < 3
        cloud = (values == CLOUD) & stripes
        for band, channel in enumerate(CLOUD_RGBA):
            rgba[band][cloud] = channel

    nodata = values == NODATA
    for band, channel in enumerate(NODATA_RGBA):
        rgba[band][nodata] = channel
    return rgba


def encode_png(rgba: np.ndarray) -> bytes:
    _, height, width = rgba.shape
    with MemoryFile() as memory, warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as target:
            target.write(rgba)
        return memory.read()


@lru_cache(maxsize=4)
def nodata_png() -> bytes:
    return encode_png(colorize(np.full((TILE_SIZE, TILE_SIZE), NODATA, dtype=np.uint8), show_clouds=False))


# --- Statistics --------------------------------------------------------------

def area_statistics(values: np.ndarray) -> dict[str, float | None]:
    land = values != WATER
    total = int(land.sum())
    valid = values <= 100
    valid_count = int(valid.sum())
    cloud_count = int((values == CLOUD).sum())
    nodata_count = int((values == NODATA).sum())
    snow = valid & (values > 0)
    return {
        "snow_area_percent": round(100 * int(snow.sum()) / valid_count, 1) if valid_count else None,
        "mean_coverage_percent": round(float(values[valid].mean()), 1) if valid_count else None,
        "valid_percent": round(100 * valid_count / total, 1) if total else 0.0,
        "cloud_percent": round(100 * cloud_count / total, 1) if total else 0.0,
        "nodata_percent": round(100 * nodata_count / total, 1) if total else 0.0,
    }


@dataclass(frozen=True)
class ObservationSummary:
    newest: datetime | None
    oldest: datetime | None
    distinct_count: int
    source: str


def cell_statistics(
    scene: Scene,
    root: Path,
    longitude: float,
    latitude: float,
    cell_size_m: int,
) -> dict[str, Any] | None:
    """Statistics for the grid-aligned display cell that contains the point."""

    snow_path = root / scene.directory / scene.snow_file
    with rasterio.open(snow_path) as snow_source:
        xs, ys = transform_coordinates("EPSG:4326", snow_source.crs, [longitude], [latitude])
        row, column = snow_source.index(xs[0], ys[0])
        if not (0 <= row < snow_source.height and 0 <= column < snow_source.width):
            return None
        resolution_m = abs(float(snow_source.transform.a))
        pixels_per_cell = max(1, round(cell_size_m / resolution_m))
        row_start = (row // pixels_per_cell) * pixels_per_cell
        column_start = (column // pixels_per_cell) * pixels_per_cell
        window = Window(
            column_start,
            row_start,
            min(pixels_per_cell, snow_source.width - column_start),
            min(pixels_per_cell, snow_source.height - row_start),
        )
        values = snow_source.read(1, window=window)
        polygon = _window_polygon(snow_source, window)

    valid = values <= 100
    cloud = values == CLOUD
    water = values == WATER
    valid_count = int(valid.sum())
    size = values.size
    if valid_count == 0 and int(cloud.sum()) == 0 and int(water.sum()) == 0:
        return None

    observation = _observation_summary(scene, root, window, valid)
    quality_good = _quality_good_percent(root / scene.directory / scene.quality_file, window, valid)
    cell_id = f"{scene.product}-{scene.tile_id}-r{row_start:04d}c{column_start:04d}"
    return {
        "type": "Feature",
        "id": cell_id,
        "properties": {
            "cell_id": cell_id,
            "region_name": f"Sentinel-2 · {scene.tile_id}",
            "product": scene.product,
            "source_layer": "FSCTOC" if scene.product == "FSC" else "GF",
            "product_date": scene.observed_at[:10] if scene.observed_at else None,
            "coverage_percent": round(float(values[valid].mean()), 1) if valid_count else None,
            "snow_pixel_percent": round(100 * int((values[valid] > 0).sum()) / valid_count, 1) if valid_count else None,
            "valid_percent": round(100 * valid_count / size, 1),
            "cloud_percent": round(100 * int(cloud.sum()) / size, 1),
            "water_percent": round(100 * int(water.sum()) / size, 1),
            "observed_at": _iso(observation.newest),
            "oldest_observed_at": _iso(observation.oldest),
            "at_distinct_count": observation.distinct_count,
            "at_source": observation.source,
            "quality_good_percent": _rounded(quality_good),
            "resolution_m": round(resolution_m),
            "cell_size_m": round(window.width * resolution_m),
            "elevation_m": None,
            "confidence": "hoch" if valid_count / size >= 0.8 else "mittel",
            "source": "WEkEO",
            "source_product_id": scene.product_id,
        },
        "geometry": {"type": "Polygon", "coordinates": [polygon]},
    }


def _observation_summary(scene: Scene, root: Path, window: Window, snow_valid: np.ndarray) -> ObservationSummary:
    fallback = scene.observed
    if not scene.at_file:
        return ObservationSummary(fallback, fallback, 1 if fallback else 0, "product_id")
    with rasterio.open(root / scene.directory / scene.at_file) as at_source:
        values = at_source.read(1, window=window)
    valid = snow_valid & (values > MINIMUM_VALID_AT)
    if not valid.any():
        return ObservationSummary(fallback, fallback, 0, "product_id_fallback" if fallback else "unavailable")
    timestamps = values[valid].astype(np.int64)
    return ObservationSummary(
        newest=datetime.fromtimestamp(int(timestamps.max()), tz=UTC),
        oldest=datetime.fromtimestamp(int(timestamps.min()), tz=UTC),
        distinct_count=int(np.unique(timestamps).size),
        source="AT",
    )


def _quality_good_percent(path: Path, window: Window, snow_valid: np.ndarray) -> float | None:
    with rasterio.open(path) as quality_source:
        values = quality_source.read(1, window=window)
    valid = snow_valid & (values <= 3)
    count = int(valid.sum())
    return 100 * int((valid & (values <= 1)).sum()) / count if count else None


def _window_polygon(source: rasterio.DatasetReader, window: Window) -> list[list[float]]:
    transform = source.window_transform(window)
    corners = [(0, 0), (window.width, 0), (window.width, window.height), (0, window.height), (0, 0)]
    xs, ys = zip(*(transform * corner for corner in corners))
    longitudes, latitudes = transform_coordinates(source.crs, "EPSG:4326", list(xs), list(ys))
    return [[round(lon, 6), round(lat, 6)] for lon, lat in zip(longitudes, latitudes)]


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
