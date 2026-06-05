# README - Implementacion multiagente

Este directorio contiene la implementacion Python del sistema multiagente de
comercio electronico. La guia general del repositorio esta en
[README.md](../README.md).

## Arranque rapido

```bash
# Desde la raiz del repo, con venv activado:
cd src
bash develop.sh
```

Interfaz web: `http://127.0.0.1:9010/iface`

## Scripts de despliegue

| Script | Uso |
| --- | --- |
| `develop.sh` | Levanta el stack completo en la maquina actual |
| `distributed.sh` | Levanta **un solo agente** para despliegue en varias maquinas |

Ejemplo distribuido (en cada maquina):

```bash
DIR_HOST=<ip-directorio> HOSTADDR=<ip-esta-maquina> ./distributed.sh <agente> [puerto]
```

Guia completa: [doc/distributed-demo.md](../doc/distributed-demo.md)

Agentes soportados por `distributed.sh`:

`directorio`, `transportista_express`, `transportista_eco`,
`transportista_externo`, `cl_bcn`, `cl_mad`, `proveedor_pagos`,
`financiero`, `feedback`, `vendedor_externo`, `comerciante`, `catalogo`,
`devolucion`, `asistente`

## Clientes de prueba (CLI)

```bash
PYTHONPATH=. python -m assistant_demo \
  --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm

PYTHONPATH=. python -m feedback_demo \
  --feedback-url http://127.0.0.1:9007/comm --simulate-notify

PYTHONPATH=. python -m devolucion_demo \
  --catalog-url http://127.0.0.1:9006/comm \
  --shop-url http://127.0.0.1:9001/comm \
  --devolucion-url http://127.0.0.1:9009/comm
```

## Juegos de prueba

Escenarios reproducibles para la entrega y defensa:
[JUEGOS_PRUEBA.md](JUEGOS_PRUEBA.md)

## Tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```
