from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.config import Settings
from app.jobs.fetch_products import fetch_newest_scenes


JobState = Literal["running", "done", "failed"]
AREA_RADIUS_DEG = 0.05


@dataclass
class AreaJob:
    id: str
    longitude: float
    latitude: float
    state: JobState = "running"
    message: str = "Starte …"
    scenes: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "state": self.state,
            "message": self.message,
            "scenes": self.scenes,
            "started_at": self.started_at,
        }


class AreaJobs:
    """In-process queue: one WEkEO download at a time, jobs kept in memory."""

    def __init__(self) -> None:
        self._jobs: dict[str, AreaJob] = {}
        self._lock = threading.Lock()
        self._download_lock = threading.Lock()

    def start(self, settings: Settings, longitude: float, latitude: float) -> AreaJob:
        if not settings.credentials_configured:
            raise RuntimeError("HDA_USER und HDA_PASSWORD fehlen in backend/.env")
        with self._lock:
            for job in self._jobs.values():
                if job.state == "running" and abs(job.longitude - longitude) < AREA_RADIUS_DEG and abs(job.latitude - latitude) < AREA_RADIUS_DEG:
                    return job
            job = AreaJob(id=uuid.uuid4().hex[:12], longitude=longitude, latitude=latitude)
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(settings, job), daemon=True).start()
        return job

    def get(self, job_id: str) -> AreaJob | None:
        return self._jobs.get(job_id)

    def _run(self, settings: Settings, job: AreaJob) -> None:
        def progress(message: str) -> None:
            job.message = message

        bbox = [
            job.longitude - AREA_RADIUS_DEG,
            job.latitude - AREA_RADIUS_DEG,
            job.longitude + AREA_RADIUS_DEG,
            job.latitude + AREA_RADIUS_DEG,
        ]
        try:
            progress("Wartet auf laufenden Download …")
            with self._download_lock:
                scenes = fetch_newest_scenes(
                    settings,
                    bbox=bbox,
                    products=["FSC", "GFSC"],
                    lookback_days=settings.refresh_lookback_days,
                    progress=progress,
                )
            job.scenes = [scene.product_id for scene in scenes]
            job.state = "done" if scenes else "failed"
            job.message = "Schneedaten bereit" if scenes else "WEkEO hat für diesen Ort keine aktuellen Aufnahmen"
        except Exception as error:  # surfaced to the UI, details in the server log
            job.state = "failed"
            job.message = f"Download fehlgeschlagen: {error}"
            raise


area_jobs = AreaJobs()
