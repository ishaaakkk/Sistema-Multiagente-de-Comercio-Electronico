from decimal import Decimal

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .namespaces import DATA, ECSDI, bind_namespaces


def product_uri(product_id: str) -> URIRef:
    return DATA[f"producto/{product_id}"]


def center_uri(center_id: str) -> URIRef:
    return DATA[f"centro/{center_id}"]


def stock_uri(product_id: str, center_id: str) -> URIRef:
    return DATA[f"stock/{product_id}/{center_id}"]


PRODUCT_SEARCH_SPARQL = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX ecsdi: <http://www.semanticweb.org/ecsdi/comercio_electronico/>

SELECT DISTINCT ?product WHERE {
    {
        ?product rdf:type ecsdi:ProductoInterno .
    } UNION {
        ?product rdf:type ecsdi:ProductoExterno .
    }
    ?product ecsdi:nombreProducto ?name ;
             ecsdi:marcaProducto ?brand ;
             ecsdi:precioProducto ?price ;
             ecsdi:valoracionMedia ?rating .
    OPTIONAL { ?product ecsdi:descripcionProducto ?description }
    OPTIONAL { ?product ecsdi:idProducto ?pid }
    FILTER (
        (!BOUND(?name_filter)     || CONTAINS(LCASE(STR(?name)),       LCASE(STR(?name_filter)))) &&
        (!BOUND(?brand_filter)    || CONTAINS(LCASE(STR(?brand)),      LCASE(STR(?brand_filter)))) &&
        (!BOUND(?min_price)       || xsd:decimal(?price) >= xsd:decimal(?min_price)) &&
        (!BOUND(?max_price)       || xsd:decimal(?price) <= xsd:decimal(?max_price)) &&
        (!BOUND(?min_rating)      || xsd:decimal(?rating) >= xsd:decimal(?min_rating))
    )
}
ORDER BY ?product
"""


def filter_products(graph: Graph, constraints: dict) -> list[URIRef]:
    """Filtra productos del catálogo aplicando las restricciones recibidas.

    Implementado como SPARQL SELECT con FILTERs sobre nombre, marca, precio y
    valoración (cap. 6 de los apuntes). Mantiene la misma firma que la versión
    iterativa anterior para no romper a los llamantes.
    """

    init_bindings: dict = {}
    if constraints.get("name"):
        init_bindings["name_filter"] = Literal(str(constraints["name"]))
    if constraints.get("brand"):
        init_bindings["brand_filter"] = Literal(str(constraints["brand"]))
    if constraints.get("min_price") is not None:
        init_bindings["min_price"] = Literal(str(constraints["min_price"]), datatype=XSD.decimal)
    if constraints.get("max_price") is not None:
        init_bindings["max_price"] = Literal(str(constraints["max_price"]), datatype=XSD.decimal)
    if constraints.get("min_rating") is not None:
        init_bindings["min_rating"] = Literal(str(constraints["min_rating"]), datatype=XSD.decimal)

    matches: list[URIRef] = []
    seen: set = set()
    for row in graph.query(PRODUCT_SEARCH_SPARQL, initBindings=init_bindings):
        product = row.product
        if product in seen:
            continue
        seen.add(product)
        matches.append(product)
    return matches


def extract_search_constraints(graph: Graph, action: URIRef) -> dict:
    constraints = {}
    for restriction in graph.objects(action, ECSDI.accionTieneRestriccion):
        if (restriction, RDF.type, ECSDI.RestriccionNombre) in graph:
            constraints["name"] = _str_value(graph, restriction, ECSDI.valorTextoRestriccion)
        if (restriction, RDF.type, ECSDI.RestriccionMarca) in graph:
            constraints["brand"] = _str_value(graph, restriction, ECSDI.valorTextoRestriccion)
        if (restriction, RDF.type, ECSDI.RestriccionPrecio) in graph:
            constraints["min_price"] = _decimal_value(graph, restriction, ECSDI.precioMinimo)
            constraints["max_price"] = _decimal_value(graph, restriction, ECSDI.precioMaximo)
        if (restriction, RDF.type, ECSDI.RestriccionValoracion) in graph:
            constraints["min_rating"] = _decimal_value(graph, restriction, ECSDI.valoracionMinima)
    return {key: value for key, value in constraints.items() if value is not None}


def describe_product(graph: Graph, product: URIRef) -> dict:
    return {
        "uri": product,
        "id": _str_value(graph, product, ECSDI.idProducto),
        "name": _str_value(graph, product, ECSDI.nombreProducto),
        "brand": _str_value(graph, product, ECSDI.marcaProducto),
        "description": _str_value(graph, product, ECSDI.descripcionProducto),
        "price": _decimal_value(graph, product, ECSDI.precioProducto) or Decimal("0"),
        "rating": _decimal_value(graph, product, ECSDI.valoracionMedia) or Decimal("0"),
        "weight": _decimal_value(graph, product, ECSDI.pesoProducto) or Decimal("0"),
    }


def copy_product(graph: Graph, target: Graph, product: URIRef) -> None:
    for triple in graph.triples((product, None, None)):
        target.add(triple)


def copy_center(graph: Graph, target: Graph, center: URIRef) -> None:
    for triple in graph.triples((center, None, None)):
        target.add(triple)


def choose_single_center(graph: Graph, product_quantities: dict[str, int], destination_city: str) -> URIRef | None:
    candidate_sets = []
    for product_id, quantity in product_quantities.items():
        product = product_uri(product_id)
        centers = set()
        for stock in graph.subjects(ECSDI.stockDeProducto, product):
            available = _int_value(graph, stock, ECSDI.cantidadDisponible) or 0
            if available >= quantity:
                center = next(graph.objects(stock, ECSDI.stockEnCentro), None)
                if center is not None:
                    centers.add(center)
        candidate_sets.append(centers)

    if not candidate_sets:
        return None

    candidates = set.intersection(*candidate_sets)
    if not candidates:
        return None

    normalized_city = destination_city.casefold()
    for center in sorted(candidates, key=str):
        city = _str_value(graph, center, ECSDI.ciudadCentroLogistico) or ""
        if city.casefold() == normalized_city:
            return center
    return sorted(candidates, key=str)[0]


def reserve_stock(graph: Graph, center: URIRef, product_quantities: dict[str, int]) -> None:
    for product_id, quantity in product_quantities.items():
        product = product_uri(product_id)
        for stock in graph.subjects(ECSDI.stockDeProducto, product):
            if (stock, ECSDI.stockEnCentro, center) not in graph:
                continue
            available = _int_value(graph, stock, ECSDI.cantidadDisponible) or 0
            graph.set((stock, ECSDI.cantidadDisponible, Literal(available - quantity, datatype=XSD.integer)))


def order_total(graph: Graph, product_quantities: dict[str, int]) -> Decimal:
    total = Decimal("0")
    for product_id, quantity in product_quantities.items():
        total += describe_product(graph, product_uri(product_id))["price"] * quantity
    return total


def order_weight(graph: Graph, product_quantities: dict[str, int]) -> Decimal:
    total = Decimal("0")
    for product_id, quantity in product_quantities.items():
        total += describe_product(graph, product_uri(product_id))["weight"] * quantity
    return total


def decimal_literal(value: Decimal | str | int | float) -> Literal:
    return Literal(str(value), datatype=XSD.decimal)


def _str_value(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = next(graph.objects(subject, predicate), None)
    return str(value) if value is not None else None


def _decimal_value(graph: Graph, subject: URIRef, predicate: URIRef) -> Decimal | None:
    value = next(graph.objects(subject, predicate), None)
    return Decimal(str(value)) if value is not None else None


def _int_value(graph: Graph, subject: URIRef, predicate: URIRef) -> int | None:
    value = next(graph.objects(subject, predicate), None)
    return int(value) if value is not None else None