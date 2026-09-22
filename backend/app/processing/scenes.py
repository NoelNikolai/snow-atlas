from __future__ import annotations

import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform as transform_coordinates
from rasterio.warp import transform_bounds

from app.providers.wekeo import parse_observed_at
from app.storage.scene_catalog import Scene, SceneCatalog


TILE_PATTERN = re.compile(r"_T([0-9A-Z]{5})_")
SNOW_SUFFIX = {"FSC": "_FSCTOC.tif", "GFSC": "_GF.tif"}
QUALITY_SUFFIX = {"FSC": "_FSCTOC-QA.tif", "GFSC": "_GF-QA.tif"}


def product_of(archive: Path) -> str:
    if "_GFSC_" in archive.name:
        return "GFSC"
    if "_FSC_" in archive.name:
        return "FSC"
    raise ValueError(f"Cannot tell FSC/GFSC from archive name: {archive.name}")


def import_archive(archive: Path, catalog: SceneCatalog) -> Scene:
    """Extract the rasters Snow Atlas needs from a WEkEO ZIP and register the scene."""

    product = product_of(archive)
    product_id = archive.stem
    existing = catalog.get(product_id)
    if existing and (catalog.root / existing.directory / existing.snow_file).is_file():
        return existing

    directory = catalog.root / product_id
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        snow_file = _extract(bundle, SNOW_SUFFIX[product], directory)
        quality_file = _extract(bundle, QUALITY_SUFFIX[product], directory)
        flags_file = _extract(bundle, "_QAFLAGS.tif", directory)
        at_file = _extract(bundle, "_AT.tif", directory) if product == "GFSC" else None

    with rasterio.open(directory / snow_file) as source:
        bounds = list(transform_bounds(source.crs, "EPSG:4326", *source.bounds, densify_pts=21))
        footprint = _footprint(source)
        resolution_m = abs(float(source.transform.a))

    observed = parse_observed_at(product_id)
    tile_match = TILE_PATTERN.search(product_id)
    scene = Scene(
        product_id=product_id,
        product=product,
        tile_id=tile_match.group(1) if tile_match else "unknown",
        observed_at=observed.isoformat().replace("+00:00", "Z") if observed else None,
        directory=product_id,
        snow_file=snow_file,
        quality_file=quality_file,
        flags_file=flags_file,
        at_file=at_file,
        bounds_wgs84=[round(value, 6) for value in bounds],
        footprint=footprint,
        resolution_m=resolution_m,
        imported_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    catalog.add(scene)
    return scene


def _extract(bundle: zipfile.ZipFile, suffix: str, destination: Path) -> str:
    matches = [name for name in bundle.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {suffix} raster, found {len(matches)}")
    target = destination / Path(matches[0]).name
    with bundle.open(matches[0]) as source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
    return target.name


def _footprint(source: rasterio.DatasetReader) -> list[list[float]]:
    left, bottom, right, top = source.bounds
    steps = np.linspace(0, 1, 11)
    xs = [*(left + (right - left) * steps), *([right] * 11), *(right - (right - left) * steps), *([left] * 11)]
    ys = [*([top] * 11), *(top - (top - bottom) * steps), *([bottom] * 11), *(bottom + (top - bottom) * steps)]
    longitudes, latitudes = transform_coordinates(source.crs, "EPSG:4326", xs, ys)
    ring = [[round(lon, 6), round(lat, 6)] for lon, lat in zip(longitudes, latitudes)]
    return [*ring, ring[0]]
