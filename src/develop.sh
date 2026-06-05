#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configurable vía variables de entorno para poder lanzar el sistema
# desde otra máquina o detrás de NAT. Por defecto sigue siendo localhost.
DIR_HOST="${DIR_HOST:-127.0.0.1}"
DIR_PORT="${DIR_PORT:-9000}"
DIR_URL="${DIR_URL:-http://${DIR_HOST}:${DIR_PORT}}"
HOSTADDR="${HOSTADDR:-127.0.0.1}"

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

# Lotes: agrupar al AvisarCL; sondeo CiertaHoraDia + ventana de inactividad antes de despachar.
export LOT_DISPATCH_INTERVAL="${LOT_DISPATCH_INTERVAL:-10}"
export LOT_DEBOUNCE_SECONDS="${LOT_DEBOUNCE_SECONDS:-30}"
export LOT_URGENT_DEBOUNCE="${LOT_URGENT_DEBOUNCE:-5}"
export LOT_MAX_LINES="${LOT_MAX_LINES:-8}"
# El comerciante debe esperar al menos: debounce + intervalo de sondeo + margen CFP transportistas.
: "${SHIPPING_CONFIRMATION_TIMEOUT:=$((LOT_DEBOUNCE_SECONDS + LOT_DISPATCH_INTERVAL + 15))}"
export SHIPPING_CONFIRMATION_TIMEOUT
: "${ORDER_TIMEOUT:=$((SHIPPING_CONFIRMATION_TIMEOUT + 25))}"
export ORDER_TIMEOUT

start_agent "DirectoryService" "$PYTHON" -m agents.directorio --port "$DIR_PORT" --open --hostaddr "$HOSTADDR"
sleep 1
# Dos transportistas con tarifas distintas; el centro logístico negocia
# Contract Net en paralelo y elige la mejor oferta.
start_agent "TransportistaExpress" "$PYTHON" -m agents.transportista --port 9003 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --tarifa-base 4.50 --tarifa-kg 1.75 --tarifa-dia 0.80
sleep 0.5
start_agent "TransportistaEco" "$PYTHON" -m agents.transportista --port 9011 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --tarifa-base 3.00 --tarifa-kg 2.50 --tarifa-dia 0.50
sleep 0.5
# Transportista proporcionado por un tercero, con tarifa fija  
start_agent "TransportistaExterno" "$PYTHON" -m agents.transportista_externo --port 9014 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --preu "${TRANSPORTISTA_PREU:-5.50}" --dies "${TRANSPORTISTA_DIES:-3}"
sleep 0.5

# Dos centros logísticos; el comerciante contacta cada CL en orden de
# proximidad a la dirección de entrega (|dist_CL - dist_entrega|).
# Cada CL ofrece todos los productos logísticos del catálogo (defecto --stock-products *).
start_agent "CentroLogisticoBCN" "$PYTHON" -m agents.agente_logistico --port 9002 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --center-id CL-BCN --center-city Barcelona --dist 130
sleep 0.5
start_agent "CentroLogisticoMAD" "$PYTHON" -m agents.agente_logistico --port 9012 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --center-id CL-MAD --center-city Madrid --dist 500
sleep 0.5
start_agent "ProveedorPagos" "$PYTHON" -m agents.proveedor_pagos --port 9004 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"
sleep 0.5
start_agent "AgenteFinanciero" "$PYTHON" -m agents.agente_financiero --port 9005 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --provider-url "http://${HOSTADDR}:9004"
sleep 0.5
# Feedback con scheduler proactivo y delay corto para la demo.
start_agent "AgenteFeedback" "$PYTHON" -m agents.agente_feedback --port 9007 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --feedback-delay 60 --recommendation-period 120 --recommendation-warmup 30
sleep 0.5
start_agent "Tienda" "$PYTHON" -m agents.agente_comerciante --port 9001 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"
sleep 0.5
start_agent "AgenteCatalogo" "$PYTHON" -m agents.agente_catalogo --port 9006 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"
sleep 0.5
# Tras el catálogo: anuncia P-CARGADOR-GAN (envío externo) vía DarAltaProductoExterno.
start_agent "VendedorExterno" "$PYTHON" -m agents.vendedor_externo --port 9008 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR" --announce-products
sleep 0.5
start_agent "AgenteDevolucion" "$PYTHON" -m agents.agente_devolucion --port 9009 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"
sleep 0.5
start_agent "AsistenteVirtual" "$PYTHON" -m agents.asistente --port 9010 --dir "$DIR_URL" --open --hostaddr "$HOSTADDR"

echo
echo "Agents are running."
echo "Run the demo in another terminal with:"
echo "  cd $SCRIPT_DIR && PYTHONPATH=$SCRIPT_DIR $PYTHON -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm"
echo "  cd $SCRIPT_DIR && PYTHONPATH=$SCRIPT_DIR $PYTHON -m devolucion_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm --devolucion-url http://127.0.0.1:9009/comm"
echo "  Interfaz web: http://127.0.0.1:9010/iface"
echo
read -r -n 1 -s -p "Press any key to stop all agents..."
echo
