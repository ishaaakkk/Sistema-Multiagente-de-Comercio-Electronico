### Practica ECSDI

Proyecto de la practica de ECSDI basado en un sistema multiagente de
comercio electronico.

## Estructura del proyecto

- `ontology/`: ontologia OWL/RDF del dominio de comercio electronico.
  - `comercio_electronico.ttl`: ontologia principal en Turtle.
  - `catalog-v001.xml`: catalogo XML auxiliar para herramientas OWL.
- `doc/`: documentacion generada como anexo.
  - `ontology/comercio_electronico.html`: documentacion automatica de la ontologia generada con PyLODE.
  - `ontology/comercio_electronico.docx`: version Word de la documentacion automatica.
  - `pdtool/defaultreport_2026-06-05/`: reporte HTML y diagramas generados desde PDT.
- `src/`: implementacion Python del prototipo multiagente.
  - `develop.sh`: arranque del stack completo en local (recomendado).
  - `distributed.sh`: arranque de un solo agente para despliegue distribuido.
  - `JUEGOS-PRUEBA.md`: juegos de prueba reproducibles para la interfaz web.
  - `requirements.txt`: dependencias Python de la implementacion.
  - `agents/`: agentes ejecutables del sistema.
  - `utilities/`: utilidades compartidas para RDF, FIPA-ACL, HTTP, catalogo y runtime.
  - `tests/`: tests unitarios del sistema.
- `pdtool/`: modelo PDT y reportes generados para la parte de diseno.
- `README.md`: resumen general del repositorio y guia de ejecucion.

## Implementacion

La implementacion de `src/` usa Flask para exponer endpoints HTTP y RDFLib
para construir y procesar grafos RDF. Los mensajes de negocio se envian como
grafos RDF con una envoltura FIPA-ACL minima. Los agentes se descubren entre si
mediante un directorio FIPA (`agents.directorio`).

Agentes del diseno PDT:

- `agents.agente_catalogo`: busqueda de productos en el catalogo RDF en memoria.
- `agents.agente_comerciante`: recibe pedidos, genera factura, coordina logistica
  multi-centro, cobro, feedback y vendedores externos; agrupa lineas en lotes.
- `agents.agente_logistico`: reserva stock, crea lotes de envio y negocia
  transporte (Contract Net) con varios transportistas registrados.
- `agents.agente_financiero`: cobra pedidos y coordina reembolsos via el
  proveedor de pagos.
- `agents.agente_feedback`: registra compras pendientes de valoracion, opiniones
  y recomendaciones basicas.
- `agents.agente_devolucion`: valida devoluciones, coordina recogida y
  solicita reembolso al agente financiero.

Componentes auxiliares:

- `agents.directorio`: registro y descubrimiento de agentes.
- `agents.transportista`: transportista interno; responde ofertas de transporte.
- `agents.transportista_externo`: transportista de terceros (codigo ajeno al nucleo).
- `agents.proveedor_pagos`: pasarela de pagos externa simulada.
- `agents.vendedor_externo`: anuncia productos externos y recibe avisos de envio.
- `agents.asistente`: interfaz web/API del asistente virtual.

Extensiones implementadas:

- **Multi-CL**: dos centros logisticos (BCN y MAD); el comerciante contacta
  centros en orden de proximidad y cada uno sirve las lineas que puede cubrir.
- **Varios transportistas**: Express y Eco compiten en Contract Net; el centro
  logistico elige la mejor oferta.
- **Lotes**: el comerciante agrupa lineas antes de avisar a los centros
  logisticos (ventana de debounce configurable).
- **Despliegue distribuido**: cada agente puede ejecutarse en una maquina
  distinta anunciandose con `--open --hostaddr <ip>`.

Flujo principal de la demo:

1. El asistente (interfaz web) solicita una busqueda a `AgenteCatalogo`.
2. El catalogo devuelve productos que cumplen las restricciones RDF.
3. El asistente envia un pedido a `AgenteComerciante`.
4. La tienda genera factura y delega la logistica a uno o varios centros.
5. Cada centro reserva stock, agrupa lotes y negocia transporte.
6. La tienda notifica el cobro al agente financiero y la compra al feedback.
7. El usuario puede valorar, solicitar devolucion o recibir recomendaciones.

## Requisitos

Desde la raiz del repositorio:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
```

Dependencias principales:

- `Flask`: servidores HTTP de los agentes.
- `requests`: llamadas HTTP entre agentes.
- `rdflib`: construccion, lectura y serializacion de grafos RDF.

## Ejecucion local (recomendada)

La forma mas sencilla de levantar el sistema completo:

```bash
cd src
bash develop.sh
```

El script arranca todos los agentes con el directorio y registra:

- Directorio (9000)
- Transportista Express (9003) y Eco (9011)
- Centros logisticos BCN (9002) y MAD (9012)
- Proveedor de pagos (9004), financiero (9005), feedback (9007)
- Comerciante (9001), catalogo (9006), vendedor externo (9008)
- Devolucion (9009) y asistente (9010)

Interfaz web del asistente: `http://127.0.0.1:9010/iface`

Guion de juegos de prueba (JP-01…JP-19): [`src/JUEGOS-PRUEBA.md`](src/JUEGOS-PRUEBA.md)

Estado del directorio: `http://127.0.0.1:9000/info`

Estado de opiniones pendientes (feedback): `http://127.0.0.1:9007/status`

Para lanzar el stack con IP de red (p. ej. detras de NAT):

```bash
DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.10 bash src/develop.sh
```

## Ejecucion distribuida

Para la demo en varias maquinas o contenedores, usar
`src/distributed.sh`. Este script lanza **un solo agente** por ejecucion,
exporta `PYTHONPATH` automaticamente y aplica los mismos parametros de lotes
y timeouts que `develop.sh`.

```bash
cd src
DIR_HOST=<ip-directorio> HOSTADDR=<ip-esta-maquina> ./distributed.sh <agente> [puerto]
```

El primer agente que debe arrancar es el directorio. El resto de maquinas
deben indicar `DIR_HOST` para registrarse contra el directorio y `HOSTADDR`
para anunciar una URL accesible desde la red:

| Maquina | Comando |
| --- | --- |
| Directorio (10.0.0.10) | `HOSTADDR=10.0.0.10 ./distributed.sh directorio 9000` |
| Comerciante (10.0.0.15) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.15 ./distributed.sh comerciante 9001` |
| Catalogo (10.0.0.15) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.15 ./distributed.sh catalogo 9006` |
| Feedback (10.0.0.15) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.15 ./distributed.sh feedback 9007` |
| Centro logistico BCN (10.0.0.11) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.11 ./distributed.sh cl_bcn 9002` |
| Centro logistico MAD (10.0.0.12) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.12 ./distributed.sh cl_mad 9012` |
| Transportista Express (10.0.0.13) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.13 ./distributed.sh transportista_express 9003` |
| Transportista Eco (10.0.0.14) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.14 ./distributed.sh transportista_eco 9011` |
| Transportista externo (10.0.0.20, opcional) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.20 ./distributed.sh transportista_externo 9014` |
| Proveedor de pagos (10.0.0.16) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.16 ./distributed.sh proveedor_pagos 9004` |
| Financiero (10.0.0.17) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.17 PROVEEDOR_HOSTADDR=10.0.0.16 ./distributed.sh financiero 9005` |
| Vendedor externo (10.0.0.18) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.18 ./distributed.sh vendedor_externo 9008` |
| Devolucion (10.0.0.19) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.19 ./distributed.sh devolucion 9009` |
| Asistente / UI (10.0.0.19) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.19 ./distributed.sh asistente 9010` |

Despues de arrancar los agentes, abrir la interfaz en:

```text
http://10.0.0.19:9010/iface
```

Variables utiles:

| Variable | Uso |
| --- | --- |
| `DIR_HOST` | IP/host del directorio. |
| `DIR_PORT` | Puerto del directorio, por defecto `9000`. |
| `DIR_URL` | URL completa del directorio; sobrescribe `DIR_HOST`/`DIR_PORT`. |
| `HOSTADDR` | IP/host con el que el agente se anuncia al directorio. |
| `PROVEEDOR_HOSTADDR` | IP/host del proveedor de pagos cuando no comparte maquina con financiero. |
| `FEEDBACK_DELAY` | Retardo antes de pedir valoracion. |
| `RECOMMENDATION_PERIOD` | Periodo de recomendaciones proactivas. |
| `TRANSPORTISTA_PREU` / `TRANSPORTISTA_DIES` | Tarifa fija y dias del transportista externo. |

Agentes soportados por `distributed.sh`:

`directorio`, `transportista_express`, `transportista_eco`,
`transportista_externo`, `cl_bcn`, `cl_mad`, `proveedor_pagos`,
`financiero`, `feedback`, `vendedor_externo`, `comerciante`, `catalogo`,
`devolucion`, `asistente`.

## Ejecucion en Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r src\requirements.txt
cd src
bash develop.sh
```

Si no hay bash, levantar el stack agente a agente (mismos puertos que
`develop.sh`):

```powershell
$env:PYTHONPATH="src"
python -m agents.directorio --port 9000 --open --hostaddr 127.0.0.1
python -m agents.transportista --port 9003 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1 --tarifa-base 4.50 --tarifa-kg 1.75 --tarifa-dia 0.80
python -m agents.transportista --port 9011 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1 --tarifa-base 3.00 --tarifa-kg 2.50 --tarifa-dia 0.50
python -m agents.agente_logistico --port 9002 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1 --center-id CL-BCN --center-city Barcelona --dist 130
python -m agents.agente_logistico --port 9012 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1 --center-id CL-MAD --center-city Madrid --dist 500
python -m agents.proveedor_pagos --port 9004 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
python -m agents.agente_financiero --port 9005 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1 --provider-url http://127.0.0.1:9004
python -m agents.agente_feedback --port 9007 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
python -m agents.agente_catalogo --port 9006 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
python -m agents.vendedor_externo --port 9008 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1 --announce-products
python -m agents.agente_devolucion --port 9009 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
python -m agents.asistente --port 9010 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
```

Interfaz web: `http://127.0.0.1:9010/iface`

## Puertos usados

| Puerto | Componente |
| --- | --- |
| 9000 | `DirectoryService` |
| 9001 | `AgenteComerciante` |
| 9002 | `CentroLogisticoBCN` |
| 9003 | `TransportistaExpress` |
| 9004 | `ProveedorPagos` |
| 9005 | `AgenteFinanciero` |
| 9006 | `AgenteCatalogo` |
| 9007 | `AgenteFeedback` |
| 9008 | `VendedorExterno` |
| 9009 | `AgenteDevolucion` |
| 9010 | `AsistenteVirtual` (interfaz web) |
| 9011 | `TransportistaEco` |
| 9012 | `CentroLogisticoMAD` |
| 9014 | `TransportistaExterno` (opcional) |

## Tests

Tests unitarios en `src/tests/`:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s src/tests -v
```

## Documentacion

| Recurso | Contenido |
| --- | --- |
| `src/JUEGOS-PRUEBA.md` | Juegos de prueba reproducibles |
| `src/README.md` | Guia rapida del directorio `src/` |

## Ontologia

La ontologia principal del proyecto se encuentra en:

- `ontology/comercio_electronico.ttl`

La documentacion automatica generada con PyLODE esta disponible como anexo:

- `doc/ontology/comercio_electronico.html`
- `doc/ontology/comercio_electronico.docx`

Para regenerar la documentacion HTML:

```bash
pylode ontology/comercio_electronico.ttl -o doc/ontology/comercio_electronico.html -c true -s -p ontpub
```

Para generar la version Word a partir del HTML:

```bash
pandoc doc/ontology/comercio_electronico.html -f html -t docx -o doc/ontology/comercio_electronico.docx
```

Esta documentacion automatica sirve como anexo de referencia.

## Autores

- Eduard Corrons
- Mohamed Dari
- Ishak Felfoul
