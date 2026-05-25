import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message
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


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    logistics_urls: list[str] | None = None,
    directory_url: str | None = None,
    financiero_url="http://127.0.0.1:9005/comm",
    feedback_url="http://127.0.0.1:9007/comm",
    vendedor_externo_url="http://127.0.0.1:9008/comm",
):
    app = Flask(__name__)
    completed_orders: dict[str, Graph] = load_graph_collection("completed_orders")
    fallback_logistics_urls = list(logistics_urls or [])

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
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Plan: PreguntarDatosCompra → EscogerCL → Notificador (AgenteComerciante / PrepararPedido)
            # Msg entrante: RealizarPedido (AsistenteVirtual → AgenteComerciante)
            # El asistente incluye idProducto, precio, vendedor y quienEnvia por cada linea.
            if (action, RDF.type, ECSDI.RealizarPedido) in graph:
                logistics_urls_now = _discover_logistics_centers(
                    directory_url, fallback_logistics_urls, agent_uri
                )
                return rdf_response(
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
                    )
                )

            # Protocolo InfoPedidoCompletado — AgenteDevolucion valida una compra ya completada.
            if (action, RDF.type, ECSDI.PeticionInfoPedidoCompletado) in graph:
                return rdf_response(_handle_completed_order_info(completed_orders, agent_uri, message.sender, action, graph))

            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteComerciante"))
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
) -> Graph:
    """Orquestador del Plan «RealizarPedido» del Agente Comerciante.

    Cada paso del plan se delega en una capacidad concreta (subfunción)
    siguiendo el desglose del PD:

      1. `_capability_preguntar_datos_compra`  → valida y normaliza el pedido.
      2. `_capability_registrar_pedido_pendiente` → construye el grafo del pedido.
      3. `_capability_escoger_cl` → contacta con los centros logísticos.
      4. `_capability_gestionar_vendedores_externos` → pago + aviso vendedor.
      5. `_capability_realizar_cobro` → orden de cobro al cliente.
      6. `_capability_finalizar_pedido` → notifica compra completada + persiste.
    """

    pedido, lines, error = _capability_preguntar_datos_compra(
        agent_uri, receiver, action, graph
    )
    if error is not None:
        return error

    order_graph = _capability_registrar_pedido_pendiente(graph, action, pedido, lines)

    internal_lines, ext_envio_tienda, ext_envio_propio = _classify_lines(graph, lines)
    log("comerciante", (
        f"Pedido clasificado: {len(internal_lines)} internas, "
        f"{len(ext_envio_tienda)} ext-envio-tienda, "
        f"{len(ext_envio_propio)} ext-envio-propio"
    ))

    cl_error = _capability_escoger_cl(
        agent_uri,
        receiver,
        action,
        order_graph,
        pedido,
        internal_lines + ext_envio_tienda,
        logistics_urls,
    )
    if cl_error is not None:
        return cl_error

    _capability_gestionar_vendedores_externos(
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

    _capability_realizar_cobro(agent_uri, order_graph, pedido, financiero_url)
    _capability_finalizar_pedido(
        agent_uri, order_graph, pedido, feedback_url, completed_orders
    )

    return build_message(order_graph, pedido, ACL.inform, agent_uri, receiver)


# --- Capacidades del Agente Comerciante (subfunciones nombradas como en el PD) ---


def _capability_preguntar_datos_compra(
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
) -> tuple[URIRef | None, list, Graph | None]:
    """Valida que el mensaje contenga el pedido y al menos una línea."""

    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return None, [], build_failure(agent_uri, receiver, action, "Falta accionSobrePedido")
    lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not lines:
        return None, [], build_failure(agent_uri, receiver, action, "El pedido no contiene lineas")
    return pedido, lines, None


def _capability_registrar_pedido_pendiente(
    request_graph: Graph, action: URIRef, pedido: URIRef, lines: list
) -> Graph:
    """Plan RegistrarPedidoPendiente: genera factura y deja el pedido en
    estado `aceptado_sin_pago`."""

    return _build_order_graph(request_graph, action, pedido, lines)


def _capability_escoger_cl(
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    lines_for_logistics: list,
    logistics_urls: list[str],
) -> Graph | None:
    """Plan EscogerCL: contacta con TODOS los centros logísticos en paralelo
    (extensión avanzada #3 multi-CL). Devuelve `None` si se planificó al
    menos un envío, o un mensaje de fallo si no hay forma de servir.
    """

    if not lines_for_logistics:
        return None
    if not logistics_urls:
        return build_failure(
            agent_uri,
            receiver,
            action,
            "No hay centros logísticos disponibles para planificar el envío",
        )

    logistics_graph = _build_partial_order_graph(order_graph, pedido, lines_for_logistics)
    confirmaciones = _dispatch_to_logistics(
        agent_uri, logistics_graph, pedido, logistics_urls
    )
    if not confirmaciones:
        return build_failure(
            agent_uri,
            receiver,
            action,
            "Ningún centro logístico pudo planificar el envío",
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
        f"Envíos planificados por {len(confirmaciones)} centro(s) para {len(lines_for_logistics)} línea(s)",
    )
    return None


def _capability_gestionar_vendedores_externos(
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


def _capability_realizar_cobro(
    agent_uri: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    financiero_url: str,
) -> None:
    """Plan RealizarCobro: dispara SolicitarCobro al Agente Financiero."""

    total = Decimal(str(next(order_graph.objects(pedido, ECSDI.importeTotalPedido), "0")))
    _post_safe(
        financiero_url,
        build_cobro_request(agent_uri, AGENTS.AgenteFinanciero, pedido, total),
        "cobro",
    )


def _capability_finalizar_pedido(
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
    CENTRO_LOGISTICO; si no, usa la lista de fallback heredada de la CLI.
    Las URLs se normalizan a /comm.
    """

    if directory_url:
        urls = search_all_services(directory_url, "CENTRO_LOGISTICO", requester)
        if urls:
            return [_comm_url(u) for u in urls]
    return [_comm_url(u) for u in fallback if u]


def _dispatch_to_logistics(
    agent_uri: URIRef,
    logistics_graph: Graph,
    pedido: URIRef,
    logistics_urls: list[str],
) -> list[Graph]:
    """Envía AvisarCL a todos los centros logísticos en paralelo y agrega
    las confirmaciones válidas. Ignora los failures (centros sin stock).
    """

    def _ask(url: str) -> Graph | None:
        try:
            message = build_logistics_request(
                agent_uri, AGENTS.CentroLogistico, logistics_graph, pedido
            )
            response = post_graph(url, message)
            msg = get_message(response)
            if msg is None:
                return None
            if msg.performative == ACL.failure:
                log("comerciante", f"CL {url} sin stock o sin transporte; se ignora")
                return None
            if any(response.subjects(RDF.type, ECSDI.ConfirmacionEnvio)):
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
    try:
        post_graph(url, graph)
    except Exception as exc:
        log("comerciante", f"[{tag}] aviso fire-and-forget fallido ({url}): {exc}")


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
            for triple in full_graph.triples((product, None, None)):
                graph.add(triple)
    address = next(full_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is not None:
        for triple in full_graph.triples((address, None, None)):
            graph.add(triple)
    return graph


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
            _copy_subject(request_graph, graph, product)
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
