# Juegos de prueba

Conjunto de escenarios que cubren las **5 tareas básicas** del enunciado
(§ 3.3) y los **4 elementos avanzados** implementados (§ 3.4). Cada
escenario indica los agentes implicados, los pasos a ejecutar desde la
interfaz del Asistente (`http://localhost:9000/iface` por defecto) y
las trazas/datos que validan el comportamiento.

Prerrequisitos comunes:

```bash
cd src
bash develop.sh   # arranca directorio + 2 transportistas + 2 CL + ...
```

Para acortar la latencia del feedback diferido en demo, `develop.sh`
exporta `FEEDBACK_DELAY_SECONDS=20` y `RECOMMENDATION_PERIOD_SECONDS=30`
(ver §6 de la memoria).

## A. Tareas básicas

### A1. Búsqueda en el catálogo (BuscarProductos)

- Pasos: abrir el asistente, pestaña "01 / Buscar", buscar `iPhone`.
- Salida esperada: lista de productos con `id`, `precio` y `valoración`.
- Validación adicional: aparece una entrada en `searches.json` y en el
  grafo `searches` del Dataset (`dataset.trig`), lo que confirma el
  Protocolo Consulta Catálogo (Catálogo → Feedback).

### A2. Realización de pedido interno (RealizarPedido)

- Pasos: seleccionar `iPhone 19`, pestaña "02 / Pedido", introducir
  dirección de Barcelona y confirmar.
- Salida esperada: el asistente recibe `inform` con la factura, una o
  más `ConfirmacionEnvio` (una por CL que tenga stock) y los datos del
  transportista ganador del Contract-Net.
- Validación adicional: en `completed_orders/` aparece el TTL del
  pedido; en `dataset.trig` aparece el grafo nombrado
  `completed_orders/<id>`.

### A3. Pedido con producto externo y `gestionEnvioExterno=true`

- Pasos: dar de alta producto externo (Asistente → Catálogo) con
  `gestionEnvioExterno = true`; comprar ese producto.
- Salida esperada:
  - El Comerciante NO contacta al CL para ese producto.
  - El Financiero recibe `PagarProductoExterno`.
  - El VendedorExterno recibe `ComunicarProductosExternosPedidos` con la
    dirección.

### A4. Gestión de envío y multi-CL

- Pasos: comprar a la vez 1× `iPhone 19` (CL-BCN) y 1× `Libro Rust`
  (CL-MAD).
- Salida esperada: el asistente recibe **dos** `ConfirmacionEnvio`, una
  por cada CL, cada una con su transportista y fecha estimada.

### A5. Devolución (SolicitarDevolucion)

- Pasos: pestaña "03 / Valoración" → desplegar pedido y pulsar
  "Solicitar devolución" sobre una línea entregada.
- Salida esperada (caso aceptado): el AgenteDevolucion contacta con el
  Comerciante para validar el pedido, con el Transportista
  (`SolicitarRecogidaDevolucion`) y con el Financiero
  (`SolicitarReembolso`).
- Caso de fallo (denegada): repetir con un pedido inexistente. Debe
  responder `failure` con motivo "Pedido no encontrado".

## B. Elementos avanzados

### B1. Transportistas dinámicos (Contract-Net)

- Verificación: con dos transportistas activos (`Express` con tarifa
  alta, `Eco` con tarifa baja), realizar un pedido pesado. El CL debe
  seleccionar a `TransportistaEco` y enviar `accept-proposal`; al otro
  llega `reject-proposal`.
- Validación: log de `centro-logistico-*` y `transportista-*`.

### B2. Multi-CL

- Cubierto en A4. Verificar que cada CL filtra las líneas según su
  stock (consultable en `/info` de cada CL).

### B3. Agentes de pago

- Validar en A2 que `agente-financiero` recibe `SolicitarCobro` y a su
  vez emite `SolicitarOperacionPago` al `ProveedorPagos`.
- Validar en A5 que `agente-financiero` recibe `SolicitarReembolso`.
- Validar en A3 que `agente-financiero` recibe `PagarProductoExterno`.

### B4. Feedback diferido y recomendación proactiva

- Inmediatamente después de A2, el Feedback registra la compra y
  programa un Timer. Al cabo de `FEEDBACK_DELAY_SECONDS` el asistente
  recibe un `PedirFeedback` (visible en su inbox).
- Cada `RECOMMENDATION_PERIOD_SECONDS`, el asistente recibe una
  `Recomendacion` (ACL.inform), visible en `/recommendations-inbox`.
- Variante de fallo: borrar `searches.json` y `opinions.json` antes de
  arrancar. La recomendación debe degradar a un ranking neutral del
  catálogo, no a un error.

## C. Casos de fallo a documentar

| Caso | Cómo provocarlo | Comportamiento esperado |
| --- | --- | --- |
| Devolución denegada | Pedir devolución sobre pedido inexistente. | `failure` del AgenteDevolucion con motivo. |
| Transportista no responde | Detener los dos transportistas y hacer A2. | CL responde `failure` por no haber propuestas; el asistente recibe `failure` controlado. |
| CL sin stock | Pedir un producto que solo tiene CL-BCN, apagar CL-BCN. | El otro CL responde `failure` (sin stock); el Comerciante devuelve `failure` "Ningún CL pudo planificar el envío". |
| Pedido multi-CL parcial | Apagar CL-MAD y pedir A4. | El Comerciante completa el envío con CL-BCN para las líneas que cubre; deja constancia en los logs. |
| Producto externo sin VendedorExterno | Apagar el agente VendedorExterno. | El pago al vendedor se intenta y se loguea `aviso fire-and-forget fallido`; el pedido sigue. |

## D. Comandos rápidos

```bash
# tests unitarios
cd src && python -m unittest discover -s tests -t . -v

# regenerar documentación de la ontología
python doc/ontology/generate_docs.py

# inspeccionar el dataset común
python - <<'PY'
import sys; sys.path.insert(0, 'src')
from utilities.storage import list_named_graphs
print(list_named_graphs())
PY
```
