import argparse
from datetime import datetime
from uuid import uuid4

from decimal import Decimal

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message

from utilities.builders import build_payment_request, build_search_response

from utilities.catalog import (
    build_catalog_graph,
    choose_single_center,
    copy_center,
    copy_product,
    decimal_literal,
    describe_product,
    extract_search_constraints,
    filter_products,
    order_total,
    product_uri,
    reserve_stock,
)
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


DEFAULT_AGENT_URI = AGENTS.TiendaAgent


def create_app(agent_uri=DEFAULT_AGENT_URI, logistics_url="http://127.0.0.1:9002/comm", payments_url="http://127.0.0.1:9004/comm"):
    app = Flask(__name__)
    catalog = build_catalog_graph()

    @app.get("/")
    def index():
        return "TiendaAgent listo"

    @app.get("/catalog")
    def catalog_route():
        return rdf_response(catalog)

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
            if (action, RDF.type, ECSDI.BuscarProductos) in graph:
                return rdf_response(_handle_search(catalog, agent_uri, message.sender, action, graph))
            if (action, RDF.type, ECSDI.RealizarPedido) in graph:
                return rdf_response(_handle_order(catalog, agent_uri, message.sender, action, graph, logistics_url, payments_url))
            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por TiendaAgent"))
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_search(catalog: Graph, agent_uri: URIRef, receiver: URIRef, action: URIRef, graph: Graph) -> Graph:
    constraints = extract_search_constraints(graph, action)
    products = filter_products(catalog, constraints)
    return build_search_response(agent_uri, receiver, action, products, catalog)


def _handle_order(
    catalog: Graph,
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
    logistics_url: str,
    payments_url: str,
) -> Graph:
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return build_failure(agent_uri, receiver, action, "Falta accionSobrePedido")

    product_quantities = _extract_product_quantities(graph, pedido)
    if not product_quantities:
        return build_failure(agent_uri, receiver, action, "El pedido no contiene lineas")

    address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    city = str(next(graph.objects(address, ECSDI.ciudad), "")) if address is not None else ""
    center = choose_single_center(catalog, product_quantities, city)
    if center is None:
        return build_failure(agent_uri, receiver, action, "No hay un unico centro logistico con stock suficiente")

    order_graph = _build_enriched_order_graph(catalog, graph, action, pedido, center, product_quantities)

    # --- PAGO: debe ocurrir antes de planificar el envío ---
    total = Decimal(str(next(order_graph.objects(pedido, ECSDI.importeTotalPedido), "0")))
    payment_message, operacion = build_payment_request(agent_uri, AGENTS.ProveedorPagos, pedido, total)
    payment_response = post_graph(payments_url, payment_message)

    confirmacion_pago = next(payment_response.subjects(RDF.type, ECSDI.ConfirmacionTransaccion), None)
    if confirmacion_pago is None:
        return build_failure(agent_uri, receiver, action, "El proveedor de pagos no devolvio confirmacion")

    estado_op = str(next(payment_response.objects(operacion, ECSDI.estadoOperacion), ""))
    if estado_op != "confirmada":
        return build_failure(agent_uri, receiver, action, f"Pago rechazado (estado: {estado_op})")

    # Incorporar SOLO la información relevante del pago
    for triple in payment_response.triples((operacion, None, None)):
        order_graph.add(triple)

    confirmacion_pago = next(
        payment_response.subjects(RDF.type, ECSDI.ConfirmacionTransaccion),
        None
    )

    if confirmacion_pago is not None:
        for triple in payment_response.triples((confirmacion_pago, None, None)):
            order_graph.add(triple)

    order_graph.add((pedido, ECSDI.pedidoTieneOperacionPago, operacion))
    # ------------------------------------------------------

    logistics_message = build_message(order_graph, action, ACL.request, agent_uri, AGENTS.CentroLogisticoBarcelona)
    shipping_response = post_graph(logistics_url, logistics_message)

    reserve_stock(catalog, center, product_quantities)
    for triple in shipping_response:
        order_graph.add(triple)

    order_graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_envio_planificado")))
    return build_message(order_graph, pedido, ACL.inform, agent_uri, receiver)


def _build_enriched_order_graph(
    catalog: Graph,
    request_graph: Graph,
    action: URIRef,
    pedido: URIRef,
    center: URIRef,
    product_quantities: dict[str, int],
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    _copy_subject(request_graph, graph, action)
    _copy_subject(request_graph, graph, pedido)

    address = next(request_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is not None:
        _copy_subject(request_graph, graph, address)

    for line in request_graph.objects(pedido, ECSDI.pedidoTieneLinea):
        _copy_subject(request_graph, graph, line)
        product = next(request_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is not None:
            copy_product(catalog, graph, product)
            price = describe_product(catalog, product)["price"]
            graph.add((line, ECSDI.precioUnitario, decimal_literal(price)))

    copy_center(catalog, graph, center)
    total = order_total(catalog, product_quantities)
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


def _extract_product_quantities(graph: Graph, pedido: URIRef) -> dict[str, int]:
    quantities = {}
    for line in graph.objects(pedido, ECSDI.pedidoTieneLinea):
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        quantity = int(next(graph.objects(line, ECSDI.cantidad), 1))
        if product is None:
            continue
        product_id = str(product).rstrip("/").split("/")[-1]
        if product_id.startswith("P-"):
            quantities[product_id] = quantities.get(product_id, 0) + quantity
        else:
            quantities[str(next(graph.objects(product, ECSDI.idProducto), product_id))] = quantity
    return quantities


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
    parser.add_argument("--payments-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    logistics_base = args.logistics_url or search_service(args.dir, "CENTRO_LOGISTICO") or "http://127.0.0.1:9002"
    logistics_url = _comm_url(logistics_base)
    payments_base = args.payments_url or search_service(args.dir, "PROVEEDOR_PAGOS") or "http://127.0.0.1:9004"
    payments_url = _comm_url(payments_base)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("TIENDA", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "TIENDA", address, f"tienda-{args.port}")
    try:
        log(f"tienda-{args.port}", f"listening on {bind_host}:{args.port}, logistics={logistics_url}, payments={payments_url}")
        create_app(logistics_url=logistics_url, payments_url=payments_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"tienda-{args.port}")


def _comm_url(base_url: str) -> str:
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


if __name__ == "__main__":
    main()