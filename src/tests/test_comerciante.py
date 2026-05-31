"""Tests del grafo de pedido que prepara el AgenteComerciante."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Literal
from rdflib.namespace import RDF

from agents.agente_catalogo import build_catalog_graph
from agents.agente_comerciante import _build_order_graph
from utilities.builders import build_order_message
from utilities.catalog import product_uri
from utilities.namespaces import AGENTS, ECSDI


class OrderGraphTests(unittest.TestCase):
    def test_copies_product_stock_and_center_context(self):
        catalog_graph = build_catalog_graph()
        request_graph = build_order_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteComerciante,
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("1199.00")},
            city="Barcelona",
            street="Carrer Mallorca 401",
            postal_code="08013",
            country="Espana",
            priority=1,
            catalog_graph=catalog_graph,
        )

        action = next(request_graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(request_graph.objects(action, ECSDI.accionSobrePedido))
        lines = list(request_graph.objects(pedido, ECSDI.pedidoTieneLinea))
        order_graph = _build_order_graph(request_graph, action, pedido, lines)

        product = product_uri("P-IPHONE19")
        stock = next(order_graph.subjects(ECSDI.stockDeProducto, product), None)
        self.assertIn((product, RDF.type, ECSDI.ProductoInterno), order_graph)
        self.assertIsNotNone(stock)

        center = next(order_graph.objects(stock, ECSDI.stockEnCentro), None)
        self.assertIsNotNone(center)
        self.assertIn((center, ECSDI.idCentroLogistico, Literal("CL-BCN")), order_graph)


if __name__ == "__main__":
    unittest.main()
