"""Tests de mensajería interna mock en devoluciones (sin transportistas)."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib.namespace import RDF

from agents.agente_devolucion import (
    RETURN_WINDOW_DAYS,
    _motivo_expectations,
    _reception_date_for_policy,
    _return_allowed,
    _return_already_accepted,
    _simulate_mensajeria_interna,
)
from rdflib import Graph, Literal
from rdflib.namespace import XSD
from utilities.namespaces import AGENTS, DATA, ECSDI


class DevolucionMensajeriaTests(unittest.TestCase):
    def test_simulate_mensajeria_interna_confirms_pickup(self):
        devolucion = DATA["devolucion/TEST-001"]
        pedido = DATA["pedido/P-TEST"]
        product = DATA["producto/P-IPHONE19"]

        graph = _simulate_mensajeria_interna(devolucion, pedido, product, pickup_days=2)

        self.assertIn((devolucion, RDF.type, ECSDI.Devolucion), graph)
        pickup = next(graph.objects(devolucion, ECSDI.fechaRecogidaDevolucion), None)
        self.assertIsNotNone(pickup)
        parsed = datetime.fromisoformat(str(pickup))
        self.assertGreater(parsed, datetime.now() + timedelta(days=1))

        envio = next(graph.subjects(RDF.type, ECSDI.EnvioDevolucion), None)
        self.assertIsNotNone(envio)
        self.assertEqual(next(graph.objects(envio, ECSDI.envioRealizadoPor)), AGENTS.MensajeriaInterna)

    def test_reason_expectations_requires_delivery_date(self):
        self.assertFalse(_return_allowed("No satisface expectativas", None))

    def test_reason_expectations_within_fifteen_days(self):
        in_window = datetime.now() - timedelta(days=10)
        self.assertTrue(_return_allowed("No satisface expectativas", in_window))

    def test_reason_expectations_outside_fifteen_days(self):
        out_of_window = datetime.now() - timedelta(days=20)
        self.assertFalse(_return_allowed("No satisface expectativas", out_of_window))

    def test_duplicate_return_blocked(self):
        db = [
            {
                "pedido_id": "PED-ABC",
                "product_id": "P-IPHONE19",
                "aceptada": True,
            }
        ]
        self.assertTrue(_return_already_accepted(db, "PED-ABC", "P-IPHONE19"))
        self.assertFalse(_return_already_accepted(db, "PED-ABC", "P-OTHER"))
        self.assertFalse(_return_already_accepted(db, "PED-XYZ", "P-IPHONE19"))

    def test_expectations_use_reception_hint_not_order_date(self):
        pedido = DATA["pedido/P-TEST"]
        graph = Graph()
        graph.add((pedido, ECSDI.fechaPedido, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))
        motivo = f"No satisface expectativas (recepcion={(datetime.now() - timedelta(days=20)).date().isoformat()})"
        self.assertTrue(_motivo_expectations(motivo))
        reception = _reception_date_for_policy(motivo, graph, pedido)
        self.assertIsNotNone(reception)
        self.assertFalse(_return_allowed(motivo, reception))

    def test_window_days_constant(self):
        self.assertEqual(RETURN_WINDOW_DAYS, 15)


if __name__ == "__main__":
    unittest.main()
