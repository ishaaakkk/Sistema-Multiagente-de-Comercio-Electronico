"""Tests del Agente Asistente."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.agente_asistente import _acl_failure_payload, create_app
from utilities.acl import ACL, build_failure, get_message
from utilities.namespaces import AGENTS, ECSDI, bind_namespaces


class AsistenteFailurePayloadTests(unittest.TestCase):
    def test_extracts_acl_failure_reason_for_json_api(self):
        graph = build_failure(
            AGENTS.AgenteComerciante,
            AGENTS.AsistenteVirtual,
            None,
            "pedido incompleto",
        )

        self.assertEqual(
            _acl_failure_payload(graph, "fallback"),
            {"error": "pedido incompleto"},
        )


class AsistenteSearchApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            agent_uri=AGENTS.AsistenteVirtual,
            catalog_url="http://catalog.test/comm",
        )
        self.client = self.app.test_client()

    def _catalog_search_response(self) -> Graph:
        graph = Graph()
        bind_namespaces(graph)

        action = URIRef("http://test/action/resultado")
        graph.add((action, RDF.type, ECSDI.ResultadoBusqueda))

        p1 = URIRef("http://test/product/P-1")
        p2 = URIRef("http://test/product/P-2")
        graph.add((action, ECSDI.resultadoContieneProducto, p1))
        graph.add((action, ECSDI.resultadoContieneProducto, p2))

        graph.add((p1, RDF.type, ECSDI.ProductoInterno))
        graph.add((p1, ECSDI.idProducto, Literal("P-1")))
        graph.add((p1, ECSDI.nombreProducto, Literal("iPhone 19")))
        graph.add((p1, ECSDI.marcaProducto, Literal("Apple")))
        graph.add((p1, ECSDI.precioProducto, Literal("999.00", datatype=XSD.decimal)))
        graph.add((p1, ECSDI.valoracionMedia, Literal("4.5", datatype=XSD.decimal)))

        graph.add((p2, RDF.type, ECSDI.ProductoInterno))
        graph.add((p2, ECSDI.idProducto, Literal("P-2")))
        graph.add((p2, ECSDI.nombreProducto, Literal("Galaxy Ultra")))
        graph.add((p2, ECSDI.marcaProducto, Literal("Samsung")))
        graph.add((p2, ECSDI.precioProducto, Literal("899.00", datatype=XSD.decimal)))
        graph.add((p2, ECSDI.valoracionMedia, Literal("4.0", datatype=XSD.decimal)))
        return graph

    def test_search_without_constraints_returns_products(self):
        with patch("agents.agente_asistente.post_graph", return_value=self._catalog_search_response()):
            response = self.client.get("/search")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertIn("products", payload)
        self.assertEqual(len(payload["products"]), 2)
        self.assertFalse(payload.get("error"))

    def test_search_passes_all_restrictions_coherently(self):
        captured_constraints = {}

        def fake_post_graph(_url: str, message: Graph):
            msg = get_message(message)
            action = msg.content
            parsed = {}
            for restriction in message.objects(action, ECSDI.accionTieneRestriccion):
                if (restriction, RDF.type, ECSDI.RestriccionNombre) in message:
                    parsed["name"] = str(next(message.objects(restriction, ECSDI.valorTextoRestriccion), ""))
                if (restriction, RDF.type, ECSDI.RestriccionMarca) in message:
                    parsed["brand"] = str(next(message.objects(restriction, ECSDI.valorTextoRestriccion), ""))
                if (restriction, RDF.type, ECSDI.RestriccionPrecio) in message:
                    parsed["min_price"] = str(next(message.objects(restriction, ECSDI.precioMinimo), ""))
                    parsed["max_price"] = str(next(message.objects(restriction, ECSDI.precioMaximo), ""))
                if (restriction, RDF.type, ECSDI.RestriccionValoracion) in message:
                    parsed["min_rating"] = str(next(message.objects(restriction, ECSDI.valoracionMinima), ""))
            captured_constraints.update(parsed)
            return self._catalog_search_response()

        with patch("agents.agente_asistente.post_graph", side_effect=fake_post_graph):
            response = self.client.get(
                "/search?name=iphone&brand=apple&min_price=100&max_price=1200&min_rating=4.1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            captured_constraints,
            {
                "name": "iphone",
                "brand": "apple",
                "min_price": "100",
                "max_price": "1200",
                "min_rating": "4.1",
            },
        )


if __name__ == "__main__":
    unittest.main()
