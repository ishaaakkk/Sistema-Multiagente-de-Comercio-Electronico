import argparse
from decimal import Decimal

from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import build_busqueda_realizada_notification, build_search_response
from utilities.catalog import (
    center_uri,
    decimal_literal,
    describe_product,
    extract_search_constraints,
    filter_products,
    product_uri,
    stock_uri,
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
from utilities.storage import load_graph, save_graph, save_named_graph


DEFAULT_AGENT_URI = AGENTS.AgenteCatalogo

# --- Datos del catalogo (futura ProductosDB via SPARQL) ---

CATALOG_PRODUCTS = [
    {
        "id": "P-IPHONE19",
        "name": "iPhone 19",
        "brand": "Apple",
        "description": "Smartphone interno de gama alta con 256 GB",
        "price": Decimal("1199.00"),
        "rating": Decimal("4.75"),
        "weight": Decimal("0.45"),
        "center": "CL-BCN",
        "stock": 25,
    },
    {
        "id": "P-EBOOK-AURORA",
        "name": "Ebook Reader Aurora",
        "brand": "Readly",
        "description": "Lector de libros electronicos con pantalla mate",
        "price": Decimal("149.90"),
        "rating": Decimal("4.40"),
        "weight": Decimal("0.30"),
        "center": "CL-BCN",
        "stock": 18,
    },
    {
        "id": "P-BATIDORA-MINI",
        "name": "Batidora Mini",
        "brand": "HomeUp",
        "description": "Pequeno electrodomestico interno para cocina",
        "price": Decimal("44.50"),
        "rating": Decimal("4.10"),
        "weight": Decimal("1.20"),
        "center": "CL-MAD",
        "stock": 11,
    },
    {
        "id": "P-LIBRO-RUST",
        "name": "Programacion en Rust",
        "brand": "ManningES",
        "description": "Libro tecnico sobre desarrollo Rust de sistemas distribuidos",
        "price": Decimal("39.00"),
        "rating": Decimal("4.65"),
        "weight": Decimal("0.70"),
        "center": "CL-MAD",
        "stock": 22,
    },
]

EXTERNAL_VENDORS = [
    {
        "id": "VEND-TECHWORLD",
        "name": "TechWorld SL",
        "uri": "VEND-TECHWORLD",
    },
    {
        "id": "VEND-HOMEGADGETS",
        "name": "HomeGadgets Europe",
        "uri": "VEND-HOMEGADGETS",
    },
]

# Productos externos de demo:
#   - P-SMARTWATCH-X: vendedor gestiona el envio (gestionEnvioExterno=true)
#   - P-AURICULARES-BT: la tienda gestiona el envio (gestionEnvioExterno=false)
EXTERNAL_PRODUCTS = [
    {
        "id": "P-SMARTWATCH-X",
        "name": "SmartWatch X Pro",
        "brand": "TechWorld",
        "description": "Reloj inteligente externo con GPS y monitor cardiaco",
        "price": Decimal("299.00"),
        "rating": Decimal("4.50"),
        "weight": Decimal("0.15"),
        "vendor": "VEND-TECHWORLD",
        "shipping_external": True,   # El vendedor gestiona el envio
    },
    {
        "id": "P-AURICULARES-BT",
        "name": "Auriculares BT Pro",
        "brand": "HomeGadgets",
        "description": "Auriculares inalambricos externos con cancelacion de ruido",
        "price": Decimal("89.90"),
        "rating": Decimal("4.20"),
        "weight": Decimal("0.25"),
        "vendor": "VEND-HOMEGADGETS",
        "shipping_external": False,  # La tienda gestiona el envio
    },
]

LOGISTIC_CENTERS = [
    {
        "id": "CL-BCN",
        "name": "Centro Logistico Barcelona",
        "city": "Barcelona",
    },
    {
        "id": "CL-MAD",
        "name": "Centro Logistico Madrid",
        "city": "Madrid",
    },
]


def build_catalog_graph() -> Graph:
    """Construye el grafo RDF inicial con productos y centros logisticos.
    Futura sustitucion: carga desde ProductosDB via SPARQL.
    """
    graph = Graph()
    bind_namespaces(graph)

    for center in LOGISTIC_CENTERS:
        node = center_uri(center["id"])
        graph.add((node, RDF.type, ECSDI.CentroLogistico))
        graph.add((node, ECSDI.idCentroLogistico, Literal(center["id"])))
        graph.add((node, ECSDI.nombreCentroLogistico, Literal(center["name"])))
        graph.add((node, ECSDI.ciudadCentroLogistico, Literal(center["city"])))

    for product in CATALOG_PRODUCTS:
        pnode = product_uri(product["id"])
        graph.add((pnode, RDF.type, ECSDI.ProductoInterno))
        graph.add((pnode, RDF.type, ECSDI.Producto))
        graph.add((pnode, ECSDI.idProducto, Literal(product["id"])))
        graph.add((pnode, ECSDI.nombreProducto, Literal(product["name"])))
        graph.add((pnode, ECSDI.marcaProducto, Literal(product["brand"])))
        graph.add((pnode, ECSDI.descripcionProducto, Literal(product["description"])))
        graph.add((pnode, ECSDI.precioProducto, decimal_literal(product["price"])))
        graph.add((pnode, ECSDI.valoracionMedia, decimal_literal(product["rating"])))
        graph.add((pnode, ECSDI.pesoProducto, decimal_literal(product["weight"])))

        snode = stock_uri(product["id"], product["center"])
        graph.add((snode, RDF.type, ECSDI.StockProducto))
        graph.add((snode, ECSDI.stockDeProducto, pnode))
        graph.add((snode, ECSDI.stockEnCentro, center_uri(product["center"])))
        graph.add((snode, ECSDI.cantidadDisponible, Literal(product["stock"], datatype=XSD.integer)))

    for vendor in EXTERNAL_VENDORS:
        vnode = AGENTS[vendor["uri"]]
        graph.add((vnode, RDF.type, ECSDI.VendedorExterno))
        graph.add((vnode, ECSDI.idVendedor, Literal(vendor["id"])))
        graph.add((vnode, ECSDI.nombreVendedor, Literal(vendor["name"])))

    for product in EXTERNAL_PRODUCTS:
        pnode = product_uri(product["id"])
        vendor_node = AGENTS[product["vendor"]]
        graph.add((pnode, RDF.type, ECSDI.ProductoExterno))
        graph.add((pnode, RDF.type, ECSDI.Producto))
        graph.add((pnode, ECSDI.idProducto, Literal(product["id"])))
        graph.add((pnode, ECSDI.nombreProducto, Literal(product["name"])))
        graph.add((pnode, ECSDI.marcaProducto, Literal(product["brand"])))
        graph.add((pnode, ECSDI.descripcionProducto, Literal(product["description"])))
        graph.add((pnode, ECSDI.precioProducto, decimal_literal(product["price"])))
        graph.add((pnode, ECSDI.valoracionMedia, decimal_literal(product["rating"])))
        graph.add((pnode, ECSDI.pesoProducto, decimal_literal(product["weight"])))
        graph.add((pnode, ECSDI.gestionEnvioExterno, Literal(product["shipping_external"])))
        graph.add((pnode, ECSDI.productoOfrecidoPor, vendor_node))

    return graph


def create_app(agent_uri=DEFAULT_AGENT_URI, feedback_url: str | None = None):
    app = Flask(__name__)
    catalog = build_catalog_graph()
    for triple in load_graph("catalog.ttl"):
        catalog.add(triple)

    # Historial de busquedas en memoria (futura HistorialBusquedasDB via SPARQL)
    search_history: list[dict] = []

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
                    _handle_search(catalog, search_history, agent_uri, message.sender, action, graph, feedback_url)
                )

            # Capacidad AñadirProductoExt — Plan: ActualizarCatalogo
            # Msg entrante: DarAltaProductoExterno (VendedorExterno → AgenteCatalogo)
            if (action, RDF.type, ECSDI.DarAltaProductoExterno) in graph:
                return reply(_handle_external_product_registration(catalog, agent_uri, message.sender, action, graph))

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteCatalogo"))

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_search(
    catalog: Graph,
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
    constraints = extract_search_constraints(graph, action)

    products = filter_products(catalog, constraints)

    tipo = str(next(graph.objects(action, ECSDI.tipoBusqueda), "compra"))
    if tipo == "compra":
        search_history.append({
            "constraints": constraints,
            "results": [str(p) for p in products],
            "tipo": tipo,
        })
        log("catalogo", f"Busqueda registrada en historial: {constraints} -> {len(products)} productos")

    log("catalogo", f"Busqueda: {constraints} -> {len(products)} productos encontrados")

    if feedback_url and tipo == "compra":
        try:
            notify = build_busqueda_realizada_notification(
                agent_uri, AGENTS.AgenteFeedback, receiver, constraints, products
            )
            post_graph(feedback_url, notify)
            log("catalogo", f"Protocolo Consulta Catálogo → feedback notificado ({len(products)} resultados)")
        except Exception as exc:
            log("catalogo", f"Aviso protocolo consulta catalogo fallido: {exc}")

    return build_search_response(agent_uri, receiver, action, products, catalog)


def _handle_external_product_registration(
    catalog: Graph,
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Plan: ActualizarCatalogo — integra productos externos anunciados."""
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

    log("catalogo", f"Alta externa registrada: {len(products)} producto(s)")
    save_graph("catalog.ttl", catalog)
    save_named_graph("catalog", catalog)
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
