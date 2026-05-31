#!/usr/bin/env bash
#
# Lanza UN solo agente del sistema en la máquina actual.
# Pensado para la demo realmente distribuida (criterio 3.6 del guión).
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
# El flag `--open` hace que Flask escuche en 0.0.0.0; `--hostaddr` es la
# dirección con la que el agente se anuncia al directorio (debe ser
# accesible desde los demás).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -x "../.venv/bin/python" ]]; then
    PYTHON="../.venv/bin/python"
elif [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

DIR_HOST="${DIR_HOST:-127.0.0.1}"
DIR_PORT="${DIR_PORT:-9000}"
DIR_URL="${DIR_URL:-http://${DIR_HOST}:${DIR_PORT}}"
HOSTADDR="${HOSTADDR:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
HOSTADDR="${HOSTADDR:-127.0.0.1}"

usage() {
    cat <<EOF
Uso: $(basename "$0") <agente> [puerto]

Agentes soportados (puerto por defecto):
  directorio                  9000
  transportista_express       9003
  transportista_eco           9011
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
  DIR_HOST    host del directorio (default: 127.0.0.1)
  DIR_PORT    puerto del directorio (default: 9000)
  DIR_URL     URL completa del directorio (sobrescribe lo anterior)
  HOSTADDR    IP con la que este agente se anuncia (default: hostname -I)
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
        # El directorio no se registra a sí mismo, no necesita --dir.
        exec "$PYTHON" -m agents.directory_service --port "$PORT" --open --hostaddr "$HOSTADDR"
        ;;
    transportista_express)
        PORT="${PORT:-9003}"
        exec "$PYTHON" -m agents.transportista_agent --port "$PORT" "${common_args[@]}" \
            --tarifa-base 4.50 --tarifa-kg 1.75 --tarifa-dia 0.80
        ;;
    transportista_eco)
        PORT="${PORT:-9011}"
        exec "$PYTHON" -m agents.transportista_agent --port "$PORT" "${common_args[@]}" \
            --tarifa-base 3.00 --tarifa-kg 2.50 --tarifa-dia 0.50
        ;;
    cl_bcn)
        PORT="${PORT:-9002}"
        exec "$PYTHON" -m agents.centro_logistico_agent --port "$PORT" "${common_args[@]}" \
            --center-id CL-BCN --center-city Barcelona \
            --stock-products "P-IPHONE19,P-EBOOK-AURORA,P-AURICULARES-BT"
        ;;
    cl_mad)
        PORT="${PORT:-9012}"
        exec "$PYTHON" -m agents.centro_logistico_agent --port "$PORT" "${common_args[@]}" \
            --center-id CL-MAD --center-city Madrid \
            --stock-products "P-BATIDORA-MINI,P-LIBRO-RUST"
        ;;
    proveedor_pagos)
        PORT="${PORT:-9004}"
        exec "$PYTHON" -m agents.proveedor_pagos_agent --port "$PORT" "${common_args[@]}"
        ;;
    financiero)
        PORT="${PORT:-9005}"
        exec "$PYTHON" -m agents.agente_financiero --port "$PORT" "${common_args[@]}"
        ;;
    feedback)
        PORT="${PORT:-9007}"
        exec "$PYTHON" -m agents.agente_feedback --port "$PORT" "${common_args[@]}" \
            --feedback-delay "${FEEDBACK_DELAY:-60}" \
            --recommendation-period "${RECOMMENDATION_PERIOD:-120}" \
            --recommendation-warmup "${RECOMMENDATION_WARMUP:-30}"
        ;;
    vendedor_externo)
        PORT="${PORT:-9008}"
        exec "$PYTHON" -m agents.agente_VendedorExterno --port "$PORT" "${common_args[@]}" --announce-products
        ;;
    comerciante)
        PORT="${PORT:-9001}"
        exec "$PYTHON" -m agents.agente_comerciante --port "$PORT" "${common_args[@]}"
        ;;
    catalogo)
        PORT="${PORT:-9006}"
        exec "$PYTHON" -m agents.agente_catalogo --port "$PORT" "${common_args[@]}"
        ;;
    devolucion)
        PORT="${PORT:-9009}"
        exec "$PYTHON" -m agents.agente_devolucion --port "$PORT" "${common_args[@]}"
        ;;
    asistente)
        PORT="${PORT:-9010}"
        exec "$PYTHON" -m agents.agente_asistente --port "$PORT" "${common_args[@]}"
        ;;
    *)
        echo "Agente desconocido: $AGENT"
        usage
        exit 1
        ;;
esac
