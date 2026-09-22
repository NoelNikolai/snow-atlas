from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.jobs.fetch_products import fetch_newest_scenes
from app.processing.scenes import import_archive
from app.storage.scene_catalog import Scene, SceneCatalog


def import_local_archives() -> list[Scene]:
    """Register every WEkEO ZIP already on disk (data/raw and data/smoke) without downloading."""

    settings = get_settings()
    catalog = SceneCatalog(settings.scenes_dir)
    archives = sorted(
        [*settings.data_dir.glob("raw/*/*.zip"), *settings.data_dir.glob("smoke/*.zip")]
    )
    if not archives:
        raise FileNotFoundError("No cached archives found. Run with --bbox first.")
    scenes = []
    for archive in archives:
        scene = import_archive(archive, catalog)
        print(f"{scene.product:<4} {scene.tile_id} {scene.observed_at}  {archive.name}")
        scenes.append(scene)
    return scenes


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Download the newest FSC/GFSC scenes for an area and prepare them for map tiles"
    )
    parser.add_argument("--product", action="append", choices=["FSC", "GFSC"])
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--lookback-days", type=int, default=settings.refresh_lookback_days)
    parser.add_argument(
        "--reuse-latest",
        action="store_true",
        help="only import ZIPs that are already downloaded, no WEkEO request",
    )
    args = parser.parse_args()

    if args.reuse_latest:
        scenes = import_local_archives()
    else:
        if not args.bbox:
            parser.error("--bbox is required unless --reuse-latest is given")
        scenes = fetch_newest_scenes(
            settings,
            bbox=args.bbox,
            products=args.product or ["FSC", "GFSC"],
            lookback_days=args.lookback_days,
        )
    print(f"Scenes ready: {len(scenes)} → {settings.scenes_dir}")


if __name__ == "__main__":
    main()
