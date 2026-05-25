### Practica ECSDI

Proyecto de la practica de ECSDI basado en un sistema multiagente de
comercio electronico.

## Estructura del proyecto

- `ontology/`: ontologia OWL/RDF del dominio de comercio electronico.
  - `comercio_electronico.ttl`: ontologia principal en Turtle.
  - `comercio_electronico.properties`: metadatos auxiliares generados por la herramienta de ontologias.
- `doc/`: documentacion generada para entregar como anexo.
  - `ontology/Pylode/doc_ontology.html`: documentacion automatica de la ontologia generada con PyLODE.
  - `ontology/Pylode/doc_ontology.docx`: version Word de la documentacion automatica.
  - `pdtool/defaultreport_2026-05-19/`: reporte HTML y diagramas generados desde PDT.
- `src/`: implementacion Python del prototipo multiagente.
  - `assistant_demo.py`: cliente de prueba que actua como asistente virtual.
  - `devolucion_demo.py`: cliente de prueba para comprar y solicitar devolucion.
  - `develop.sh`: script auxiliar para levantar el stack local de la demo.
  - `requirements.txt`: dependencias Python de la implementacion.
  - `agents/`: agentes ejecutables del sistema.
  - `utilities/`: utilidades compartidas para RDF, FIPA-ACL, HTTP, catalogo y runtime.
- `pdtool/`: modelo PDT y reportes generados para la parte de diseno.
- `README.md`: resumen general del repositorio y guia de ejecucion.

## Implementacion

La implementacion de `src/` usa Flask para exponer endpoints HTTP y RDFLib
para construir y procesar grafos RDF. Los mensajes de negocio se envian como
grafos RDF con una envoltura FIPA-ACL minima.

Agentes principales:

- `agents.directory_service`: directorio de registro y descubrimiento de agentes.
- `agents.agente_catalogo`: busqueda de productos en el catalogo RDF en memoria.
- `agents.agente_comerciante`: agente comerciante; recibe pedidos, genera factura y coordina logistica y cobro.
- `agents.centro_logistico_agent`: crea lotes de envio y solicita ofertas de transporte.
- `agents.transportista_agent`: devuelve ofertas de transporte para lotes.
- `agents.agente_financiero`: simula el cobro del pedido.
- `agents.proveedor_pagos_agent`: proveedor de pagos externo simplificado.
- `agents.agente_feedback`: registra compras pendientes de valoracion y opiniones de productos.
- `agents.agente_devolucion`: valida devoluciones de pedidos completados y solicita el reembolso al agente financiero.

Flujo principal de la demo:

1. `assistant_demo.py` solicita una busqueda a `AgenteCatalogo`.
2. El catalogo devuelve productos que cumplen las restricciones.
3. El asistente escoge el primer producto y envia un pedido a `AgenteComerciante`.
4. La tienda genera factura y delega la preparacion del envio al centro logistico.
5. El centro logistico solicita una oferta al transportista.
6. La tienda notifica el cobro al agente financiero y la compra completada al agente feedback.
7. La demo muestra el pedido, estado, factura, importe y confirmacion de envio.

Tras una compra, `feedback_demo.py` puede enviar una valoracion para un producto del pedido.
Tras una compra, `devolucion_demo.py` puede solicitar la devolucion de un producto del pedido
contra `AgenteDevolucion`, que consulta el pedido completado en la tienda y coordina el reembolso.
Las recomendaciones y la solicitud proactiva de opinion tienen una implementacion basica en memoria.

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

## Ejecucion local completa

La forma recomendada para probar la implementacion actual es abrir una terminal
por agente y arrancarlos en este orden. El orden importa porque algunos agentes
buscan dependencias en el directorio al iniciarse.

Terminal 1 - Directorio:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.directory_service --port 9000
```

Terminal 2 - Transportista:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.transportista_agent --port 9003 --dir http://127.0.0.1:9000
```

Terminal 3 - Centro logistico:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000
```

Terminal 4 - Agente financiero:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.agente_financiero --port 9005 --dir http://127.0.0.1:9000
```

Terminal 5 - Tienda:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000
```

Terminal 6 - Catalogo:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.agente_catalogo --port 9006 --dir http://127.0.0.1:9000
```

Terminal 7 - Agente feedback:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.agente_feedback --port 9007 --dir http://127.0.0.1:9000
```

Terminal 8 - Agente vendedor externo:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.agente_VendedorExterno --port 9008 --dir http://127.0.0.1:9000
```

Terminal 9 - Agente devolucion:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m agents.agente_devolucion --port 9009 --dir http://127.0.0.1:9000
```

Terminal 10 - Demo compra:

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
```

Arranque de agentes:

```powershell
$env:PYTHONPATH="src"; python -m agents.directory_service --port 9000
$env:PYTHONPATH="src"; python -m agents.transportista_agent --port 9003 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.agente_financiero --port 9005 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.agente_catalogo --port 9006 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.agente_feedback --port 9007 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.agente_VendedorExterno --port 9008 --dir http://127.0.0.1:9000
$env:PYTHONPATH="src"; python -m agents.agente_devolucion --port 9009 --dir http://127.0.0.1:9000
```

Demo:

```powershell
$env:PYTHONPATH="src"; python -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm
$env:PYTHONPATH="src"; python -m feedback_demo --feedback-url http://127.0.0.1:9007/comm --simulate-notify
$env:PYTHONPATH="src"; python -m devolucion_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm --devolucion-url http://127.0.0.1:9009/comm
```

## Puertos usados

| Puerto | Componente |
| --- | --- |
| 9000 | `DirectoryService` |
| 9001 | `AgenteComerciante` |
| 9002 | `CentroLogisticoAgent` |
| 9003 | `TransportistaAgent` |
| 9004 | `ProveedorPagosAgent` |
| 9005 | `AgenteFinanciero` |
| 9006 | `AgenteCatalogo` |
| 9007 | `AgenteFeedback` |
| 9008 | `AgenteVendedorExterno` |
| 9009 | `AgenteDevolucion` |

## Script auxiliar

Tambien existe un script para arrancar rapidamente el stack basico:

```bash
cd src
bash develop.sh
```

Este script levanta el directorio y los agentes principales de la demo actual:
transportista, centro logistico, financiero, feedback, vendedor externo, tienda,
catalogo y devolucion.

Para una prueba distribuida, los agentes pueden arrancarse en maquinas distintas
usando `--open --hostaddr <ip>` y registrandolos contra el directorio comun con
`--dir http://<ip-directorio>:9000`.

## Ontologia

La ontologia principal del proyecto se encuentra en:

- `ontology/comercio_electronico.ttl`

La documentacion automatica generada con PyLODE esta disponible como anexo:

- `doc/ontology/Pylode/doc_ontology.html`
- `doc/ontology/Pylode/doc_ontology.docx`

Para regenerar la documentacion HTML:

```bash
.venv/bin/pylode ontology/comercio_electronico.ttl -o doc/ontology/Pylode/doc_ontology.html
```

Para generar la version Word a partir del HTML:

```bash
pandoc doc/ontology/Pylode/doc_ontology.html -f html -t docx -o doc/ontology/Pylode/doc_ontology.docx
```

Esta documentacion automatica sirve como anexo y no sustituye la seccion
redactada de la memoria.

## Autores

- Eduard Corrons
- Mohamed Dari
- Ishak Felfoul
