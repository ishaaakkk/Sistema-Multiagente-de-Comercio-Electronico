"""Tests para el filtrado SPARQL de productos del catálogo."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decimal import Decimal

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import get_message
from utilities.builders import build_external_product_registration
from utilities.catalog import filter_products
from utilities.namespaces import ACL, AGENTS, ECSDI, bind_namespaces


def _add_product(graph, uri, *, name, brand, price, rating, is_internal=True):
    graph.add((uri, RDF.type, ECSDI.ProductoInterno if is_internal else ECSDI.ProductoExterno))
    graph.add((uri, ECSDI.nombreProducto, Literal(name)))
    graph.add((uri, ECSDI.marcaProducto, Literal(brand)))
    graph.add((uri, ECSDI.precioProducto, Literal(str(price), datatype=XSD.decimal)))
    graph.add((uri, ECSDI.valoracionMedia, Literal(str(rating), datatype=XSD.decimal)))


class FilterProductsTests(unittest.TestCase):
    def setUp(self):
        self.graph = Graph()
        bind_namespaces(self.graph)
        self.p1 = URIRef("http://test/p/p1")
        self.p2 = URIRef("http://test/p/p2")
        self.p3 = URIRef("http://test/p/p3")
        _add_product(self.graph, self.p1, name="iPhone 19", brand="Apple", price=Decimal("999"), rating=Decimal("4.5"))
        _add_product(self.graph, self.p2, name="Galaxy Ultra", brand="Samsung", price=Decimal("899"), rating=Decimal("4.0"))
        _add_product(self.graph, self.p3, name="Libro Rust", brand="O'Reilly", price=Decimal("35"), rating=Decimal("4.8"), is_internal=False)

    def test_no_constraints_returns_all(self):
        result = set(filter_products(self.graph, {}))
        self.assertEqual(result, {self.p1, self.p2, self.p3})

    def test_filter_by_name(self):
        result = filter_products(self.graph, {"name": "iphone"})
        self.assertEqual(result, [self.p1])

    def test_filter_by_brand(self):
        result = filter_products(self.graph, {"brand": "Samsung"})
        self.assertEqual(result, [self.p2])

    def test_filter_by_price_range(self):
        result = set(filter_products(self.graph, {"min_price": 100, "max_price": 950}))
        self.assertEqual(result, {self.p2})

    def test_filter_by_min_rating(self):
        result = set(filter_products(self.graph, {"min_rating": 4.6}))
        self.assertEqual(result, {self.p3})


class ExternalProductRegistrationBuilderTests(unittest.TestCase):
    def test_builds_dar_alta_producto_externo_message(self):
        graph = build_external_product_registration(
            AGENTS.AgenteVendedorExterno,
            AGENTS.AgenteCatalogo,
            [
                {
                    "id": "P-EXT-1",
                    "nombre": "Producto externo",
                    "marca": "Marca",
                    "precio": "12.50",
                    "valoracion": "4.1",
                    "peso": "0.3",
                    "gestion_envio_externo": True,
                }
            ],
        )

        message = get_message(graph)
        self.assertEqual(message.performative, ACL.request)
        self.assertIn((message.content, RDF.type, ECSDI.DarAltaProductoExterno), graph)
        product = next(graph.subjects(ECSDI.idProducto, Literal("P-EXT-1")), None)
        self.assertIsNotNone(product)
        self.assertIn((product, RDF.type, ECSDI.ProductoExterno), graph)


if __name__ == "__main__":
    unittest.main()
