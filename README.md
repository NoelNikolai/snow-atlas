# Snow Atlas

Snow Atlas ist ein erster Full-Stack-MVP für die Frage: **Wo liegt an meinem Ziel aktuell Schnee?**

Der Nutzer startet ohne Karte, sucht einen Ort, eine Adresse oder Koordinaten und erhält anschließend eine interaktive Satellitenkarte. FSC- und GFSC-Schneedaten von WEkEO werden als anklickbare Abschnitte dargestellt. Pro Abschnitt zeigt die Oberfläche Schneebedeckung, Beobachtungszeit/AT, Wolken beziehungsweise AT-Zeitraum, native Auflösung und Anteil gültiger Pixel.

## Aktueller Testfall

Der vorbereitete reale Datenausschnitt deckt **Farchant bis Hoher Fricken** ab:

- FSC-Quelldaten: 20 m, Anzeigeabschnitte ca. 100 m
- GFSC-Quelldaten: 60 m, Anzeigeabschnitte ca. 120 m
- Suche nach `Farchant`, `Hoher Fricken`, Koordinaten oder einer Adresse
- 31.619 lokal vorbereitete, anklickbare Abschnitte
- private Web-Vorschau mit einem kompakten echten WEkEO-Snapshot in 240-m-Abschnitten
- aktuell erkanntes Ergebnis im Ausschnitt: 0 % Schnee; die App zeigt bewusst keine erfundene Schneeauflage

## Architektur

```text
app/, components/, lib/       React/Vinext-Frontend mit MapLibre
backend/app/api/              FastAPI-Endpunkte
backend/app/providers/        WEkEO/HDA-Zugriff
backend/app/processing/       GeoTIFF- und AT-Verarbeitung
backend/app/jobs/             kleine, einzeln ausführbare Datenjobs
backend/app/storage/          lokaler GeoJSON-Speicher
```

Die Zugangsdaten bleiben ausschließlich im Python-Backend. `backend/.env`, Downloads und verarbeitete Daten sind von Git ausgeschlossen.

## Lokal starten

Voraussetzungen: Python 3.12+, Node.js 22.13+ und pnpm.

```bash
cp backend/.env.example backend/.env
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
pnpm install
```

In `backend/.env` nur lokal eintragen:

```dotenv
HDA_USER=...
HDA_PASSWORD=...
```

Echte Daten für den Farchant-Testausschnitt laden und hochauflösend vorbereiten:

```bash
cd backend
../.venv/bin/python -m app.jobs.prepare_area \
  --bbox 11.02 47.45 11.19 47.59
```

Bereits geladene ZIPs lassen sich ohne neuen WEkEO-Download erneut verarbeiten:

```bash
../.venv/bin/python -m app.jobs.prepare_area \
  --bbox 11.02 47.45 11.19 47.59 \
  --reuse-latest
```

Backend und Frontend in zwei Terminals starten:

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
pnpm dev
```

Danach `http://localhost:5173` öffnen und nach **Farchant** suchen.

## API

- `GET /api/v1/health`
- `GET /api/v1/snow/status`
- `GET /api/v1/snow/cells?west=…&south=…&east=…&north=…`
- `GET /api/v1/geocode/search?q=…`
- Swagger UI: `http://127.0.0.1:8000/docs`

## Karten- und Suchanbieter

Mit `NEXT_PUBLIC_MAPTILER_KEY` verwendet die App MapTiler Satellite. Ohne Key nutzt der lokale, nichtkommerzielle MVP EOxCloudless 2025. EOxCloudless ist in dieser Form nur für nichtkommerzielle Nutzung freigegeben; vor einer kommerziellen Veröffentlichung muss ein passender Satellitenkartenvertrag gewählt werden.

Die freie Adresssuche nutzt die öffentliche Nominatim-Instanz nur nach ausdrücklichem Absenden, nie als Autocomplete. Der Server begrenzt Anfragen auf höchstens eine pro Sekunde und cached identische Suchen. Für Produktion oder größere Nutzerzahlen muss eine eigene Instanz oder ein kommerzieller Geocoder eingesetzt werden. Es gilt die [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/).

## Datenjobs

- `smoke_test_wekeo.py`: Login, Suche, Download-URL und optionaler Beispieldownload
- `app.jobs.prepare_area`: sucht/lädt FSC und GFSC und bereitet einen kleinen hochauflösenden Suchausschnitt vor
- `app.jobs.refresh_snow`: allgemeiner, gröberer Refresh
- `app.jobs.seed_from_samples`: verarbeitet vorhandene Smoke-Test-ZIPs

## MVP-Grenzen

- Der Python-Dienst läuft derzeit lokal und ist noch nicht separat gehostet.
- Die private Web-Vorschau nutzt für Farchant/Hoher Fricken einen klar markierten, echten WEkEO-Snapshot; die lokale Version lädt den feineren 100/120-m-Ausschnitt über die Python-API.
- Der vorbereitete echte Datensatz ist auf Farchant/Hoher Fricken begrenzt. Weitere Orte benötigen einen neuen `prepare_area`-Lauf oder später einen Queue-/Cache-Dienst.
- Die App visualisiert Schneelage, aber plant noch keine Wanderroute und ersetzt keine Lawinen- oder Sicherheitsinformation.
