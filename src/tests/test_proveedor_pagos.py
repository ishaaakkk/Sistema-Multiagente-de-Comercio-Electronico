"""Tests del agente ProveedorPagos."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph
from rdflib.namespace import RDF

from agents.proveedor_pagos_agent import create_app
from utilities.acl import get_message
from utilities.builders import build_provider_payment_request
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces


class ProveedorPagosAgentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(agent_uri=AGENTS.ProveedorPagos)
        self.client = self.app.test_client()

    def _post_payment(self, card: str):
        operacion = DATA[f"pago/test/{card[-4:]}"]
        request = build_provider_payment_request(
            AGENTS.AgenteFinanciero,
            AGENTS.ProveedorPagos,
            DATA[f"action/cobro/test/{card[-4:]}"],
            operacion,
            ECSDI.CobroCliente,
            Decimal("10.00"),
            metodo_pago="tarjeta",
            tarjeta=card,
        )
        response = self.client.post(
            "/comm",
            data=request.serialize(format="turtle"),
            content_type="text/turtle",
        )
        graph = Graph()
        bind_namespaces(graph)
        graph.parse(data=response.get_data(as_text=True), format="turtle")
        return graph, get_message(graph)

    def test_accepts_valid_card(self):
        graph, msg = self._post_payment("4111111111111111")
        self.assertEqual(msg.performative, ACL.inform)
        self.assertTrue(any(graph.subjects(RDF.type, ECSDI.ConfirmacionTransaccion)))

    def test_accepts_arbitrary_card_number(self):
        graph, msg = self._post_payment("1234567890123456")
        self.assertEqual(msg.performative, ACL.inform)
        self.assertTrue(any(graph.subjects(RDF.type, ECSDI.ConfirmacionTransaccion)))


if __name__ == "__main__":
    unittest.main()
