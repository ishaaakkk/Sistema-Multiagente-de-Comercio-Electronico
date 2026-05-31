"""Tests de persistencia ProductosDB y stock por centro."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF, XSD

from agents.agente_catalogo import build_catalog_graph, load_catalog_graph
from utilities.catalog import (
    build_stock_graph,
    decrement_catalog_stock,
    load_persisted_catalog,
    persist_catalog,
    stock_uri,
)
from utilities.namespaces import ECSDI, bind_namespaces
from utilities.storage import DATA_DIR, load_graph, load_named_graph


class CatalogPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog_path = DATA_DIR / "catalog.ttl"
        if self.catalog_path.exists():
            self.catalog_path.unlink()
        dataset = DATA_DIR / "dataset.trig"
        if dataset.exists():
            text = dataset.read_text(encoding="utf-8")
            if "graph/catalog" in text or "graph/stock/" in text:
                dataset.unlink()

    def test_load_catalog_graph_creates_catalog_ttl(self):
        catalog = load_catalog_graph()
        self.assertGreater(len(catalog), 0)
        self.assertTrue(self.catalog_path.exists())
        self.assertGreater(len(load_named_graph("catalog")), 0)

    def test_load_catalog_graph_reuses_existing_file(self):
        seed = build_catalog_graph()
        persist_catalog(seed)
        loaded = load_catalog_graph()
        self.assertEqual(len(loaded), len(seed))

    def test_decrement_catalog_stock_updates_productos_db(self):
        persist_catalog(build_catalog_graph())
        decrement_catalog_stock("CL-BCN", {"P-IPHONE19": 2})
        catalog = load_persisted_catalog()
        stock = stock_uri("P-IPHONE19", "CL-BCN")
        available = int(next(catalog.objects(stock, ECSDI.cantidadDisponible)))
        self.assertEqual(available, 23)

        stock_graph = load_named_graph("stock/CL-BCN")
        self.assertGreater(len(stock_graph), 0)
        self.assertEqual(
            int(next(stock_graph.objects(stock, ECSDI.cantidadDisponible))),
            23,
        )


class StockGraphTests(unittest.TestCase):
    def test_build_stock_graph_contains_center_stock(self):
        catalog = build_catalog_graph()
        stock_graph = build_stock_graph(catalog, "CL-MAD")
        self.assertGreater(len(stock_graph), 0)
        self.assertTrue(
            any(stock_graph.triples((None, RDF.type, ECSDI.StockProducto)))
        )


if __name__ == "__main__":
    unittest.main()
