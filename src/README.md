# README - Prototipo fase 3

Este directorio contiene una implementacion preliminar alineada con la tercera fase de ECSDI.

Alcance implementado:

- Busqueda de productos internos de la tienda mediante restricciones RDF: nombre, marca, precio y valoracion.
- Compra simple de productos internos vendidos por la tienda.
- Verificacion logistica de que las lineas con stock declarado se pueden servir desde un unico centro logistico con stock suficiente.
- Planificacion de envio con negociacion de transporte y reserva de stock logistico.
- Agente externo de transporte separado del centro logistico.
- Cobro simulado del pedido y pagos a vendedores externos.
- Registro de compras completadas para feedback y validacion de devoluciones.
- Devolucion de productos comprados con consulta del pedido completado, recogida y reembolso simulado posterior.
- Solicitud proactiva de feedback al asistente y recomendaciones basicas a partir de valoraciones.
- Mensajes RDF con una envoltura FIPA-ACL minima y contenido definido con la ontologia del repositorio.

Agentes:

- `DirectoryService`: registro y descubrimiento de agentes para poder desplegarlos en procesos o maquinas distintas.
- `AgenteComerciante`: atiende `RealizarPedido`, genera factura, coordina logistica, cobro, feedback y vendedores externos.
- `CentroLogisticoAgent`: selecciona un centro con stock suficiente, transforma el pedido en `LoteEnvio` y solicita presupuesto al transportista.
- `TransportistaAgent`: responde a `SolicitarPresupuestoTransporte` con una `OfertaTransporte`.
- `AgenteFinanciero`: confirma cobros, reembolsos y pagos a vendedores externos.
- `AgenteCatalogo`: responde busquedas sobre el catalogo RDF en memoria y acepta altas `DarAltaProductoExterno`.
- `AgenteFeedback`: registra compras completadas y valoraciones.
- `AgenteVendedorExterno`: anuncia productos externos al catalogo y recibe avisos de envio de los productos que gestiona.
- `AgenteDevolucion`: valida solicitudes de devolucion contra pedidos completados, solicita recogida y despues solicita reembolso.
- `assistant_demo.py`: cliente de prueba que actua como `AsistenteVirtual`.
- `devolucion_demo.py`: cliente de prueba que compra un producto y solicita su devolucion.

Limitaciones de momento:

- El cobro, los reembolsos y los pagos externos se simulan en memoria.
- Las recomendaciones son basicas y se calculan en memoria a partir de compras/valoraciones registradas.
- El servicio de directorio se comunica mediante RDF/FIPA-ACL, pero el registro sigue siendo en memoria; los agentes envian `request` con acciones `DSO.RegistrarAgente`, `DSO.BuscarAgente`, `DSO.BuscarTodosAgentes` y `DSO.EliminarAgente`.
- El catalogo de datos es pequeno y esta generado en codigo para facilitar la demo; las reservas logisticas se guardan en `src/data`.
- La seleccion de transportista es simple, aunque ya admite varios transportistas registrados.

Ejecucion local:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt

PYTHONPATH=src python -m agents.transportista_agent --port 9003
PYTHONPATH=src python -m agents.centro_logistico_agent --port 9002 --transport-url http://127.0.0.1:9003/comm
PYTHONPATH=src python -m agents.agente_financiero --port 9005
PYTHONPATH=src python -m agents.agente_feedback --port 9007
PYTHONPATH=src python -m agents.agente_VendedorExterno --port 9008
PYTHONPATH=src python -m agents.agente_comerciante --port 9001 --logistics-url http://127.0.0.1:9002/comm --financiero-url http://127.0.0.1:9005/comm --feedback-url http://127.0.0.1:9007/comm --vendedor-externo-url http://127.0.0.1:9008/comm
PYTHONPATH=src python -m agents.agente_catalogo --port 9006
PYTHONPATH=src python -m agents.agente_devolucion --port 9009 --shop-url http://127.0.0.1:9001/comm --financiero-url http://127.0.0.1:9005/comm --transport-url http://127.0.0.1:9003/comm
PYTHONPATH=src python -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm
PYTHONPATH=src python -m devolucion_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm --devolucion-url http://127.0.0.1:9009/comm
```

Con servicio de directorio:

```bash
PYTHONPATH=src python -m agents.directory_service --port 9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.transportista_agent --port 9003 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_financiero --port 9005 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_feedback --port 9007 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_VendedorExterno --port 9008 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_catalogo --port 9006 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m agents.agente_devolucion --port 9009 --dir http://127.0.0.1:9000 --open --hostaddr 127.0.0.1
PYTHONPATH=src python -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm
PYTHONPATH=src python -m devolucion_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm --devolucion-url http://127.0.0.1:9009/comm
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
$env:PYTHONPATH="src"; python -m agents.transportista_agent --port 9003 --dir http://127.0.0.1:9000 --tarifa-base 2.00 --tarifa-kg 2.50 --tarifa-dia 0.20 --verbose
$env:PYTHONPATH="src"; python -m agents.transportista_agent --port 9004 --dir http://127.0.0.1:9000 --tarifa-base 8.00 --tarifa-kg 1.00 --tarifa-dia 2.00 --verbose
$env:PYTHONPATH="src"; python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000 --dist 130 --verbose
$env:PYTHONPATH="src"; python -m agents.centro_logistico_agent --port 9002 --dir http://127.0.0.1:9000 --dist 700 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_financiero --port 9005 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_comerciante --port 9001 --dir http://127.0.0.1:9000  --verbose 
$env:PYTHONPATH="src"; python -m agents.agente_catalogo --port 9006 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_feedback --port 9007 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_VendedorExterno --port 9008 --dir http://127.0.0.1:9000 --verbose
$env:PYTHONPATH="src"; python -m agents.agente_devolucion --port 9009 --dir http://127.0.0.1:9000 --verbose

Demo:
$env:PYTHONPATH="src"; python -m assistant_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm
$env:PYTHONPATH="src"; python -m feedback_demo --feedback-url http://127.0.0.1:9007/comm --simulate-notify
$env:PYTHONPATH="src"; python -m devolucion_demo --catalog-url http://127.0.0.1:9006/comm --shop-url http://127.0.0.1:9001/comm --devolucion-url http://127.0.0.1:9009/comm

$env:PYTHONPATH="src"; python -m agents.agente_asistente --port 9010
