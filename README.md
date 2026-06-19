### Practica de Ingeniería del Conocimiento y Sistemas Distribuidos Inteligentes

Proyecto de la practica de Ingeniería del Conocimiento y Sistemas Distribuidos Inteligentes, basado en un sistema multiagente de
comercio electronico.

**English description:**

This repository contains an educational multi-agent e-commerce prototype. It models catalog search, order orchestration, logistics coordination, payment processing, returns management, and customer feedback using RDF/OWL and FIPA-ACL over HTTP.

## Estructura del proyecto

- `ontology/`: ontologia OWL/RDF del dominio de comercio electronico.
  - `comercio_electronico.ttl`: ontologia principal en Turtle.
  - `catalog-v001.xml`: catalogo XML auxiliar para herramientas OWL.
- `doc/`: documentacion generada como anexo.
  - `Documentación práctica ECSDI.pdf`: documentacion de la practica.
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

Para ejecutar los agentes en varios ordenadores, todos deben estar en la misma
red y poder acceder al ordenador del directorio. La ejecucion completa consiste
en abrir una terminal por agente y arrancarlos en el orden indicado. En local se
puede probar igual usando `127.0.0.1` como IP de todos los agentes.

La regla basica de IPs es:

- `DIR_HOST`: IP del ordenador donde corre `DirectoryService`.
- `HOSTADDR`: IP del ordenador donde se esta arrancando ese agente.
- `PROVEEDOR_HOSTADDR`: IP del proveedor de pagos, solo si `AgenteFinanciero`
  esta en otra maquina.

En Linux se puede ver la IP de cada maquina con:

```bash
hostname -I
```

Desde la raiz del repositorio (`practica-ecsdi`), usar `bash src/distributed.sh`
para evitar problemas de permisos de ejecucion. Los agentes que necesitan una
URL fija de otro agente que aun no ha arrancado se lanzan directamente con
`python -m`.

Ejemplo suponiendo:

- Directorio, PC1: `10.0.0.1`
- Transportistas, PC2/PC3/PC4: `10.0.0.2`, `10.0.0.3`, `10.0.0.4`
- Centros logisticos, PC5/PC6: `10.0.0.5`, `10.0.0.6`
- Proveedor de pagos, PC7: `10.0.0.7`
- Financiero, PC8: `10.0.0.8`
- Feedback, PC9: `10.0.0.9`
- Comerciante, PC10: `10.0.0.10`
- Catalogo, PC11: `10.0.0.11`
- Vendedor externo, PC12: `10.0.0.12`
- Devolucion, PC13: `10.0.0.13`
- Asistente/UI, PC14: `10.0.0.14`

En cada terminal:

```bash
source .venv/bin/activate
```

Orden recomendado de arranque. El orden evita que agentes como `catalogo`,
`comerciante` o `asistente` caigan a URLs locales `127.0.0.1` al no encontrar
sus dependencias en el directorio:

Terminal 1 - Directorio (PC1):

```bash
HOSTADDR=10.0.0.1 bash src/distributed.sh directorio 9000
```

Terminal 2 - Transportistas (PC2, PC3 y opcional PC4):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.2 bash src/distributed.sh transportista_express 9003
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.3 bash src/distributed.sh transportista_eco 9011
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.4 bash src/distributed.sh transportista_externo 9014
```

Terminal 3 - Centros logisticos (PC5 y PC6):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.5 bash src/distributed.sh cl_bcn 9002
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.6 bash src/distributed.sh cl_mad 9012
```

Terminal 4 - Proveedor de pagos (PC7):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.7 bash src/distributed.sh proveedor_pagos 9004
```

Terminal 5 - Agente financiero (PC8):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.8 PROVEEDOR_HOSTADDR=10.0.0.7 bash src/distributed.sh financiero 9005
```

Terminal 6 - Agente feedback (PC9):

```bash
PYTHONPATH=src python -m agents.agente_feedback \
  --port 9007 \
  --dir http://10.0.0.1:9000 \
  --open \
  --hostaddr 10.0.0.9 \
  --assistant-url http://10.0.0.14:9010
```

Este agente se lanza directamente con `python -m` porque `distributed.sh` no
expone `--assistant-url`. Asi el feedback puede conocer la URL del asistente
aunque el asistente arranque mas tarde.

Terminal 7 - Catalogo (PC11):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.11 bash src/distributed.sh catalogo 9006
```

Terminal 8 - Comerciante (PC10):

```bash
PYTHONPATH=src python -m agents.agente_comerciante \
  --port 9001 \
  --dir http://10.0.0.1:9000 \
  --open \
  --hostaddr 10.0.0.10 \
  --vendedor-externo-url http://10.0.0.12:9008
```

Este agente se lanza directamente con `python -m` porque el vendedor externo
arranca despues y asi el comerciante no cae al fallback `127.0.0.1:9008`.

Terminal 9 - Vendedor externo (PC12):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.12 bash src/distributed.sh vendedor_externo 9008
```

Terminal 10 - Agente devolucion (PC13):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.13 bash src/distributed.sh devolucion 9009
```

Terminal 11 - Asistente/UI (PC14):

```bash
DIR_HOST=10.0.0.1 HOSTADDR=10.0.0.14 bash src/distributed.sh asistente 9010
```

Despues se abre la interfaz en el navegador:

```text
http://10.0.0.14:9010/iface
```

Comprobaciones utiles:

- Directorio: `http://10.0.0.1:9000/status`
- Feedback: `http://10.0.0.9:9007/status`
- Asistente/UI: `http://10.0.0.14:9010/iface`
- Si algun log muestra `127.0.0.1`, ese agente no descubrio su dependencia:
  reiniciarlo despues de arrancar la dependencia correspondiente.
- Si aparece `No route to host`, no es un error del codigo: las maquinas no se
  ven por red o hay firewall.

Demos por consola opcionales:

Si se ejecutan contra agentes distribuidos, sustituir `127.0.0.1` por la IP de
la maquina donde corre cada agente.

Demo compra:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm
```

La demo tambien acepta parametros para cambiar la busqueda y los datos de
entrega:

```bash
PYTHONPATH=src python -m assistant_demo \
  --search-name iphone \
  --max-price 1300 \
  --city Barcelona \
  --street "Carrer Mallorca 401" \
  --postal-code 08013 \
  --country Espana \
  --priority 1
```

Demo feedback (valoracion; con `--simulate-notify` no hace falta compra previa):

```bash
source .venv/bin/activate
PYTHONPATH=src python -m feedback_demo --feedback-url http://127.0.0.1:9007/comm --simulate-notify
```

Tras `assistant_demo`, valorar el pedido devuelto:

```bash
PYTHONPATH=src python -m feedback_demo --feedback-url http://127.0.0.1:9007/comm --pedido-id PED-XXXXXXXX --product-id P-IPHONE19
```

Estado de opiniones pendientes: `http://127.0.0.1:9007/status`

Demo devolucion completa (compra un producto y solicita su devolucion):

```bash
source .venv/bin/activate
PYTHONPATH=src python -m devolucion_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm --devolucion-url http://127.0.0.1:9009/comm
```

Para devolver un pedido ya completado que siga en memoria en la tienda:

```bash
PYTHONPATH=src python -m devolucion_demo --pedido-id PED-XXXXXXXX --product-id P-IPHONE19 --devolucion-url http://127.0.0.1:9009/comm
```

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
| `doc/Documentación práctica ECSDI.pdf` | Documentación de la práctica |
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
