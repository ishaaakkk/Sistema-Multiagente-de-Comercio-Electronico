# Práctica ECSDI — Memoria

> Esta es la memoria de la tercera entrega. Está estructurada según los
> nueve criterios de la rúbrica del guión (cap. 5 del enunciado) y se
> apoya en los artefactos versionados del repositorio (ontología, PD y
> código fuente).

## 1. Definición del problema (rúbrica: definición)

Se modela un sistema multiagente para una **tienda de comercio
electrónico** con productos propios y de vendedores externos. El sistema
debe permitir buscar productos, hacer pedidos, gestionar el envío con
centros logísticos y transportistas, cobrar al cliente, pagar al
vendedor externo, gestionar devoluciones con reembolso y, además,
solicitar valoraciones al usuario y recomendar productos a partir de su
historial.

Las 5 tareas básicas del guión (3.3) se cubren todas:

1. Búsqueda de productos en el catálogo.
2. Realización de pedidos (productos internos y externos).
3. Gestión de envíos por centros logísticos y transportistas.
4. Gestión de devoluciones (validación, recogida y reembolso).
5. Solicitud diferida de valoraciones y recomendaciones proactivas.

Además se implementan **4 de los 5 elementos del nivel avanzado**
(criterio 3.4 del guión), dejando fuera la negociación con
contraofertas:

- **#1 Transportistas dinámicos**: 2 transportistas (`Express` y `Eco`)
  registrados en el **Directorio Service**; cada Centro Logístico les
  pide presupuesto en **paralelo** mediante un **Contract-Net**
  (cfp/propose/accept-proposal/reject-proposal).
- **#3 Multi-CL**: 2 centros logísticos en ciudades distintas
  (`CL-BCN` y `CL-MAD`); cada uno sirve las líneas para las que tiene
  stock y negocia su propio transporte.
- **#4 Agentes de pago**: `AgenteFinanciero` cobra al cliente, reembolsa
  devoluciones y paga a vendedores externos, apoyándose en un
  `ProveedorPagos` simulado.
- **#5 Feedback proactivo + recomendación**: petición de valoración
  diferida N días tras la entrega y recomendaciones periódicas
  proactivas basadas en compras, búsquedas y valoraciones.

## 2. Descripción de la ontología

Toda la ontología se mantiene en `ontology/comercio_electronico.ttl`.
La documentación HTML se regenera con:

```bash
python doc/ontology/generate_docs.py
```

y se publica en `doc/ontology/comercio_electronico.html` (pyLODE) junto
con el diagrama de clases en `doc/ontology/comercio_electronico.dot`
(`.png` si Graphviz está disponible).

### 2.1 Decisiones de modelado

- **Reutilización de vocabularios estándar** (cap. 6.5):
  - `Actor rdfs:subClassOf foaf:Agent`.
  - `Producto rdfs:subClassOf schema:Product`.
  - `Pedido rdfs:subClassOf schema:Order`.
  - `Direccion rdfs:subClassOf schema:PostalAddress`.
  - `Valoracion rdfs:subClassOf schema:Review`.
  - Fechas y deadlines tipadas con `xsd:dateTime` o como instancias de
    `time:Instant` cuando se quiere razonar temporalmente.
- **Anotación de la ontología** con `dcterms:creator`,
  `dcterms:license`, `dcterms:modified` y `owl:versionInfo "1.1.0"`.

### 2.2 Jerarquía principal (Figura 1)

La Figura 1 de la memoria es el render del archivo
`doc/ontology/comercio_electronico.dot` (`.png` cuando se renderiza con
`dot -Tpng`). Cubre la jerarquía de `Producto`, `Pedido`, `Envio`,
`OperacionPago`, `Accion` y `Notificacion`.

### 2.3 Restricciones DL añadidas (cap. 6.4)

- `owl:disjointWith`:
  - `ProductoInterno` ⊥ `ProductoExterno`.
  - `EnvioDevolucion` ⊥ `EnvioExterno` ⊥ `EnvioInterno`.
  - `CobroCliente` ⊥ `ReembolsoCliente` ⊥ `PagoVendedorExterno`.
- `owl:FunctionalProperty`: `idDevolucion`, `idFactura`,
  `idOperacionPago`, `idPedido`, `idProducto` (cada entidad tiene un
  identificador único).
- `owl:inverseOf`: `facturaDePedido` ↔ `pedidoTieneFactura`,
  `envioDePedido` ↔ `pedidoTieneEnvio`.
- `owl:minCardinality 1` sobre `pedidoTieneLinea` en `Pedido` (un
  pedido siempre tiene al menos una línea).

### 2.4 Vocabulario nuevo añadido en esta entrega

- `NotificarBusquedaRealizada` (subclase de `Notificacion`) para el
  **Protocolo Consulta Catálogo**: el Catálogo informa al Feedback de
  cada búsqueda.
- `fechaBusqueda` para anotar la búsqueda.
- `DecisionContratoTransporte` (subclase de `Respuesta`) para representar
  la decisión informativa del Centro Logístico tras comparar ofertas.
- `envioDesdeCentro` para identificar el centro logístico que sirve un
  envío en el escenario multi-CL.
- `metodoPago` en `Pedido` y `dist` en `Direccion` (entero 0–1000): métrica
  logística unidimensional para la heurística de selección de CL.

### 2.5 PreguntarDatosCompra y selección de CL

El plan **PreguntarDatosCompra** se ejecuta en el **AsistenteVirtual**
(formulario: dirección, prioridad, método de pago, `dist` de entrega). El
**AgenteComerciante** solo valida que el mensaje `RealizarPedido` incluya
`pedidoEnviadoA`, `prioridadEntrega`, `metodoPago` y `dist` en la dirección,
y propaga `metodoPago` en `SolicitarCobro`.

Para **EscogerCL**, cada centro logístico se registra con `--dist` (métrica
operativa 0–1000). El comerciante descubre todos los CL, lee `dist` vía
`GET /info`, ordena por `|dist_CL − dist_entrega|` y contacta de forma
**secuencial y greedy** hasta asignar todas las líneas (multi-CL).

### 2.6 Correcciones aplicadas

Se han corregido errores que aparecían en versiones anteriores tanto en
la ontología como en los ejemplos citados en la memoria:

- `ConfirmacionComprra` → `ConfirmacionCompra`.
- `pedidioiPhone19` → `pedidoiPhone19`.
- `Barceluna` → `Barcelona` (instancia y literales).
- Propiedades duplicadas unificadas:
  - `pedidoDeUsuario` deprecada, sustituida por `pedidoSolicitadoPor`
    (`owl:equivalentProperty`, `owl:deprecated true`).
  - `accionTieneValoracion` deprecada, sustituida por
    `notificacionTieneValoracion`.

### 2.7 Aclaración Feedback vs Recomendador

En las versiones anteriores aparecía un agente `AgenteRecomendador` como
si fuera independiente. **Hay un único agente, `AgenteFeedback`**, que
asume tres roles:

1. *Registrador de búsquedas* — recibe `NotificarBusquedaRealizada` del
   Catálogo.
2. *Recogedor de feedback* — programa peticiones diferidas de
   valoración tras la entrega.
3. *Recomendador* — calcula recomendaciones content-based y las envía
   proactivamente o a petición.

El PD debe reflejar esto como roles del mismo agente (ver
`doc/pd-pending-updates.md`).

### 2.7 Agente Feedback / Recomendador — detalle

El `AgenteFeedback` (`src/agents/agente_feedback.py`) es un solo agente
con tres roles internos:

#### Rol RegistradorBúsquedas (protocolo Consulta Catálogo)

- Recibe `NotificarBusquedaRealizada` (ACL.inform) desde el Catálogo
  cada vez que se ejecuta una `BuscarProductos`.
- Guarda la búsqueda en `searches.json` y replica el contenido como
  triples (`NotificarBusquedaRealizada`,
  `accionSolicitadaPor`/`fechaBusqueda`/restricciones) en el grafo
  nombrado `searches` del Dataset compartido.

#### Rol RecogedorFeedback (petición diferida de valoración)

- Tras `NotificarCompraCompletada` no pregunta inmediatamente: programa
  un `Timer` que, transcurridos `FEEDBACK_DELAY_SECONDS` segundos desde
  la fecha de entrega prevista, envía `PedirFeedback` (ACL.request) al
  asistente.
- El valor por defecto en producción son N días; en demo se reduce a
  segundos vía variable de entorno `FEEDBACK_DELAY_SECONDS` (cf.
  `src/develop.sh`).
- Cada opinión queda con campo `feedback_solicitado` y, cuando llega la
  `EnviarOpinion`/`RegistrarValoracion`, se rellenan `puntuacion` y
  `comentario` y se persiste tanto en `opinions.json` como en el grafo
  `opinions` del Dataset.

#### Rol Recomendador (proactivo y periódico)

- Un *scheduler* en background ejecuta el algoritmo content-based cada
  `RECOMMENDATION_PERIOD_SECONDS` segundos.
- El perfil del usuario se construye combinando **compras** (peso 3),
  **valoraciones positivas** (peso 2 · puntuación-3) y **búsquedas**
  (peso 1), por marca, categoría y rango de precio. Es una versión
  ligera del modelo de perfil del cap. 9.5 de los apuntes.
- Para cada asistente conocido se obtienen los productos candidatos del
  catálogo, se les asigna un score y se materializa el grafo de
  resultados con un `SPARQL CONSTRUCT`
  (`_materialize_recommendations_sparql`) sobre triples sembrados.
- El grafo resultante se envía como `ACL.inform` al asistente; el
  asistente lo expone en `/recommendations-inbox` para que el usuario
  lo consulte.
- Se mantiene también el modo "a petición" (compatibilidad): si el
  asistente envía `BuscarProductos` con `tipoBusqueda=recomendacion`,
  el feedback responde con el mismo algoritmo.

#### Justificación de la elección (content-based)

- El sistema solo tiene **un usuario** activo a la vez (el asistente del
  cliente que está navegando), por lo que la matriz usuario-producto
  sería degenerada y un filtrado colaborativo no aportaría señal.
- El historial disponible (compras + búsquedas + valoraciones) es
  suficiente para inferir preferencias por marca, categoría y precio.
- El algoritmo content-based del cap. 9.5 (perfil ponderado y similitud)
  encaja directamente con esos datos y se puede expresar como un par
  de SPARQL CONSTRUCT/SELECT, lo que justifica la elección frente a un
  recomendador colaborativo.

## 3. Diseño con Prometheus (rúbrica: proceso/estrategias)

El PD se mantiene en `pdtool/finalMod.pd`. Los cambios necesarios para
sincronizarlo con esta entrega están enumerados en
`doc/pd-pending-updates.md` (capacidades por agente, protocolos FIPA por
conversación, patrones de coordinación, fuentes de datos). El report
HTML actual está en `doc/pdtool/defaultreport_2026-05-19/`.

## 4. Estrategias y patrones de coordinación

- **Brokering / Matchmaking** vía `DirectoryService`: los agentes se
  registran con `dso:AgentType` y, además, con `dso:Capability` (URI
  de la ontología, perfil de servicio OWL-S del cap. 8.5.2). Los demás
  agentes pueden buscar por tipo o por capacidad.
- **Red de contratos simplificada** (cap. 8.3): cada Centro Logístico, al
  recibir `AvisarCL`, solicita presupuestos en paralelo a los
  transportistas registrados, elige la mejor oferta y cierra la decisión
  con `accept-proposal` al ganador y `reject-proposal` a los demás.
- **Notificación / fire-and-forget**: protocolo Consulta Catálogo
  (Catálogo → Feedback), `NotificarCompraCompletada` (Comerciante →
  Feedback) y recomendaciones proactivas (Feedback → Asistente)
  utilizan `ACL.inform` sin esperar respuesta.

## 5. Resolución del problema

El flujo principal de compra es:

```
Asistente ──RealizarPedido──▶ Comerciante
                                  │
                                  ├─AvisarCL──▶ CL-BCN ─CFP─▶ Transportistas (paralelo)
                                  └─AvisarCL──▶ CL-MAD ─CFP─▶ Transportistas (paralelo)
Comerciante ──SolicitarCobro──▶ Financiero ──SolicitarOperacionPago──▶ ProveedorPagos
Comerciante ──PagarProductoExterno──▶ Financiero (si hay producto externo)
Comerciante ──NotificarCompraCompletada──▶ Feedback (programa PedirFeedback diferido)
Feedback ──Recomendacion (proactiva, periódica)──▶ Asistente
```

Las devoluciones siguen un flujo análogo:

```
Asistente ──SolicitarDevolucion──▶ AgenteDevolucion
                                       │
                                       ├─PeticionInfoPedidoCompletado──▶ Comerciante (valida)
                                       ├─SolicitarRecogidaDevolucion──▶ Transportista
                                       └─SolicitarReembolso──▶ Financiero
```

## 6. Implementación (rúbrica: implementación)

- Cada agente vive en `src/agents/*.py` y se arranca con Flask en su
  propio puerto, con `register_service` al directorio y
  `unregister_service` al apagado.
- El envoltorio FIPA-ACL en `src/utilities/acl.py` añade
  `conversation-id`, `reply-with`, `in-reply-to` y `protocol` (cap.
  2.3.1).
- La capa SPARQL (cap. 6) se usa en:
  - `utilities/catalog.py` (`PRODUCT_SEARCH_SPARQL`).
  - `agente_devolucion._find_order_line` (UNION/OPTIONAL para casar
    por URI o por id).
  - `agente_feedback._materialize_recommendations_sparql` (CONSTRUCT
    que genera el grafo de `Recomendacion`).
- La persistencia es doble:
  - JSON legible (`opinions.json`, `searches.json`,
    `devoluciones.json`) para depuración rápida.
  - Espejo RDF en `dataset.trig` con grafos nombrados
    (`utilities/storage.save_named_graph`) para usar SPARQL/CONSTRUCT
    sobre todo el estado del sistema.

## 7. Explicaciones de decisiones

### 7.1 Preguntas del cap. 1.5 (Wooldridge / apuntes)

| Pregunta | Respuesta |
| --- | --- |
| ¿Qué problemas resuelve el sistema? | E-commerce con productos internos+externos, multi-CL y multi-transportista. |
| ¿Por qué agentes y no un monolito? | Heterogeneidad de actores (clientes, vendedores externos, financiero) y necesidad de descubrimiento dinámico. |
| ¿Qué información usan? | Ontología compartida + grafos nombrados RDF + JSON espejo. |
| ¿Cómo se coordinan? | FIPA-ACL: Request/Inform + Contract-Net para transporte. |
| ¿Quién decide qué? | Comerciante orquesta el pedido; cada CL decide el transportista; Feedback decide cuándo recomendar. |
| ¿Cómo se descubren? | DirectoryService con `dso:AgentType` + `dso:Capability` (URI ontología, perfil OWL-S). |
| ¿Cómo se garantiza tolerancia a fallos? | Timeouts y `failure` controlados por agente; el Comerciante absorbe `failure` de CL sin stock y continúa con los que respondan. |
| ¿Cómo se evita el cuello de botella central? | Lógica orquestada (Comerciante) + delegación en agentes especializados (CL, Transportista, Financiero, Feedback). |

### 7.2 Tabla de mensajes FIPA-ACL (resumen)

| Conversación | Iniciador | Receptor | Protocolo | Performativas |
| --- | --- | --- | --- | --- |
| BuscarProductos | Asistente | Catálogo | FIPA Request | request → inform/failure |
| RealizarPedido | Asistente | Comerciante | FIPA Request | request → inform/failure |
| AvisarCL | Comerciante | Cada CL | FIPA Request (multi-destinatario) | request → inform/failure |
| CFP Transporte | CL | Cada Transportista | **FIPA Contract-Net** | cfp → propose / refuse; accept-proposal / reject-proposal; inform |
| ConfirmarEnvio | CL | Comerciante | FIPA Inform | inform |
| SolicitarCobro / SolicitarReembolso / PagarProductoExterno | Comerciante / Devolución | Financiero | FIPA Request | request → inform/failure |
| SolicitarOperacionPago | Financiero | ProveedorPagos | FIPA Request | request → inform/failure |
| ComunicarProductosExternos | Comerciante | VendedorExterno | FIPA Inform (fire-and-forget) | inform |
| NotificarBusquedaRealizada | Catálogo | Feedback | FIPA Inform | inform |
| NotificarCompraCompletada | Comerciante | Feedback | FIPA Inform | inform |
| PedirFeedback (diferida) | Feedback | Asistente | FIPA Request | request → inform |
| Recomendacion proactiva | Feedback | Asistente | FIPA Inform | inform |
| SolicitarDevolucion | Asistente | Devolución | FIPA Request | request → inform/failure |
| PeticionInfoPedidoCompletado | Devolución | Comerciante | FIPA Request | request → inform/failure |
| Registro / Búsqueda | Cualquier agente | Directorio | FIPA Request | request → confirm/inform/failure |

Todas las conversaciones llevan `conversation-id` y `reply-with` para
correlación, gestionados por `utilities/acl.py` (helpers `build_message`
y `build_reply`).

## 8. Pruebas y evaluación (rúbrica: pruebas/evaluación)

Los juegos de prueba están detallados en `doc/test-scenarios.md`
(§ Test Scenarios). Cubren las 5 tareas básicas y los 3+ elementos
avanzados, incluyendo casos de fallo (devolución denegada, transportista
que no responde, producto externo, pedido multi-CL).

Tests unitarios de utilidades (`utilities/acl`, `utilities/comm`,
`utilities/catalog`) en `src/tests/`. Se ejecutan con:

```bash
cd src && python -m unittest discover -s tests -t . -v
```

## 9. Limitaciones

- No se implementan **contraofertas** en el Contract-Net (elemento
  avanzado #2): el CL elige al transportista más barato sin
  renegociar.
- La cobertura del grafo `dataset.trig` es **espejo** de la
  persistencia JSON; el sistema sigue ejecutando la lógica en
  estructuras Python para no penalizar rendimiento (ver §6).
- La demo distribuida real (varias máquinas) se documenta en
  `src/develop.sh` y `doc/distributed-demo.md`; el binding a 0.0.0.0 se
  controla con el flag `--open` de cada agente.
- La ontología de transporte **no está compartida** con otro grupo
  (nota extra m del guión); queda como trabajo futuro.
