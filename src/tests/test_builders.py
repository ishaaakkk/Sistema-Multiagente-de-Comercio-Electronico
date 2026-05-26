"""Tests de builders RDF (pedido y cobro)."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.builders import build_cobro_request, build_order_message
from utilities.namespaces import AGENTS, DATA, ECSDI


class BuildOrderMessageTests(unittest.TestCase):
    def test_includes_metodo_pago_and_delivery_dist(self):
        graph = build_order_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteComerciante,
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("100.00")},
            city="Barcelona",
            street="Carrer Test 1",
            postal_code="08013",
            country="Espana",
            priority=2,
            payment_method="paypal",
            delivery_dist=130,
        )
        action = next(graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(graph.objects(action, ECSDI.accionSobrePedido))
        address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA))

        self.assertEqual(str(next(graph.objects(pedido, ECSDI.metodoPago))), "paypal")
        dist = next(graph.objects(address, ECSDI.dist))
        self.assertEqual(int(dist), 130)
        self.assertEqual(dist.datatype, XSD.integer)


class BuildCobroRequestTests(unittest.TestCase):
    def test_serializes_metodo_pago(self):
        pedido = DATA["pedido/TEST-001"]
        graph = build_cobro_request(
            AGENTS.AgenteComerciante,
            AGENTS.AgenteFinanciero,
            pedido,
            Decimal("50.00"),
            metodo_pago="tarjeta",
        )
        action = next(graph.subjects(RDF.type, ECSDI.SolicitarCobro))
        operacion = next(graph.objects(action, ECSDI.accionTieneOperacionPago))
        self.assertEqual(str(next(graph.objects(action, ECSDI.metodoPago))), "tarjeta")
        self.assertEqual(str(next(graph.objects(operacion, ECSDI.metodoPago))), "tarjeta")


if __name__ == "__main__":
    unittest.main()
