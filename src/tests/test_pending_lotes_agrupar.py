"""Tests del plan AgruparPedidoEnLote (zona dist, tope de líneas, debounce)."""

import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Literal
from rdflib.namespace import RDF

from utilities.builders import build_order_message
from utilities.catalog import center_uri
from utilities.namespaces import DATA, ECSDI
from utilities.pending_lotes import (
    append_lines_to_pending_lote,
    count_lote_lines,
    create_pending_lote,
    dist_zone,
    find_open_lote,
    grouping_key,
    list_pending_lote_ids,
    load_pending_lote,
    load_pending_meta,
    save_pending_meta,
    select_lotes_for_dispatch,
)
from utilities.storage import DATA_DIR


class PendingLotesAgruparTests(unittest.TestCase):
    def setUp(self):
        self.center_id = "CL-TEST"
        base = DATA_DIR / "pending_lotes" / self.center_id
        if base.exists():
            for path in base.glob("*"):
                path.unlink()

    def _order(
        self,
        pedido_id: str,
        street: str,
        priority: int = 2,
        delivery_dist: int = 130,
        city: str = "Barcelona",
    ):
        graph = build_order_message(
            sender=DATA["asistente/test"],
            receiver=DATA["comerciante/test"],
            product_quantities={"P-IPHONE19": 1},
            product_prices={"P-IPHONE19": Decimal("100")},
            city=city,
            street=street,
            postal_code="08013",
            country="Espana",
            priority=priority,
            payment_method="tarjeta",
            delivery_dist=delivery_dist,
        )
        action = next(graph.subjects(RDF.type, ECSDI.RealizarPedido))
        pedido = next(graph.objects(action, ECSDI.accionSobrePedido))
        for o in list(graph.objects(pedido, ECSDI.idPedido)):
            graph.remove((pedido, ECSDI.idPedido, o))
        graph.add((pedido, ECSDI.idPedido, Literal(pedido_id)))
        lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
        return graph, pedido, lines, action

    def test_dist_zone_bands(self):
        self.assertEqual(dist_zone(0), 0)
        self.assertEqual(dist_zone(199), 0)
        self.assertEqual(dist_zone(200), 1)
        self.assertEqual(dist_zone(350), 1)

    def test_merge_same_dist_zone_different_streets(self):
        g1, p1, lines1, a1 = self._order("PED-A", "Carrer Unica 1", delivery_dist=130)
        create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        g2, p2, lines2, a2 = self._order("PED-B", "Avinguda Diferent 99", delivery_dist=180)
        group = grouping_key(self.center_id, g2, p2)
        found = find_open_lote(self.center_id, group, max_lines=8, additional_lines=len(lines2))
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

    def test_new_lote_when_dist_zone_differs(self):
        g1, p1, lines1, a1 = self._order("PED-1", "Carrer Dos 2", delivery_dist=150)
        create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        g2, p2, lines2, a2 = self._order("PED-2", "Carrer Dos 2", delivery_dist=350)
        group = grouping_key(self.center_id, g2, p2)
        found = find_open_lote(self.center_id, group, max_lines=8, additional_lines=len(lines2))
        self.assertIsNone(found)
        create_pending_lote(
            g2, p2, lines2, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a2, "http://comerciante",
        )
        self.assertEqual(len(list_pending_lote_ids(self.center_id)), 2)

    def test_new_lote_when_max_lines_exceeded(self):
        g1, p1, lines1, a1 = self._order("PED-1", "Carrer Dos 2")
        create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        g2, p2, lines2, a2 = self._order("PED-2", "Carrer Dos 2")
        group = grouping_key(self.center_id, g2, p2)
        found = find_open_lote(self.center_id, group, max_lines=1, additional_lines=len(lines2))
        self.assertIsNone(found)
        create_pending_lote(
            g2, p2, lines2, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a2, "http://comerciante",
        )
        self.assertEqual(len(list_pending_lote_ids(self.center_id)), 2)

    def test_lote_keeps_most_urgent_priority(self):
        g1, p1, lines1, a1 = self._order("PED-NORMAL", "Carrer Tres 3", priority=3)
        lote_id, lote_graph, lote = create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        g2, p2, lines2, a2 = self._order("PED-URGENT", "Carrer Tres 3", priority=1)
        append_lines_to_pending_lote(
            self.center_id, lote_id, lote_graph, lote, g2, p2, lines2,
            "http://127.0.0.1:9001/comm", a2, "http://comerciante",
        )
        loaded = load_pending_lote(self.center_id, lote_id)
        self.assertIsNotNone(loaded)
        _, loaded_lote = loaded
        self.assertEqual(int(next(loaded[0].objects(loaded_lote, ECSDI.prioridadLote))), 1)
        self.assertEqual(load_pending_meta(self.center_id, lote_id)["prioridad"], 1)

    def test_select_lotes_respects_debounce(self):
        g1, p1, lines1, a1 = self._order("PED-WAIT", "Carrer Quatre 4", priority=2)
        lote_id, _, _ = create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        self.assertEqual(select_lotes_for_dispatch(self.center_id, debounce_seconds=90), [])
        meta = load_pending_meta(self.center_id, lote_id)
        meta["last_activity_at"] = time.time() - 100
        save_pending_meta(self.center_id, lote_id, meta)
        self.assertEqual(len(select_lotes_for_dispatch(self.center_id, debounce_seconds=90)), 1)

    def test_urgent_lote_dispatches_with_shorter_debounce(self):
        g1, p1, lines1, a1 = self._order("PED-URGENT", "Carrer Cinc 5", priority=1)
        lote_id, _, _ = create_pending_lote(
            g1, p1, lines1, center_uri(self.center_id), self.center_id, "Barcelona",
            "http://127.0.0.1:9001/comm", a1, "http://comerciante",
        )
        self.assertEqual(
            select_lotes_for_dispatch(
                self.center_id, debounce_seconds=90, urgent_debounce_seconds=5
            ),
            [],
        )
        meta = load_pending_meta(self.center_id, lote_id)
        meta["last_activity_at"] = time.time() - 6
        save_pending_meta(self.center_id, lote_id, meta)
        self.assertEqual(
            len(
                select_lotes_for_dispatch(
                    self.center_id, debounce_seconds=90, urgent_debounce_seconds=5
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
