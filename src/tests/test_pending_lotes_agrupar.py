"""Tests del plan AgruparPedidoEnLote (misma dirección, tope de líneas)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.builders import build_order_message
from utilities.catalog import center_uri
from utilities.namespaces import DATA, ECSDI, bind_namespaces
from utilities.pending_lotes import (
    append_lines_to_pending_lote,
    count_lote_lines,
    create_pending_lote,
    destination_key,
    find_open_lote,
    list_pending_lote_ids,
    load_pending_lote,
)
from utilities.storage import DATA_DIR
from decimal import Decimal


class PendingLotesAgruparTests(unittest.TestCase):
    def setUp(self):
        self.center_id = "CL-TEST"
        base = DATA_DIR / "pending_lotes" / self.center_id
        if base.exists():
            for path in base.glob("*"):
                path.unlink()

    def _order(self, pedido_id: str, street: str, priority: int = 2) -> tuple[Graph, URIRef]:
        graph = build_order_message(
            sender=DATA["asistente/test"],
            receiver=DATA["comerciante/test"],
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("100")},
            city="Barcelona",
            street=street,
            postal_code="08013",
            country="Espana",
            priority=priority,
            payment_method="tarjeta",
            delivery_dist=130,
        )
        action = next(graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(graph.objects(action, ECSDI.accionSobrePedido))
        for o in list(graph.objects(pedido, ECSDI.idPedido)):
            graph.remove((pedido, ECSDI.idPedido, o))
        graph.add((pedido, ECSDI.idPedido, Literal(pedido_id)))
        lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
        return graph, pedido, lines, action

    def test_merge_same_destination_up_to_max_lines(self):
        g1, p1, lines1, a1 = self._order("PED-A", "Carrer Unica 1")
        create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        g2, p2, lines2, a2 = self._order("PED-B", "Carrer Unica 1")
        dest = destination_key(g2, p2)
        found = find_open_lote(self.center_id, dest, max_lines=8, additional_lines=len(lines2))
        self.assertIsNotNone(found)
        lote_id, lote_graph, lote = found
        append_lines_to_pending_lote(
            self.center_id, lote_id, lote_graph, lote, g2, p2, lines2,
            "http://127.0.0.1:9001/comm", a2, "http://comerciante",
        )
        loaded = load_pending_lote(self.center_id, lote_id)
        self.assertIsNotNone(loaded)
        _, lote_node = loaded
        self.assertEqual(count_lote_lines(loaded[0], lote_node), 2)
        self.assertEqual(len(list_pending_lote_ids(self.center_id)), 1)

    def test_new_lote_when_max_lines_exceeded(self):
        g1, p1, lines1, a1 = self._order("PED-1", "Carrer Dos 2")
        create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        g2, p2, lines2, a2 = self._order("PED-2", "Carrer Dos 2")
        dest = destination_key(g2, p2)
        found = find_open_lote(self.center_id, dest, max_lines=1, additional_lines=len(lines2))
        self.assertIsNone(found)
        create_pending_lote(
            g2, p2, lines2, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a2, "http://comerciante",
        )
        self.assertEqual(len(list_pending_lote_ids(self.center_id)), 2)


if __name__ == "__main__":
    unittest.main()
