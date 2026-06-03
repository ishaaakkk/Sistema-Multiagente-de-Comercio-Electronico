"""El catálogo recarga valoracionMedia tras actualizar ProductosDB."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Literal
from rdflib.namespace import RDF

from agents import agente_catalogo
from tests.fixtures.catalog_fixtures import build_catalog_graph
from utilities.builders import build_search_message
from utilities.catalog import persist_catalog, product_uri, update_product_average_rating
from utilities.namespaces import AGENTS, ECSDI
from utilities.storage import DATA_DIR


class CatalogRatingReloadTests(unittest.TestCase):
    def setUp(self):
        self.catalog_path = DATA_DIR / "catalog.ttl"
        if self.catalog_path.exists():
            self.catalog_path.unlink()
        persist_catalog(build_catalog_graph())

    def test_search_returns_updated_rating_from_disk(self):
        update_product_average_rating("P-IPHONE19", "2.50")

        app = agente_catalogo.create_app(agent_uri=AGENTS.AgenteCatalogo, feedback_url=None)
        client = app.test_client()
        msg = build_search_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteCatalogo,
            constraints={"name": "iphone"},
        )
        action = next(msg.subjects(RDF.type, ECSDI.BuscarProductos))
        msg.add((action, ECSDI.tipoBusqueda, Literal("compra")))

        rv = client.post("/comm", data=msg.serialize(format="turtle"), content_type="text/turtle")
        self.assertEqual(rv.status_code, 200)

        from rdflib import Graph

        response = Graph().parse(data=rv.data, format="turtle")
        product = next(response.subjects(ECSDI.idProducto, Literal("P-IPHONE19")), None)
        if product is None:
            product = product_uri("P-IPHONE19")
        rating = next(response.objects(product, ECSDI.valoracionMedia), None)
        self.assertEqual(str(rating), "2.50")


if __name__ == "__main__":
    unittest.main()
