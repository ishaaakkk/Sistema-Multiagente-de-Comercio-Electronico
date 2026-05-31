"""Grafo de catálogo de demo solo para tests (no usado en runtime)."""

from decimal import Decimal

from rdflib import Graph, Literal
from rdflib.namespace import RDF, XSD

from utilities.catalog import center_uri, decimal_literal, product_uri, stock_uri
from utilities.namespaces import AGENTS, ECSDI, bind_namespaces

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
        "id": "P-MACBOOK-AIR",
        "name": "MacBook Air M4",
        "brand": "Apple",
        "description": "Portatil ligero Apple",
        "price": Decimal("1299.00"),
        "rating": Decimal("4.80"),
        "weight": Decimal("1.10"),
        "center": "CL-BCN",
        "stock": 10,
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
    {"id": "VEND-TECHWORLD", "name": "TechWorld SL", "uri": "VEND-TECHWORLD"},
    {"id": "VEND-HOMEGADGETS", "name": "HomeGadgets Europe", "uri": "VEND-HOMEGADGETS"},
]

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
        "shipping_external": True,
    },
    {
        "id": "P-AIRPODS-PRO",
        "name": "AirPods Pro 3",
        "brand": "Apple",
        "description": "Auriculares Apple",
        "price": Decimal("249.00"),
        "rating": Decimal("4.60"),
        "weight": Decimal("0.05"),
        "vendor": "VEND-TECHWORLD",
        "shipping_external": False,
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
        "shipping_external": False,
    },
]

LOGISTIC_CENTERS = [
    {"id": "CL-BCN", "name": "Centro Logistico Barcelona", "city": "Barcelona"},
    {"id": "CL-MAD", "name": "Centro Logistico Madrid", "city": "Madrid"},
]


def build_catalog_graph() -> Graph:
    """Construye un grafo RDF de demo para tests unitarios."""

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
