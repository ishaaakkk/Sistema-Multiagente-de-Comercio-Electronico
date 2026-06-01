"""Tests de mensajería interna mock en devoluciones (sin transportistas)."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib.namespace import RDF

from agents.agente_devolucion import _simulate_mensajeria_interna
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


if __name__ == "__main__":
    unittest.main()
