# Snow Atlas

Snow Atlas ist ein erster Full-Stack-MVP für die Frage: **Wo liegt an meinem Ziel aktuell Schnee?**

Der Nutzer startet ohne Karte, sucht einen Ort, eine Adresse oder Koordinaten und erhält anschließend eine interaktive Karte. FSC- und GFSC-Schneedaten von WEkEO liegen als Rasterebene darüber. Ein Klick zeigt für den Abschnitt an dieser Stelle Schneebedeckung, Beobachtungszeit/AT, Wolken beziehungsweise AT-Zeitraum, native Auflösung und Anteil gültiger Pixel.

## So funktioniert es

- Das Backend lädt pro Sentinel-2-Kachel (ca. 110 × 110 km) die neueste FSC- (20 m, Tagesaufnahme) und GFSC-Szene (60 m, lückengefüllt über 7 Tage) von WEkEO und legt die GeoTIFFs unter `backend/data/scenes/` ab.
- Die Karte zeigt die Schneebedeckung als Rasterkacheln (`/api/v1/snow/tiles/…`), die das Backend direkt aus den GeoTIFFs rendert. Standard ist **FSC + GFSC kombiniert**: FSC hat Vorrang, wo FSC Wolken sieht, füllt GFSC auf.
- Farbskala in vier Stufen (1–25 / 26–50 / 51–75 / 76–100 %), hell nach dunkel. 0 % bleibt transparent, Wolken sind schraffiert, Bereiche ohne Daten grau abgedunkelt.
- Ein Klick auf die Karte fragt den 100-m-Abschnitt (FSC) bzw. 120-m-Abschnitt (GFSC) an dieser Stelle ab.
- Liegt ein gesuchter Ort außerhalb der geladenen Szenen, lädt die App die passenden Szenen automatisch von WEkEO nach (meist 1–3 Minuten, ca. 10–20 MB).

## Architektur

```text
app/, components/, lib/       React/Vinext-Frontend mit MapLibre
backend/app/api/              FastAPI-Endpunkte
backend/app/providers/        WEkEO/HDA-Zugriff
backend/app/processing/       Szenen-Import, Kachel-Rendering, Abschnittsstatistik
backend/app/services/         Snow-Service und Download-Jobs für neue Gebiete
backend/app/storage/          Szenenkatalog (backend/data/scenes/catalog.json)
backend/app/jobs/             CLI-Job prepare_area
```

Die Zugangsdaten bleiben ausschließlich im Python-Backend. `backend/.env`, Downloads und verarbeitete Daten sind von Git ausgeschlossen.

## Lokal starten

Voraussetzungen: Python 3.12+, Node.js 22.13+ und pnpm.

Einmalig einrichten:

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

Danach startet ein Befehl Backend und Frontend zusammen und öffnet den Browser (beenden mit Ctrl+C):

```bash
./start.sh
```

Mit `./start.sh --no-open` öffnet sich kein Browser. Laufen Backend oder Frontend schon (etwa aus einem anderen Terminal), beendet das Skript sie vorher und startet sie neu, damit Ctrl+C immer beides stoppt. Aus einem anderen Terminal lässt sich alles mit `./start.sh stop` beenden.

Neueste Szenen für ein Gebiet vorab laden, zum Beispiel für das Wettersteingebirge mit Zugspitze:

```bash
cd backend
../.venv/bin/python -m app.jobs.prepare_area --bbox 10.90 47.38 11.20 47.60
```

Bereits heruntergeladene ZIPs (`backend/data/raw`, `backend/data/smoke`) ohne neuen WEkEO-Download importieren:

```bash
../.venv/bin/python -m app.jobs.prepare_area --reuse-latest
```

## API

- `GET /api/v1/health`
- `GET /api/v1/snow/status`: geladene Szenen und Datenversion
- `GET /api/v1/snow/tiles/{combined|FSC|GFSC}/{z}/{x}/{y}.png?clouds=1`
- `GET /api/v1/snow/point?lon=…&lat=…`: Abschnittswerte für FSC und GFSC
- `GET /api/v1/snow/summary?west=…&south=…&east=…&north=…&mode=combined`: Schneefläche, Wolken und fehlende Daten im Ausschnitt
- `GET /api/v1/snow/coverage`: Umrisse der geladenen Szenen
- `POST /api/v1/snow/areas` mit `{"longitude": …, "latitude": …}` und `GET /api/v1/snow/areas/{id}`: Szenen für einen Ort nachladen
- `GET /api/v1/geocode/search?q=…`
- Swagger UI: `http://127.0.0.1:8000/docs`

## Karten- und Suchanbieter

Mit `NEXT_PUBLIC_MAPTILER_KEY` verwendet die App MapTiler Satellite. Ohne Key nutzt der lokale, nichtkommerzielle MVP EOxCloudless 2025. EOxCloudless ist in dieser Form nur für nichtkommerzielle Nutzung freigegeben; vor einer kommerziellen Veröffentlichung muss ein passender Satellitenkartenvertrag gewählt werden.

Die freie Adresssuche nutzt die öffentliche Nominatim-Instanz nur nach ausdrücklichem Absenden, nie als Autocomplete. Der Server begrenzt Anfragen auf höchstens eine pro Sekunde und cached identische Suchen. Für Produktion oder größere Nutzerzahlen muss eine eigene Instanz oder ein kommerzieller Geocoder eingesetzt werden. Es gilt die [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/).

## Datenjobs

- `smoke_test_wekeo.py`: Login, Suche, Download-URL und optionaler Beispieldownload
- `app.jobs.prepare_area`: lädt die neuesten FSC/GFSC-Szenen für eine Bounding Box oder importiert vorhandene ZIPs (`--reuse-latest`)

## MVP-Grenzen

- Der Python-Dienst läuft derzeit lokal und ist noch nicht separat gehostet.
- Die private Web-Vorschau hat kein Backend und zeigt nur den klar markierten Farchant-Snapshot (`public/data/farchant-snow.geojson`). Alle anderen Orte brauchen das lokale Backend.
- Neue Gebiete werden in einem einfachen In-Process-Job nachgeladen (ein Download gleichzeitig, Jobstatus nur im Speicher). Für mehrere Nutzer braucht es später eine echte Queue.
- Pro Sentinel-2-Kachel wird immer die neueste Szene angezeigt. Ist sie bewölkt, füllt GFSC die Lücken; ältere wolkenfreie FSC-Szenen werden nicht nachgemischt.
- Die App visualisiert Schneelage, aber plant noch keine Wanderroute und ersetzt keine Lawinen- oder Sicherheitsinformation.
