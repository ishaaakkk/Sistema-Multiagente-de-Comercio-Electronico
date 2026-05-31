"""Tests del filtrado de líneas por stock del Centro Logístico."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF, XSD

from agents.centro_logistico_agent import _filter_lines_by_stock
from utilities.catalog import center_uri, product_uri, stock_uri
from utilities.namespaces import DATA, ECSDI, bind_namespaces


class LogisticsStockTests(unittest.TestCase):
    def _order_graph(self, requested_quantity: int = 1) -> tuple[Graph, object, object]:
        graph = Graph()
        bind_namespaces(graph)
        pedido = DATA["pedido/test-stock"]
        line = DATA["linea/test-stock/1"]
        product = product_uri("P-STOCK")
        center = center_uri("CL-BCN")
        stock = stock_uri("P-STOCK", "CL-BCN")

        graph.add((pedido, RDF.type, ECSDI.Pedido))
        graph.add((pedido, ECSDI.pedidoTieneLinea, line))
        graph.add((line, RDF.type, ECSDI.LineaPedido))
        graph.add((line, ECSDI.lineaDeProducto, product))
        graph.add((line, ECSDI.cantidad, Literal(requested_quantity, datatype=XSD.integer)))
        graph.add((product, RDF.type, ECSDI.ProductoInterno))
        graph.add((product, ECSDI.idProducto, Literal("P-STOCK")))
        graph.add((stock, RDF.type, ECSDI.StockProducto))
        graph.add((stock, ECSDI.stockDeProducto, product))
        graph.add((stock, ECSDI.stockEnCentro, center))
        graph.add((stock, ECSDI.cantidadDisponible, Literal(1, datatype=XSD.integer)))
        return graph, pedido, line

    def test_reserved_stock_reduces_available_quantity(self):
        graph, pedido, _line = self._order_graph()

        lines = _filter_lines_by_stock(
            graph,
            pedido,
            center_uri("CL-BCN"),
            "CL-BCN",
            accepts_all=True,
            stock_set={"*"},
            reservations={"CL-BCN": {"P-STOCK": 1}},
        )

        self.assertEqual(lines, [])

    def test_line_is_fulfillable_when_stock_remains(self):
        graph, pedido, line = self._order_graph()

        lines = _filter_lines_by_stock(
            graph,
            pedido,
            center_uri("CL-BCN"),
            "CL-BCN",
            accepts_all=True,
            stock_set={"*"},
            reservations={},
        )

        self.assertEqual(lines, [line])


if __name__ == "__main__":
    unittest.main()
