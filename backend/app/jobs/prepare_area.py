from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.jobs.fetch_products import fetch_latest_product
from app.processing.raster_to_cells import merge_feature_collections, process_product_zip
from app.storage.local_store import LocalGeoJsonStore


def _latest_local_archive(data_dir: Path, product: str) -> Path:
    archives = sorted((data_dir / "raw" / product.lower()).glob("*.zip"))
    if not archives:
        raise FileNotFoundError(
            f"No cached {product} archive found. Run without --reuse-latest first."
        )
    return archives[-1]


def prepare_area(
    products: list[str],
    bbox: list[float],
    lookback_days: int,
    reuse_latest: bool,
    fsc_cell_m: int,
    gfsc_cell_m: int,
) -> dict:
    settings = get_settings()
    collections = []
    for product in products:
        archive = (
            _latest_local_archive(settings.data_dir, product)
            if reuse_latest
            else fetch_latest_product(settings, product, bbox, lookback_days)[0]
        )
        collections.append(
            process_product_zip(
                archive,
                product,
                cell_size_m=fsc_cell_m if product == "FSC" else gfsc_cell_m,
                minimum_snow_percent=0,
                bbox=bbox,
            )
        )

    merged = merge_feature_collections(collections)
    merged["metadata"].update(
        {
            "bbox": bbox,
            "purpose": "search-area",
            "display_cell_size_m": {"FSC": fsc_cell_m, "GFSC": gfsc_cell_m},
        }
    )
    LocalGeoJsonStore(settings.processed_geojson).write(merged)
    return merged


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Prepare a high-resolution Snow Atlas search area"
    )
    parser.add_argument("--product", action="append", choices=["FSC", "GFSC"])
    parser.add_argument("--bbox", nargs=4, type=float, required=True)
    parser.add_argument("--lookback-days", type=int, default=settings.refresh_lookback_days)
    parser.add_argument("--reuse-latest", action="store_true")
    parser.add_argument("--fsc-cell-m", type=int, default=100)
    parser.add_argument("--gfsc-cell-m", type=int, default=120)
    args = parser.parse_args()

    result = prepare_area(
        products=args.product or ["FSC", "GFSC"],
        bbox=args.bbox,
        lookback_days=args.lookback_days,
        reuse_latest=args.reuse_latest,
        fsc_cell_m=args.fsc_cell_m,
        gfsc_cell_m=args.gfsc_cell_m,
    )
    print(f"Snow cells written: {len(result['features'])}")


if __name__ == "__main__":
    main()
