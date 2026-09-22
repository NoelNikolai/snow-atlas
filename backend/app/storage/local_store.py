from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class LocalGeoJsonStore:
    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, feature_collection: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(feature_collection, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            temporary.replace(self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
