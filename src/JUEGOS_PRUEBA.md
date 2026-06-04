# Juegos de prueba — ECSDI (Capítulo 8)

Documento para la **entrega y defensa de la práctica**: escenarios reproducibles alineados con el **Capítulo 8** de la memoria. Cada juego aísla un mecanismo (directorio, RDF, FIPA-ACL, multi-CL, CFP transporte, lotes, externos, feedback, devoluciones). Se evita inflar instancias: **dos transportistas** (Express/Eco), **dos centros logísticos** (BCN/MAD) y, cuando haga falta, el **transportista de terceros** (puerto 9014) bastan para demostrar selección y competencia.

---

## Criterio de diseño

| Principio | Aplicación |
|-----------|------------|
| Un mecanismo por juego | Cada escenario comprueba una capacidad concreta. |
| Instancias mínimas | 2 CL + 2 transportistas (+ 1 externo opcional en JP-18). |
| Reproducibilidad | `develop.sh` + `assistant_demo` / interfaz web. |
| Evidencia | Logs de agentes, JSON en `/info`, tickets, ficheros en `data/`. |

### Productos de referencia (`data/catalog.ttl`)

| ID | Tipo | Envío | Uso típico |
|----|------|--------|------------|
| `P-IPHONE19` | Interno | CL | Apple, Barcelona, CFP ligero |
| `P-MACBOOK-AIR` | Interno | CL | Apple, peso 1,10 kg |
| `P-BATIDORA-MINI` | Interno | CL | Peso 1,20 kg, lotes |
| `P-LIBRO-RUST` | Interno | CL | Segundo pedido en lote |
| `P-CARGADOR-GAN` | Externo (alta al arranque) | Vendedor (`gestionEnvioExterno=true`) |
| `P-AIRPODS-PRO` | Externo en catálogo | CL (`gestionEnvioExterno=false`) |
| `P-EBOOK-AURORA` | Interno | CL | Búsquedas por precio |

### Tarifas en `develop.sh` (negociación transporte)

| Agente | Puerto | `tarifa-base` | `tarifa-kg` | `tarifa-dia` |
|--------|--------|---------------|-------------|--------------|
| TransportistaExpress | 9003 | 4,50 € | **1,75** €/kg (menor → gana en peso) | 0,80 €/día |
| TransportistaEco | 9011 | 3,00 € | 2,50 €/kg | **0,50** €/día (menor → gana en días) |

Prioridad de entrega → días usados en la oferta: **1 → 1 día**, **2 → 3 días**, **3 → 5 días** (`transportista.py`).

---

## Preparación común

### Arranque (Linux / macOS / Git Bash)

```bash
cd src
bash develop.sh
```

En **otra terminal**:

```bash
cd src
export PYTHONPATH=.
```

### Interfaz y demos

| Recurso | URL / comando |
|---------|----------------|
| Interfaz asistente | [http://127.0.0.1:9010/iface](http://127.0.0.1:9010/iface) |
| Directorio | `curl -s http://127.0.0.1:9000/info \| jq` |
| CL-BCN `pending_lotes` | `curl -s http://127.0.0.1:9002/info \| jq .pending_lotes` |
| Demo CLI | `python -m assistant_demo` (tarjeta demo por defecto: `4111111111111111`) |

### Variables de lote (`develop.sh`)

| Variable | Valor | Efecto |
|----------|-------|--------|
| `LOT_DEBOUNCE_SECONDS` | 30 | Ventana sin nuevas líneas antes de despachar (no urgente) |
| `LOT_URGENT_DEBOUNCE` | 5 | Prioridad 1 despacha antes |
| `LOT_DISPATCH_INTERVAL` | 10 | Sondeo del scheduler del CL |

### Feedback (`develop.sh`)

| Parámetro | Valor | Efecto |
|-----------|-------|--------|
| `--feedback-delay` | 60 s | `PedirFeedback` tras compra |
| `--recommendation-period` | 120 s | Recomendaciones proactivas |
| `--recommendation-warmup` | 30 s | Retraso inicial del recomendador |

### Pago

Método por defecto: **tarjeta**. Sin PAN válido el ProveedorPagos rechaza el cobro. En la interfaz, rellenad «Número tarjeta» al confirmar el pedido.

### Transportista de terceros (solo JP-14)

Con el stack en marcha, en una **terminal extra** (no está en `develop.sh`):

```bash
cd src
./distributed.sh transportista_externo 9014
```

Comprobad que aparece en `http://127.0.0.1:9000/info` antes del pedido de prueba.

### Windows

Equivalente: `$env:PYTHONPATH = "."` y los mismos módulos `python -m agents.*` (ver lista en versiones anteriores del doc o `src/README.md`).

---

## Tabla resumen (Capítulo 8)

| ID | Sección | Juego | Mecanismo |
|----|---------|-------|-----------|
| JP-01 | 8.1 | Catálogo sin filtros | ProductosDB + comunicación catálogo |
| JP-02 | 8.1 | Filtros Apple → 1000 → iPhone + historial | RDF + `NotificarBusquedaRealizada` → Feedback |
| JP-03 | 8.1 | Alta producto externo | `DarAltaProductoExterno` |
| JP-04 | 8.2 | Carrito + Barcelona `dist` 130 | Proximidad CL-BCN + stock |
| JP-05 | 8.2 | Compra urgente | Prioridad 1, entrega ≤ 1 día |
| JP-06 | 8.2 | Compra no urgente + lote pendiente | `pending_lotes` antes del despacho |
| JP-07 | 8.2 | Dos compras simultáneas (misma ubicación) | Mismo lote y transportista, distinto `pedido_id` |
| JP-08 | 8.2 | Simultáneas con urgencia distinta | Adhesión al lote + prioridad del lote = 1 |
| JP-09 | 8.2 | Carrito interno + externo | Despacho mixto comerciante |
| JP-10 | 8.2 | Histórico de pedidos | Persistencia en asistente |
| JP-11 | 8.2 | Producto pesado → `tarifa_kg` | CFP, gana Express (9003) |
| JP-12 | 8.2 | Compra normal → `tarifa_dia` | CFP, prioridad 2, componente día |
| JP-13 | 8.2 | Selección CL Madrid | Multi-CL por proximidad |
| JP-14 | 8.2 | Transportista grupo de 3os | `transportista_externo` en CFP |
| JP-15 | 8.3 | Callback `PedirFeedback` + media | Proactivo + `valoracionMedia` |
| JP-16 | 8.3 | Recomendación tras búsqueda por marca | Historial + scheduler |
| JP-17 | 8.3 | Recomendación tras compra | Perfil de compra |
| JP-18 | 8.4 | Devolución aceptada | Agente devolución + reembolso |
| JP-19 | 8.4 | Devolución rechazada (plazo 15 días) | Política de motivos |

---

## 8.1 Búsqueda, filtros y persistencia

### JP-01 — Catálogo entero sin filtros

**Objetivo:** Comprobar acceso a ProductosDB con atributos y comunicación Asistente → Catálogo.

**Pasos (interfaz — pestaña «01 / Buscar»)**

1. Dejad vacíos: marca, nombre, precio máximo, valoración mínima.
2. Pulsad **Buscar**.

**Resultado esperado**

- Lista con **todos** los productos del catálogo (p. ej. 8 ítems) con `id`, precio, valoración, tipo interno/externo.
- Log del catálogo: `Busqueda: {} -> N productos`.

**Evidencia:** Captura de la lista o log `[catalogo] Busqueda: {}`.

> `assistant_demo` siempre intenta comprar si hay resultados; para este juego usad la **interfaz** (solo búsqueda).

---

### JP-02 — Filtros en cadena + historial Feedback

**Objetivo:** Ver cómo se reducen resultados al añadir restricciones y que el **AgenteFeedback** registra cada consulta (Protocolo Consulta Catálogo).

**Pasos (interfaz — misma pestaña, sin recargar entre pasos si queréis ver el efecto “dinámico”)**

| Paso | Marca | Precio máx. | Nombre | Resultado esperado |
|------|-------|-------------|--------|-------------------|
| 1 | `Apple` | (vacío) | (vacío) | Solo productos Apple (`P-IPHONE19`, `P-MACBOOK-AIR`, …) |
| 2 | `Apple` | `1000` | (vacío) | Desaparece `P-MACBOOK-AIR` (1299 €); permanece iPhone si ≤ 1000 |
| 3 | `Apple` | `1000` | `Iphone` | Lista acotada a iPhone (p. ej. `P-IPHONE19`) |

**Resultado esperado (comunicación Feedback)**

- Log del feedback: `Protocolo Consulta Catálogo: búsqueda registrada`.
- Tras reiniciar agentes, persisten entradas en:
  - `src/data/searches.json` (historial Feedback / HistorialDB)
  - `src/data/catalog_searches.json` (traza local del catálogo)

**Evidencia:** Últimas líneas de `searches.json` con `brand`, `max_price`, `name` y recuento de productos.

**CLI (paso 3, incluye compra opcional):**

```bash
python -m assistant_demo --brand Apple --max-price 1000 --search-name iphone \
  --city Barcelona --delivery-dist 130 --priority 2 --payment-card 4111111111111111
```

---

### JP-03 — Adición de un nuevo producto externo

**Objetivo:** Un producto externo nuevo aparece en el catálogo tras `DarAltaProductoExterno`.

**Precondición:** `develop.sh` arranca **VendedorExterno** con `--announce-products` (registra `P-CARGADOR-GAN` al inicio).

**Pasos**

1. Tras el arranque, en **01 / Buscar** buscad `cargador` o `voltix`.
2. Comprobad que aparece `P-CARGADOR-GAN` como **externo**.
3. Log del catálogo: alta externa / producto integrado; log del vendedor (9008): anuncio al catálogo.

**Variante (producto realmente nuevo):** añadid otra entrada en `_default_external_products()` de `agents/vendedor_externo.py`, reiniciad solo vendedor + catálogo, y repetid la búsqueda.

**Evidencia:** Producto visible en interfaz + triple en `data/catalog.ttl` actualizado tras el alta.

---

## 8.2 Compra y planificación de pedido

### JP-04 — Carrito, Barcelona (`dist` 130) y selección de CL

**Objetivo:** Añadir productos al carrito, comprar en Barcelona con distancia logística 130; el comerciante elige **CL-BCN** por proximidad y el CL comprueba stock.

**Pasos (interfaz — recomendado para carrito)**

1. **01 / Buscar:** `iphone` → seleccionar `P-IPHONE19` → **Añadir al carrito** (podéis añadir un segundo interno si queréis varias líneas).
2. **02 / Pedido:** ciudad `Barcelona`, calle `Carrer Mallorca 401`, CP `08013`, **Distancia logística entrega** `130`, prioridad `2` (normal), tarjeta demo.
3. Confirmar pedido.

**CLI (un producto):**

```bash
python -m assistant_demo --search-name iphone --city Barcelona \
  --delivery-dist 130 --priority 2 --payment-card 4111111111111111
```

**Resultado esperado**

- Pedido aceptado; ticket con `centro_label` / **Barcelona** (CL-BCN, puerto 9002).
- Log CL-BCN: disponibilidad, `AgruparPedidoEnLote`.

**Evidencia:** Ticket + log comerciante (`Centros logísticos descubiertos`) + primer `AvisarCL` a 9002.

---

### JP-05 — Compra urgente (entrega día siguiente)

**Objetivo:** El ticket muestra **fecha de entrega** acorde a prioridad **1** (máximo al día siguiente en la oferta del transportista).

**Pasos**

```bash
python -m assistant_demo --search-name iphone --city Barcelona \
  --delivery-dist 130 --priority 1 --payment-card 4111111111111111
```

O en interfaz: prioridad de entrega **Urgente (1)**.

**Resultado esperado**

- En consola / ticket: `Fecha estimada` a **1 día** vista (oferta CFP con `dias=1` en log del transportista).
- El lote usa debounce corto (`LOT_URGENT_DEBOUNCE`, ~5 s) si consultáis `pending_lotes` justo después.

**Evidencia:** Línea `Fecha estimada` en `assistant_demo` o bloque «Ticket envío tienda / logística» en iface.

---

### JP-06 — Compra no urgente y lote pendiente

**Objetivo:** Comprobar que el pedido queda en un **lote pendiente** antes del despacho.

**Pasos**

1. Ejecutad JP-04 con **prioridad 3** (o 2) y **no** esperéis 35 s.
2. Inmediatamente:

```bash
curl -s http://127.0.0.1:9002/info | python3 -m json.tool
```

**Resultado esperado**

- `pending_lotes` con al menos un lote en estado `pendiente_envio`, con `lineas` / `pedidos` y `prioridad` coherente.
- Tras **35–45 s** sin nuevos pedidos: despacho, negociación CFP y fichero en `data/lotes/`.

**Evidencia:** JSON de `pending_lotes` **antes** del despacho (captura con timestamp).

---

### JP-07 — Dos compras simultáneas (misma ubicación)

**Objetivo:** Dos pedidos desde el mismo destino comparten **lote** y **transportista**; cada pedido tiene **identificador distinto** (`pedido_id` / confirmación distinta).

**Pasos**

En **dos terminales**, casi a la vez (misma ciudad y `delivery-dist`):

```bash
# Terminal A
python -m assistant_demo --search-name batidora --city Barcelona \
  --delivery-dist 130 --priority 3 --payment-card 4111111111111111

# Terminal B (inmediatamente)
python -m assistant_demo --search-name libro --city Barcelona \
  --delivery-dist 130 --priority 3 --payment-card 4111111111111111
```

**Resultado esperado**

- Un solo `lote_id` en `pending_lotes` con **≥ 2** líneas / pedidos.
- Tras el despacho: mismos transportista y lote en ambos tickets; **`Pedido:`** distinto en cada consola (códigos de envío / pedido distintos).

**Evidencia:** `curl` a `9002/info` + captura de dos tickets con mismo `Lote:` y distinto `Pedido:`.

---

### JP-08 — Simultáneas con urgencia distinta

**Objetivo:** Si ya hay un lote hacia la misma zona, el segundo pedido **se adhiere**; la prioridad del lote pasa a la más urgente (1) y el despacho se adelanta.

**Pasos**

1. Terminal A — pedido **no urgente** (prioridad 3):

```bash
python -m assistant_demo --search-name batidora --city Barcelona \
  --delivery-dist 130 --priority 3 --payment-card 4111111111111111
```

2. En los **5 s siguientes**, terminal B — pedido **urgente** (prioridad 1):

```bash
python -m assistant_demo --search-name iphone --city Barcelona \
  --delivery-dist 130 --priority 1 --payment-card 4111111111111111
```

3. Consultad `pending_lotes`: el lote debe mostrar `prioridad: 1` y `ready_for_dispatch` antes que si solo hubiera pedidos con prioridad 3.

**Resultado esperado**

- Un único lote con ambos pedidos; prioridad del lote = **1**; debounce efectivo ~5 s (urgente).

**Evidencia:** JSON `pending_lotes` + comparación de tiempos de despacho frente a JP-07.

---

### JP-09 — Carrito con productos internos y externos

**Objetivo:** Un solo pedido mezcla línea **interna** (CL) y **externa** (vendedor envía).

**Pasos (interfaz)**

1. Buscar `iphone` → añadir `P-IPHONE19` al carrito.
2. Buscar `cargador` → añadir `P-CARGADOR-GAN` al carrito.
3. Pedido a Barcelona, `dist` 130, prioridad 2, confirmar.

**CLI (dos búsquedas fusionadas):**

```bash
python -m assistant_demo --search-name iphone --extra-search-name cargador \
  --buy-results 2 --product-index 1 --city Barcelona --delivery-dist 130 \
  --priority 2 --payment-card 4111111111111111
```

**Resultado esperado**

- Ticket con **envío logístico** (CL) para el interno y **ticket envío vendedor externo** para `P-CARGADOR-GAN`.
- Log vendedor 9008: `ComunicarProductosExternosPedidos`.
- Log CL-BCN: actividad solo para la línea interna.

**Evidencia:** Resumen de pedido en iface con dos bloques de envío.

---

### JP-10 — Consultar histórico de pedidos

**Objetivo:** Comprobar **persistencia** de pedidos confirmados en el asistente.

**Pasos**

1. Completad al menos JP-04 o JP-05.
2. Interfaz → pestaña **«06 / Pedidos»** → **Actualizar**.

**Resultado esperado**

- Lista con `pedido_id`, fecha, importe y enlaces a devolución/valoración.
- Tras reiniciar solo el asistente (comerciante y `data/completed_orders/` intactos), el histórico sigue visible si el comerciante responde a la consulta.

**Evidencia:** Captura pestaña 06 + ficheros en `src/data/completed_orders/`.

---

### JP-11 — Producto pesado: gana menor `tarifa_kg`

**Objetivo:** Con peso alto, el CL selecciona el transportista con **menor tarifa por kg** (Express, 9003).

**Pasos**

```bash
python -m assistant_demo --search-name batidora --city Barcelona \
  --delivery-dist 130 --priority 2 --payment-card 4111111111111111
```

(`P-BATIDORA-MINI`, 1,20 kg.)

**Resultado esperado**

- Log CL-BCN (verbose recomendado): ofertas de 9003 y 9011; **oferta seleccionada** del Express.
- Log transportista: `peso=1.2` (aprox.) y precio calculado con `tarifa_kg=1.75` en 9003.

**Evidencia:** Fragmento de log «Oferta seleccionada» / transportista ganador `9003`.

---

### JP-12 — Compra normal: componente `tarifa_dia`

**Objetivo:** Pedido ligero con prioridad **2** (3 días en fórmula); el CFP penaliza más el transportista con **`tarifa_dia` alta** (Express 0,80 vs Eco 0,50).

**Pasos**

```bash
python -m assistant_demo --search-name iphone --city Barcelona \
  --delivery-dist 130 --priority 2 --payment-card 4111111111111111
```

**Resultado esperado**

- Suele ganar **TransportistaEco (9011)** por menor coste total (base baja + `tarifa_dia` 0,50 × 3 días).
- Log: `dias=3` en la oferta.

**Evidencia:** Log CL + línea `Coste envio` en ticket; comparar con JP-11 (mismo CL, distinto ganador según peso).

---

### JP-13 — Selección de centro logístico (Madrid)

**Objetivo:** Con dos CL registrados, el comerciante elige **CL-MAD** por proximidad cuando `delivery-dist` ≈ 480.

**Pasos**

```bash
python -m assistant_demo --search-name iphone --city Madrid \
  --street "Gran Via 28" --postal-code 28013 --delivery-dist 480 \
  --priority 2 --payment-card 4111111111111111
```

**Resultado esperado**

- Ticket con centro **Madrid** (9012), no BCN.
- Actividad en logs de **9012**.

**Evidencia:** `centro_label` en ticket + `curl http://127.0.0.1:9012/info`.

---

### JP-14 — Transportista del grupo de terceros

**Objetivo:** Verificar integración del **AgTransportista** externo en el Contract Net.

**Precondición:** JP-14 en preparación común (puerto **9014** registrado en el directorio).

**Pasos**

1. Arrancad `transportista_externo` (9014).
2. Pedido estándar en Barcelona:

```bash
python -m assistant_demo --search-name iphone --city Barcelona \
  --delivery-dist 130 --priority 2 --payment-card 4111111111111111
```

**Resultado esperado**

- Log CL: **tres** ofertas (9003, 9011, 9014); una seleccionada (según precio fijo 5,50 € + lógica del agente externo).
- Si 9014 gana, el ticket muestra ese transportista.

**Evidencia:** Log «Oferta seleccionada» mencionando el agente del puerto 9014.

---

## 8.3 Valoraciones y recomendaciones

### JP-15 — Callback `PedirFeedback` y actualización de media

**Objetivo:** Llegada **proactiva** de la solicitud de opinión y cambio de `valoracionMedia` en búsquedas posteriores.

**Pasos**

1. Completad JP-04 (compra iPhone).
2. Esperad **~60 s** (consola asistente 9010 o pestaña valoración / notificaciones).
3. Valorad el producto (p. ej. 5 estrellas) desde la notificación o pestaña correspondiente.
4. Buscad de nuevo `iphone` en **01 / Buscar**.

**Resultado esperado**

- Log asistente: `PedirFeedback recibido`.
- `valoracionMedia` de `P-IPHONE19` distinta a la previa.

**Atajo de laboratorio (si el tiempo en defensa es corto):**

```bash
python -m feedback_demo --simulate-notify --product-id P-IPHONE19 --puntuacion 4
```

Luego repetid la búsqueda en iface.

**Evidencia:** Captura antes/después de la media + entrada en catálogo persistido.

---

### JP-16 — Recomendación proactiva tras búsqueda por marca

**Objetivo:** Tras buscar por marca, el scheduler de Feedback envía recomendaciones al asistente.

**Pasos**

1. JP-02 paso 1 (marca **Apple**) o búsqueda `--brand Apple`.
2. Esperad **~2 min** (`recommendation-warmup` 30 s + `recommendation-period` 120 s).
3. Interfaz → **Recomendaciones** → **Actualizar buzón**.

**Resultado esperado**

- Log feedback: `Recomendaciones content-based generadas`.
- Log asistente: `Recomendaciones proactivas recibidas`.
- Productos relacionados con Apple / historial.

**Evidencia:** Buzón de recomendaciones con al menos un ítem y motivo en la UI.

---

### JP-17 — Recomendación proactiva tras compra

**Objetivo:** Tras una compra, se recomiendan productos similares a los intereses.

**Pasos**

1. Completad JP-04.
2. Esperad el periodo de recomendación (~2 min) o forzad con compra reciente y buzón actualizado.
3. Revisad pestaña **Recomendaciones**.

**CLI auxiliar:**

```bash
python -m assistant_demo --search-name iphone --show-recommendations \
  --payment-card 4111111111111111
```

**Resultado esperado**

- Recomendaciones no vacías vinculadas al perfil (marca/precio del iPhone u otros Apple).

**Evidencia:** Lista en buzón + log `Recomendación proactiva enviada`.

---

## 8.4 Devoluciones

### JP-18 — Devolución aceptada

**Objetivo:** Flujo completo: validación, recogida simulada, reembolso.

**Pasos**

```bash
python -m devolucion_demo --search-name iphone \
  --motivo "Pantalla con defecto de fabrica" --payment-card 4111111111111111
```

O interfaz → devolución sobre un pedido de JP-04 con motivo «Producto defectuoso».

**Resultado esperado**

- Devolución **aceptada**; log agente devolución (9009) y reembolso simulado.

**Evidencia:** Salida de `devolucion_demo` o confirmación en UI.

---

### JP-19 — Devolución rechazada (plazo 15 días)

**Objetivo:** Impedir la devolución cuando el motivo **«No satisface expectativas»** y la **fecha de recepción** supera los **15 días** (política implementada en `agente_devolucion` y validación en interfaz).

> **Nota memoria:** El rechazo por plazo aplica al motivo *expectativas* con fecha de recepción explícita, no al motivo «defecto de fábrica» (sin límite de 15 días en la política actual). Ajustad la redacción del capítulo 8.4 si el evaluador debe ver exactamente este flujo.

**Pasos (interfaz — pestaña devolución)**

1. Elegid un pedido completado (JP-04).
2. Motivo: **«No satisface expectativas»**.
3. Fecha de recepción: **hace más de 15 días** (p. ej. hace 20 días).
4. Solicitar devolución.

**Resultado esperado**

- Mensaje de error / solicitud **denegada** (UI o `failure` ACL).
- Texto referente al plazo de 15 días.

**Evidencia:** Captura del mensaje de denegación (sin reembolso).

---

## Directorio (transversal)

Registro y descubrimiento de agentes (complementa cualquier JP):

```bash
curl -s http://127.0.0.1:9000/info | python3 -m json.tool
```

**Resultado esperado:** Entradas `AGENTE_COMERCIANTE`, `AGENTE_CATALOGO`, `CENTRO_LOGISTICO` (×2), transportistas, feedback, devolución, asistente, etc., con `address` `http://127.0.0.1:9xxx/comm`.

---

## Juego opcional — Fallo por stock (multi-CL)

**Objetivo:** El comerciante prueba otro CL si el primero no tiene stock.

1. En `data/catalog.ttl`: `cantidadDisponible 0` para un producto solo en CL-BCN; mantener stock en CL-MAD.
2. Reiniciar catálogo y CLs.
3. Pedido con `delivery-dist` que prefiera BCN pero stock solo en MAD.

**Resultado esperado:** Pedido aceptado vía **CL-MAD** tras skip/fallo de BCN.

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
| Transportista externo (3os) | **9014** (`./distributed.sh transportista_externo`) |
