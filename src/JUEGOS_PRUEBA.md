# Juegos de prueba — ECSDI Fase 3/4

Documento para la **entrega de la práctica**: escenarios reproducibles que demuestran el sistema en funcionamiento, con pasos, evidencias y justificación de diseño.

## Criterio de diseño

Los juegos se han elegido por **cobertura de capacidades**, no por cantidad de instancias:

| Principio | Aplicación |
|-----------|------------|
| Un mecanismo por juego | Cada escenario aísla una funcionalidad (directorio, CFP, lotes, etc.). |
| Instancias mínimas suficientes | **2 transportistas** (tarifas distintas) y **2 centros logísticos** (BCN/MAD) bastan para negociación y selección greedy. |
| Reproducibilidad | Arranque estándar con `develop.sh` (o la lista Windows equivalente). |
| Evidencia observable | Logs de agentes, JSON en `/info`, ticket de pedido, ficheros en `data/`. |

**Productos “pin”** usados en varios juegos:

| ID | Tipo | Envío |
|----|------|--------|
| `P-IPHONE19` | Interno tienda | Centro logístico |
| `P-BATIDORA-MINI` | Interno | Centro logístico |
| `P-CARGADOR-GAN` | Externo (alta en arranque) | **Vendedor externo** (`gestionEnvioExterno=true`) |
| `P-AIRPODS-PRO` | Externo en catálogo | **Tienda / CL** (`gestionEnvioExterno=false`) |
| `P-EBOOK-AURORA` | Interno | Búsqueda por restricciones |

No es necesario añadir más transportistas, CL ni decenas de productos: el catálogo en `data/catalog.ttl` ya cubre internos, externos y stock en ambos centros.

---

## Preparación común

### Opción A — Linux / macOS / Git Bash

```bash
cd src
bash develop.sh
```

En **otra terminal**:

```bash
cd src
export PYTHONPATH=.
```

### Opción B — Windows (varias terminales)

Desde `Practica\src`:

```powershell
$env:PYTHONPATH = "."
```

Levantar el stack (mismo orden que `develop.sh`):

1. `python -m agents.directorio --port 9000 --open --hostaddr 127.0.0.1`
2. Transportista Express `9003`, Eco `9011` (con `--dir http://127.0.0.1:9000` y tarifas como en `develop.sh`)
3. CL-BCN `9002`, CL-MAD `9012` (`--center-id` / `--center-city` / `--dist` como en `develop.sh`)
4. Proveedor pagos `9004`, financiero `9005`, feedback `9007`, comerciante `9001` **con** `--dir http://127.0.0.1:9000`
5. Catálogo `9006`, vendedor externo `9008` **con** `--announce-products`, devolución `9009`, asistente `9010`

Variables de lote (recomendadas para la demo; `develop.sh` ya las exporta):

| Variable | Valor típico | Efecto |
|----------|--------------|--------|
| `LOT_DEBOUNCE_SECONDS` | 30 | Segundos sin nuevas líneas antes de despachar |
| `LOT_DISPATCH_INTERVAL` | 10 | Sondeo del scheduler del CL |
| `LOT_URGENT_DEBOUNCE` | 5 | Prioridad 1 despacha antes |

**Interfaz web:** [http://127.0.0.1:9010/iface](http://127.0.0.1:9010/iface)

**Cliente por línea de comandos:** `python -m assistant_demo` (mismos flags en bash y PowerShell).

### Pago (importante)

Por defecto el método es **`tarjeta`**. El **ProveedorPagos** rechaza el cobro si falta el PAN (`Falta el numero de tarjeta`).

En **`assistant_demo`** y **`devolucion_demo`** podéis usar:

| Opción | Ejemplo |
|--------|---------|
| Tarjeta de prueba (recomendado) | `--payment-card 4111111111111111` |
| PayPal (sin tarjeta) | `--payment-method paypal` |
| Transferencia (sin tarjeta) | `--payment-method transferencia` |

Tarjeta usada en los ejemplos de abajo (válida en modo demo): **`4111111111111111`**.

`assistant_demo` y `devolucion_demo` ya llevan esa tarjeta por defecto; los flags `--payment-card` en los ejemplos son explícitos para la memoria y por si cambiáis el default.

**Atajo PowerShell** (evita repetir la tarjeta en cada comando):

```powershell
$card = "4111111111111111"
# Luego: --payment-card $card
```

En la **interfaz web** del asistente, rellenad el campo «Número tarjeta» al hacer el pedido.

---

## Tabla resumen

| # | Juego | Funcionalidad principal |
|---|--------|-------------------------|
| 1 | Directorio y descubrimiento | Registro DSO, multi-agente |
| 2 | Búsqueda RDF | Catálogo + restricciones |
| 3 | Compra logística Barcelona | Pedido → CL-BCN → transporte |
| 4 | Selección CL Madrid | Greedy multi-centro |
| 5 | Negociación transportistas | CFP, mejor oferta |
| 6 | Agrupación de lotes | Debounce + misma zona dist |
| 7 | Externo envía vendedor | `P-CARGADOR-GAN` |
| 8 | Externo envía tienda/CL | `P-AIRPODS-PRO` |
| 9 | Valoración y media | Feedback → catálogo |
| 10 | Devolución | Agente devolución + reembolso |
| 11 | Feedback / recomendaciones | Proactivo (opcional) |

---

## Juego 1 — Directorio y descubrimiento de agentes

**Objetivo:** Demostrar que los agentes se registran en el **Directory Service** y son descubribles sin URLs fijas en cada par.

**Por qué:** Requisito de despliegue distribuido y competencia de integración multi-agente.

**Pasos**

```powershell
Invoke-RestMethod http://127.0.0.1:9000/info | ConvertTo-Json -Depth 5
```

**Resultado esperado**

- Entradas con `address` apuntando a `http://127.0.0.1:9xxx/comm` para comerciante, catálogo, CL-BCN, CL-MAD, transportistas, etc.

**Evidencia:** Captura del JSON o copia en memoria.

---

## Juego 2 — Búsqueda con restricciones RDF

**Objetivo:** El **Agente Catálogo** responde a `BuscarProductos` filtrando por ontología (nombre, precio, valoración).

**Por qué:** Muestra el uso de RDF/OWL en el flujo de compra, no solo almacenamiento.

**Pasos (recomendado — solo búsqueda)**

En **http://127.0.0.1:9010/iface**: buscar `ebook` con precio máximo **200** € (y opcionalmente valoración mínima).

**Alternativa por consola** (el demo también compra si hay resultados; úsalo si queréis cerrar el flujo):

```powershell
cd Practica\src
$env:PYTHONPATH = "."
python -m assistant_demo --search-name ebook --max-price 200 --product-index 1 --buy-results 1 --payment-card 4111111111111111
```

Antes de ejecutar, observad la lista impresa de productos: debe incluir `P-EBOOK-AURORA` y excluir artículos por encima de 200 €.

**Resultado esperado**

- Aparece `P-EBOOK-AURORA` (u otros que cumplan restricciones).
- No aparecen productos por encima del precio máximo.

**Evidencia:** Lista en consola o pantalla de búsqueda.

---

## Juego 3 — Compra logística estándar (Barcelona → CL-BCN)

**Objetivo:** Flujo completo: asistente → comerciante → CL → transportista → cobro → confirmación.

**Por qué:** Caso base de la práctica (pedido interno con logística).

**Pasos**

```powershell
python -m assistant_demo `
  --search-name iphone `
  --product-index 1 `
  --city Barcelona `
  --street "Carrer Mallorca 401" `
  --delivery-dist 130 `
  --priority 2 `
  --payment-card 4111111111111111
```

**Resultado esperado**

- Pedido **aceptado** con factura e importe.
- En el resumen de envío: centro cercano a **Barcelona** (`centro_label` / CL-BCN).
- Log del **CentroLogisticoBCN (9002)**: agrupación en lote, negociación transporte, confirmación al comerciante.
- Tras ~30–45 s: lote pasa a histórico (`data/lotes/`).

**Evidencia**

```powershell
Invoke-RestMethod http://127.0.0.1:9002/info | Select-Object -ExpandProperty pending_lotes
```

Antes del despacho puede haber un lote `pendiente_envio`; después, vacío y fichero en `data\lotes\`.

---

## Juego 4 — Selección de centro logístico (Madrid → CL-MAD)

**Objetivo:** Con **dos CL** registrados, el comerciante elige por proximidad `|dist_CL − dist_entrega|`.

**Por qué:** Extensión multi-centro; demuestra que no todo va siempre a BCN.

**Precondición:** Comerciante arrancado con `--dir http://127.0.0.1:9000` (como en `develop.sh`).

**Pasos**

```powershell
python -m assistant_demo `
  --search-name iphone `
  --city Madrid `
  --street "Gran Via 28" `
  --postal-code 28013 `
  --delivery-dist 480 `
  --priority 2 `
  --payment-card 4111111111111111
```

**Resultado esperado**

- Ticket / resumen con centro **Madrid** (CL-MAD, puerto 9012).
- Actividad en logs de **9012**, no solo en 9002.

**Evidencia:** Comparar `GET http://127.0.0.1:9012/info` vs `9002/info` tras el pedido.

---

## Juego 5 — Dos transportistas (mejor oferta)

**Objetivo:** El CL lanza **Contract Net** a varios transportistas y elige la oferta más favorable.

**Por qué:** Extensión avanzada #1; diferencia respecto a un único transportista fijo.

**Precondición:** Express (9003) y Eco (9011) con tarifas distintas (ver `develop.sh`).

**Pasos**

1. Arrancar al menos un CL con `--verbose`.
2. Ejecutar el **Juego 3** (pedido Barcelona).

**Resultado esperado**

- Log del CL: descubrimiento de transportistas, varias ofertas, **oferta seleccionada** con precio.
- El precio de envío en el ticket refleja la oferta ganadora (suele ganar **Eco** con peso moderado y tarifas bajas en base).

**Evidencia:** Fragmento de log del CL o línea “Oferta seleccionada” / importe envío en `assistant_demo`.

---

## Juego 6 — Agrupación de lotes (debounce)

**Objetivo:** Varios pedidos a la **misma zona de distancia** se fusionan en un solo `LoteEnvio` antes del despacho.

**Por qué:** Plan AgruparPedidoEnLote + ventana de inactividad (competencia de logística).

**Pasos**

1. Asegurar `LOT_DEBOUNCE_SECONDS=30` (valor por defecto en `develop.sh`).
2. En **dos terminales**, ejecutar casi a la vez (misma ciudad y `delivery-dist`):

```powershell
# Terminal A
python -m assistant_demo --search-name batidora --city Barcelona --delivery-dist 130 --priority 3 --payment-card 4111111111111111

# Terminal B (inmediatamente después)
python -m assistant_demo --search-name libro --city Barcelona --delivery-dist 130 --priority 3 --payment-card 4111111111111111
```

3. Esperar **35–45 segundos** sin nuevos pedidos.
4. Consultar estado:

```powershell
Invoke-RestMethod http://127.0.0.1:9002/info | ConvertTo-Json -Depth 6
```

**Resultado esperado**

- Un solo lote con `lineas` ≥ 2 y varios `pedidos` en la lista, **antes** del despacho (`estado`: `pendiente_envio`).
- Tras el debounce: un único ciclo de negociación transporte y un fichero en `data/lotes/`.

**Evidencia:** JSON de `pending_lotes` o captura de `idle_seconds` / `ready_for_dispatch: true`.

---

## Juego 7 — Producto externo (envía el vendedor)

**Objetivo:** Producto dado de alta con `DarAltaProductoExterno` y **`gestionEnvioExterno=true`**: el comerciante avisa al vendedor, **sin** lote en el CL.

**Por qué:** Modelo marketplace con envío del proveedor.

**Precondición:** `AgenteVendedorExterno` en marcha con `--announce-products` (registra `P-CARGADOR-GAN` al inicio).

**Pasos**

```powershell
python -m assistant_demo --search-name cargador --product-index 1 --city Barcelona --delivery-dist 130 --payment-card 4111111111111111
```

**Resultado esperado**

- Pedido aceptado y cobrado.
- Log del **vendedor externo (9008)**: aviso `ComunicarProductosExternosPedidos` / gestión de envío.
- **No** debe aparecer actividad de agrupación de ese pedido en el CL (o solo productos internos si el carrito los mezclara).

**Evidencia:** Log vendedor 9008; ausencia de nuevo lote en CL para esa línea externa.

---

## Juego 8 — Producto externo (envía la tienda / CL)

**Objetivo:** Producto externo con **`gestionEnvioExterno=false`**: stock en CLs y flujo logístico normal.

**Por qué:** Contrasta con el juego 7; mismo tipo “externo” en catálogo, distinta responsabilidad de envío.

**Producto:** `P-AIRPODS-PRO` (ya en `data/catalog.ttl`).

**Pasos**

```powershell
python -m assistant_demo --search-name airpods --product-index 1 --city Barcelona --delivery-dist 130 --payment-card 4111111111111111
```

**Resultado esperado**

- Pedido aceptado.
- Log del **CL-BCN**: `AgruparPedidoEnLote`, negociación transporte.
- Pago al vendedor externo vía financiero (simulado), pero **envío por centro logístico**.

**Evidencia:** Log CL + ticket con centro logístico; opcional `GET http://127.0.0.1:9002/info`.

---

## Juego 9 — Valoración y actualización de media

**Objetivo:** Tras la compra, `EnviarOpinion` actualiza `valoracionMedia` en el catálogo persistido.

**Por qué:** Ciclo feedback y datos semánticos actualizados en búsquedas posteriores.

**Pasos**

```powershell
python -m assistant_demo `
  --search-name iphone `
  --rate 5 `
  --comment "Excelente para la demo de entrega" `
  --payment-card 4111111111111111
```

Luego repetir la búsqueda en **http://127.0.0.1:9010/iface** (`iphone`) y comprobar que la media de `P-IPHONE19` ha cambiado respecto a antes de valorar.

**Resultado esperado**

- Mensaje “Valoracion enviada”.
- En la siguiente búsqueda, `valoracionMedia` de `P-IPHONE19` refleja la opinión (media ponderada según opiniones registradas).

**Evidencia:** Salida de búsqueda antes/después o `data/catalog.ttl` actualizado.

---

## Juego 10 — Devolución y reembolso simulado

**Objetivo:** **AgenteDevolucion** valida contra compra completada, simula recogida y pide reembolso al financiero.

**Por qué:** Cierra el ciclo post-venta exigido en fases avanzadas.

**Pasos**

```powershell
python -m devolucion_demo --search-name iphone --motivo "Pantalla con defecto de fabrica" --payment-card 4111111111111111
```

(o con pedido ya existente: `--pedido-id PED-... --product-id P-IPHONE19`).

**Resultado esperado**

- Compra completada y, acto seguido, solicitud de devolución aceptada.
- Mensaje de confirmación / reembolso simulado en consola.

**Evidencia:** Salida de `devolucion_demo` y log del agente devolución (9009).

**Variante en un solo flujo:**

```powershell
python -m assistant_demo --search-name iphone --request-return --return-reason "No coincide con la descripcion" --payment-card 4111111111111111
```

---

## Juego 11 — Feedback proactivo y recomendaciones (opcional)

**Objetivo:** **AgenteFeedback** con scheduler: solicitud de opinión y recomendaciones básicas.

**Por qué:** Comportamiento proactivo del sistema.

**Precondición:** Feedback con `--feedback-delay 60` (como en `develop.sh`).

**Pasos**

1. Completar una compra (Juego 3).
2. Esperar ~60 s y observar la consola del **asistente (9010)** o la interfaz.
3. O ejecutar:

```powershell
python -m feedback_demo --simulate-notify --product-id P-IPHONE19 --puntuacion 4
```

Con recomendaciones tras compra real:

```powershell
python -m assistant_demo --search-name iphone --show-recommendations --payment-card 4111111111111111
```

**Resultado esperado**

- Notificación de compra registrada en feedback.
- Lista de recomendaciones (productos con buena valoración relacionada).

---

## Juego opcional — Fallo por stock (multi-CL)

**Objetivo:** Demostrar que el comerciante **prueba otro CL** si el primero no tiene stock.

**Por qué:** Robustez del fan-out greedy (solo si queréis una demo de error controlado).

**Pasos**

1. Editar `data/catalog.ttl`: poner `ecsdi:cantidadDisponible 0` para un producto solo en `CL-BCN`, mantener stock en `CL-MAD`.
2. Reiniciar catálogo y CLs.
3. Pedido con entrega que prefiera BCN pero con stock solo en MAD (ajustar `delivery-dist` si hace falta).

**Resultado esperado:** Pedido aceptado vía CL-MAD tras rechazo o skip de BCN.

---

## Checklist para la defensa / entrega

- [ ] `develop.sh` (o stack Windows) arranca sin errores.
- [ ] Juegos 1, 3, 4, 5, 6, 7 u 8, 9, 10 ejecutados al menos una vez.
- [ ] Capturas: directorio `/info`, ticket con `centro_label`, `pending_lotes`, log transportista.
- [ ] Memoria incluye tabla “juego → competencia → evidencia”.
- [ ] Tests automáticos (`python -m unittest discover -s tests`) pasan como respaldo técnico.

```powershell
cd Practica\src
$env:PYTHONPATH = "."
python -m unittest discover -s tests -v
```

---

## Mapa juego → competencia (texto para memoria)

> Hemos definido once juegos de prueba que recorren el ciclo de vida del comercio electrónico multi-agente: descubrimiento en el directorio, consultas RDF al catálogo, realización de pedidos con FIPA-ACL, elección greedy entre dos centros logísticos, negociación Contract Net entre dos transportistas, agrupación temporal de pedidos en lotes, dos modelos de producto externo (envío vendedor vs envío tienda), valoraciones que actualizan el grafo del catálogo, devoluciones con reembolso simulado y feedback proactivo. Se han evitado instancias redundantes porque dos transportistas y dos centros ya exponen selección y competencia; la reproducibilidad se garantiza con `develop.sh` y scripts `*_demo.py`.

---

## Referencias rápidas de puertos (`develop.sh`)

| Agente | Puerto |
|--------|--------|
| Directory | 9000 |
| Comerciante | 9001 |
| CL-BCN | 9002 |
| Transportista Express | 9003 |
| Proveedor pagos | 9004 |
| Financiero | 9005 |
| Catálogo | 9006 |
| Feedback | 9007 |
| Vendedor externo | 9008 |
| Devolución | 9009 |
| Asistente (+ iface) | 9010 |
| Transportista Eco | 9011 |
| CL-MAD | 9012 |
