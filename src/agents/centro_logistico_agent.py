import argparse
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_not_understood, get_message
from utilities.builders import build_shipping_confirmation, build_transport_request
from utilities.catalog import center_uri, decimal_literal
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


DEFAULT_AGENT_URI = AGENTS.CentroLogisticoBarcelona


def create_app(agent_uri=DEFAULT_AGENT_URI, transport_url="http://127.0.0.1:9003/comm"):
    app = Flask(__name__)
    center = center_uri("CL-BCN")

    @app.get("/")
    def index():
        return "CentroLogisticoAgent listo"

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
            if (action, RDF.type, ECSDI.RealizarPedido) not in graph:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Accion logistica no soportada"))

            pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
            if pedido is None:
                return rdf_response(build_failure(agent_uri, message.sender, action, "Falta el pedido"))

            lote_graph, lote = _build_lote_graph(graph, pedido, center)
            request_to_transport = build_transport_request(agent_uri, AGENTS.TransportistaExpress, lote_graph, lote)
            offer_graph = post_graph(transport_url, request_to_transport)

            offer = next(offer_graph.subjects(RDF.type, ECSDI.OfertaTransporte), None)
            if offer is None:
                return rdf_response(build_failure(agent_uri, message.sender, action, "El transportista no ha devuelto oferta"))
            transportista = next(offer_graph.objects(offer, ECSDI.ofertaRealizadaPor), AGENTS.TransportistaExpress)
            offer_graph.set((offer, ECSDI.estadoOferta, Literal("aceptada")))
            _merge_graphs(offer_graph, lote_graph)

            response = build_shipping_confirmation(
                sender=URIRef(agent_uri),
                receiver=message.sender,
                action=action,
                pedido=pedido,
                lote=lote,
                offer_graph=offer_graph,
                offer=offer,
                transportista=transportista,
            )
            return rdf_response(response)
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _build_lote_graph(order_graph: Graph, pedido: URIRef, center: URIRef) -> tuple[Graph, URIRef]:
    graph = Graph()
    bind_namespaces(graph)
    lote = DATA[f"lote/{uuid4()}"]
    address = next(order_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    priority = int(next(order_graph.objects(pedido, ECSDI.prioridadEntrega), 3))
    weight = Decimal("0")

    graph.add((lote, RDF.type, ECSDI.LoteEnvio))
    graph.add((lote, ECSDI.idLote, Literal(f"LOT-{uuid4().hex[:8].upper()}")))
    graph.add((lote, ECSDI.loteOrigenCentro, center))
    graph.add((lote, ECSDI.estadoLote, Literal("pendiente_transportista")))
    graph.add((lote, ECSDI.prioridadLote, Literal(priority, datatype=XSD.integer)))
    if address is not None:
        graph.add((lote, ECSDI.loteDestinoDireccion, address))
        _copy_subject(order_graph, graph, address)

    for line in order_graph.objects(pedido, ECSDI.pedidoTieneLinea):
        graph.add((lote, ECSDI.loteTieneLinea, line))
        _copy_subject(order_graph, graph, line)
        product = next(order_graph.objects(line, ECSDI.lineaDeProducto), None)
        quantity = int(next(order_graph.objects(line, ECSDI.cantidad), 1))
        if product is not None:
            _copy_subject(order_graph, graph, product)
            product_weight = Decimal(str(next(order_graph.objects(product, ECSDI.pesoProducto), "0")))
            weight += product_weight * quantity

    graph.add((lote, ECSDI.pesoTotalLote, decimal_literal(weight)))
    return graph, lote


def _copy_subject(source: Graph, target: Graph, subject: URIRef) -> None:
    for triple in source.triples((subject, None, None)):
        target.add(triple)


def _merge_graphs(target: Graph, source: Graph) -> None:
    for triple in source:
        target.add(triple)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9002)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--transport-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    transport_base = args.transport_url or search_service(args.dir, "TRANSPORTISTA") or "http://127.0.0.1:9003"
    transport_url = _comm_url(transport_base)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("CENTRO_LOGISTICO", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "CENTRO_LOGISTICO", address, f"logistico-{args.port}")
    try:
        log(f"logistico-{args.port}", f"listening on {bind_host}:{args.port}, transport={transport_url}")
        create_app(transport_url=transport_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"logistico-{args.port}")


def _comm_url(base_url: str) -> str:
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


if __name__ == "__main__":
    main()
