"""Stock unificado: todos los CL ofrecen los mismos productos logísticos."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Literal
from rdflib.namespace import RDF

from agents.agente_catalogo import _handle_external_product_registration
from agents.centro_logistico_agent import _resolve_stock_scope, STOCK_MODE_ALL
from tests.fixtures.catalog_fixtures import build_catalog_graph
from utilities.builders import build_external_product_registration
from utilities.catalog import (
    load_persisted_catalog,
    persist_catalog,
    product_ids_for_logistics,
    product_ids_with_stock_at_center,
    product_uri,
    provision_store_managed_external_product,
    stock_uri,
    sync_stock_all_centers,
)
from utilities.namespaces import AGENTS, ECSDI
from utilities.storage import DATA_DIR


class ClStockFromCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog_path = DATA_DIR / "catalog.ttl"
        if self.catalog_path.exists():
            self.catalog_path.unlink()

    def test_sync_stock_all_centers(self):
        catalog = build_catalog_graph()
        sync_stock_all_centers(catalog)
        bcn = product_ids_with_stock_at_center(catalog, "CL-BCN")
        mad = product_ids_with_stock_at_center(catalog, "CL-MAD")
        logistics = product_ids_for_logistics(catalog)
        self.assertEqual(bcn, logistics)
        self.assertEqual(mad, logistics)
        self.assertIn("P-BATIDORA-MINI", bcn)
        self.assertIn("P-IPHONE19", mad)

    def test_resolve_stock_scope_default_is_all_products(self):
        persist_catalog(build_catalog_graph())
        sync_stock_all_centers(load_persisted_catalog())
        accepts_all, stock_set = _resolve_stock_scope("CL-BCN", STOCK_MODE_ALL)
        self.assertTrue(accepts_all)
        self.assertEqual(stock_set, set())

    def test_external_alta_adds_stock_at_all_centers(self):
        persist_catalog(build_catalog_graph())
        sync_stock_all_centers(load_persisted_catalog())
        products = [
            {
                "id": "P-NUEVO-EXT",
                "nombre": "Producto nuevo externo",
                "marca": "Voltix",
                "precio": "19.90",
                "valoracion": "4.0",
                "peso": "0.5",
                "gestion_envio_externo": False,
            }
        ]
        message = build_external_product_registration(
            AGENTS.AgenteVendedorExterno,
            AGENTS.AgenteCatalogo,
            products,
        )
        action = next(message.subjects(RDF.type, ECSDI.DarAltaProductoExterno))
        _handle_external_product_registration(
            AGENTS.AgenteCatalogo,
            AGENTS.AgenteVendedorExterno,
            action,
            message,
        )
        catalog = load_persisted_catalog()
        self.assertIsNotNone(next(catalog.subjects(ECSDI.idProducto, Literal("P-NUEVO-EXT")), None))
        self.assertIsNotNone(
            next(catalog.triples((stock_uri("P-NUEVO-EXT", "CL-BCN"), ECSDI.cantidadDisponible, None)), None)
        )
        self.assertIsNotNone(
            next(catalog.triples((stock_uri("P-NUEVO-EXT", "CL-MAD"), ECSDI.cantidadDisponible, None)), None)
        )

    def test_provision_skips_external_shipping_products(self):
        catalog = build_catalog_graph()
        centers = provision_store_managed_external_product(catalog, "P-SMARTWATCH-X")
        self.assertEqual(centers, [])
        self.assertEqual(
            len(list(catalog.triples((stock_uri("P-SMARTWATCH-X", "CL-BCN"), None, None)))),
            0,
        )


if __name__ == "__main__":
    unittest.main()
