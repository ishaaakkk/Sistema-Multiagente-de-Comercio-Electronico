from __future__ import annotations

import argparse
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from threading import Event, Lock as ThreadLock, Thread
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import (
    build_aviso_vendedor_externo,
    build_cobro_request,
    build_completed_order_info_response,
    build_logistics_request,
    build_notify_purchase_completed,
    build_pago_externo_request,
)
from utilities.catalog import decimal_literal
from utilities.comm import comm_url as _comm_url, copy_subject as _copy_subject
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    search_all_services,
    search_service,
    unregister_service,
)
from utilities.storage import load_graph_collection, save_graph_item, save_named_graph


DEFAULT_AGENT_URI = AGENTS.AgenteComerciante
_LOT_DISPATCH_INTERVAL = float(os.environ.get("LOT_DISPATCH_INTERVAL", "3"))
_CL_TRANSPORT_TIMEOUT = float(os.environ.get("CL_TRANSPORT_TIMEOUT", "4"))
# Debe cubrir: ciclo de lote pendiente + CFP paralela a transportistas.
_DEFAULT_SHIPPING_WAIT = _LOT_DISPATCH_INTERVAL + _CL_TRANSPORT_TIMEOUT * 2 + 4
DEFAULT_SHIPPING_CONFIRMATION_TIMEOUT = float(
    os.environ.get("SHIPPING_CONFIRMATION_TIMEOUT", str(max(15.0, _DEFAULT_SHIPPING_WAIT)))
)
DEFAULT_LOGISTICS_REQUEST_TIMEOUT = float(
    os.environ.get("LOGISTICS_REQUEST_TIMEOUT", str(max(20.0, DEFAULT_SHIPPING_CONFIRMATION_TIMEOUT)))
)


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    logistics_urls: list[str] | None = None,
    directory_url: str | None = None,
    financiero_url="http://127.0.0.1:9005/comm",
    feedback_url="http://127.0.0.1:9007/comm",
    vendedor_externo_url="http://127.0.0.1:9008/comm",
    shipping_confirmation_timeout: float = DEFAULT_SHIPPING_CONFIRMATION_TIMEOUT,
):
    app = Flask(__name__)
    completed_orders: dict[str, Graph] = load_graph_collection("completed_orders")
    fallback_logistics_urls = list(logistics_urls or [])
    confirmation_buffers: dict[str, dict] = {}
    confirmation_lock = ThreadLock()

    @app.get("/")
    def index():
        return "AgenteComerciante listo"

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido"))
            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))

            if message.performative == ACL.inform:
                async_ack = _handle_async_shipping_confirmation(
                    graph, message, agent_uri, confirmation_buffers, confirmation_lock
                )
                if async_ack is not None:
                    return reply(async_ack)

            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Plan: PreguntarDatosCompra → EscogerCL → Notificador (AgenteComerciante / PrepararPedido)
            # Msg entrante: RealizarPedido (AsistenteVirtual → AgenteComerciante)
            # El asistente incluye idProducto, precio, vendedor y quienEnvia por cada linea.
            if (action, RDF.type, ECSDI.RealizarPedido) in graph:
                logistics_urls_now = _discover_logistics_centers(
                    directory_url, fallback_logistics_urls, agent_uri
                )
                return reply(
                    _handle_order(
                        agent_uri,
                        message.sender,
                        action,
                        graph,
                        logistics_urls_now,
                        financiero_url,
                        feedback_url,
                        vendedor_externo_url,
                        completed_orders,
                        confirmation_buffers,
                        confirmation_lock,
                        shipping_confirmation_timeout,
                    )
                )

            # Protocolo InfoPedidoCompletado — AgenteDevolucion valida una compra ya completada.
            if (action, RDF.type, ECSDI.PeticionInfoPedidoCompletado) in graph:
                return reply(_handle_completed_order_info(completed_orders, agent_uri, message.sender, action, graph))

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteComerciante"))
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_order(
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
    logistics_urls: list[str],
    financiero_url: str,
    feedback_url: str,
    vendedor_externo_url: str,
    completed_orders: dict[str, Graph],
    confirmation_buffers: dict[str, dict],
    confirmation_lock: ThreadLock,
    shipping_confirmation_timeout: float,
) -> Graph:
    """Orquestador del Plan «RealizarPedido» del Agente Comerciante.

    Cada paso del plan se delega en un plan concreto (subfunción)
    siguiendo el desglose del PD:

      1. `_plan_preguntar_datos_compra`         → valida campos obligatorios del pedido.
      2. `_plan_preparar_pedido`                 → registra pedido y clasifica líneas.
      3. `_plan_escoger_cl`                      → selecciona CL por métrica dist y confirma envío.
      4. `_plan_gestionar_vendedores_externos`   → pago + aviso vendedor externo.
      5. `_plan_realizar_cobro`                  → orden de cobro al cliente (con metodoPago).
      6. `_plan_finalizar_pedido`                → notifica compra completada + persiste.
    """

    pedido, lines, error = _plan_preguntar_datos_compra(
        agent_uri, receiver, action, graph
    )
    if error is not None:
        return error

    order_graph, internal_lines, ext_envio_tienda, ext_envio_propio = _plan_preparar_pedido(
        graph, action, pedido, lines
    )

    client_dist = _extract_client_dist(graph, pedido)

    cl_error = _plan_escoger_cl(
        agent_uri,
        receiver,
        action,
        order_graph,
        pedido,
        internal_lines + ext_envio_tienda,
        logistics_urls,
        client_dist=client_dist,
        confirmation_buffers=confirmation_buffers,
        confirmation_lock=confirmation_lock,
        shipping_confirmation_timeout=shipping_confirmation_timeout,
    )
    if cl_error is not None:
        return cl_error

    _plan_gestionar_vendedores_externos(
        agent_uri,
        order_graph,
        graph,
        pedido,
        ext_envio_tienda,
        ext_envio_propio,
        financiero_url,
        vendedor_externo_url,
    )

    order_graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_envio_planificado")))

    _plan_realizar_cobro(agent_uri, order_graph, pedido, financiero_url)
    _plan_finalizar_pedido(
        agent_uri, order_graph, pedido, feedback_url, completed_orders
    )

    return build_message(order_graph, pedido, ACL.inform, agent_uri, receiver)


# --- Planes del Agente Comerciante (subfunciones nombradas como en el PD) ---


def _plan_preguntar_datos_compra(
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
) -> tuple[URIRef | None, list, Graph | None]:
    """Valida que el mensaje contenga el pedido, al menos una línea y los
    tres campos obligatorios: direccionEntrega, prioridadEntrega, metodoPago."""

    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return None, [], build_failure(agent_uri, receiver, action, "Falta accionSobrePedido")

    lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not lines:
        return None, [], build_failure(agent_uri, receiver, action, "El pedido no contiene lineas")

    if next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None) is None:
        return None, [], build_failure(agent_uri, receiver, action, "Falta direccionEntrega (pedidoEnviadoA)")

    if next(graph.objects(pedido, ECSDI.prioridadEntrega), None) is None:
        return None, [], build_failure(agent_uri, receiver, action, "Falta prioridadEntrega")

    if next(graph.objects(pedido, ECSDI.metodoPago), None) is None:
        return None, [], build_failure(agent_uri, receiver, action, "Falta metodoPago")

    address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    dist_raw = next(graph.objects(address, ECSDI.dist), None) if address is not None else None
    if dist_raw is None:
        return None, [], build_failure(agent_uri, receiver, action, "Falta dist en direccionEntrega")
    try:
        dist_val = int(dist_raw)
    except (TypeError, ValueError):
        return None, [], build_failure(agent_uri, receiver, action, "dist debe ser un entero 0-1000")
    if not 0 <= dist_val <= 1000:
        return None, [], build_failure(agent_uri, receiver, action, "dist debe estar entre 0 y 1000")

    return pedido, lines, None


def _plan_preparar_pedido(
    request_graph: Graph,
    action: URIRef,
    pedido: URIRef,
    lines: list,
) -> tuple[Graph, list, list, list]:
    """Plan PrepararPedido: registra el pedido pendiente y clasifica las líneas."""

    order_graph = _plan_registrar_pedido_pendiente(request_graph, action, pedido, lines)
    internal_lines, ext_envio_tienda, ext_envio_propio = _classify_lines(request_graph, lines)
    log("comerciante", (
        f"Pedido clasificado: {len(internal_lines)} internas, "
        f"{len(ext_envio_tienda)} ext-envio-tienda, "
        f"{len(ext_envio_propio)} ext-envio-propio"
    ))
    return order_graph, internal_lines, ext_envio_tienda, ext_envio_propio


def _plan_registrar_pedido_pendiente(
    request_graph: Graph, action: URIRef, pedido: URIRef, lines: list
) -> Graph:
    """Plan RegistrarPedidoPendiente: genera factura y deja el pedido en
    estado `aceptado_sin_pago`."""

    return _build_order_graph(request_graph, action, pedido, lines)


def _plan_escoger_cl(
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    lines_for_logistics: list,
    logistics_urls: list[str],
    client_dist: int | None = None,
    confirmation_buffers: dict[str, dict] | None = None,
    confirmation_lock: ThreadLock | None = None,
    shipping_confirmation_timeout: float = DEFAULT_SHIPPING_CONFIRMATION_TIMEOUT,
) -> Graph | None:
    """Plan EscogerCL: ordena CLs por |dist_CL - dist_entrega| y contacta
    secuencialmente hasta asignar todas las líneas pendientes."""

    if not lines_for_logistics:
        return None
    if not logistics_urls:
        return build_failure(
            agent_uri,
            receiver,
            action,
            "No hay centros logísticos disponibles para planificar el envío",
        )

    pedido_id = _pedido_id(order_graph, pedido) or ""
    if confirmation_buffers is not None and confirmation_lock is not None and pedido_id:
        with confirmation_lock:
            confirmation_buffers[pedido_id] = {"event": Event(), "graphs": []}

    # Reordenar por proximidad métrica dist (0-1000).
    ordered_urls = _sort_logistics_by_distance(logistics_urls, client_dist)

    logistics_graph = _build_partial_order_graph(order_graph, pedido, lines_for_logistics)
    confirmaciones, unassigned_lines = _dispatch_to_logistics_ordered(
        agent_uri, logistics_graph, pedido, ordered_urls
    )
    needs_async = any(_response_accepts_pending_lote(c) for c in confirmaciones)
    if needs_async and confirmation_buffers is not None and confirmation_lock is not None and pedido_id:
        waited = _wait_shipping_confirmations(
            pedido_id, confirmation_buffers, confirmation_lock, shipping_confirmation_timeout
        )
        confirmaciones.extend(waited)
    if not confirmaciones:
        return build_failure(
            agent_uri,
            receiver,
            action,
            "Ningún centro logístico pudo planificar el envío",
        )
    unconfirmed_lines = _unconfirmed_shipping_lines(confirmaciones, lines_for_logistics)
    if unassigned_lines or unconfirmed_lines:
        pending = list(dict.fromkeys([*unassigned_lines, *unconfirmed_lines]))
        labels = ", ".join(_line_label(order_graph, line) for line in pending)
        return build_failure(
            agent_uri,
            receiver,
            action,
            f"No se pudo confirmar el envío de todas las líneas del pedido: {labels}",
        )
    for shipping_response in confirmaciones:
        for triple in shipping_response:
            order_graph.add(triple)
        confirmacion = next(
            shipping_response.subjects(RDF.type, ECSDI.ConfirmacionEnvio), None
        )
        if confirmacion is not None:
            order_graph.add((pedido, ECSDI.pedidoTieneConfirmacion, confirmacion))
    log(
        "comerciante",
        f"Envío planificado por {len(confirmaciones)} centro(s) para {len(lines_for_logistics)} línea(s)",
    )
    return None


def _plan_gestionar_vendedores_externos(
    agent_uri: URIRef,
    order_graph: Graph,
    request_graph: Graph,
    pedido: URIRef,
    ext_envio_tienda: list,
    ext_envio_propio: list,
    financiero_url: str,
    vendedor_externo_url: str,
) -> None:
    """Plan ComunicarVendedoresExternos: pago al vendedor + aviso si gestiona el envío."""

    if not (ext_envio_tienda or ext_envio_propio):
        return
    address = next(request_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    address_graph = order_graph if address is not None else None
    _gestionar_productos_externos(
        agent_uri, order_graph, pedido, request_graph,
        ext_envio_tienda, ext_envio_propio,
        address, address_graph,
        financiero_url, vendedor_externo_url,
    )


def _plan_realizar_cobro(
    agent_uri: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    financiero_url: str,
) -> None:
    """Plan RealizarCobro: dispara SolicitarCobro al Agente Financiero,
    propagando el método de pago elegido por el cliente."""

    total = Decimal(str(next(order_graph.objects(pedido, ECSDI.importeTotalPedido), "0")))
    metodo_pago = next(order_graph.objects(pedido, ECSDI.metodoPago), None)
    _post_safe(
        financiero_url,
        build_cobro_request(agent_uri, AGENTS.AgenteFinanciero, pedido, total, metodo_pago),
        "cobro",
    )


def _plan_finalizar_pedido(
    agent_uri: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    feedback_url: str,
    completed_orders: dict[str, Graph],
) -> None:
    """Plan FinalizarPedido: notifica al Agente Feedback (NotificarCompraCompletada)
    y persiste el pedido completado."""

    _post_safe(
        feedback_url,
        build_notify_purchase_completed(
            agent_uri, AGENTS.AgenteFeedback, order_graph, pedido
        ),
        "feedback",
    )
    _store_completed_order(completed_orders, order_graph, pedido)


def _handle_completed_order_info(
    completed_orders: dict[str, Graph],
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    pedido_id = _pedido_id(graph, pedido)
    if not pedido_id:
        return build_failure(agent_uri, receiver, action, "Falta el identificador de pedido")

    order_graph = completed_orders.get(pedido_id)
    if order_graph is None:
        return build_failure(agent_uri, receiver, action, f"Pedido completado no encontrado: {pedido_id}")

    stored_pedido = next(order_graph.subjects(ECSDI.idPedido, Literal(pedido_id)), pedido)
    log("comerciante", f"Consulta pedido completado: {pedido_id}")
    return build_completed_order_info_response(agent_uri, receiver, action, order_graph, stored_pedido)


def _discover_logistics_centers(
    directory_url: str | None,
    fallback: list[str],
    requester: URIRef,
) -> list[str]:
    """Descubre todos los centros logísticos registrados (extensión avanzada #3 multi-CL).

    Si hay directorio, devuelve la lista de centros registrados como
    CENTRO_LOGISTICO; si no hay resultados usa la lista de fallback.
    Las URLs se normalizan a /comm.
    """

    if directory_url:
        urls = search_all_services(directory_url, "CENTRO_LOGISTICO", requester)
        if urls:
            comm_urls = [_comm_url(u) for u in urls]
            log("comerciante", f"Centros logísticos descubiertos via directorio: {comm_urls}")
            return comm_urls
        log("comerciante", "No se encontraron centros logísticos en el directorio, usando fallback")
    return [_comm_url(u) for u in fallback if u]


def _response_accepts_pending_lote(response: Graph) -> bool:
    for lote in response.subjects(RDF.type, ECSDI.LoteEnvio):
        estado = str(next(response.objects(lote, ECSDI.estadoLote), ""))
        if estado == "pendiente_envio":
            return True
    return False


def _unconfirmed_shipping_lines(responses: list[Graph], expected_lines: list[URIRef]) -> list[URIRef]:
    confirmed: set[URIRef] = set()
    for response in responses:
        if not any(response.subjects(RDF.type, ECSDI.ConfirmacionEnvio)):
            continue
        for confirmation in response.subjects(RDF.type, ECSDI.ConfirmacionEnvio):
            envio = next(response.objects(confirmation, ECSDI.confirmacionEnvio), None)
            lote = next(response.objects(envio, ECSDI.envioTieneLote), None) if envio is not None else None
            if lote is not None:
                confirmed.update(response.objects(lote, ECSDI.loteTieneLinea))
        for envio in response.subjects(RDF.type, ECSDI.EnvioInterno):
            lote = next(response.objects(envio, ECSDI.envioTieneLote), None)
            if lote is not None:
                confirmed.update(response.objects(lote, ECSDI.loteTieneLinea))
    return [line for line in expected_lines if line not in confirmed]


def _line_label(graph: Graph, line: URIRef) -> str:
    product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
    if product is not None:
        product_id = next(graph.objects(product, ECSDI.idProducto), None)
        if product_id is not None:
            return str(product_id)
    return str(line).rsplit("/", 1)[-1]


def _handle_async_shipping_confirmation(
    graph: Graph,
    message,
    agent_uri: URIRef,
    confirmation_buffers: dict[str, dict],
    confirmation_lock: ThreadLock,
) -> Graph | None:
    """RecibirDatosEnvio: ConfirmacionEnvio asíncrona del centro logístico."""

    if not any(graph.subjects(RDF.type, ECSDI.ConfirmacionEnvio)):
        return None
    pedido_id = ""
    for conf in graph.subjects(RDF.type, ECSDI.ConfirmacionEnvio):
        envio = next(graph.objects(conf, ECSDI.confirmacionEnvio), None)
        if envio is None:
            continue
        pedido = next(graph.objects(envio, ECSDI.envioDePedido), None)
        if pedido is not None:
            pedido_id = str(next(graph.objects(pedido, ECSDI.idPedido), _pedido_id(graph, pedido) or ""))
            break
    if not pedido_id:
        return None
    with confirmation_lock:
        buf = confirmation_buffers.setdefault(pedido_id, {"event": Event(), "graphs": []})
        buf["graphs"].append(graph)
        buf["event"].set()
    log("comerciante", f"ConfirmacionEnvio recibida para pedido {pedido_id}")
    ack = DATA[f"ack/shipping/{uuid4()}"]
    ack_graph = Graph()
    bind_namespaces(ack_graph)
    ack_graph.add((ack, RDF.type, ECSDI.Respuesta))
    return build_message(ack_graph, ack, ACL.inform, agent_uri, message.sender)


def _wait_shipping_confirmations(
    pedido_id: str,
    confirmation_buffers: dict[str, dict],
    confirmation_lock: ThreadLock,
    timeout: float,
) -> list[Graph]:
    with confirmation_lock:
        buf = confirmation_buffers.get(pedido_id)
        if buf is None:
            return []
        event = buf["event"]
    if not event.wait(timeout):
        log("comerciante", f"Timeout ({timeout}s) esperando ConfirmacionEnvio de {pedido_id}")
    with confirmation_lock:
        buf = confirmation_buffers.pop(pedido_id, {"graphs": []})
    return [g for g in buf.get("graphs", []) if any(g.subjects(RDF.type, ECSDI.ConfirmacionEnvio))]


def _dispatch_to_logistics(
    agent_uri: URIRef,
    logistics_graph: Graph,
    pedido: URIRef,
    logistics_urls: list[str],
) -> list[Graph]:
    """Envía AvisarCL a todos los centros logísticos en paralelo y agrega
    las confirmaciones válidas. Ignora los failures (centros sin stock).
    """
    log("comerciante", "ENTRANDO EN DISPATCH LOGISTICS")
    def _ask(url: str) -> Graph | None:
        try:
            message = build_logistics_request(
                agent_uri, AGENTS.CentroLogistico, logistics_graph, pedido
            )
            response = post_graph(url, message, timeout=DEFAULT_LOGISTICS_REQUEST_TIMEOUT)
            msg = get_message(response)
            if msg is None:
                return None
            if msg.performative == ACL.failure:
                log("comerciante", f"CL {url} sin stock o sin transporte; se ignora")
                return None
            if any(response.subjects(RDF.type, ECSDI.ConfirmacionEnvio)):
                return response
            if _response_accepts_pending_lote(response):
                return response
            return None
        except Exception as exc:
            log("comerciante", f"Error contactando CL {url}: {exc}")
            return None

    confirmaciones: list[Graph] = []
    if not logistics_urls:
        return confirmaciones

    with ThreadPoolExecutor(max_workers=min(8, len(logistics_urls))) as pool:
        futures = {pool.submit(_ask, url): url for url in logistics_urls}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                confirmaciones.append(result)
    return confirmaciones


def _extract_client_dist(graph: Graph, pedido: URIRef) -> float | None:
    """Extrae dist (0-1000) de la dirección de entrega si está presente."""
    address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is None:
        return None

    dist = next(graph.objects(address, ECSDI.dist), None)
    try:
        return float(dist) if dist is not None else None
    except Exception:
        return None


def _sort_logistics_by_distance(logistics_urls, client_dist):
    """Reordena URLs de CL por |dist_CL - dist_entrega| vía GET /info."""
    if client_dist is None:
        return list(logistics_urls)

    distances = {}

    for url in logistics_urls:
        try:
            info_url = url.rstrip("/").rsplit("/", 1)[0] + "/info"
            resp = requests.get(info_url, timeout=1.0)
            data = resp.json()

            cl_dist = data.get("dist")  # cada CL tiene su posición en la recta

            if cl_dist is None:
                distances[url] = float("inf")
            else:
                # distancia 1D
                distances[url] = abs(float(cl_dist) - client_dist)

        except Exception:
            distances[url] = float("inf")

    return sorted(logistics_urls, key=lambda u: distances[u])


def _dispatch_to_logistics_ordered(
    agent_uri: URIRef,
    logistics_graph: Graph,
    pedido: URIRef,
    ordered_urls: list[str],
) -> tuple[list[Graph], list[URIRef]]:
    """
    Asignación greedy:
    - se prueba CL más cercano primero
    - si acepta → se asigna y se termina
    - si no → siguiente CL
    """
    log("comerciante", "ENTRANDO EN DISPATCH LOGISTICS ORDERED")
    remaining_lines = list(logistics_graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not remaining_lines:
        return [], []

    confirmations: list[Graph] = []

    for url in ordered_urls:
        if not remaining_lines:
            break

        partial = _build_partial_order_graph(
            logistics_graph,
            pedido,
            remaining_lines
        )

        results = _dispatch_to_logistics(
            agent_uri,
            partial,
            pedido,
            [url]
        )

        if not results:
            continue

        for resp in results:
            confirmations.append(resp)

            for lote in resp.subjects(RDF.type, ECSDI.LoteEnvio):
                for line in resp.objects(lote, ECSDI.loteTieneLinea):
                    if line in remaining_lines:
                        remaining_lines.remove(line)

            for envio in resp.subjects(RDF.type, ECSDI.EnvioInterno):
                lote = next(resp.objects(envio, ECSDI.envioTieneLote), None)
                if lote:
                    for line in resp.objects(lote, ECSDI.loteTieneLinea):
                        if line in remaining_lines:
                            remaining_lines.remove(line)

    return confirmations, remaining_lines


def _classify_lines(graph: Graph, lines: list) -> tuple[list, list, list]:
    """Clasifica lineas en (internas, externas-envio-tienda, externas-envio-propio)."""
    internal, ext_tienda, ext_propio = [], [], []
    for line in lines:
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None or (product, RDF.type, ECSDI.ProductoExterno) not in graph:
            internal.append(line)
            continue
        gestion = next(graph.objects(product, ECSDI.gestionEnvioExterno), Literal(False))
        if str(gestion).lower() in ("true", "1"):
            ext_propio.append(line)
        else:
            ext_tienda.append(line)
    return internal, ext_tienda, ext_propio


def _gestionar_productos_externos(
    agent_uri: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    source_graph: Graph,
    ext_envio_tienda: list,
    ext_envio_propio: list,
    address: URIRef | None,
    address_graph: Graph | None,
    financiero_url: str,
    vendedor_externo_url: str,
) -> None:
    """Plan: ComunicarVendedoresExternos (AgenteComerciante / ComunicarConVendedoresExternos).

    Para TODOS los productos externos:
      - Solicita pago al AgenteFinanciero (PagarProductoExterno) — fire-and-forget.

    Solo para productos con gestionEnvioExterno=true:
      - Avisa al AgenteVendedorExterno con producto + direccion (ComunicarProductosExternosPedidos)
        para que gestione el envio directamente — fire-and-forget.
    """
    for line in ext_envio_tienda + ext_envio_propio:
        product = next(source_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        vendedor = next(source_graph.objects(product, ECSDI.productoOfrecidoPor), AGENTS.VendedorExterno)
        precio = Decimal(str(next(source_graph.objects(product, ECSDI.precioProducto), "0")))
        cantidad = int(next(source_graph.objects(line, ECSDI.cantidad), 1))
        importe = precio * cantidad
        product_id = str(next(source_graph.objects(product, ECSDI.idProducto), str(product)))

        # Pago al vendedor — siempre, independientemente de quien gestione el envio
        _post_safe(
            financiero_url,
            build_pago_externo_request(agent_uri, AGENTS.AgenteFinanciero, pedido, product, vendedor, importe),
            "pago_externo",
        )
        log("comerciante", f"Pago externo solicitado: producto={product_id} vendedor={vendedor} importe={importe}")

    for line in ext_envio_propio:
        product = next(source_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        vendedor = next(source_graph.objects(product, ECSDI.productoOfrecidoPor), AGENTS.VendedorExterno)
        product_id = str(next(source_graph.objects(product, ECSDI.idProducto), str(product)))

        # Aviso al vendedor con la direccion de entrega — solo si el gestiona el envio
        _post_safe(
            vendedor_externo_url,
            build_aviso_vendedor_externo(agent_uri, vendedor, pedido, product, address, address_graph),
            "aviso_vendedor",
        )
        # Registrar EnvioExterno enlazado al pedido para que el cliente pueda encontrarlo
        envio_ext = DATA[f"envio/externo/{uuid4()}"]
        order_graph.add((envio_ext, RDF.type, ECSDI.EnvioExterno))
        order_graph.add((envio_ext, ECSDI.envioDePedido, pedido))
        order_graph.add((envio_ext, ECSDI.envioExternoGestionadoPor, vendedor))
        order_graph.add((pedido, ECSDI.pedidoTieneEnvio, envio_ext))
        log("comerciante", f"Aviso envio externo enviado: producto={product_id} vendedor={vendedor}")


def _post_safe(url: str, graph, tag: str) -> None:
    """Fire-and-forget: envia el grafo y absorbe cualquier error de conexion.

    Los mensajes al Financiero, Feedback y VendedorExterno son fire-and-forget
    por diseño; si el agente destino no esta disponible el flujo principal
    no debe verse afectado.
    """
    def _send() -> None:
        try:
            post_graph(url, graph)
        except Exception as exc:
            log("comerciante", f"[{tag}] aviso fire-and-forget fallido ({url}): {exc}")

    Thread(target=_send, daemon=True).start()


def _response_reason(graph: Graph) -> str:
    reason = next(graph.objects(None, RDFS.comment), None)
    return str(reason) if reason is not None else "respuesta no inform"


def _store_completed_order(completed_orders: dict[str, Graph], order_graph: Graph, pedido: URIRef) -> None:
    pedido_id = str(next(order_graph.objects(pedido, ECSDI.idPedido), ""))
    if not pedido_id:
        return
    stored = Graph()
    bind_namespaces(stored)
    for triple in order_graph:
        stored.add(triple)
    completed_orders[pedido_id] = stored
    save_graph_item("completed_orders", pedido_id, stored)
    save_named_graph(f"completed_orders/{pedido_id}", stored)
    log("comerciante", f"Pedido completado guardado: {pedido_id}")


def _pedido_id(graph: Graph, pedido: URIRef | None) -> str | None:
    if pedido is None:
        return None
    explicit_id = next(graph.objects(pedido, ECSDI.idPedido), None)
    if explicit_id is not None:
        return str(explicit_id)
    uri = str(pedido)
    if "/pedido/" in uri:
        return uri.rsplit("/pedido/", 1)[-1]
    return uri.rsplit("/", 1)[-1] if uri else None



def _build_partial_order_graph(full_graph: Graph, pedido: URIRef, lines: list) -> Graph:
    """Subgrafo del pedido con solo las lineas indicadas para el logistico.

    La accion logistica concreta se crea despues como AvisarCL.
    """
    graph = Graph()
    bind_namespaces(graph)
    for triple in full_graph.triples((pedido, None, None)):
        if triple[1] == ECSDI.pedidoTieneLinea and triple[2] not in lines:
            continue
        graph.add(triple)
    for line in lines:
        for triple in full_graph.triples((line, None, None)):
            graph.add(triple)
        product = next(full_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is not None:
            _copy_product_context(full_graph, graph, product)
    address = next(full_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is not None:
        for triple in full_graph.triples((address, None, None)):
            graph.add(triple)
    return graph


def _copy_product_context(source: Graph, target: Graph, product: URIRef) -> None:
    """Copia el producto y el contexto de stock/centro necesario para logistica."""

    _copy_subject(source, target, product)
    for stock in source.subjects(ECSDI.stockDeProducto, product):
        _copy_subject(source, target, stock)
        center = next(source.objects(stock, ECSDI.stockEnCentro), None)
        if center is not None:
            _copy_subject(source, target, center)


def _build_order_graph(
    request_graph: Graph,
    action: URIRef,
    pedido: URIRef,
    lines: list,
) -> Graph:
    """Plan: RegistrarPedidoPendiente — genera factura a partir de precios enviados por el asistente."""
    graph = Graph()
    bind_namespaces(graph)
    _copy_subject(request_graph, graph, action)
    _copy_subject(request_graph, graph, pedido)

    address = next(request_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is not None:
        _copy_subject(request_graph, graph, address)

    total = Decimal("0")
    for line in lines:
        _copy_subject(request_graph, graph, line)
        product = next(request_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is not None:
            _copy_product_context(request_graph, graph, product)
        # El precio unitario lo manda el asistente en la linea
        price = Decimal(str(next(request_graph.objects(line, ECSDI.precioUnitario), "0")))
        quantity = int(next(request_graph.objects(line, ECSDI.cantidad), 1))
        total += price * quantity

    invoice = DATA[f"factura/{uuid4()}"]
    graph.add((invoice, RDF.type, ECSDI.Factura))
    graph.add((invoice, ECSDI.idFactura, Literal(f"FAC-{uuid4().hex[:8].upper()}")))
    graph.add((invoice, ECSDI.facturaDePedido, pedido))
    graph.add((invoice, ECSDI.importeFactura, decimal_literal(total)))
    graph.add((invoice, ECSDI.fechaFactura, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))
    graph.add((pedido, ECSDI.pedidoTieneFactura, invoice))
    graph.add((pedido, ECSDI.importeTotalPedido, decimal_literal(total)))
    graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_sin_pago")))
    return graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument(
        "--logistics-url",
        action="append",
        default=None,
        help="URL fija de un centro logístico de fallback; puede repetirse para varios",
    )
    parser.add_argument("--financiero-url", default=None)
    parser.add_argument("--feedback-url", default=None)
    parser.add_argument("--vendedor-externo-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_COMERCIANTE", advertised_host, args.port)

    logistics_fallback: list[str] = []
    if args.logistics_url:
        logistics_fallback = [_comm_url(u) for u in args.logistics_url]
    elif not args.dir:
        logistics_fallback = ["http://127.0.0.1:9002/comm"]

    financiero_base = args.financiero_url or search_service(args.dir, "AGENTE_FINANCIERO", service_id) or "http://127.0.0.1:9005"
    financiero_url = _comm_url(financiero_base)
    feedback_base = args.feedback_url or search_service(args.dir, "AGENTE_FEEDBACK", service_id) or "http://127.0.0.1:9007"
    feedback_url = _comm_url(feedback_base)
    vendedor_externo_base = args.vendedor_externo_url or search_service(args.dir, "AGENTE_VENDEDOR_EXTERNO", service_id) or "http://127.0.0.1:9008"
    vendedor_externo_url = _comm_url(vendedor_externo_base)
    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_COMERCIANTE",
        address,
        f"comerciante-{args.port}",
        capabilities=[ECSDI.RealizarPedido, ECSDI.PeticionInfoPedidoCompletado],
    )
    try:
        log(
            f"comerciante-{args.port}",
            (
                f"listening on {bind_host}:{args.port}, "
                f"logistics_fallback={logistics_fallback}, financiero={financiero_url}, "
                f"feedback={feedback_url}, vendedor_externo={vendedor_externo_url}"
            ),
        )
        create_app(
            logistics_urls=logistics_fallback,
            directory_url=args.dir,
            financiero_url=financiero_url,
            feedback_url=feedback_url,
            vendedor_externo_url=vendedor_externo_url,
        ).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"comerciante-{args.port}")


if __name__ == "__main__":
    main()
