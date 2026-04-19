#!/usr/bin/env bash
# Demo preflight targets: Python >= 3.10 and Node >= 18.
# Starts the FastAPI backend on :8000 and the Vite frontend on :3000.

set -euo pipefail

BACKEND_PORT=8000
FRONTEND_PORT=3000
BACKEND_LOG=/tmp/gwgpt-backend.log
FRONTEND_LOG=/tmp/gwgpt-frontend.log

backend_pid=""
frontend_pid=""

cleanup() {
  if [[ -n "${backend_pid}" ]]; then
    kill "${backend_pid}" 2>/dev/null || true
  fi
  if [[ -n "${frontend_pid}" ]]; then
    kill "${frontend_pid}" 2>/dev/null || true
  fi
}

require_major_version() {
  local name="$1"
  local command="$2"
  local minimum="$3"
  local version
  local major

  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "${name} is required but was not found." >&2
    exit 1
  fi

  version="$("${command}" --version | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
  major="${version%%.*}"
  if [[ -z "${major}" || "${major}" -lt "${minimum}" ]]; then
    echo "${name} ${minimum}+ is required; found $("${command}" --version)." >&2
    exit 1
  fi
}

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti :"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping stale process on :${port}"
    echo "${pids}" | xargs kill -9 2>/dev/null || true
  fi
}

wait_for_backend() {
  local url="http://127.0.0.1:${BACKEND_PORT}/api/chat/status"
  for _ in {1..20}; do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "Backend did not become healthy within 20s. Last backend log lines:" >&2
  tail -40 "${BACKEND_LOG}" >&2 || true
  exit 1
}

trap cleanup SIGINT SIGTERM EXIT

require_major_version "Python" python3 3
python_minor="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [[ "${python_minor}" -lt 10 ]]; then
  echo "Python 3.10+ is required; found $(python3 --version)." >&2
  exit 1
fi
require_major_version "Node" node 18

kill_port "${BACKEND_PORT}"
kill_port "${FRONTEND_PORT}"

: > "${BACKEND_LOG}"
: > "${FRONTEND_LOG}"

GROUNDWATERGPT_SKIP_AGENT_INIT=1 uvicorn api.main:app --port "${BACKEND_PORT}" \
  > >(tee -a "${BACKEND_LOG}") 2>&1 &
backend_pid="$!"

wait_for_backend

(
  cd frontend
  VITE_GROUNDWATER_SHOWCASE_MODE="${VITE_GROUNDWATER_SHOWCASE_MODE:-true}" \
    npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
) > >(tee -a "${FRONTEND_LOG}") 2>&1 &
frontend_pid="$!"

echo "Demo ready: http://localhost:${FRONTEND_PORT}"
echo "Backend log: ${BACKEND_LOG}"
echo "Frontend log: ${FRONTEND_LOG}"

tail -f "${BACKEND_LOG}" "${FRONTEND_LOG}" &
tail_pid="$!"
wait "${backend_pid}" "${frontend_pid}"
kill "${tail_pid}" 2>/dev/null || true
