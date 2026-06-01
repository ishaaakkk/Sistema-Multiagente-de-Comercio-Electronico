"""Tests de extracción de pedido/envío desde respuestas RDF."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF

from tests.fixtures.catalog_fixtures import build_catalog_graph
from utilities.acl import build_message
from utilities.namespaces import ACL
from utilities.builders import build_order_message, build_shipping_confirmation
from utilities.namespaces import AGENTS, DATA, ECSDI, bind_namespaces
from utilities.order_response import extract_order_summary, pick_estado_pedido, resolve_pedido


class OrderResponseTests(unittest.TestCase):
    def test_prefers_latest_estado_and_acl_pedido(self):
        catalog_graph = build_catalog_graph()
        request = build_order_message(
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
        action = next(request.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(request.objects(action, ECSDI.accionSobrePedido))

        order_graph = Graph()
        bind_namespaces(order_graph)
        for triple in request:
            order_graph.add(triple)
        order_graph.add((pedido, ECSDI.estadoPedido, Literal("aceptado_sin_pago")))
        order_graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_envio_planificado")))

        lote = DATA["lote/TEST-LOT"]
        offer_graph = Graph()
        bind_namespaces(offer_graph)
        oferta = DATA["oferta/TEST"]
        offer_graph.add((oferta, RDF.type, ECSDI.OfertaTransport))
        offer_graph.add((oferta, ECSDI.ofertaParaLote, lote))
        offer_graph.add((oferta, ECSDI.preuTransport, Literal("12.50")))
        offer_graph.add((oferta, ECSDI.dataPrevista, Literal("2026-06-05")))

        shipping = build_shipping_confirmation(
            AGENTS.CentroLogisticoBCN,
            AGENTS.AgenteComerciante,
            action,
            pedido,
            lote,
            offer_graph,
            oferta,
            AGENTS.TransportistaEco,
        )
        for triple in shipping:
            order_graph.add(triple)
        confirmacion = next(shipping.subjects(RDF.type, ECSDI.ConfirmacionEnvio))
        order_graph.add((pedido, ECSDI.pedidoTieneConfirmacion, confirmacion))

        response = build_message(
            order_graph,
            pedido,
            ACL.inform,
            AGENTS.AgenteComerciante,
            AGENTS.AsistenteVirtual,
        )
        summary = extract_order_summary(response)

        self.assertEqual(summary["pedido_id"], str(next(request.objects(pedido, ECSDI.idPedido))))
        self.assertEqual(summary["estado"], "aceptado_envio_planificado")
        self.assertTrue(summary["envio_interno"])
        self.assertEqual(len(summary["envios_internos"]), 1)
        self.assertEqual(summary["coste_envio"], "12.50")
        self.assertEqual(resolve_pedido(response), pedido)
        self.assertEqual(pick_estado_pedido(response, pedido), "aceptado_envio_planificado")


if __name__ == "__main__":
    unittest.main()
