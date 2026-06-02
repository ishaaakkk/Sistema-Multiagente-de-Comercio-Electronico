from decimal import Decimal

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .namespaces import DATA, ECSDI, bind_namespaces
from .storage import load_graph, load_named_graph, save_graph, save_graph_item, save_named_graph


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


def persist_catalog(graph: Graph) -> None:
    """ProductosDB: serializa el catálogo en Turtle y en el Dataset común (TriG)."""

    save_graph("catalog.ttl", graph)
    save_named_graph("catalog", graph)


def load_persisted_catalog() -> Graph:
    """Devuelve el catálogo persistido o un grafo vacío si aún no existe."""

    graph = load_graph("catalog.ttl")
    if len(graph) > 0:
        return graph
    return load_named_graph("catalog")


def stock_graph_name(center_id: str) -> str:
    return f"stock/{center_id}"


def build_stock_graph(catalog: Graph, center_id: str) -> Graph:
    """StockProductosDB: vista RDF del stock de un centro dentro del catálogo."""

    graph = Graph()
    bind_namespaces(graph)
    center = center_uri(center_id)
    for stock in catalog.subjects(ECSDI.stockEnCentro, center):
        for triple in catalog.triples((stock, None, None)):
            graph.add(triple)
        product = next(catalog.objects(stock, ECSDI.stockDeProducto), None)
        if product is not None:
            copy_product(catalog, graph, product)
    copy_center(catalog, graph, center)
    return graph


def persist_stock_graph(center_id: str, graph: Graph) -> None:
    save_named_graph(stock_graph_name(center_id), graph)


def load_stock_graph(center_id: str) -> Graph:
    """Carga el grafo de stock del centro; si no existe, lo materializa desde ProductosDB."""

    stock = load_named_graph(stock_graph_name(center_id))
    if len(stock) > 0:
        return stock
    catalog = load_persisted_catalog()
    if len(catalog) == 0:
        return stock
    stock = build_stock_graph(catalog, center_id)
    persist_stock_graph(center_id, stock)
    return stock


def decrement_catalog_stock(center_id: str, product_quantities: dict[str, int]) -> None:
    """Descuenta unidades en ProductosDB y actualiza el grafo nombrado stock/<CL>."""

    if not product_quantities:
        return
    catalog = load_persisted_catalog()
    if len(catalog) == 0:
        return
    reserve_stock(catalog, center_uri(center_id), product_quantities)
    persist_catalog(catalog)
    persist_stock_graph(center_id, build_stock_graph(catalog, center_id))


def average_rating_from_opinions(opinions_db: list[dict], product_id: str) -> float | None:
    """Media aritmética de las puntuaciones registradas para un producto."""

    ratings = [
        int(record["puntuacion"])
        for record in opinions_db
        if record.get("product_id") == product_id and record.get("puntuacion") is not None
    ]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def stamp_operating_center(graph: Graph, center: URIRef, center_id: str, center_city: str) -> None:
    """Alinea el nodo centro del lote con el CL que opera (no solo ProductosDB)."""

    graph.set((center, ECSDI.idCentroLogistico, Literal(center_id)))
    graph.set((center, ECSDI.ciudadCentroLogistico, Literal(center_city)))
    graph.set((center, ECSDI.nombreCentroLogistico, Literal(f"Centro Logístico {center_city}")))


def catalog_center_profile(catalog: Graph, center_id: str) -> tuple[str, str]:
    """Ciudad y nombre del centro en ProductosDB (si existe)."""

    center = center_uri(center_id)
    if (center, None, None) not in catalog:
        return "", ""
    return (
        _str_value(catalog, center, ECSDI.ciudadCentroLogistico) or "",
        _str_value(catalog, center, ECSDI.nombreCentroLogistico) or "",
    )


def format_centro_label(centro_id: str, ciudad: str, nombre: str = "") -> str:
    """Etiqueta legible para tiquets/UI."""

    nombre = (nombre or "").strip()
    centro_id = (centro_id or "").strip()
    ciudad = (ciudad or "").strip()
    if nombre and centro_id and centro_id not in nombre:
        return f"{nombre} ({centro_id})"
    if nombre:
        return nombre
    if centro_id and ciudad:
        return f"{centro_id} · {ciudad}"
    return centro_id or ciudad or "—"


def list_center_ids(catalog: Graph) -> list[str]:
    """Identificadores de centros logísticos definidos en ProductosDB."""

    ids: list[str] = []
    for center in catalog.subjects(RDF.type, ECSDI.CentroLogistico):
        center_id = _str_value(catalog, center, ECSDI.idCentroLogistico)
        if center_id:
            ids.append(center_id)
    return sorted(set(ids))


def is_product_shipped_by_logistics(catalog: Graph, product: URIRef) -> bool:
    """True si el producto puede prepararse en un centro logístico de la tienda."""

    if (product, RDF.type, ECSDI.ProductoInterno) in catalog:
        return True
    if (product, RDF.type, ECSDI.ProductoExterno) not in catalog:
        return False
    gestion = next(catalog.objects(product, ECSDI.gestionEnvioExterno), Literal(False))
    return str(gestion).lower() not in ("true", "1")


def product_ids_for_logistics(catalog: Graph) -> set[str]:
    """Identificadores de productos que los centros logísticos pueden servir."""

    product_ids: set[str] = set()
    for product in catalog.subjects(RDF.type, ECSDI.Producto):
        if not is_product_shipped_by_logistics(catalog, product):
            continue
        product_id = _str_value(catalog, product, ECSDI.idProducto)
        if product_id:
            product_ids.add(product_id)
    return product_ids


def product_ids_with_stock_at_center(
    catalog: Graph,
    center_id: str,
    *,
    min_quantity: int = 1,
) -> set[str]:
    """Productos con unidades disponibles en un centro (StockProductosDB)."""

    center = center_uri(center_id)
    product_ids: set[str] = set()
    for stock in catalog.subjects(ECSDI.stockEnCentro, center):
        available = _int_value(catalog, stock, ECSDI.cantidadDisponible) or 0
        if available < min_quantity:
            continue
        product = next(catalog.objects(stock, ECSDI.stockDeProducto), None)
        if product is None:
            continue
        product_id = _str_value(catalog, product, ECSDI.idProducto)
        if product_id:
            product_ids.add(product_id)
    return product_ids


def sync_stock_all_centers(catalog: Graph, default_quantity: int = 15) -> list[str]:
    """Replica stock de cada producto logístico en todos los centros del catálogo."""

    center_ids = list_center_ids(catalog)
    if not center_ids:
        return []
    updated: list[str] = []
    for product_id in sorted(product_ids_for_logistics(catalog)):
        for center_id in center_ids:
            ensure_stock_at_center(catalog, product_id, center_id, default_quantity)
        updated.append(product_id)
    return updated


def ensure_stock_at_center(
    catalog: Graph,
    product_id: str,
    center_id: str,
    quantity: int,
) -> bool:
    """Crea o actualiza el stock de un producto en un centro."""

    if quantity < 0:
        return False
    product = product_uri(product_id)
    if (product, None, None) not in catalog:
        return False
    stock = stock_uri(product_id, center_id)
    center = center_uri(center_id)
    if (stock, None, None) not in catalog:
        catalog.add((stock, RDF.type, ECSDI.StockProducto))
        catalog.add((stock, ECSDI.stockDeProducto, product))
        catalog.add((stock, ECSDI.stockEnCentro, center))
        catalog.add((stock, ECSDI.cantidadDisponible, Literal(quantity, datatype=XSD.integer)))
        return True
    current = _int_value(catalog, stock, ECSDI.cantidadDisponible) or 0
    if current < quantity:
        catalog.set((stock, ECSDI.cantidadDisponible, Literal(quantity, datatype=XSD.integer)))
    return True


def provision_store_managed_external_product(
    catalog: Graph,
    product_id: str,
    *,
    quantity_per_center: int = 12,
    center_ids: list[str] | None = None,
) -> list[str]:
    """Añade stock en centros para externos que envía la tienda (`gestionEnvioExterno` false)."""

    product = product_uri(product_id)
    if not is_product_shipped_by_logistics(catalog, product):
        return []
    updated: list[str] = []
    for center_id in center_ids or list_center_ids(catalog):
        if ensure_stock_at_center(catalog, product_id, center_id, quantity_per_center):
            updated.append(center_id)
    return updated


def update_product_average_rating(product_id: str, rating: Decimal | str | int | float) -> bool:
    """Actualiza `valoracionMedia` de un producto en ProductosDB."""

    catalog = load_persisted_catalog()
    if len(catalog) == 0:
        return False
    product = product_uri(product_id)
    if (product, None, None) not in catalog:
        return False
    catalog.set((product, ECSDI.valoracionMedia, decimal_literal(Decimal(str(rating)))))
    persist_catalog(catalog)
    for stock in catalog.subjects(ECSDI.stockDeProducto, product):
        center = next(catalog.objects(stock, ECSDI.stockEnCentro), None)
        if center is None:
            continue
        center_id = _str_value(catalog, center, ECSDI.idCentroLogistico)
        if center_id:
            persist_stock_graph(center_id, build_stock_graph(catalog, center_id))
    return True


def persist_lote(lote_graph: Graph, lote: URIRef) -> None:
    """LotesEnviosDB: persiste un lote de envío en fichero TTL y en el Dataset común."""

    lote_id = _str_value(lote_graph, lote, ECSDI.idLote) or str(lote).rsplit("/", 1)[-1]
    save_graph_item("lotes", lote_id, lote_graph)
    save_named_graph(f"lotes/{lote_id}", lote_graph)


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
