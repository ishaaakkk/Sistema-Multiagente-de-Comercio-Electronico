#!/usr/bin/env bash
#
# Lanza UN solo agente del sistema en la máquina actual.
# Pensado para la demo realmente distribuida (criterio 3.6 del guión).
# Parámetros de lote/timeouts y PYTHONPATH alineados con develop.sh.
#
# Ejemplos de uso (en cada máquina/contenedor):
#
#   # En la máquina del directorio:
#   DIR_HOST=10.0.0.1 DIR_PORT=9000 HOSTADDR=10.0.0.1 \
#       ./distributed.sh directorio
#
#   # En la máquina de los transportistas:
#   DIR_HOST=10.0.0.1 DIR_PORT=9000 HOSTADDR=10.0.0.2 \
#       ./distributed.sh transportista_express 9003
#
#   # En la máquina del centro logístico Madrid:
#   DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.3 \
#       ./distributed.sh cl_mad 9012
#
#   # Financiero en otra máquina que el proveedor de pagos:
#   DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.16 PROVEEDOR_HOSTADDR=10.0.0.15 \
#       ./distributed.sh financiero 9005
#
# El flag `--open` hace que Flask escuche en 0.0.0.0; `--hostaddr` es la
# dirección con la que el agente se anuncia al directorio (debe ser
# accesible desde los demás).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"

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

DIR_HOST="${DIR_HOST:-127.0.0.1}"
DIR_PORT="${DIR_PORT:-9000}"
DIR_URL="${DIR_URL:-http://${DIR_HOST}:${DIR_PORT}}"
HOSTADDR="${HOSTADDR:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
HOSTADDR="${HOSTADDR:-127.0.0.1}"
PROVEEDOR_HOSTADDR="${PROVEEDOR_HOSTADDR:-$HOSTADDR}"
PROVEEDOR_PORT="${PROVEEDOR_PORT:-9004}"
PROVEEDOR_URL="http://${PROVEEDOR_HOSTADDR}:${PROVEEDOR_PORT}"

# Mismos valores que develop.sh (lotes + timeouts del comerciante).
export LOT_DISPATCH_INTERVAL="${LOT_DISPATCH_INTERVAL:-10}"
export LOT_DEBOUNCE_SECONDS="${LOT_DEBOUNCE_SECONDS:-30}"
export LOT_URGENT_DEBOUNCE="${LOT_URGENT_DEBOUNCE:-5}"
export LOT_MAX_LINES="${LOT_MAX_LINES:-8}"
: "${SHIPPING_CONFIRMATION_TIMEOUT:=$((LOT_DEBOUNCE_SECONDS + LOT_DISPATCH_INTERVAL + 15))}"
export SHIPPING_CONFIRMATION_TIMEOUT
: "${ORDER_TIMEOUT:=$((SHIPPING_CONFIRMATION_TIMEOUT + 25))}"
export ORDER_TIMEOUT

usage() {
    cat <<EOF
Uso: $(basename "$0") <agente> [puerto]

Agentes soportados (puerto por defecto):
  directorio                  9000
  transportista_express       9003
  transportista_eco           9011
  transportista_externo       9014
  cl_bcn                      9002
  cl_mad                      9012
  proveedor_pagos             9004
  financiero                  9005
  feedback                    9007
  vendedor_externo            9008
  comerciante                 9001
  catalogo                    9006
  devolucion                  9009
  asistente                   9010

Variables de entorno:
  DIR_HOST              host del directorio (default: 127.0.0.1)
  DIR_PORT              puerto del directorio (default: 9000)
  DIR_URL               URL completa del directorio (sobrescribe lo anterior)
  HOSTADDR              IP con la que este agente se anuncia (default: hostname -I)
  PROVEEDOR_HOSTADDR    IP del proveedor de pagos (solo financiero; default: HOSTADDR)
  PROVEEDOR_PORT        puerto del proveedor (default: 9004)
  LOT_DEBOUNCE_SECONDS  ventana de lote (default: 30, igual que develop.sh)
  LOT_URGENT_DEBOUNCE   debounce urgente (default: 5)
  LOT_DISPATCH_INTERVAL sondeo CL (default: 10)
  FEEDBACK_DELAY        delay PedirFeedback (default: 60)
  RECOMMENDATION_PERIOD periodo recomendaciones (default: 120)
  RECOMMENDATION_WARMUP warmup recomendador (default: 30)
  TRANSPORTISTA_PREU    precio fijo transportista externo (default: 5.50)
  TRANSPORTISTA_DIES    dias transportista externo (default: 3)
EOF
}

if [[ $# -lt 1 ]]; then
    usage
    exit 1
fi

AGENT="$1"
PORT="${2:-}"

common_args=(--dir "$DIR_URL" --open --hostaddr "$HOSTADDR")

case "$AGENT" in
    directorio)
        PORT="${PORT:-9000}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.directorio \
            --port "$PORT" --open --hostaddr "$HOSTADDR"
        ;;
    transportista_express)
        PORT="${PORT:-9003}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.transportista \
            --port "$PORT" "${common_args[@]}" \
            --tarifa-base 4.50 --tarifa-kg 1.75 --tarifa-dia 0.80
        ;;
    transportista_eco)
        PORT="${PORT:-9011}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.transportista \
            --port "$PORT" "${common_args[@]}" \
            --tarifa-base 3.00 --tarifa-kg 2.50 --tarifa-dia 0.50
        ;;
    transportista_externo)
        PORT="${PORT:-9014}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.transportista_externo \
            --port "$PORT" "${common_args[@]}" \
            --preu "${TRANSPORTISTA_PREU:-5.50}" \
            --dies "${TRANSPORTISTA_DIES:-3}"
        ;;
    cl_bcn)
        PORT="${PORT:-9002}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_logistico \
            --port "$PORT" "${common_args[@]}" \
            --center-id CL-BCN --center-city Barcelona --dist 130
        ;;
    cl_mad)
        PORT="${PORT:-9012}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_logistico \
            --port "$PORT" "${common_args[@]}" \
            --center-id CL-MAD --center-city Madrid --dist 500
        ;;
    proveedor_pagos)
        PORT="${PORT:-9004}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.proveedor_pagos \
            --port "$PORT" "${common_args[@]}"
        ;;
    financiero)
        PORT="${PORT:-9005}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_financiero \
            --port "$PORT" "${common_args[@]}" \
            --provider-url "$PROVEEDOR_URL"
        ;;
    feedback)
        PORT="${PORT:-9007}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_feedback \
            --port "$PORT" "${common_args[@]}" \
            --feedback-delay "${FEEDBACK_DELAY:-60}" \
            --recommendation-period "${RECOMMENDATION_PERIOD:-120}" \
            --recommendation-warmup "${RECOMMENDATION_WARMUP:-30}"
        ;;
    vendedor_externo)
        PORT="${PORT:-9008}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.vendedor_externo \
            --port "$PORT" "${common_args[@]}" --announce-products
        ;;
    comerciante)
        PORT="${PORT:-9001}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_comerciante \
            --port "$PORT" "${common_args[@]}"
        ;;
    catalogo)
        PORT="${PORT:-9006}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_catalogo \
            --port "$PORT" "${common_args[@]}"
        ;;
    devolucion)
        PORT="${PORT:-9009}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.agente_devolucion \
            --port "$PORT" "${common_args[@]}"
        ;;
    asistente)
        PORT="${PORT:-9010}"
        exec env PYTHONPATH="$PYTHONPATH" "$PYTHON" -m agents.asistente \
            --port "$PORT" "${common_args[@]}"
        ;;
    *)
        echo "Agente desconocido: $AGENT"
        usage
        exit 1
        ;;
esac
