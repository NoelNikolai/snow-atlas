from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Scene:
    """One extracted FSC/GFSC product (one Sentinel-2 tile, one date)."""

    product_id: str
    product: str
    tile_id: str
    observed_at: str | None
    directory: str
    snow_file: str
    quality_file: str
    flags_file: str
    at_file: str | None
    bounds_wgs84: list[float]
    footprint: list[list[float]]
    resolution_m: float
    imported_at: str

    def path(self, root: Path, name: str | None) -> Path | None:
        return root / self.directory / name if name else None

    @property
    def observed(self) -> datetime | None:
        return datetime.fromisoformat(self.observed_at.replace("Z", "+00:00")) if self.observed_at else None

    def intersects(self, bbox: list[float]) -> bool:
        west, south, east, north = bbox
        scene_west, scene_south, scene_east, scene_north = self.bounds_wgs84
        return not (scene_east < west or scene_west > east or scene_north < south or scene_south > north)


class SceneCatalog:
    """Small JSON index of extracted scenes under ``data/scenes``."""

    _lock = threading.Lock()

    def __init__(self, root: Path):
        self.root = root
        self.index_path = root / "catalog.json"

    def scenes(self) -> list[Scene]:
        if not self.index_path.is_file():
            return []
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [Scene(**item) for item in payload.get("scenes", [])]

    def version(self) -> str:
        if not self.index_path.is_file():
            return "0"
        return str(int(self.index_path.stat().st_mtime))

    def active(self, product: str, bbox: list[float] | None = None) -> list[Scene]:
        """Newest scene per Sentinel-2 tile, oldest first so newer data paints last."""

        newest: dict[str, Scene] = {}
        for scene in self.scenes():
            if scene.product != product or (bbox and not scene.intersects(bbox)):
                continue
            current = newest.get(scene.tile_id)
            if current is None or (scene.observed_at or "") > (current.observed_at or ""):
                newest[scene.tile_id] = scene
        return sorted(newest.values(), key=lambda scene: scene.observed_at or "")

    def get(self, product_id: str) -> Scene | None:
        return next((scene for scene in self.scenes() if scene.product_id == product_id), None)

    def add(self, scene: Scene) -> None:
        with self._lock:
            scenes = [item for item in self.scenes() if item.product_id != scene.product_id]
            scenes.append(scene)
            scenes.sort(key=lambda item: (item.product, item.tile_id, item.observed_at or ""))
            self._write({"scenes": [asdict(item) for item in scenes]})

    def _write(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=self.root, prefix=".catalog.", suffix=".tmp")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=1)
                handle.write("\n")
            temporary.replace(self.index_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
