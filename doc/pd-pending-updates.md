# Cambios pendientes en el PD (Prometheus Design Tool)

Esta lista resume los puntos que faltan por reflejar en
`pdtool/finalMod.pd` (y en el report HTML asociado) tras el refactor del
código. Está priorizada de mayor a menor impacto en la rúbrica y
referencia los apuntes (cap. 1, 4, 5, 8) y el guión de la práctica.

> El PD se edita manualmente en PDT por decisión del usuario; aquí solo
> se enumera **qué** debe quedar reflejado para que código, memoria y
> diagramas sean coherentes.

## 1. Actores y roles (cap. 4.5, criterio rúbrica de definición/proceso)

- Desdoblar **Centro Logístico** en dos instancias del mismo agente:
`CL-BCN` y `CL-MAD`, cada uno con su stock y zona geográfica
(extensión avanzada #3 multi-CL del guión).
- Desdoblar **Transportista** en al menos dos: `TransportistaExpress`
(más rápido y caro) y `TransportistaEco` (más lento y barato)
(extensión avanzada #1 del guión).
- Añadir **Agente Financiero** y **Proveedor de Pagos** como agentes
diferenciados (extensión avanzada #4 del guión).
- Renombrar `AgenteRecomendador` → indicar que es **un rol del Agente
Feedback**: roles `RecogedorFeedback`, `Recomendador`,
`RegistradorBúsquedas` dentro del mismo agente
(decisión del usuario: un único agente).
- Mantener **Directorio Service** como agente de soporte ("yellow
pages") y reconocerlo como **broker/matchmaker** del sistema.

## 2. Capacidades (capabilities / planes) — cap. 5

Para cada agente, añadir los planes que faltan o renombrarlos para que
coincidan con el código:

### Agente Comerciante

- `PreguntarDatosCompra`
- `RegistrarPedidoPendiente`
- `EscogerCL` (con notificador `AvisarCL`, en paralelo a TODOS los CL)
- `ComunicarVendedoresExternos` (`PagarProductoExterno`, `AvisarVendedorExterno`)
- `RealizarCobro` (→ Agente Financiero)
- `FinalizarPedido` (→ Agente Feedback, persistir `completed_orders`)
- `ResponderInfoPedidoCompletado` (consulta del Agente Devolución)

### Agente Catálogo

- `BuscarProductos` (con SPARQL, cap. 6)
- `DarAltaProductoExterno`
- `NotificarBusquedaAFeedback` (Protocolo Consulta Catálogo, nuevo)

### Agente Feedback (con rol Recomendador y RegistradorBúsquedas)

- `RegistrarCompraCompletada` + `ProgramarPeticionFeedback` (diferida)
- `PedirFeedback` (al asistente, tras delay configurable)
- `RegistrarValoracion`
- `RegistrarBusqueda` (nuevo, alimenta el perfil de usuario)
- `RecomendarPeriodicamente` (scheduler proactivo)
- `ResponderRecomendaciones` (a petición, compatibilidad)

### Agente Devolución

- `ValidarPedidoCompletado` (via Comerciante)
- `EvaluarDevolucion`
- `OrganizarRecogida` (→ Transportista, SolicitarRecogidaDevolucion)
- `SolicitarReembolso` (→ Agente Financiero)

### Centro Logístico (multi-CL)

- `RecibirAvisarCL`
- `FiltrarLineasPorStock` (cada CL filtra las líneas que puede servir)
- `NegociarTransporteContractNet` (CFP en paralelo, accept-proposal al
ganador, reject-proposal a los demás)
- `ConfirmarEnvio`

### Transportista

- `ResponderCFP`
- `RecibirAcceptProposal` / `RecibirRejectProposal`
- `OrganizarRecogidaDevolucion`

### Agente Financiero

- `Cobrar` (cliente → tienda)
- `Reembolsar` (tienda → cliente, en devolución)
- `PagarProductoExterno` (tienda → vendedor externo)
- Interlocutor: `ProveedorPagos` (SolicitarOperacionPago)

### Asistente Virtual

- `RecibirPedirFeedback` (entrega valoración al usuario)
- `RecibirRecomendaciones` (inbox proactivo + endpoint `/recommendations-inbox`)

## 3. Conversaciones / protocolos FIPA — cap. 2.3

Etiquetar cada conversación en el PD con su protocolo y performativas:


| Conversación                                               | Iniciador                | Receptor              | Protocolo                     | Performativas                                                     |
| ---------------------------------------------------------- | ------------------------ | --------------------- | ----------------------------- | ----------------------------------------------------------------- |
| BuscarProductos                                            | Asistente                | Catálogo              | FIPA Request                  | request → inform/failure                                          |
| RealizarPedido                                             | Asistente                | Comerciante           | FIPA Request                  | request → inform/failure                                          |
| AvisarCL                                                   | Comerciante              | Cada Centro Logístico | FIPA Request (multi)          | request → inform/failure                                          |
| CFP Transporte                                             | Centro Logístico         | Cada Transportista    | FIPA Contract-Net             | cfp → propose / refuse; accept-proposal / reject-proposal; inform |
| ConfirmarEnvio                                             | Centro Logístico         | Comerciante           | FIPA Inform                   | inform                                                            |
| SolicitarCobro / SolicitarReembolso / PagarProductoExterno | Comerciante / Devolución | Financiero            | FIPA Request                  | request → inform/failure                                          |
| SolicitarOperacionPago                                     | Financiero               | ProveedorPagos        | FIPA Request                  | request → inform/failure                                          |
| ComunicarProductosExternos                                 | Comerciante              | VendedorExterno       | FIPA Inform (fire-and-forget) | inform                                                            |
| NotificarBusquedaRealizada                                 | Catálogo                 | Feedback              | FIPA Inform                   | inform                                                            |
| NotificarCompraCompletada                                  | Comerciante              | Feedback              | FIPA Inform                   | inform                                                            |
| PedirFeedback (diferida)                                   | Feedback                 | Asistente             | FIPA Request                  | request → inform                                                  |
| Recomendacion proactiva                                    | Feedback                 | Asistente             | FIPA Inform                   | inform                                                            |
| SolicitarDevolucion                                        | Asistente                | Devolución            | FIPA Request                  | request → inform/failure                                          |
| PeticionInfoPedidoCompletado                               | Devolución               | Comerciante           | FIPA Request                  | request → inform/failure                                          |
| Registro y descubrimiento                                  | Cualquier agente         | Directorio            | FIPA Request                  | request → confirm/inform/failure                                  |


Además, todas las conversaciones llevan `conversation-id` y `reply-with`
(soporte ya añadido en `utilities/acl.py`).

## 4. Patrones de coordinación — cap. 8

Añadir explícitamente en el PD:

- **Brokering** y **Matchmaking**: Directorio Service publica
`dso:AgentType` y `dso:Capability` (URI de la ontología), siguiendo el
perfil de servicio OWL-S (cap. 8.5.2). Los agentes buscan por tipo o
por capacidad.
- **Red de contratos** (Contract-Net): Centro Logístico ↔
Transportistas.
- **Notificación / suscripción ligera**: NotificarCompraCompletada,
NotificarBusquedaRealizada, Recomendación proactiva.

## 5. Fuentes de datos (cap. 1, vista de datos del PD)

Listar en una única vista todas las fuentes:


| Fuente                   | Ubicación                                                       | Formato             | Quién la mantiene   |
| ------------------------ | --------------------------------------------------------------- | ------------------- | ------------------- |
| Ontología                | `ontology/comercio_electronico.ttl`                             | Turtle/OWL          | Equipo (versionada) |
| Catálogo                 | `src/data/catalog.ttl` + grafo `catalog` en `dataset.trig`      | Turtle / TriG       | Agente Catálogo     |
| Pedidos completados      | `src/data/completed_orders/*.ttl` + grafos `completed_orders/`* | TTL + TriG          | Agente Comerciante  |
| Opiniones / valoraciones | `src/data/opinions.json` + grafo `opinions` en TriG             | JSON + RDF (espejo) | Agente Feedback     |
| Búsquedas (historial)    | `src/data/searches.json` + grafo `searches` en TriG             | JSON + RDF          | Agente Feedback     |
| Devoluciones             | `src/data/devoluciones.json` + grafo `returns` en TriG          | JSON + RDF          | Agente Devolución   |
| Directorio               | `src/data/directory.ttl`                                        | Turtle              | Directory Service   |


Sobre SPARQL: el catálogo ya consulta productos con SPARQL y el recomendador
materializa recomendaciones con SPARQL `CONSTRUCT`. Las escrituras/persistencias
pueden seguir usando RDFLib porque son inserciones directas de triples; no hace
falta convertir cada alta o actualización trivial a SPARQL `INSERT` si el dato
queda igualmente en RDF/TriG. Lo importante para la memoria es defender que las
BD compartidas son RDF y que las consultas semánticas relevantes se hacen con
SPARQL.

## 6. Normalización de nombres en el PD

Aplicar estos cambios manualmente en PDT para que `finalMod.pd`, código y
ontología usen los mismos nombres:

| Nombre antiguo / incoherente | Sustituir por | Motivo |
| ---------------------------- | ------------- | ------ |
| `AvisarPedidoACL`, `PreguntaRealizacionPedidoCL`, `RegistrarPedidoParaEnvio` | `AvisarCL` | Es la acción real que el Comerciante solicita a cada Centro Logístico mediante `request`. |
| `Notificar CL` como `Action` | Integrarlo en `ConfirmacionEnvio` / `ConfirmacionCompra` | En el PD significa "notificar al usuario del CL escogido"; no es una API externa nueva. Es información de respuesta al asistente. |
| `SeleccionarCL`              | `EscogerCL` + `AvisarCL` + `FiltrarLineasPorStock` | En el código no se escoge un único CL al inicio: se avisa a todos y cada CL filtra sus líneas. |
| AUML de `Protocolo Reembolso`: `SolicitarReembolsso` | `SolicitarReembolso` | El objeto `Message` ya está bien; queda corregir el texto AUML interno. |
| AUML de `Protocolo PagarProductoExterno`: `PagarProdExterno` | `PagarProductoExterno` | El objeto `Message` ya está bien; queda corregir el texto AUML interno. |
| `Mostrar Recomendaciones` como acción | `Recomendacion proactiva` / `RecibirRecomendaciones` | La recomendación es información enviada con `inform`, no una acción externa solicitada al agente. |
| `ListaProductos!`, `TicketCompra`, `ConfirmacionRegistroProducto`, `Notificar Resolucion Devolucion` como `Action` | Respuestas/notificaciones | Son resultados informados al solicitante, no funcionalidades solicitables mediante `request`. |
| `Opinion?`                   | `PedirFeedback` | Es la acción real: Feedback solicita al Asistente una valoración. |
| `Opiniion!`, `RegistrarValoracion` | `EnviarOpinion` / `RegistrarValoracion` como notificación | Es compartición de una valoración con `inform`, no una acción ofrecida por Feedback. |
| `ProponerLoteAentregar`      | `SolicitarPresupuestoTransporte` | Es la CFP/request del Centro Logístico a los transportistas. |
| `Informar Eleccion Transportista` como `Action` | `DecisionContratoTransporte` | Es el cierre del Contract Net con `accept-proposal` / `reject-proposal`; en la ontología es respuesta, no acción. |
| `Protocolo PagarProductoExterno` con `start Protocolo Gestion Envios` | `start Protocolo PagarProductoExterno` | El texto AUML interno del protocolo tiene el nombre antiguo. |
| `Protocolo AveriguarStockCL` con `start Protocolo Gestion Envios` | Actualizar o eliminar | El flujo actual multi-CL usa `AvisarCL` a todos los centros; no una consulta previa de stock separada. |

Regla práctica para PDT: dejar como `Action` solo lo que tenga sentido en una
performativa `request` y como API externa de un agente. Lo que solo comparte
conocimiento entre agentes debe modelarse como mensaje/percepción/notificación.

## 7. Comentarios de la 1ª y 2ª entrega

Si en las entregas anteriores quedaron comentarios concretos en PDT
(roles que faltaban, planes mal nombrados, escenarios sin cubrir),
aplicarlos aquí antes de exportar el report definitivo. Como el .pd no
se ha tocado en este sprint, esta lista debe usarse junto al feedback
recibido por el profesor.

## 8. Antes de exportar el report HTML definitivo

- Asegurar que cada plan tiene su **ficha textual** (precondiciones,
postcondiciones, eventos, acciones), no solo el nombre.
- Comprobar que el report incluye las conversaciones nuevas y los
protocolos etiquetados.
- Mover el report exportado a `doc/pdtool/<fecha>/` y referenciarlo
desde la memoria.
