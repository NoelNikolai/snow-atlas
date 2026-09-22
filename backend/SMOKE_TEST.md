# WEkEO zuerst prüfen

Dieser Test bleibt absichtlich klein: Er prüft Login, Katalog und eine auf drei
Treffer begrenzte FSC-/GFSC-Suche über Stubai und Ötztal. Standardmäßig wird
keine Produktdatei heruntergeladen.

1. `backend/.env.example` als `backend/.env` speichern.
2. Dort `HDA_USER` und `HDA_PASSWORD` eintragen. Die Datei wird vom Projekt
   ignoriert und darf nicht committed werden.
3. Virtuelle Python-Umgebung anlegen und `backend/requirements-smoke.txt`
   installieren.
4. `python backend/smoke_test_wekeo.py` ausführen.

Erst wenn beide Suchen Treffer oder zumindest eine fehlerfreie leere Antwort
liefern, folgt `python backend/smoke_test_wekeo.py --resolve-url`. Dieser zweite
Lauf lässt WEkEO eine Download-URL erzeugen, lädt aber weiterhin keine große
Datei herunter.

Ein einzelnes, bewusst ausgewähltes Beispiel kann anschließend mit
`python backend/smoke_test_wekeo.py --dataset gfsc --download-sample`
nach `backend/data/smoke` geladen werden. Das Verzeichnis wird nicht versioniert.
