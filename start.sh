#!/usr/bin/env bash
# Startet Snow Atlas lokal: FastAPI-Backend (Port 8000) und Frontend (Port 5173).
# Aufruf: ./start.sh            startet beides und öffnet den Browser
#         ./start.sh --no-open  startet beides ohne Browser
# Beenden mit Ctrl+C – beide Prozesse werden gemeinsam gestoppt.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
OPEN_BROWSER=1
[[ "${1:-}" == "--no-open" ]] && OPEN_BROWSER=0

info() { printf '\033[36m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for_port() {
  local port=$1 name=$2
  for _ in $(seq 1 60); do
    port_in_use "$port" && return 0
    sleep 0.5
  done
  warn "$name antwortet nach 30 s noch nicht auf Port $port."
}

find_node() {
  if command -v node >/dev/null 2>&1; then command -v node; return; fi
  local candidate
  for candidate in \
    /opt/homebrew/bin/node \
    /usr/local/bin/node \
    "$HOME"/.nvm/versions/node/*/bin/node \
    "$HOME"/.cache/codex-runtimes/*/dependencies/node/bin/node; do
    [[ -x "$candidate" ]] && { echo "$candidate"; return; }
  done
  return 1
}

cd "$ROOT"

# --- Python-Backend vorbereiten ---------------------------------------------
if [[ ! -x .venv/bin/python ]]; then
  info "Lege Python-Umgebung (.venv) an …"
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi
[[ -f backend/.env ]] || warn "backend/.env fehlt – WEkEO-Downloads gehen ohne Zugangsdaten nicht (vorbereitete Daten schon)."
[[ -f backend/data/processed/snow_cells.geojson ]] || warn "Keine vorbereiteten Schneedaten – siehe README, Abschnitt prepare_area."

# --- Frontend vorbereiten ----------------------------------------------------
NODE_BIN="$(find_node)" || fail "Node.js nicht gefunden. Bitte Node 22.13+ installieren (z. B. brew install node)."
export PATH="$(dirname "$NODE_BIN"):$ROOT/node_modules/.bin:$PATH"
[[ -d node_modules ]] || fail "node_modules fehlt. Einmalig 'pnpm install' ausführen."

# --- Starten -----------------------------------------------------------------
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  if ((${#PIDS[@]})); then
    info "Stoppe Snow Atlas …"
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

if port_in_use "$BACKEND_PORT"; then
  warn "Port $BACKEND_PORT ist belegt – nutze das bereits laufende Backend."
else
  info "Starte Backend auf http://127.0.0.1:$BACKEND_PORT"
  (cd backend && exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload) \
    > >(sed -u 's/^/[backend]  /') 2>&1 &
  PIDS+=($!)
fi

if port_in_use "$FRONTEND_PORT"; then
  warn "Port $FRONTEND_PORT ist belegt – nutze das bereits laufende Frontend."
else
  info "Starte Frontend auf http://localhost:$FRONTEND_PORT"
  "$NODE_BIN" scripts/run-framework.mjs dev > >(sed -u 's/^/[frontend] /') 2>&1 &
  PIDS+=($!)
fi

wait_for_port "$BACKEND_PORT" "Backend"
wait_for_port "$FRONTEND_PORT" "Frontend"
info "Snow Atlas läuft: http://localhost:$FRONTEND_PORT  (API-Doku: http://127.0.0.1:$BACKEND_PORT/docs)"
((OPEN_BROWSER)) && command -v open >/dev/null && open "http://localhost:$FRONTEND_PORT"

if ((${#PIDS[@]})); then
  info "Beenden mit Ctrl+C"
  wait
fi
