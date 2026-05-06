from decimal import Decimal

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .namespaces import DATA, ECSDI, bind_namespaces


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


def product_uri(product_id: str) -> URIRef:
    return DATA[f"producto/{product_id}"]


def center_uri(center_id: str) -> URIRef:
    return DATA[f"centro/{center_id}"]


def stock_uri(product_id: str, center_id: str) -> URIRef:
    return DATA[f"stock/{product_id}/{center_id}"]


def build_catalog_graph() -> Graph:
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


def filter_products(graph: Graph, constraints: dict) -> list[URIRef]:
    matches = []
    for product in graph.subjects(RDF.type, ECSDI.ProductoInterno):
        data = describe_product(graph, product)
        if _matches(data, constraints):
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


def _matches(product: dict, constraints: dict) -> bool:
    text = f"{product['name']} {product['description']} {product['id']}".casefold()
    if constraints.get("name") and constraints["name"].casefold() not in text:
        return False
    if constraints.get("brand") and constraints["brand"].casefold() not in product["brand"].casefold():
        return False
    if constraints.get("min_price") is not None and product["price"] < constraints["min_price"]:
        return False
    if constraints.get("max_price") is not None and product["price"] > constraints["max_price"]:
        return False
    if constraints.get("min_rating") is not None and product["rating"] < constraints["min_rating"]:
        return False
    return True


def _str_value(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = next(graph.objects(subject, predicate), None)
    return str(value) if value is not None else None


def _decimal_value(graph: Graph, subject: URIRef, predicate: URIRef) -> Decimal | None:
    value = next(graph.objects(subject, predicate), None)
    return Decimal(str(value)) if value is not None else None


def _int_value(graph: Graph, subject: URIRef, predicate: URIRef) -> int | None:
    value = next(graph.objects(subject, predicate), None)
    return int(value) if value is not None else None
