import argparse
from decimal import Decimal

from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import build_busqueda_realizada_notification, build_search_response
from utilities.catalog import (
    build_stock_graph,
    decimal_literal,
    describe_product,
    extract_search_constraints,
    filter_products,
    load_persisted_catalog,
    list_center_ids,
    persist_catalog,
    persist_stock_graph,
    sync_stock_all_centers,
)
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
    search_service,
    unregister_service,
)
from utilities.storage import DATA_DIR, load_graph, load_json


DEFAULT_AGENT_URI = AGENTS.AgenteCatalogo
CATALOG_PATH = DATA_DIR / "catalog.ttl"


def load_catalog_graph() -> Graph:
    """ProductosDB: carga exclusivamente desde catalog.ttl."""

    if not CATALOG_PATH.exists():
        raise FileNotFoundError(
            f"No existe ProductosDB en {CATALOG_PATH}. "
            "Copia o versiona data/catalog.ttl antes de arrancar el agente."
        )
    catalog = load_graph("catalog.ttl")
    if len(catalog) == 0:
        raise ValueError(f"{CATALOG_PATH} está vacío o no contiene tripletas válidas.")
    return catalog


def _bootstrap_unified_stock() -> None:
    """Todos los productos logísticos con stock en cada centro (ProductosDB)."""

    catalog = load_persisted_catalog()
    if len(catalog) == 0:
        return
    stock_rows_before = sum(1 for _ in catalog.triples((None, ECSDI.stockEnCentro, None)))
    sync_stock_all_centers(catalog)
    stock_rows_after = sum(1 for _ in catalog.triples((None, ECSDI.stockEnCentro, None)))
    if stock_rows_after == stock_rows_before:
        return
    persist_catalog(catalog)
    for center_id in list_center_ids(catalog):
        persist_stock_graph(center_id, build_stock_graph(catalog, center_id))
    log("catalogo", f"Stock unificado: {stock_rows_after} filas en {len(list_center_ids(catalog))} CL")


def create_app(agent_uri=DEFAULT_AGENT_URI, feedback_url: str | None = None):
    app = Flask(__name__)
    initial_catalog = load_catalog_graph()
    _bootstrap_unified_stock()
    log("catalogo", f"ProductosDB lista ({len(initial_catalog)} tripletas)")

    # Historial de búsquedas local del Catálogo (útil para depurar).
    # Para persistencia del sistema de recomendación se usa el protocolo hacia AgenteFeedback,
    # pero mantenemos también esta traza local en disco.
    search_history: list[dict] = load_json("catalog_searches.json", [])

    @app.get("/")
    def index():
        return "AgenteCatalogo listo"

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, message.sender if message else AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido"))
            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))
            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Capacidad PDT BuscarEnCatalogo — accion ontologica BuscarProductos.
            # Plan: BuscarEnCatalogo → FiltrarProductos → MostrarProductos
            # Msg entrante: BuscarProductos (AsistenteVirtual → AgenteCatalogo)
            # Msg saliente: ResultadoBusqueda (AgenteCatalogo → AsistenteVirtual)
            # Tras la respuesta se dispara el protocolo Consulta Catálogo
            # (NotificarBusquedaRealizada → AgenteFeedback) para alimentar el
            # historial de búsquedas usado por la recomendación periódica.
            if (action, RDF.type, ECSDI.BuscarProductos) in graph:
                return reply(
                    _handle_search(search_history, agent_uri, message.sender, action, graph, feedback_url)
                )

            # Capacidad AñadirProductoExt — Plan: ActualizarCatalogo
            # Msg entrante: DarAltaProductoExterno (VendedorExterno → AgenteCatalogo)
            if (action, RDF.type, ECSDI.DarAltaProductoExterno) in graph:
                return reply(_handle_external_product_registration(agent_uri, message.sender, action, graph))

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteCatalogo"))

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_search(
    search_history: list[dict],
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    graph: Graph,
    feedback_url: str | None = None,
) -> Graph:
    """Plan PDT BuscarEnCatalogo sobre la accion ontologica BuscarProductos.

    Extrae restricciones, filtra productos y registra la busqueda en el historial
    si el tipo de peticion es compra (futura HistorialBusquedasDB via SPARQL).
    Devuelve ResultadoBusqueda directamente al solicitante (AsistenteVirtual).

    Protocolo Consulta Catálogo (cap. 9 sobre recomendadores): tras devolver
    los productos al asistente, se dispara una NotificarBusquedaRealizada
    (ACL.inform) al AgenteFeedback para que la búsqueda alimente el algoritmo
    de recomendación. Si el agente feedback no está disponible, se ignora.
    """
    catalog = _load_live_catalog()
    constraints = extract_search_constraints(graph, action)

    products = filter_products(catalog, constraints)

    tipo = str(next(graph.objects(action, ECSDI.tipoBusqueda), "compra"))
    if tipo == "compra":
        search_history.append({
            "constraints": constraints,
            "results": [str(p) for p in products],
            "tipo": tipo,
        })
        from utilities.storage import save_json
        save_json("catalog_searches.json", search_history)
        log("catalogo", f"Busqueda registrada en historial: {constraints} -> {len(products)} productos")

    log("catalogo", f"Busqueda: {constraints} -> {len(products)} productos encontrados")

    if feedback_url and tipo == "compra":
        try:
            notify = build_busqueda_realizada_notification(
                agent_uri, AGENTS.AgenteFeedback, receiver, constraints, products, catalog
            )
            post_graph(feedback_url, notify)
            log("catalogo", f"Protocolo Consulta Catálogo → feedback notificado ({len(products)} resultados)")
        except Exception as exc:
            log("catalogo", f"Aviso protocolo consulta catalogo fallido: {exc}")

    return build_search_response(agent_uri, receiver, action, products, catalog)


def _load_live_catalog() -> Graph:
    """ProductosDB en disco (recarga en cada petición para ver valoracionMedia actualizada)."""

    catalog = load_persisted_catalog()
    if len(catalog) > 0:
        return catalog
    return load_catalog_graph()


def _handle_external_product_registration(
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Plan: ActualizarCatalogo — integra productos externos anunciados."""
    catalog = _load_live_catalog()
    products = list(graph.objects(action, ECSDI.accionSobreProducto))
    for product in graph.subjects(RDF.type, ECSDI.ProductoExterno):
        if product not in products:
            products.append(product)

    if not products:
        return build_failure(agent_uri, sender, action, "Falta el producto externo a registrar")

    response_graph = Graph()
    bind_namespaces(response_graph)
    response = DATA[f"response/catalogo/alta-externa/{uuid4()}"]
    response_graph.add((response, RDF.type, ECSDI.Respuesta))
    response_graph.add((response, ECSDI.respuestaDeAccion, action))

    for product in products:
        _copy_subject(graph, catalog, product)
        catalog.add((product, RDF.type, ECSDI.Producto))
        catalog.add((product, RDF.type, ECSDI.ProductoExterno))
        if next(catalog.objects(product, ECSDI.idProducto), None) is None:
            catalog.add((product, ECSDI.idProducto, Literal(_product_id_from_uri(product))))
        if next(catalog.objects(product, ECSDI.nombreProducto), None) is None:
            catalog.add((product, ECSDI.nombreProducto, Literal(_product_id_from_uri(product))))
        if next(catalog.objects(product, ECSDI.precioProducto), None) is None:
            catalog.add((product, ECSDI.precioProducto, decimal_literal(Decimal("0"))))
        if next(catalog.objects(product, ECSDI.valoracionMedia), None) is None:
            catalog.add((product, ECSDI.valoracionMedia, decimal_literal(Decimal("0"))))
        if next(catalog.objects(product, ECSDI.pesoProducto), None) is None:
            catalog.add((product, ECSDI.pesoProducto, decimal_literal(Decimal("1.0"))))
        if next(catalog.objects(product, ECSDI.gestionEnvioExterno), None) is None:
            catalog.add((product, ECSDI.gestionEnvioExterno, Literal(True, datatype=XSD.boolean)))
        if next(catalog.objects(product, ECSDI.productoOfrecidoPor), None) is None:
            catalog.add((product, ECSDI.productoOfrecidoPor, sender))
        _copy_subject(catalog, response_graph, product)

    sync_stock_all_centers(catalog)
    persist_catalog(catalog)
    for center_id in list_center_ids(catalog):
        persist_stock_graph(center_id, build_stock_graph(catalog, center_id))
    log("catalogo", f"Alta externa registrada: {len(products)} producto(s)")
    return build_message(response_graph, response, ACL.inform, agent_uri, sender)


def _copy_subject(source: Graph, target: Graph, subject: URIRef) -> None:
    for triple in source.triples((subject, None, None)):
        target.add(triple)


def _product_id_from_uri(product: URIRef) -> str:
    uri = str(product)
    return uri.rsplit("/producto/", 1)[-1] if "/producto/" in uri else uri.rsplit("/", 1)[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9006)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--feedback-url", default=None, help="URL del agente feedback (Protocolo Consulta Catálogo)")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_CATALOGO", advertised_host, args.port)
    feedback_base = args.feedback_url or search_service(args.dir, "AGENTE_FEEDBACK", service_id)
    feedback_url = _comm_url(feedback_base) if feedback_base else None
    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_CATALOGO",
        address,
        f"catalogo-{args.port}",
        capabilities=[ECSDI.BuscarProductos, ECSDI.DarAltaProductoExterno],
    )
    try:
        log(
            f"catalogo-{args.port}",
            f"listening on {bind_host}:{args.port}, feedback={feedback_url or 'N/A'}",
        )
        create_app(feedback_url=feedback_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"catalogo-{args.port}")


if __name__ == "__main__":
    main()
