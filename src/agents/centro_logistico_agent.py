import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message
from utilities.builders import build_shipping_confirmation, build_transport_request
from utilities.catalog import center_uri, decimal_literal
from utilities.comm import comm_url as _comm_url
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
from utilities.storage import load_json, save_json


DEFAULT_AGENT_URI = AGENTS.CentroLogisticoBarcelona


# Configuración por defecto: el centro logístico de Barcelona acepta todos los
# productos internos. Para multi-CL se pasa --stock-products con la lista
# concreta de identificadores de producto que cada centro maneja.
DEFAULT_STOCK_ANY = ("*",)

# Timeout por transportista en la fase de CFP (Contract Net cap. 7.3.2).
DEFAULT_TRANSPORT_TIMEOUT = float(os.environ.get("CL_TRANSPORT_TIMEOUT", "4"))


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    transport_url: str | None = None,
    directory_url: str | None = None,
    center_id: str = "CL-BCN",
    center_city: str = "Barcelona",
    stock_products: tuple[str, ...] = DEFAULT_STOCK_ANY,
):
    """Crea la aplicación Flask del centro logístico.

    Parámetros relevantes para la extensión avanzada #3 (multi-CL):
        center_id: identificador del centro (CL-BCN, CL-MAD, ...).
        center_city: ciudad servida por el centro.
        stock_products: lista de IDs de producto que el centro puede servir;
            ("*",) significa "todos los productos internos".
    """

    app = Flask(__name__)
    center = center_uri(center_id)
    stock_set = {p.strip() for p in stock_products if p.strip()}
    accepts_all = stock_set == {"*"} or not stock_set
    log_tag = f"logistico-{center_id}"

    @app.get("/")
    def index():
        return f"CentroLogisticoAgent {center_id} listo (ciudad={center_city})"

    @app.get("/info")
    def info():
        return {
            "center_id": center_id,
            "center_uri": str(center),
            "center_city": center_city,
            "accepts_all": accepts_all,
            "stock_products": sorted(stock_set) if not accepts_all else [],
        }

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(
                    build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido")
                )
            if message.performative != ACL.request:
                return rdf_response(
                    build_not_understood(agent_uri, message.sender, "Se esperaba performativa request")
                )

            action = message.content
            if (action, RDF.type, ECSDI.AvisarCL) not in graph and (action, RDF.type, ECSDI.RealizarPedido) not in graph:
                return rdf_response(
                    build_not_understood(agent_uri, message.sender, "Accion logistica no soportada")
                )

            pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
            if pedido is None:
                return rdf_response(build_failure(agent_uri, message.sender, action, "Falta el pedido"))

            fulfillable_lines = _filter_lines_by_stock(graph, pedido, accepts_all, stock_set)
            if not fulfillable_lines:
                log(log_tag, "Sin lineas servibles para este centro; respondiendo failure controlado")
                return rdf_response(
                    build_failure(
                        agent_uri,
                        message.sender,
                        action,
                        f"Centro {center_id} sin stock para las lineas del pedido",
                    )
                )

            lote_graph, lote = _build_lote_graph(graph, pedido, fulfillable_lines, center, center_city)

            transport_urls = _discover_transportistas(directory_url, transport_url, agent_uri, log_tag)
            if not transport_urls:
                return rdf_response(
                    build_failure(agent_uri, message.sender, action, "No hay transportistas disponibles")
                )

            best_offer_graph, best_offer, best_transportista, all_offers = _negotiate_transport(
                agent_uri, lote_graph, lote, transport_urls, log_tag
            )

            if best_offer is None:
                return rdf_response(
                    build_failure(
                        agent_uri,
                        message.sender,
                        action,
                        "Ningun transportista respondio con oferta valida",
                    )
                )

            _close_contract_net(
                agent_uri,
                lote,
                lote_graph,
                best_offer,
                best_transportista,
                all_offers,
                log_tag,
            )

            best_offer_graph.set((best_offer, ECSDI.estadoOferta, Literal("aceptada")))
            _merge_graphs(best_offer_graph, lote_graph)
            _reserve_stock(stock_reservations, graph, center, product_quantities)
            save_json("stock_reservations.json", stock_reservations)

            # Anotar el envío con el centro para que el asistente lo identifique.
            envio = DATA[f"envio/{uuid4()}"]
            for triple in best_offer_graph:
                if triple[1] == RDF.type and triple[2] == ECSDI.EnvioInterno:
                    envio = triple[0]
                    break

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
            # Etiqueta del centro en la respuesta (multi-CL).
            envio_in_resp = next(response.subjects(RDF.type, ECSDI.EnvioInterno), envio)
            response.add((envio_in_resp, ECSDI.envioDesdeCentro, center))
            response.add((envio_in_resp, ECSDI.idCentroLogistico, Literal(center_id)))
            response.add((envio_in_resp, ECSDI.ciudadCentroLogistico, Literal(center_city)))
            return rdf_response(response)
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _filter_lines_by_stock(
    graph: Graph, pedido: URIRef, accepts_all: bool, stock_set: set[str]
) -> list[URIRef]:
    """Devuelve sólo las líneas que este centro logístico puede servir."""

    fulfillable = []
    for line in graph.objects(pedido, ECSDI.pedidoTieneLinea):
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        if accepts_all:
            fulfillable.append(line)
            continue
        product_id = str(next(graph.objects(product, ECSDI.idProducto), ""))
        if product_id and product_id in stock_set:
            fulfillable.append(line)
    return fulfillable


def _discover_transportistas(
    directory_url: str | None,
    fallback_url: str | None,
    requester: URIRef,
    prefix: str,
) -> list[str]:
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
    transport_urls: list[str],
    log_tag: str,
) -> tuple[Graph | None, URIRef | None, URIRef | None, list[dict]]:
    """Contract Net en paralelo (cap. 7.3.2): envía la CFP a todos los
    transportistas a la vez con timeout, recoge las propuestas y devuelve la
    más barata. Cumple con el enunciado 3.6 sobre no penalizar paralelismo.
    """

    proposals: list[dict] = []

    def _cfp(url: str) -> dict | None:
        try:
            request_msg = build_transport_request(agent_uri, AGENTS.TransportistaExpress, lote_graph, lote)
            offer_graph = post_graph(url, request_msg, timeout=DEFAULT_TRANSPORT_TIMEOUT)
            offer = next(offer_graph.subjects(RDF.type, ECSDI.OfertaTransporte), None)
            if offer is None:
                return None
            price = Decimal(str(next(offer_graph.objects(offer, ECSDI.precioOferta), "99999")))
            transportista = next(
                offer_graph.objects(offer, ECSDI.ofertaRealizadaPor),
                AGENTS.TransportistaExpress,
            )
            days = next(offer_graph.objects(offer, ECSDI.plazoMaximoDias), "?")
            return {
                "url": url,
                "graph": offer_graph,
                "offer": offer,
                "price": price,
                "transportista": transportista,
                "days": days,
            }
        except Exception as exc:
            log(log_tag, f"Error contactando transportista {url}: {exc}")
            return None

    if not transport_urls:
        return None, None, None, []

    with ThreadPoolExecutor(max_workers=min(8, len(transport_urls))) as pool:
        futures = {pool.submit(_cfp, url): url for url in transport_urls}
        for future in as_completed(futures, timeout=DEFAULT_TRANSPORT_TIMEOUT * 2):
            try:
                proposal = future.result()
            except Exception as exc:
                log(log_tag, f"Future falló: {exc}")
                continue
            if proposal is not None:
                proposals.append(proposal)
                log(
                    log_tag,
                    f"Oferta de {proposal['url']}: {proposal['price']:.2f}€ en {proposal['days']} dia(s)",
                )

    if not proposals:
        return None, None, None, []

    winner = min(proposals, key=lambda p: p["price"])
    log(log_tag, f"Oferta seleccionada: {winner['transportista']} a {winner['price']:.2f}€")
    return winner["graph"], winner["offer"], winner["transportista"], proposals


def _close_contract_net(
    agent_uri: URIRef,
    lote: URIRef,
    lote_graph: Graph,
    best_offer: URIRef,
    best_transportista: URIRef,
    proposals: list[dict],
    log_tag: str,
) -> None:
    """Cierra el Contract Net enviando accept-proposal al ganador y
    reject-proposal a los perdedores (cap. 7.3.2 de los apuntes).

    Los mensajes son informativos: el contrato lo cerrará el centro logístico
    en la siguiente fase. El cierre es best-effort: si un transportista no
    está disponible, simplemente se loguea.
    """

    def _decision_msg(performative: URIRef, offer: URIRef, transportista: URIRef) -> Graph:
        msg = Graph()
        bind_namespaces(msg)
        decision = DATA[f"decision/{uuid4()}"]
        msg.add((decision, RDF.type, ECSDI.DecisionContratoTransporte))
        msg.add((decision, ECSDI.accionSobreLote, lote))
        msg.add((decision, ECSDI.accionSobreOferta, offer))
        return build_message(msg, decision, performative, agent_uri, transportista)

    for proposal in proposals:
        try:
            if proposal["offer"] == best_offer:
                msg = _decision_msg(ACL["accept-proposal"], proposal["offer"], proposal["transportista"])
                log(log_tag, f"accept-proposal → {proposal['url']}")
            else:
                msg = _decision_msg(ACL["reject-proposal"], proposal["offer"], proposal["transportista"])
                log(log_tag, f"reject-proposal → {proposal['url']}")
            try:
                post_graph(proposal["url"], msg, timeout=DEFAULT_TRANSPORT_TIMEOUT)
            except Exception as exc:
                log(log_tag, f"No se pudo notificar a {proposal['url']}: {exc}")
        except Exception as exc:
            log(log_tag, f"Fallo construyendo decision para {proposal['url']}: {exc}")


def _build_lote_graph(
    order_graph: Graph,
    pedido: URIRef,
    lines: list[URIRef],
    center: URIRef,
    center_city: str,
) -> tuple[Graph, URIRef]:
    graph = Graph()
    bind_namespaces(graph)
    lote = DATA[f"lote/{uuid4()}"]
    address = next(order_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    priority = int(next(order_graph.objects(pedido, ECSDI.prioridadEntrega), 3))
    weight = Decimal("0")

    graph.add((lote, RDF.type, ECSDI.LoteEnvio))
    graph.add((lote, ECSDI.idLote, Literal(f"LOT-{uuid4().hex[:8].upper()}")))
    graph.add((lote, ECSDI.loteOrigenCentro, center))
    _copy_subject(order_graph, graph, center)
    graph.add((lote, ECSDI.estadoLote, Literal("pendiente_transportista")))
    graph.add((lote, ECSDI.prioridadLote, Literal(priority, datatype=XSD.integer)))
    graph.add((lote, ECSDI.ciudadCentroLogistico, Literal(center_city)))
    if address is not None:
        graph.add((lote, ECSDI.loteDestinoDireccion, address))
        _copy_subject(order_graph, graph, address)

    for line in lines:
        graph.add((lote, ECSDI.loteTieneLinea, line))
        _copy_subject(order_graph, graph, line)
        product = next(order_graph.objects(line, ECSDI.lineaDeProducto), None)
        quantity = int(next(order_graph.objects(line, ECSDI.cantidad), 1))
        if product is not None:
            _copy_product_context(order_graph, graph, product)
            product_weight = Decimal(str(next(order_graph.objects(product, ECSDI.pesoProducto), "0")))
            weight += product_weight * quantity

    graph.add((lote, ECSDI.pesoTotalLote, decimal_literal(weight)))
    return graph, lote


def _copy_subject(source: Graph, target: Graph, subject: URIRef) -> None:
    for triple in source.triples((subject, None, None)):
        target.add(triple)


def _copy_product_context(source: Graph, target: Graph, product: URIRef) -> None:
    _copy_subject(source, target, product)
    for stock in source.subjects(ECSDI.stockDeProducto, product):
        _copy_subject(source, target, stock)
        center = next(source.objects(stock, ECSDI.stockEnCentro), None)
        if center is not None:
            _copy_subject(source, target, center)


def _merge_graphs(target: Graph, source: Graph) -> None:
    for triple in source:
        target.add(triple)


def _parse_stock_products(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_STOCK_ANY
    items = [s.strip() for s in raw.split(",") if s.strip()]
    return tuple(items) if items else DEFAULT_STOCK_ANY


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9002)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--transport-url", default=None, help="URL fija de fallback para un transportista")
    parser.add_argument("--center-id", default=None, help="Identificador del centro logístico (CL-BCN, CL-MAD, ...)")
    parser.add_argument("--center-city", default=None, help="Ciudad servida por el centro logístico")
    parser.add_argument(
        "--stock-products",
        default=None,
        help="Lista de IDs de producto separados por coma; '*' = todos los productos internos",
    )
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)

    fallback_transport = None
    if args.transport_url:
        fallback_transport = _comm_url(args.transport_url)
    elif not args.dir:
        fallback_transport = "http://127.0.0.1:9003/comm"

    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    center_id = (args.center_id or os.environ.get("CL_CENTER_ID") or "CL-BCN").upper()
    center_city = args.center_city or os.environ.get("CL_CENTER_CITY") or "Barcelona"
    stock_products = _parse_stock_products(args.stock_products or os.environ.get("CL_STOCK_PRODUCTS"))

    service_id = agent_id(f"CENTRO_LOGISTICO_{center_id}", advertised_host, args.port)
    registered = register_service(
        args.dir,
        service_id,
        "CENTRO_LOGISTICO",
        address,
        f"logistico-{center_id}-{args.port}",
        capabilities=[ECSDI.AvisarCL],
    )
    try:
        log(
            f"logistico-{center_id}-{args.port}",
            (
                f"listening on {bind_host}:{args.port}, center={center_id} ({center_city}), "
                f"stock={'*' if stock_products == DEFAULT_STOCK_ANY else stock_products}, "
                f"dir={args.dir or 'N/A'}, fallback_transport={fallback_transport or 'N/A'}"
            ),
        )
        create_app(
            transport_url=fallback_transport,
            directory_url=args.dir,
            center_id=center_id,
            center_city=center_city,
            stock_products=stock_products,
        ).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"logistico-{center_id}-{args.port}")


if __name__ == "__main__":
    main()
