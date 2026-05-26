"""Tests de validación de datos de compra y selección de CL por dist."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from agents.agente_comerciante import (
    _dispatch_to_logistics_ordered,
    _plan_preguntar_datos_compra,
    _sort_logistics_by_distance,
)
from utilities.acl import get_message
from utilities.builders import build_order_message
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces


def _minimal_order_graph(line_uris: list[URIRef]) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    pedido = DATA["pedido/TEST-MULTI"]
    graph.add((pedido, RDF.type, ECSDI.Pedido))
    graph.add((pedido, ECSDI.idPedido, Literal("TEST-MULTI")))
    for line in line_uris:
        graph.add((pedido, ECSDI.pedidoTieneLinea, line))
        graph.add((line, RDF.type, ECSDI.LineaPedido))
    return graph


def _confirmation_for_line(line: URIRef) -> Graph:
    resp = Graph()
    bind_namespaces(resp)
    lote = DATA[f"lote/{line}"]
    envio = DATA[f"envio/{line}"]
    confirmacion = DATA[f"confirmacion/{line}"]
    resp.add((lote, RDF.type, ECSDI.LoteEnvio))
    resp.add((lote, ECSDI.loteTieneLinea, line))
    resp.add((envio, RDF.type, ECSDI.EnvioInterno))
    resp.add((envio, ECSDI.envioTieneLote, lote))
    resp.add((confirmacion, RDF.type, ECSDI.ConfirmacionEnvio))
    return resp


class PreguntarDatosCompraTests(unittest.TestCase):
    def test_accepts_complete_order(self):
        graph = build_order_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteComerciante,
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("100")},
            city="Barcelona",
            street="Calle",
            postal_code="08013",
            country="Espana",
            priority=1,
            payment_method="tarjeta",
            delivery_dist=130,
        )
        action = next(graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido, lines, error = _plan_preguntar_datos_compra(
            AGENTS.AgenteComerciante, AGENTS.AsistenteVirtual, action, graph
        )
        self.assertIsNone(error)
        self.assertIsNotNone(pedido)
        self.assertEqual(len(lines), 1)

    def test_fails_without_metodo_pago(self):
        graph = build_order_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteComerciante,
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("100")},
            city="Barcelona",
            street="Calle",
            postal_code="08013",
            country="Espana",
            priority=1,
            delivery_dist=130,
        )
        action = next(graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(graph.objects(action, ECSDI.accionSobrePedido))
        for o in list(graph.objects(pedido, ECSDI.metodoPago)):
            graph.remove((pedido, ECSDI.metodoPago, o))

        _, _, error = _plan_preguntar_datos_compra(
            AGENTS.AgenteComerciante, AGENTS.AsistenteVirtual, action, graph
        )
        self.assertIsNotNone(error)
        msg = get_message(error)
        self.assertEqual(msg.performative, ACL.failure)

    def test_fails_without_dist(self):
        graph = build_order_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteComerciante,
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("100")},
            city="Barcelona",
            street="Calle",
            postal_code="08013",
            country="Espana",
            priority=1,
            payment_method="tarjeta",
            delivery_dist=130,
        )
        action = next(graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(graph.objects(action, ECSDI.accionSobrePedido))
        address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA))
        for o in list(graph.objects(address, ECSDI.dist)):
            graph.remove((address, ECSDI.dist, o))

        _, _, error = _plan_preguntar_datos_compra(
            AGENTS.AgenteComerciante, AGENTS.AsistenteVirtual, action, graph
        )
        self.assertIsNotNone(error)
        msg = get_message(error)
        self.assertEqual(msg.performative, ACL.failure)


class SortLogisticsTests(unittest.TestCase):
    @patch("agents.agente_comerciante.requests.get")
    def test_orders_by_absolute_dist_difference(self, mock_get):
        def fake_info(url, timeout=1.0):
            resp = MagicMock()
            if "9002" in url:
                resp.json.return_value = {"dist": 130}
            else:
                resp.json.return_value = {"dist": 500}
            return resp

        mock_get.side_effect = fake_info
        urls = [
            "http://127.0.0.1:9012/comm",
            "http://127.0.0.1:9002/comm",
        ]
        ordered = _sort_logistics_by_distance(urls, client_dist=130)
        self.assertEqual(ordered[0], "http://127.0.0.1:9002/comm")
        self.assertEqual(ordered[1], "http://127.0.0.1:9012/comm")


class DispatchOrderedTests(unittest.TestCase):
    @patch("agents.agente_comerciante._dispatch_to_logistics")
    def test_continues_to_second_cl_for_remaining_lines(self, mock_dispatch):
        line_a = DATA["linea/A"]
        line_b = DATA["linea/B"]
        pedido = DATA["pedido/TEST-MULTI"]
        logistics_graph = _minimal_order_graph([line_a, line_b])

        mock_dispatch.side_effect = [
            [_confirmation_for_line(line_a)],
            [_confirmation_for_line(line_b)],
        ]

        result = _dispatch_to_logistics_ordered(
            AGENTS.AgenteComerciante,
            logistics_graph,
            pedido,
            ["http://cl-bcn/comm", "http://cl-mad/comm"],
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(mock_dispatch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
