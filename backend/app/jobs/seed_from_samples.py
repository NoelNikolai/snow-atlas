from __future__ import annotations

from app.core.config import get_settings
from app.processing.raster_to_cells import merge_feature_collections, process_product_zip
from app.storage.local_store import LocalGeoJsonStore


def main() -> None:
    settings = get_settings()
    sample_directory = settings.data_dir / "smoke"
    archives = sorted(sample_directory.glob("*.zip"))
    if not archives:
        raise FileNotFoundError(f"No sample ZIPs found in {sample_directory}")

    collections = []
    for archive in archives:
        product = "GFSC" if "_GFSC_" in archive.name else "FSC" if "_FSC_" in archive.name else None
        if product is None:
            continue
        collection = process_product_zip(
            archive,
            product,
            cell_size_m=settings.snow_cell_size_m,
            minimum_snow_percent=settings.snow_min_percent,
        )
        collections.append(collection)
        print(f"{product}: {len(collection['features'])} cells from {archive.name}")

    merged = merge_feature_collections(collections)
    LocalGeoJsonStore(settings.processed_geojson).write(merged)
    print(f"Combined cache: {len(merged['features'])} cells → {settings.processed_geojson}")


if __name__ == "__main__":
    main()
