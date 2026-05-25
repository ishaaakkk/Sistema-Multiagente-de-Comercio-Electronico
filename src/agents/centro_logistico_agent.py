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
    search_all_services,
    unregister_service,
)


DEFAULT_AGENT_URI = AGENTS.CentroLogisticoBarcelona


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    transport_url: str | None = None,
    directory_url: str | None = None,
):
    """
    transport_url: URL fija de fallback si no hay directorio (compatibilidad).
    directory_url: URL del directorio para descubrir transportistas dinamicamente.
    Si hay directorio, se ignora transport_url y se usan todos los registrados.
    """
    app = Flask(__name__)
    center = center_uri("CL-BCN")

    @app.get("/")
    def index():
        return "CentroLogisticoAgent listo"

    @app.post("/comm")
    def comm():
        # Plan: AgruparPedidoEnLote (AgenteLogistico / AgruparEnLotes)
        # Msg entrante: AvisarPedidoACL (AgenteComerciante → AgenteLogistico)
        # Recibe RealizarPedido, construye un LoteEnvio y negocia el transporte
        # con TODOS los transportistas registrados, eligiendo la oferta mas barata.
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

            # Plan: ProponerEnvioTransportistas → SeleccionOfertaIniciales
            # Descubrir transportistas: primero via directorio, fallback a URL fija
            transport_urls = _discover_transportistas(directory_url, transport_url, agent_uri, f"logistico")

            if not transport_urls:
                return rdf_response(build_failure(agent_uri, message.sender, action, "No hay transportistas disponibles"))

            # Pedir oferta a cada transportista y quedarse con la mas barata
            best_offer_graph, best_offer, best_transportista = _negotiate_transport(
                agent_uri, lote_graph, lote, action, transport_urls
            )

            if best_offer is None:
                return rdf_response(build_failure(agent_uri, message.sender, action, "Ningun transportista respondio con oferta valida"))

            best_offer_graph.set((best_offer, ECSDI.estadoOferta, Literal("aceptada")))
            _merge_graphs(best_offer_graph, lote_graph)

            # Plan: InformarDatosEnvioMsg (AgenteLogistico → AgenteComerciante)
            response = build_shipping_confirmation(
                sender=URIRef(agent_uri),
                receiver=message.sender,
                action=action,
                pedido=pedido,
                lote=lote,
                offer_graph=best_offer_graph,
                offer=best_offer,
                transportista=best_transportista,
            )
            return rdf_response(response)
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _discover_transportistas(
    directory_url: str | None,
    fallback_url: str | None,
    requester: URIRef,
    prefix: str,
) -> list[str]:
    """Devuelve la lista de URLs /comm de todos los transportistas disponibles.

    Si hay directorio, consulta search_all_services para obtener todos los
    transportistas registrados. Si no hay ninguno o no hay directorio, usa
    la URL de fallback (compatibilidad con lanzamientos sin directorio).
    """
    if directory_url:
        urls = search_all_services(directory_url, "TRANSPORTISTA", requester)
        if urls:
            comm_urls = [_comm_url(u) for u in urls]
            log(prefix, f"Transportistas descubiertos via directorio: {comm_urls}")
            return comm_urls
        log(prefix, "No se encontraron transportistas en el directorio, usando fallback")

    if fallback_url:
        log(prefix, f"Usando transportista de fallback: {fallback_url}")
        return [fallback_url]

    return []


def _negotiate_transport(
    agent_uri: URIRef,
    lote_graph: Graph,
    lote: URIRef,
    action: URIRef,
    transport_urls: list[str],
) -> tuple[Graph | None, URIRef | None, URIRef | None]:
    """Solicita presupuesto a cada transportista y devuelve la oferta mas barata.

    Retorna (offer_graph, offer_uri, transportista_uri) del ganador,
    o (None, None, None) si ninguno responde correctamente.
    """
    best_price = None
    best_offer_graph = None
    best_offer = None
    best_transportista = None

    for url in transport_urls:
        try:
            request_msg = build_transport_request(agent_uri, AGENTS.TransportistaExpress, lote_graph, lote)
            offer_graph = post_graph(url, request_msg)

            offer = next(offer_graph.subjects(RDF.type, ECSDI.OfertaTransporte), None)
            if offer is None:
                log("logistico", f"Transportista {url} no devolvio oferta valida")
                continue

            price = Decimal(str(next(offer_graph.objects(offer, ECSDI.precioOferta), "99999")))
            transportista = next(offer_graph.objects(offer, ECSDI.ofertaRealizadaPor), AGENTS.TransportistaExpress)
            days = next(offer_graph.objects(offer, ECSDI.plazoMaximoDias), "?")

            log("logistico", f"Oferta de {url}: {price:.2f}€ en {days} dia(s)")

            if best_price is None or price < best_price:
                best_price = price
                best_offer_graph = offer_graph
                best_offer = offer
                best_transportista = transportista

        except Exception as exc:
            log("logistico", f"Error contactando transportista {url}: {exc}")
            continue

    if best_offer is not None:
        log("logistico", f"Oferta seleccionada: {best_transportista} a {best_price:.2f}€")

    return best_offer_graph, best_offer, best_transportista


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
    parser.add_argument("--transport-url", default=None, help="URL fija de fallback para un transportista")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)

    # Si hay directorio, los transportistas se descubren dinamicamente en cada pedido.
    # Si no, se usa --transport-url como fallback.
    fallback_transport = None
    if args.transport_url:
        fallback_transport = _comm_url(args.transport_url)
    elif not args.dir:
        # Sin directorio ni URL explicita: fallback al puerto por defecto
        fallback_transport = "http://127.0.0.1:9003/comm"

    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("CENTRO_LOGISTICO", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "CENTRO_LOGISTICO", address, f"logistico-{args.port}")
    try:
        log(
            f"logistico-{args.port}",
            f"listening on {bind_host}:{args.port}, "
            f"dir={args.dir or 'N/A'}, fallback_transport={fallback_transport or 'N/A'}"
        )
        create_app(
            transport_url=fallback_transport,
            directory_url=args.dir,
        ).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"logistico-{args.port}")


def _comm_url(base_url: str) -> str:
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


if __name__ == "__main__":
    main()
