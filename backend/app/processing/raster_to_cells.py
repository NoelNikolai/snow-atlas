from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil, floor
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.windows import from_bounds
from rasterio.warp import transform as transform_coordinates
from rasterio.warp import transform_bounds

from app.providers.wekeo import parse_observed_at


TILE_PATTERN = re.compile(r"_T([0-9A-Z]{5})_")
MINIMUM_VALID_AT = 946_684_800  # 2000-01-01T00:00:00Z; AT nodata is 0.


@dataclass(frozen=True)
class ObservationSummary:
    representative: datetime | None
    newest: datetime | None
    oldest: datetime | None
    representative_unix: int | None
    newest_unix: int | None
    oldest_unix: int | None
    distinct_count: int
    valid_percent: float | None
    source: str


def process_product_zip(
    archive_path: Path,
    product: str,
    cell_size_m: int = 5_040,
    minimum_snow_percent: float = 2.0,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    product = product.upper()
    product_id = archive_path.stem
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(prefix="snow-atlas-") as temporary:
        temporary_path = Path(temporary)
        snow_member = _snow_member(archive, product)
        source_layer = _source_layer(product)
        snow_path = _extract_member(archive, snow_member, temporary_path)
        quality_path = _extract_member(
            archive,
            _find_member(archive, f"_{source_layer}-QA.tif"),
            temporary_path,
        )
        flags_path = _extract_member(archive, _find_member(archive, "_QAFLAGS.tif"), temporary_path)
        at_path = None
        if product == "GFSC":
            at_path = _extract_member(archive, _find_member(archive, "_AT.tif"), temporary_path)

        features = _aggregate_raster(
            snow_path=snow_path,
            quality_path=quality_path,
            flags_path=flags_path,
            at_path=at_path,
            product=product,
            product_id=product_id,
            source_layer=source_layer,
            cell_size_m=cell_size_m,
            minimum_snow_percent=minimum_snow_percent,
            bbox=bbox,
        )

    product_date = _product_date(product_id)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "mode": "processed",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "products": [product],
            "source_product_ids": [product_id],
            "source_layers": [source_layer],
            "product_dates": [product_date] if product_date else [],
            "cell_size_m": cell_size_m,
            "bbox": bbox,
        },
    }


def merge_feature_collections(collections: list[dict[str, Any]]) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    features: list[dict[str, Any]] = []
    products: set[str] = set()
    source_product_ids: set[str] = set()
    source_layers: set[str] = set()
    product_dates: set[str] = set()
    for collection in collections:
        features.extend(collection.get("features", []))
        metadata = collection.get("metadata", {})
        products.update(metadata.get("products", []))
        source_product_ids.update(metadata.get("source_product_ids", []))
        source_layers.update(metadata.get("source_layers", []))
        product_dates.update(metadata.get("product_dates", []))
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "mode": "processed",
            "generated_at": generated_at,
            "products": sorted(products),
            "source_product_ids": sorted(source_product_ids),
            "source_layers": sorted(source_layers),
            "product_dates": sorted(product_dates),
        },
    }


def _snow_member(archive: zipfile.ZipFile, product: str) -> str:
    if product == "GFSC":
        return _find_member(archive, "_GF.tif", excluded=("_GF-QA.tif",))
    if product == "FSC":
        return _find_member(archive, "_FSCTOC.tif")
    raise ValueError(f"Unsupported product: {product}")


def _source_layer(product: str) -> str:
    if product == "GFSC":
        return "GF"
    if product == "FSC":
        return "FSCTOC"
    raise ValueError(f"Unsupported product: {product}")


def _find_member(
    archive: zipfile.ZipFile,
    suffix: str,
    excluded: tuple[str, ...] = (),
) -> str:
    matches = [
        name
        for name in archive.namelist()
        if name.endswith(suffix) and not any(name.endswith(value) for value in excluded)
    ]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {suffix} raster, found {len(matches)}")
    return matches[0]


def _extract_member(archive: zipfile.ZipFile, member: str, destination: Path) -> Path:
    target = destination / Path(member).name
    with archive.open(member) as source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
    return target


def _aggregate_raster(
    snow_path: Path,
    quality_path: Path,
    flags_path: Path,
    at_path: Path | None,
    product: str,
    product_id: str,
    source_layer: str,
    cell_size_m: int,
    minimum_snow_percent: float,
    bbox: list[float] | None,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    product_observed = parse_observed_at(product_id)
    product_date = product_observed.date().isoformat() if product_observed else None
    tile_match = TILE_PATTERN.search(product_id)
    tile_id = tile_match.group(1) if tile_match else "unknown"

    with (
        rasterio.open(snow_path) as snow_source,
        rasterio.open(quality_path) as quality_source,
        rasterio.open(flags_path) as flags_source,
    ):
        if snow_source.crs is None:
            raise ValueError("Snow raster has no coordinate reference system")
        resolution_m = abs(float(snow_source.transform.a))
        pixels_per_cell = max(1, round(cell_size_m / resolution_m))
        at_source = rasterio.open(at_path) if at_path else None
        try:
            _validate_aligned(snow_source, quality_source, source_layer + "-QA")
            _validate_aligned(snow_source, flags_source, "QAFLAGS")
            if at_source:
                _validate_aligned(snow_source, at_source, "AT")

            row_start, row_stop, column_start, column_stop = _pixel_extent(snow_source, bbox)
            for row in range(row_start, row_stop, pixels_per_cell):
                for column in range(column_start, column_stop, pixels_per_cell):
                    window = Window(
                        column,
                        row,
                        min(pixels_per_cell, column_stop - column),
                        min(pixels_per_cell, row_stop - row),
                    )
                    snow = snow_source.read(1, window=window, masked=True)
                    snow_values = np.asarray(snow.data)
                    raster_valid = ~np.ma.getmaskarray(snow) & np.isfinite(snow_values)
                    valid = raster_valid & (snow_values >= 0) & (snow_values <= 100)
                    cloud = raster_valid & (snow_values == 205)
                    water = raster_valid & (snow_values == 210)
                    nodata = ~(valid | cloud | water)
                    valid_count = int(valid.sum())
                    if not valid_count:
                        continue

                    coverage = float(snow_values[valid].mean())
                    if coverage < minimum_snow_percent:
                        continue

                    observation = _observation_summary(
                        at_source,
                        window,
                        valid,
                        fallback=product_observed,
                    )
                    quality_good_percent, quality_valid_percent = _quality_percentages(
                        quality_source,
                        window,
                        valid,
                    )
                    radar_percent, flags_valid_percent = _flags_percentages(
                        flags_source,
                        window,
                        valid,
                        include_radar=product == "GFSC",
                    )
                    valid_percent = 100 * valid_count / valid.size
                    cloud_percent = 100 * int(cloud.sum()) / valid.size
                    water_percent = 100 * int(water.sum()) / valid.size
                    nodata_percent = 100 * int(nodata.sum()) / valid.size
                    snow_pixel_percent = 100 * int((snow_values[valid] > 0).sum()) / valid_count
                    coordinates = _window_polygon(snow_source, window)
                    cell_id = f"{product}-{tile_id}-r{row:04d}c{column:04d}"
                    features.append(
                        {
                            "type": "Feature",
                            "id": cell_id,
                            "properties": {
                                "cell_id": cell_id,
                                "region_name": f"Sentinel-2 · {tile_id}",
                                "product": product,
                                "source_layer": source_layer,
                                "product_date": product_date,
                                "coverage_percent": round(coverage, 1),
                                "snow_pixel_percent": round(snow_pixel_percent, 1),
                                "valid_percent": round(valid_percent, 1),
                                # Keep observed_at/newest and oldest_observed_at compatible
                                # while exposing a representative pixel-level AT for GFSC.
                                "observed_at": _iso(observation.newest),
                                "oldest_observed_at": _iso(observation.oldest),
                                "representative_observed_at": _iso(observation.representative),
                                "at_unix": observation.representative_unix,
                                "at_min_unix": observation.oldest_unix,
                                "at_max_unix": observation.newest_unix,
                                "at_distinct_count": observation.distinct_count,
                                "at_valid_percent": _rounded(observation.valid_percent),
                                "at_source": observation.source,
                                "cloud_percent": round(cloud_percent, 1),
                                "water_percent": round(water_percent, 1),
                                "nodata_percent": round(nodata_percent, 1),
                                "quality_good_percent": _rounded(quality_good_percent),
                                "quality_valid_percent": _rounded(quality_valid_percent),
                                "radar_percent": _rounded(radar_percent),
                                "flags_valid_percent": _rounded(flags_valid_percent),
                                "resolution_m": round(resolution_m),
                                "cell_size_m": round(window.width * resolution_m),
                                "elevation_m": None,
                                "confidence": "hoch" if valid_percent >= 80 else "mittel",
                                "source": "WEkEO",
                                "source_product_id": product_id,
                            },
                            "geometry": {"type": "Polygon", "coordinates": [coordinates]},
                        }
                    )
        finally:
            if at_source:
                at_source.close()

    return features


def _pixel_extent(
    dataset: rasterio.DatasetReader,
    bbox: list[float] | None,
) -> tuple[int, int, int, int]:
    if bbox is None:
        return 0, dataset.height, 0, dataset.width
    if len(bbox) != 4:
        raise ValueError("bbox must contain west,south,east,north")
    west, south, east, north = bbox
    if west >= east or south >= north:
        raise ValueError("bbox must have a positive width and height")

    left, bottom, right, top = transform_bounds(
        "EPSG:4326",
        dataset.crs,
        west,
        south,
        east,
        north,
        densify_pts=21,
    )
    requested = from_bounds(left, bottom, right, top, transform=dataset.transform)
    column_start = max(0, floor(requested.col_off))
    column_stop = min(dataset.width, ceil(requested.col_off + requested.width))
    row_start = max(0, floor(requested.row_off))
    row_stop = min(dataset.height, ceil(requested.row_off + requested.height))
    if column_start >= column_stop or row_start >= row_stop:
        return 0, 0, 0, 0
    return row_start, row_stop, column_start, column_stop


def _observation_summary(
    at_source: rasterio.DatasetReader | None,
    window: Window,
    snow_valid: np.ndarray,
    fallback: datetime | None,
) -> ObservationSummary:
    if at_source is None:
        fallback_unix = int(fallback.timestamp()) if fallback else None
        return ObservationSummary(
            representative=fallback,
            newest=fallback,
            oldest=fallback,
            representative_unix=fallback_unix,
            newest_unix=fallback_unix,
            oldest_unix=fallback_unix,
            distinct_count=1 if fallback else 0,
            valid_percent=100.0 if fallback else None,
            source="product_id",
        )

    at = at_source.read(1, window=window, masked=True)
    values = np.asarray(at.data)
    valid = snow_valid & ~np.ma.getmaskarray(at) & (values > MINIMUM_VALID_AT)
    if not valid.any():
        fallback_unix = int(fallback.timestamp()) if fallback else None
        return ObservationSummary(
            representative=fallback,
            newest=fallback,
            oldest=fallback,
            representative_unix=fallback_unix,
            newest_unix=fallback_unix,
            oldest_unix=fallback_unix,
            distinct_count=0,
            valid_percent=0.0,
            source="product_id_fallback" if fallback else "unavailable",
        )

    timestamps = values[valid].astype(np.int64)
    unique, counts = np.unique(timestamps, return_counts=True)
    most_common = unique[counts == counts.max()]
    representative_unix = int(most_common.max())  # deterministic: newest wins ties
    newest_unix = int(timestamps.max())
    oldest_unix = int(timestamps.min())
    return ObservationSummary(
        representative=datetime.fromtimestamp(representative_unix, tz=UTC),
        newest=datetime.fromtimestamp(newest_unix, tz=UTC),
        oldest=datetime.fromtimestamp(oldest_unix, tz=UTC),
        representative_unix=representative_unix,
        newest_unix=newest_unix,
        oldest_unix=oldest_unix,
        distinct_count=int(unique.size),
        valid_percent=100 * int(valid.sum()) / int(snow_valid.sum()),
        source="AT",
    )


def _observation_times(
    age_source: rasterio.DatasetReader | None,
    window: Window,
    snow_valid: np.ndarray,
    fallback: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    """Compatibility wrapper for the previous private helper."""

    summary = _observation_summary(age_source, window, snow_valid, fallback)
    return summary.newest, summary.oldest


def _quality_percentages(
    quality_source: rasterio.DatasetReader,
    window: Window,
    snow_valid: np.ndarray,
) -> tuple[float | None, float]:
    quality = quality_source.read(1, window=window, masked=True)
    values = np.asarray(quality.data)
    valid = snow_valid & ~np.ma.getmaskarray(quality) & (values >= 0) & (values <= 3)
    quality_count = int(valid.sum())
    snow_count = int(snow_valid.sum())
    valid_percent = 100 * quality_count / snow_count
    if not quality_count:
        return None, valid_percent
    good_percent = 100 * int((valid & (values <= 1)).sum()) / quality_count
    return good_percent, valid_percent


def _flags_percentages(
    flags_source: rasterio.DatasetReader,
    window: Window,
    snow_valid: np.ndarray,
    include_radar: bool,
) -> tuple[float | None, float]:
    flags = flags_source.read(1, window=window, masked=True)
    values = np.asarray(flags.data)
    valid = snow_valid & ~np.ma.getmaskarray(flags) & (values != 255)
    flags_count = int(valid.sum())
    snow_count = int(snow_valid.sum())
    valid_percent = 100 * flags_count / snow_count
    if not include_radar or not flags_count:
        return None, valid_percent
    radar = valid & ((values & 0b1000_0000) != 0)
    return 100 * int(radar.sum()) / flags_count, valid_percent


def _validate_aligned(
    snow_source: rasterio.DatasetReader,
    other_source: rasterio.DatasetReader,
    layer_name: str,
) -> None:
    if (
        other_source.shape != snow_source.shape
        or other_source.crs != snow_source.crs
        or other_source.transform != snow_source.transform
    ):
        raise ValueError(f"Snow and {layer_name} rasters do not share shape/CRS/transform")


def _product_date(product_id: str) -> str | None:
    observed_at = parse_observed_at(product_id)
    return observed_at.date().isoformat() if observed_at else None


def _window_polygon(source: rasterio.DatasetReader, window: Window) -> list[list[float]]:
    transform = source.window_transform(window)
    pixel_corners = [
        (0, 0),
        (window.width, 0),
        (window.width, window.height),
        (0, window.height),
        (0, 0),
    ]
    source_coordinates = [transform * point for point in pixel_corners]
    xs, ys = zip(*source_coordinates)
    longitudes, latitudes = transform_coordinates(source.crs, "EPSG:4326", list(xs), list(ys))
    return [[round(lon, 6), round(lat, 6)] for lon, lat in zip(longitudes, latitudes)]


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
