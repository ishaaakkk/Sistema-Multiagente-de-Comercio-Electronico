import argparse
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message
from utilities.builders import build_cobro_request
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


DEFAULT_AGENT_URI = AGENTS.TiendaAgent


def create_app(agent_uri=DEFAULT_AGENT_URI, logistics_url="http://127.0.0.1:9002/comm", financiero_url="http://127.0.0.1:9005/comm"):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "TiendaAgent listo"

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
            # El asistente ya incluye idProducto, precio, vendedor y quienEnvia por cada linea.
            if (action, RDF.type, ECSDI.RealizarPedido) in graph:
                return rdf_response(_handle_order(agent_uri, message.sender, action, graph, logistics_url, financiero_url))

            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por TiendaAgent"))
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
) -> Graph:
    """Plan: PreguntarDatosCompra → RegistrarPedidoPendiente → EscogerCL (AgenteComerciante / PrepararPedido).

    Recibe RealizarPedido del asistente con los productos ya elegidos (idProducto, precio,
    vendedor, quienEnvia). Construye la factura a partir de los precios recibidos,
    coordina el envio con el centro logistico y notifica el cobro al financiero.
    """
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return build_failure(agent_uri, receiver, action, "Falta accionSobrePedido")

    lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not lines:
        return build_failure(agent_uri, receiver, action, "El pedido no contiene lineas")

    # Plan: RegistrarPedidoPendiente — construye grafo enriquecido con factura
    order_graph = _build_order_graph(graph, action, pedido, lines)

    # Plan: EscogerCL + Notificador → AvisarPedidoACL (AgenteComerciante → AgenteLogistico)
    # Se delega al CentroLogistico que agrupe en lote y negocie transporte.
    logistics_message = build_message(order_graph, action, ACL.request, agent_uri, AGENTS.CentroLogisticoBarcelona)
    shipping_response = post_graph(logistics_url, logistics_message)

    for triple in shipping_response:
        order_graph.add(triple)

    order_graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_envio_planificado")))

    # Plan: RecibirDatosEnvio → RealizarCobro (AgenteComerciante / FinalizarCompra)
    # Envio planificado; se notifica al AgenteFinanciero para cobrar (fire-and-forget).
    total = Decimal(str(next(order_graph.objects(pedido, ECSDI.importeTotalPedido), "0")))
    post_graph(financiero_url, build_cobro_request(agent_uri, AGENTS.AgenteFinanciero, pedido, total))

    return build_message(order_graph, pedido, ACL.inform, agent_uri, receiver)


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
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    logistics_base = args.logistics_url or search_service(args.dir, "CENTRO_LOGISTICO") or "http://127.0.0.1:9002"
    logistics_url = _comm_url(logistics_base)
    financiero_base = args.financiero_url or search_service(args.dir, "AGENTE_FINANCIERO") or "http://127.0.0.1:9005"
    financiero_url = _comm_url(financiero_base)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("TIENDA", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "TIENDA", address, f"tienda-{args.port}")
    try:
        log(f"tienda-{args.port}", f"listening on {bind_host}:{args.port}, logistics={logistics_url}, financiero={financiero_url}")
        create_app(logistics_url=logistics_url, financiero_url=financiero_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"tienda-{args.port}")


def _comm_url(base_url: str) -> str:
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


if __name__ == "__main__":
    main()