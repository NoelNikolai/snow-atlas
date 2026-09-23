#!/usr/bin/env bash
# Startet Snow Atlas lokal: FastAPI-Backend (Port 8000) und Frontend (Port 5173).
# Aufruf: ./start.sh            startet beides im Vordergrund und öffnet den Browser
#         ./start.sh --no-open  startet beides ohne Browser
#         ./start.sh stop       beendet laufende Snow-Atlas-Prozesse (z. B. aus einem anderen Terminal)
# Beenden mit Ctrl+C – beide Prozesse werden gemeinsam gestoppt.
# Laufen Backend oder Frontend bereits, werden sie vorher beendet und neu gestartet.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
BACKEND_PATTERN="uvicorn app.main:app"
FRONTEND_PATTERN="run-framework.mjs dev|vinext|vite"
OPEN_BROWSER=1
COMMAND=start
for argument in "$@"; do
  case "$argument" in
    --no-open) OPEN_BROWSER=0 ;;
    stop) COMMAND=stop ;;
    *) printf 'Unbekannte Option: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

info() { printf '\033[36m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# Beendet, was auf dem Port lauscht – aber nur, wenn es ein Snow-Atlas-Prozess ist.
stop_port() {
  local port=$1 pattern=$2 name=$3 pid command directory pids
  pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true)"
  [[ -z "$pids" ]] && return 0
  for pid in $pids; do
    command="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    directory="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
    if ! grep -Eq "$pattern" <<<"$command" && [[ "$command" != *"$ROOT"* && "$directory" != "$ROOT"* ]]; then
      fail "Port $port ist von einem fremden Prozess belegt (PID $pid: $command). Bitte selbst beenden."
    fi
  done
  info "Beende laufendes $name (PID $(echo $pids | tr '\n' ' '))"
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 20); do
    port_in_use "$port" || return 0
    sleep 0.5
  done
  warn "$name reagiert nicht – erzwinge Beenden."
  kill -9 $pids 2>/dev/null || true
}

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

stop_port "$BACKEND_PORT" "$BACKEND_PATTERN" "Backend"
stop_port "$FRONTEND_PORT" "$FRONTEND_PATTERN" "Frontend"
if [[ "$COMMAND" == stop ]]; then
  info "Snow Atlas ist beendet."
  exit 0
fi

# --- Python-Backend vorbereiten ---------------------------------------------
if [[ ! -x .venv/bin/python ]]; then
  info "Lege Python-Umgebung (.venv) an …"
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi
[[ -f backend/.env ]] || warn "backend/.env fehlt – WEkEO-Downloads gehen ohne Zugangsdaten nicht (vorhandene Daten schon)."
[[ -f backend/data/scenes/catalog.json ]] || warn "Noch keine Schneedaten – sie werden bei der ersten Suche von WEkEO geladen."

# --- Frontend vorbereiten ----------------------------------------------------
NODE_BIN="$(find_node)" || fail "Node.js nicht gefunden. Bitte Node 22.13+ installieren (z. B. brew install node)."
export PATH="$(dirname "$NODE_BIN"):$ROOT/node_modules/.bin:$PATH"
[[ -d node_modules ]] || fail "node_modules fehlt. Einmalig 'pnpm install' ausführen."

# --- Starten -----------------------------------------------------------------
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  echo
  info "Stoppe Snow Atlas …"
  kill "${PIDS[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
  info "Beendet."
  exit 0
}
trap cleanup INT TERM EXIT

info "Starte Backend auf http://127.0.0.1:$BACKEND_PORT"
(cd backend && exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload) \
  > >(sed -u 's/^/[backend]  /') 2>&1 &
PIDS+=($!)

info "Starte Frontend auf http://localhost:$FRONTEND_PORT"
"$NODE_BIN" scripts/run-framework.mjs dev > >(sed -u 's/^/[frontend] /') 2>&1 &
PIDS+=($!)

wait_for_port "$BACKEND_PORT" "Backend"
wait_for_port "$FRONTEND_PORT" "Frontend"
info "Snow Atlas läuft: http://localhost:$FRONTEND_PORT  (API-Doku: http://127.0.0.1:$BACKEND_PORT/docs)"
if ((OPEN_BROWSER)) && command -v open >/dev/null; then open "http://localhost:$FRONTEND_PORT"; fi
info "Beenden mit Ctrl+C"

# Läuft, bis einer der Dienste endet oder Ctrl+C kommt; dann stoppt cleanup beide.
while kill -0 "${PIDS[0]}" 2>/dev/null && kill -0 "${PIDS[1]}" 2>/dev/null; do
  sleep 1
done
warn "Ein Dienst hat sich beendet – stoppe auch den anderen."
