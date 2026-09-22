from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.processing.raster_to_cells import process_product_zip


def process_archive(archive: Path, product: str) -> dict:
    settings = get_settings()
    return process_product_zip(
        archive_path=archive,
        product=product,
        cell_size_m=settings.snow_cell_size_m,
        minimum_snow_percent=settings.snow_min_percent,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate one FSC/GFSC ZIP into GeoJSON cells")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--product", choices=["FSC", "GFSC"], required=True)
    args = parser.parse_args()
    result = process_archive(args.archive, args.product)
    print(json.dumps({"features": len(result["features"]), "metadata": result["metadata"]}, indent=2))


if __name__ == "__main__":
    main()
