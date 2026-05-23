# README - Prototipo fase 2

Este directorio contiene una implementacion preliminar alineada con la segunda fase de ECSDI.

Alcance implementado:

- Busqueda de productos internos de la tienda mediante restricciones RDF: nombre, marca, precio y valoracion.
- Compra simple de productos internos vendidos por la tienda.
- Verificacion de que el pedido se puede servir desde un unico centro logistico con stock suficiente.
- Planificacion de envio sin proceso de pago.
- Agente externo de transporte separado del centro logistico.
- Mensajes RDF con una envoltura FIPA-ACL minima y contenido definido con la ontologia del repositorio.

Agentes:

- `DirectoryService`: registro y descubrimiento de agentes para poder desplegarlos en procesos o maquinas distintas.
- `AgenteComerciante`: atiende `BuscarProductos` y `RealizarPedido`, mantiene catalogo/stock interno y genera factura.
- `CentroLogisticoAgent`: transforma un pedido aceptado en `LoteEnvio` y solicita presupuesto al transportista.
- `TransportistaAgent`: responde a `SolicitarPresupuestoTransporte` con una `OfertaTransporte`.
- `assistant_demo.py`: cliente de prueba que actua como `AsistenteVirtual`.

Limitaciones de momento:

- No hay cobro ni proveedor de pagos.
- No se implementan vendedores externos, devoluciones, feedback ni recomendaciones.
- El servicio de directorio usa un protocolo ligero `REGISTER|...`/`SEARCH|...` solo para infraestructura. Las comunicaciones de negocio entre agentes se mantienen en RDF/FIPA-ACL.
- El catalogo de datos es pequeno y esta generado en codigo para facilitar la demo.
- La seleccion de transportista es trivial porque solo hay un transportista, aunque ya esta separado como agente.

Ejecucion local:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt

PYTHONPATH=src python -m agents.transportista_agent --port 9003
PYTHONPATH=src python -m agents.centro_logistico_agent --port 9002 --transport-url http://127.0.0.1:9003/comm
PYTHONPATH=src python -m agents.agente_comerciante --port 9001 --logistics-url http://127.0.0.1:9002/comm
PYTHONPATH=src python -m assistant_demo --shop-url http://127.0.0.1:9001/comm
```

Con servicio de directorio:

```bash
PYTHONPATH=src python -m agents.directory_service --port 9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.transportista_agent --port 9003 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m assistant_demo --shop-url http://127.0.0.1:9001/comm
```

Tambien se puede levantar todo el stack local con:

```bash
cd src
bash develop.sh
```

Para una demostracion distribuida, cada agente puede arrancarse en una maquina distinta usando `--open --hostaddr <ip>` y pasando `--dir http://<ip-directorio>:9000`.


Update, en windows:
.\.venv\Scripts\Activate.ps1

Agentes:
$env:PYTHONPATH="src"; python -m agents.directory_service --port 9000
$env:PYTHONPATH="src"; python -m agents.transportista_agent --port 9003 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_financiero --port 9005 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_catalogo --port 9006 --dir http://127.0.0.1:9000 --verbose


Demo:
$env:PYTHONPATH="src"; python -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm