import argparse
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
    build_notify_purchase_completed,
    build_pago_externo_request,
)
from utilities.catalog import decimal_literal
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    search_service,
    unregister_service,
)


DEFAULT_AGENT_URI = AGENTS.AgenteComerciante


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    logistics_url="http://127.0.0.1:9002/comm",
    financiero_url="http://127.0.0.1:9005/comm",
    feedback_url="http://127.0.0.1:9007/comm",
    vendedor_externo_url="http://127.0.0.1:9008/comm",
):
    app = Flask(__name__)

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
                return rdf_response(_handle_order(agent_uri, message.sender, action, graph, logistics_url, financiero_url, feedback_url, vendedor_externo_url))

            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteComerciante"))
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_order(
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
    logistics_url: str,
    financiero_url: str,
    feedback_url: str,
    vendedor_externo_url: str,
) -> Graph:
    """Plan: PreguntarDatosCompra → bifurcacion por linea de pedido.

    Flujo por tipo de producto y gestion de envio:

      Interno                        → EscogerCL (logistico)
      Externo + gestionEnvioExterno=false  → EscogerCL (logistico) + pago al vendedor
      Externo + gestionEnvioExterno=true   → pago al vendedor + aviso al vendedor con direccion
    """
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return build_failure(agent_uri, receiver, action, "Falta accionSobrePedido")

    lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not lines:
        return build_failure(agent_uri, receiver, action, "El pedido no contiene lineas")

    # Plan: RegistrarPedidoPendiente
    order_graph = _build_order_graph(graph, action, pedido, lines)

    # Clasificar lineas
    internal_lines, ext_envio_tienda, ext_envio_propio = _classify_lines(graph, lines)

    log("comerciante", (
        f"Pedido clasificado: {len(internal_lines)} internas, "
        f"{len(ext_envio_tienda)} ext-envio-tienda, "
        f"{len(ext_envio_propio)} ext-envio-propio"
    ))

    # --- Lineas que necesitan logistico: internas + externas con envio por tienda ---
    # Plan: EscogerCL + Notificador → AvisarPedidoACL (AgenteComerciante → AgenteLogistico)
    lines_for_logistics = internal_lines + ext_envio_tienda
    if lines_for_logistics:
        logistics_graph = _build_partial_order_graph(order_graph, pedido, lines_for_logistics)
        logistics_message = build_message(
            logistics_graph, action, ACL.request, agent_uri, AGENTS.CentroLogisticoBarcelona
        )
        shipping_response = post_graph(logistics_url, logistics_message)
        for triple in shipping_response:
            order_graph.add(triple)
        # Enlazar ConfirmacionEnvio al pedido para que el cliente pueda encontrarla
        confirmacion = next(shipping_response.subjects(RDF.type, ECSDI.ConfirmacionEnvio), None)
        if confirmacion is not None:
            order_graph.add((pedido, ECSDI.pedidoTieneConfirmacion, confirmacion))
        log("comerciante", f"Envio logistico planificado para {len(lines_for_logistics)} linea(s)")

    # --- Productos externos: pago al vendedor + aviso si gestiona el envio ---
    # Plan: ComunicarVendedoresExternos (AgenteComerciante / ComunicarConVendedoresExternos)
    all_external = ext_envio_tienda + ext_envio_propio
    if all_external:
        address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
        address_graph = order_graph if address is not None else None
        _gestionar_productos_externos(
            agent_uri, order_graph, pedido, graph,
            ext_envio_tienda, ext_envio_propio,
            address, address_graph,
            financiero_url, vendedor_externo_url,
        )

    order_graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_envio_planificado")))

    # Plan: RealizarCobro → SolicitarCobro (AgenteComerciante → AgenteFinanciero)
    total = Decimal(str(next(order_graph.objects(pedido, ECSDI.importeTotalPedido), "0")))
    post_graph(financiero_url, build_cobro_request(agent_uri, AGENTS.AgenteFinanciero, pedido, total))

    # Plan: FinalizarPedido → NotificarCompraCompletada (AgenteComerciante → AgenteFeedback)
    post_graph(feedback_url, build_notify_purchase_completed(agent_uri, AGENTS.AgenteFeedback, order_graph, pedido))

    return build_message(order_graph, pedido, ACL.inform, agent_uri, receiver)


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
      - Solicita pago al AgenteFinanciero (PagarProdExterno) — fire-and-forget.

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
        post_graph(
            financiero_url,
            build_pago_externo_request(agent_uri, AGENTS.AgenteFinanciero, pedido, product, vendedor, importe),
        )
        log("comerciante", f"Pago externo solicitado: producto={product_id} vendedor={vendedor} importe={importe}")

    for line in ext_envio_propio:
        product = next(source_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        vendedor = next(source_graph.objects(product, ECSDI.productoOfrecidoPor), AGENTS.VendedorExterno)
        product_id = str(next(source_graph.objects(product, ECSDI.idProducto), str(product)))

        # Aviso al vendedor con la direccion de entrega — solo si el gestiona el envio
        post_graph(
            vendedor_externo_url,
            build_aviso_vendedor_externo(agent_uri, vendedor, pedido, product, address, address_graph),
        )
        # Registrar EnvioExterno enlazado al pedido para que el cliente pueda encontrarlo
        envio_ext = DATA[f"envio/externo/{uuid4()}"]
        order_graph.add((envio_ext, RDF.type, ECSDI.EnvioExterno))
        order_graph.add((envio_ext, ECSDI.envioDePedido, pedido))
        order_graph.add((envio_ext, ECSDI.envioExternoGestionadoPor, vendedor))
        order_graph.add((pedido, ECSDI.pedidoTieneEnvio, envio_ext))
        log("comerciante", f"Aviso envio externo enviado: producto={product_id} vendedor={vendedor}")


def _build_partial_order_graph(full_graph: Graph, pedido: URIRef, lines: list) -> Graph:
    """Subgrafo del pedido con solo las lineas indicadas para el logistico."""
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


def _copy_subject(source: Graph, target: Graph, subject: URIRef) -> None:
    for triple in source.triples((subject, None, None)):
        target.add(triple)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--logistics-url", default=None)
    parser.add_argument("--financiero-url", default=None)
    parser.add_argument("--feedback-url", default=None)
    parser.add_argument("--vendedor-externo-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    logistics_base = args.logistics_url or search_service(args.dir, "CENTRO_LOGISTICO") or "http://127.0.0.1:9002"
    logistics_url = _comm_url(logistics_base)
    financiero_base = args.financiero_url or search_service(args.dir, "AGENTE_FINANCIERO") or "http://127.0.0.1:9005"
    financiero_url = _comm_url(financiero_base)
    feedback_base = args.feedback_url or search_service(args.dir, "AGENTE_FEEDBACK") or "http://127.0.0.1:9007"
    feedback_url = _comm_url(feedback_base)
    vendedor_externo_base = args.vendedor_externo_url or search_service(args.dir, "AGENTE_VENDEDOR_EXTERNO") or "http://127.0.0.1:9008"
    vendedor_externo_url = _comm_url(vendedor_externo_base)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_COMERCIANTE", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "AGENTE_COMERCIANTE", address, f"comerciante-{args.port}")
    try:
        log(f"comerciante-{args.port}", f"listening on {bind_host}:{args.port}, logistics={logistics_url}, financiero={financiero_url}, feedback={feedback_url}, vendedor_externo={vendedor_externo_url}")
        create_app(logistics_url=logistics_url, financiero_url=financiero_url, feedback_url=feedback_url, vendedor_externo_url=vendedor_externo_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"comerciante-{args.port}")


def _comm_url(base_url: str) -> str:
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


if __name__ == "__main__":
    main()