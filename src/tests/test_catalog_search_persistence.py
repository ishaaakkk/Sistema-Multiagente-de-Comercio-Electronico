"""Tests de persistencia del historial de búsquedas del catálogo."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF

from utilities.builders import build_search_message
from utilities.namespaces import AGENTS, ECSDI, bind_namespaces


class CatalogSearchPersistenceTests(unittest.TestCase):
    def test_catalog_search_history_is_saved_to_json(self):
        """Ejecuta una búsqueda 'compra' y verifica que se persiste el JSON.

        Nota: este test necesita Flask test_client; no arranca servidor real.
        """
        data_dir = Path(__file__).resolve().parents[1] / "data"
        path = data_dir / "catalog_searches.json"
        if path.exists():
            path.unlink()

        from agents import agente_catalogo

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
        self.assertTrue(path.exists())

    def test_catalog_search_with_max_price_decimal(self):
        """Búsqueda con max_price Decimal no debe fallar al persistir historial."""
        data_dir = Path(__file__).resolve().parents[1] / "data"
        path = data_dir / "catalog_searches.json"
        if path.exists():
            path.unlink()

        from agents import agente_catalogo

        app = agente_catalogo.create_app(agent_uri=AGENTS.AgenteCatalogo, feedback_url=None)
        client = app.test_client()

        msg = build_search_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteCatalogo,
            constraints={"name": "iphone", "max_price": Decimal("1300")},
        )
        action = next(msg.subjects(RDF.type, ECSDI.BuscarProductos))
        msg.add((action, ECSDI.tipoBusqueda, Literal("compra")))

        rv = client.post("/comm", data=msg.serialize(format="turtle"), content_type="text/turtle")
        self.assertEqual(rv.status_code, 200)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()

