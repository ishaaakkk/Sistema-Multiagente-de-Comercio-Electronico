import argparse
from decimal import Decimal

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_not_understood, get_message
from utilities.builders import build_search_response
from utilities.catalog import (
    center_uri,
    decimal_literal,
    describe_product,
    extract_search_constraints,
    filter_products,
    product_uri,
    stock_uri,
)
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    unregister_service,
)


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
        "center": "CL-BCN",
        "stock": 11,
    },
]

LOGISTIC_CENTERS = [
    {
        "id": "CL-BCN",
        "name": "Centro Logistico Barcelona",
        "city": "Barcelona",
    }
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

    return graph


def create_app(agent_uri=DEFAULT_AGENT_URI):
    app = Flask(__name__)
    catalog = build_catalog_graph()

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
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Capacidad BuscarEnCatalogo — Plan: BuscarEnCatalogo → FiltrarProductos → MostrarProductos
            # Msg entrante: BuscarProductos (AsistenteVirtual → AgenteCatalogo)
            # Msg saliente: ResultadoBusqueda (AgenteCatalogo → AsistenteVirtual)
            if (action, RDF.type, ECSDI.BuscarProductos) in graph:
                return rdf_response(_handle_search(catalog, search_history, agent_uri, message.sender, action, graph))

            # Capacidad AñadirProductoExt — Plan: ActualizarCatalogo (pendiente de implementar)
            # Msg entrante: AnunciarProductoExterno (VendedorExterno → AgenteCatalogo)
            if (action, RDF.type, ECSDI.AnadirProductoExterno) in graph:
                return rdf_response(
                    build_not_understood(agent_uri, message.sender, "AnadirProductoExterno: pendiente de implementar")
                )

            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteCatalogo"))

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
) -> Graph:
    """Plan: BuscarEnCatalogo → FiltrarProductos → MostrarProductos (AgenteCatalogo / BuscarEnCatalogo).

    Extrae restricciones, filtra productos y registra la busqueda en el historial
    si el tipo de peticion es compra (futura HistorialBusquedasDB via SPARQL).
    Devuelve ResultadoBusqueda directamente al solicitante (AsistenteVirtual).
    """
    constraints = extract_search_constraints(graph, action)

    # Plan: FiltrarProductos — aplica restricciones sobre ProductosDB
    products = filter_products(catalog, constraints)

    # Plan: BuscarEnCatalogo — registra en historial si es busqueda de compra
    tipo = str(next(graph.objects(action, ECSDI.tipoBusqueda), "compra"))
    if tipo == "compra":
        search_history.append({
            "constraints": constraints,
            "results": [str(p) for p in products],
            "tipo": tipo,
        })
        log("catalogo", f"Busqueda registrada en historial: {constraints} -> {len(products)} productos")

    # Plan: MostrarProductos — devuelve productos al solicitante
    log("catalogo", f"Busqueda: {constraints} -> {len(products)} productos encontrados")
    return build_search_response(agent_uri, receiver, action, products, catalog)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9006)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_CATALOGO", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "AGENTE_CATALOGO", address, f"catalogo-{args.port}")
    try:
        log(f"catalogo-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app().run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"catalogo-{args.port}")


if __name__ == "__main__":
    main()