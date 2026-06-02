"""Valoraciones actualizan valoracionMedia en ProductosDB."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib.namespace import RDF
from threading import Lock

from agents.agente_feedback import _handle_registrar_valoracion
from tests.fixtures.catalog_fixtures import build_catalog_graph
from utilities.builders import build_valoracion_request
from utilities.catalog import load_persisted_catalog, persist_catalog, product_uri
from utilities.namespaces import AGENTS, ECSDI
from utilities.storage import DATA_DIR


class ValoracionMediaTests(unittest.TestCase):
    def setUp(self):
        self.catalog_path = DATA_DIR / "catalog.ttl"
        if self.catalog_path.exists():
            self.catalog_path.unlink()

    def test_registrar_valoracion_updates_catalog_average(self):
        persist_catalog(build_catalog_graph())
        opinions_db = [
            {
                "pedido_id": "PED-TEST",
                "product_id": "P-IPHONE19",
                "product_uri": str(product_uri("P-IPHONE19")),
                "puntuacion": None,
                "comentario": None,
            }
        ]
        message = build_valoracion_request(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteFeedback,
            pedido_id="PED-TEST",
            product_id="P-IPHONE19",
            puntuacion=5,
            comentario="Excelente",
        )
        action = next(message.subjects(RDF.type, ECSDI.EnviarOpinion))
        lock = Lock()
        response = _handle_registrar_valoracion(
            opinions_db,
            lock,
            AGENTS.AgenteFeedback,
            AGENTS.AsistenteVirtual,
            action,
            message,
        )
        self.assertIsNotNone(next(response.subjects(RDF.type, ECSDI.Valoracion), None))
        catalog = load_persisted_catalog()
        product = product_uri("P-IPHONE19")
        self.assertEqual(str(next(catalog.objects(product, ECSDI.valoracionMedia))), "5.00")

        message2 = build_valoracion_request(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteFeedback,
            pedido_id="PED-TEST-2",
            product_id="P-IPHONE19",
            puntuacion=3,
            comentario="Regular",
        )
        opinions_db.append(
            {
                "pedido_id": "PED-TEST-2",
                "product_id": "P-IPHONE19",
                "product_uri": str(product_uri("P-IPHONE19")),
                "puntuacion": None,
                "comentario": None,
            }
        )
        action2 = next(message2.subjects(RDF.type, ECSDI.EnviarOpinion))
        _handle_registrar_valoracion(
            opinions_db,
            lock,
            AGENTS.AgenteFeedback,
            AGENTS.AsistenteVirtual,
            action2,
            message2,
        )
        catalog = load_persisted_catalog()
        self.assertEqual(str(next(catalog.objects(product, ECSDI.valoracionMedia))), "4.00")


if __name__ == "__main__":
    unittest.main()
