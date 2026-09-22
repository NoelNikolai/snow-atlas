"""Kleiner, isolierter WEkEO-Test für FSC und GFSC.

Der Standardlauf authentifiziert sich, liest den Datensatzkatalog und sucht
höchstens drei Produkte. Es werden keine großen Produktdateien heruntergeladen.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hda import Client, Configuration


DATASETS = {
    "fsc": "EO:CLMS:DAT:FSC_EUROPE_20M_DAILY_V2",
    "gfsc": "EO:CLMS:DAT:GFSC_EUROPE_60M_DAILY_V1",
}

# Kleine Box über Stubai/Ötztal; Reihenfolge: west, south, east, north.
DEFAULT_BBOX = [10.75, 46.75, 11.55, 47.25]


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def as_query(self) -> dict[str, str]:
        return {
            "startdate": self.start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "enddate": self.end.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
        }


def load_local_credentials() -> None:
    """Lädt ausschließlich HDA_USER/HDA_PASSWORD aus backend/.env."""

    env_file = Path(__file__).with_name(".env")
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"HDA_USER", "HDA_PASSWORD"} or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def selected_datasets(selection: str) -> list[tuple[str, str]]:
    if selection == "all":
        return list(DATASETS.items())
    return [(selection, DATASETS[selection])]


def parse_args() -> argparse.Namespace:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(
        description="WEkEO FSC/GFSC Smoke-Test ohne großen Download",
    )
    parser.add_argument("--dataset", choices=["all", *DATASETS], default="all")
    parser.add_argument("--days", type=int, default=14, help="Suchfenster rückwärts ab heute")
    parser.add_argument(
        "--resolve-url",
        action="store_true",
        help="Zusätzlich die erste Download-URL auflösen, aber keine Datei laden",
    )
    parser.add_argument(
        "--probe-url",
        action="store_true",
        help="Download-URL per HEAD prüfen und gemeldete Dateigröße anzeigen",
    )
    parser.add_argument(
        "--download-sample",
        action="store_true",
        help="Genau das erste gefundene Produkt nach backend/data/smoke laden",
    )
    parser.set_defaults(now=now)
    return parser.parse_args()


def result_id(result: dict[str, object]) -> str:
    return str(result.get("id") or result.get("title") or "(ohne ID)")


def probe_download_url(client: Client, url: str) -> tuple[int, str, str, str]:
    response = client.session.head(url, allow_redirects=True, timeout=30)
    method = "HEAD"
    if response.status_code >= 400:
        response.close()
        response = client.session.get(
            url,
            headers={"Range": "bytes=0-0"},
            allow_redirects=True,
            timeout=30,
            stream=True,
        )
        method = "GET-Handshake"
    try:
        content_range = response.headers.get("content-range", "")
        range_match = re.search(r"/(\d+)$", content_range)
        size = range_match.group(1) if range_match else response.headers.get("content-length")
        size_label = f"{int(size) / 1_048_576:.1f} MB" if size and size.isdigit() else "unbekannt"
        content_type = response.headers.get("content-type", "unbekannt")
        return response.status_code, size_label, content_type, method
    finally:
        response.close()


def run() -> int:
    args = parse_args()
    load_local_credentials()

    user = os.environ.get("HDA_USER")
    password = os.environ.get("HDA_PASSWORD")
    if not user or not password:
        print("STOP: HDA_USER oder HDA_PASSWORD fehlt.")
        print("Kopiere backend/.env.example nach backend/.env und trage die Zugangsdaten dort ein.")
        return 2

    client = Client(
        config=Configuration(user=user, password=password),
        timeout=45,
        retry_max=2,
        sleep_max=5,
        progress=False,
        max_workers=1,
    )
    window = Window(start=args.now - timedelta(days=max(1, args.days)), end=args.now)
    sample_dir = Path(__file__).parent / "data" / "smoke"
    failures = 0

    print(f"WEkEO-Verbindung: Nutzer {user[:2]}*** · Fenster {window.start.date()} bis {window.end.date()}")
    print(f"Testgebiet: {DEFAULT_BBOX}\n")

    for label, dataset_id in selected_datasets(args.dataset):
        print(f"[{label.upper()}] {dataset_id}")
        try:
            dataset = client.dataset(dataset_id)
            returned_id = dataset.get("datasetId") or dataset.get("dataset_id") or dataset_id
            print(f"  OK Katalog: {returned_id}")

            query: dict[str, object] = {
                "dataset_id": dataset_id,
                "bbox": DEFAULT_BBOX,
                **window.as_query(),
            }
            matches = client.search(query, limit=3)
            results = list(matches.results)
            print(f"  OK Suche: {len(results)} Treffer (maximal 3 angefordert)")
            for item in results:
                print(f"    - {result_id(item)}")

            if not results:
                print("  HINWEIS: Kein Treffer im aktuellen Fenster. Query funktioniert, Produktverfügbarkeit bleibt zu prüfen.")
                continue

            if args.resolve_url or args.probe_url:
                urls = matches[:1].get_download_urls(limit=1)
                print(f"  OK Download-Auflösung: {len(urls)} URL erhalten; keine Datei geladen")
                if args.probe_url and urls:
                    status, size, content_type, method = probe_download_url(client, urls[0])
                    state = "OK" if 200 <= status < 400 else "FEHLER"
                    print(f"  {state} URL-Probe ({method}): HTTP {status} · Größe {size} · {content_type}")
                    if state == "FEHLER":
                        failures += 1

            if args.download_sample:
                sample_dir.mkdir(parents=True, exist_ok=True)
                matches[:1].download(download_dir=str(sample_dir))
                print(f"  OK Beispieldownload: {sample_dir}")
        except Exception as error:  # HDA nutzt mehrere requests-basierte Fehlertypen.
            failures += 1
            print(f"  FEHLER: {type(error).__name__}: {error}")

        print()

    if failures:
        print(f"ERGEBNIS: {failures} Datensatz-Test(s) fehlgeschlagen. Noch nicht in die App integrieren.")
        return 1

    print("ERGEBNIS: Authentifizierung und Suche sind technisch erreichbar.")
    if not args.resolve_url and not args.probe_url:
        print("Nächster kleiner Schritt: denselben Test einmal mit --resolve-url ausführen.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
