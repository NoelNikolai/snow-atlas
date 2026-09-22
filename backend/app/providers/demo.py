from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


DEMO_CELLS = [
    ("AT-07-STB", "Stubai · Tirol", "FSC", 82, [10.92, 46.88, 11.42, 47.18], 7, 20, 2_380),
    ("AT-07-OET", "Ötztal · Tirol", "GFSC", 68, [10.45, 46.72, 10.92, 47.10], 4, 60, 2_460),
    ("AT-05-TAU", "Hohe Tauern", "GFSC", 89, [12.42, 46.82, 13.15, 47.25], 5, 60, 2_540),
    ("IT-32-DOL", "Dolomiten", "FSC", 38, [11.82, 46.34, 12.48, 46.74], 18, 20, 2_120),
    ("CH-BE-JUN", "Berner Alpen", "GFSC", 71, [7.55, 46.26, 8.18, 46.68], 8, 60, 2_350),
    ("FR-ARA-MBL", "Mont Blanc", "FSC", 93, [6.68, 45.72, 7.12, 46.10], 3, 20, 2_710),
]


def demo_feature_collection() -> dict[str, Any]:
    now = datetime.now(UTC)
    features: list[dict[str, Any]] = []

    for index, (cell_id, region, product, coverage, bounds, cloud, resolution, elevation) in enumerate(DEMO_CELLS):
        west, south, east, north = bounds
        observed = now - timedelta(hours=2 + index * 3)
        features.append(
            {
                "type": "Feature",
                "id": cell_id,
                "properties": {
                    "cell_id": cell_id,
                    "region_name": region,
                    "product": product,
                    "coverage_percent": coverage,
                    "observed_at": observed.isoformat().replace("+00:00", "Z"),
                    "cloud_percent": cloud,
                    "resolution_m": resolution,
                    "elevation_m": elevation,
                    "confidence": "hoch" if cloud <= 12 else "mittel",
                    "source": "demo",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]],
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "mode": "demo",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "products": ["FSC", "GFSC"],
        },
    }
