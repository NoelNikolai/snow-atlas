from __future__ import annotations

import json
import threading
import time
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query


router = APIRouter(prefix="/geocode", tags=["geocode"])
_request_lock = threading.Lock()
_last_request_at = 0.0


@lru_cache(maxsize=256)
def _nominatim_search(query: str) -> dict:
    global _last_request_at

    parameters = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "accept-language": "de",
        }
    )
    request = Request(
        f"https://nominatim.openstreetmap.org/search?{parameters}",
        headers={
            "User-Agent": "SnowAtlas-MVP/0.1 (https://snow-atlas-alps.quirky-wave-1060.chatgpt.site)",
            "Accept": "application/json",
        },
    )

    with _request_lock:
        delay = 1.05 - (time.monotonic() - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        try:
            with urlopen(request, timeout=8) as response:
                payload = json.load(response)
        except Exception as error:
            raise RuntimeError("OpenStreetMap search is currently unavailable") from error
        finally:
            _last_request_at = time.monotonic()

    if not payload:
        raise LookupError("No matching place found")
    match = payload[0]
    return {
        "display_name": match["display_name"],
        "latitude": float(match["lat"]),
        "longitude": float(match["lon"]),
        "boundingbox": [float(value) for value in match.get("boundingbox", [])],
        "source": "OpenStreetMap Nominatim",
    }


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=180)) -> dict:
    query = " ".join(q.split())
    try:
        return _nominatim_search(query)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
