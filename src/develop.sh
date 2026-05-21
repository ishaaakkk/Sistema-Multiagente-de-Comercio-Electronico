#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIR_HOST="127.0.0.1"
DIR_PORT="9000"
DIR_URL="http://${DIR_HOST}:${DIR_PORT}"
HOSTADDR="127.0.0.1"

if [[ -x "../.venv/bin/python" ]]; then
    PYTHON="../.venv/bin/python"
elif [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

if [[ -z "${PYTHON:-}" ]]; then
    echo "Python interpreter not found."
    exit 1
fi

PIDS=()
NAMES=()

start_agent() {
    local name="$1"
    shift
    echo "Starting ${name}..."
    PYTHONPATH="$SCRIPT_DIR" "$@" &
    local pid=$!
    PIDS+=("$pid")
    NAMES+=("$name")
    echo "  -> ${name} PID: ${pid}"
}

shutdown_all() {
    echo
    echo "Stopping agents..."
    for i in "${!PIDS[@]}"; do
        local pid="${PIDS[$i]}"
        local name="${NAMES[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping ${name} (${pid})"
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "${PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
}

trap shutdown_all EXIT INT TERM

start_agent "DirectoryService" "$PYTHON" -m agents.directory_service --port "$DIR_PORT" --open --hostaddr "$HOSTADDR"
sleep 1
start_agent "Transportista" "$PYTHON" -m agents.transportista_agent --port 9003 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"
sleep 0.5
start_agent "CentroLogistico" "$PYTHON" -m agents.centro_logistico_agent --port 9002 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"
sleep 0.5
start_agent "Tienda" "$PYTHON" -m agents.agente_comerciante --port 9001 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"

echo
echo "Agents are running."
echo "Run the demo in another terminal with:"
echo "  cd $SCRIPT_DIR && PYTHONPATH=$SCRIPT_DIR $PYTHON -m assistant_demo --shop-url http://127.0.0.1:9001/comm"
echo
read -r -n 1 -s -p "Press any key to stop all agents..."
echo
