from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.jobs.fetch_products import fetch_latest_product
from app.processing.raster_to_cells import merge_feature_collections, process_product_zip
from app.storage.local_store import LocalGeoJsonStore


def refresh(products: list[str], bbox: list[float], lookback_days: int) -> dict:
    settings = get_settings()
    collections = []
    for product in products:
        archive, _match = fetch_latest_product(settings, product, bbox, lookback_days)
        collections.append(
            process_product_zip(
                archive,
                product,
                cell_size_m=settings.snow_cell_size_m,
                minimum_snow_percent=settings.snow_min_percent,
            )
        )
    merged = merge_feature_collections(collections)
    LocalGeoJsonStore(settings.processed_geojson).write(merged)
    return merged


def process_local_sample(archive: Path, product: str) -> dict:
    settings = get_settings()
    collection = process_product_zip(
        archive,
        product,
        cell_size_m=settings.snow_cell_size_m,
        minimum_snow_percent=settings.snow_min_percent,
    )
    LocalGeoJsonStore(settings.processed_geojson).write(collection)
    return collection


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Refresh Snow Atlas cells")
    parser.add_argument("--product", action="append", choices=["FSC", "GFSC"])
    parser.add_argument("--bbox", nargs=4, type=float)
    parser.add_argument("--lookback-days", type=int, default=settings.refresh_lookback_days)
    parser.add_argument("--from-zip", type=Path)
    parser.add_argument("--zip-product", choices=["FSC", "GFSC"], default="GFSC")
    args = parser.parse_args()

    if args.from_zip:
        result = process_local_sample(args.from_zip, args.zip_product)
    else:
        result = refresh(
            products=args.product or ["GFSC"],
            bbox=args.bbox or settings.default_bbox_values,
            lookback_days=args.lookback_days,
        )
    print(f"Snow cells written: {len(result['features'])}")


if __name__ == "__main__":
    main()
