"""Tests del recomendador de AgenteFeedback."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib.namespace import RDF

from agents.agente_feedback import _build_recommendation_graph
from utilities.catalog import product_uri
from utilities.namespaces import AGENTS, ECSDI


class FeedbackRecommendationTests(unittest.TestCase):
    def test_neutral_fallback_recommends_catalog_candidate_with_metadata(self):
        asistente = str(AGENTS.AsistenteVirtual)
        opinions = [
            {
                "pedido_id": "PED-1",
                "product_id": "P-IPHONE19",
                "product_uri": str(product_uri("P-IPHONE19")),
                "brand": "Apple",
                "asistente": asistente,
                "puntuacion": 5,
            }
        ]
        searches = [
            {
                "asistente": asistente,
                "brand": None,
                "results": [str(product_uri("P-IPHONE19"))],
                "catalog_details": [
                    {
                        "id": "P-IPHONE19",
                        "uri": str(product_uri("P-IPHONE19")),
                        "name": "iPhone 19",
                        "brand": "Apple",
                        "price": "1199.00",
                        "rating": "4.75",
                    },
                    {
                        "id": "P-EBOOK-AURORA",
                        "uri": str(product_uri("P-EBOOK-AURORA")),
                        "name": "Ebook Reader Aurora",
                        "brand": "Readly",
                        "price": "149.90",
                        "rating": "4.40",
                    },
                ],
            }
        ]

        _, graph = _build_recommendation_graph(
            opinions,
            searches,
            asistente,
            AGENTS.AgenteFeedback,
            AGENTS.AsistenteVirtual,
            action_uri=None,
            top_n=3,
        )

        rec = next(graph.subjects(RDF.type, ECSDI.Recomendacion), None)
        self.assertIsNotNone(rec)
        product = next(graph.objects(rec, ECSDI.recomendacionDeProducto))
        self.assertEqual(str(next(graph.objects(product, ECSDI.idProducto))), "P-EBOOK-AURORA")
        self.assertEqual(str(next(graph.objects(product, ECSDI.nombreProducto))), "Ebook Reader Aurora")
        self.assertEqual(str(next(graph.objects(product, ECSDI.precioProducto))), "149.90")


if __name__ == "__main__":
    unittest.main()
