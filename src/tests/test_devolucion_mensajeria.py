import unittest
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from agents.agente_devolucion import _request_recogida
from utilities.acl import build_message
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces


class DevolucionRecogidaTests(unittest.TestCase):
    def test_request_recogida_returns_transportista_response(self):
        devolucion = DATA[f"devolucion/{uuid4()}"]
        pedido = DATA[f"pedido/{uuid4()}"]
        product = DATA["productos/iphone15"]
        order_graph = Graph()
        bind_namespaces(order_graph)
        order_graph.add((pedido, RDF.type, ECSDI.PedidoCompletado))
        order_graph.add((product, RDF.type, ECSDI.Producto))

        pickup_date = datetime(2026, 6, 10, 10, 0, 0)
        envio = DATA[f"envio/devolucion/{uuid4()}"]
        response_graph = Graph()
        bind_namespaces(response_graph)
        response_graph.add((devolucion, RDF.type, ECSDI.Devolucion))
        response_graph.add((devolucion, ECSDI.devolucionDePedido, pedido))
        response_graph.add((devolucion, ECSDI.devolucionDeProducto, product))
        response_graph.add(
            (
                devolucion,
                ECSDI.fechaRecogidaDevolucion,
                Literal(pickup_date.isoformat(timespec="seconds"), datatype=XSD.dateTime),
            )
        )
        response_graph.add((envio, RDF.type, ECSDI.EnvioDevolucion))
        response_graph.add((envio, ECSDI.envioDePedido, pedido))
        response_graph.add((envio, ECSDI.envioRealizadoPor, AGENTS.TransportistaExpress))
        response = build_message(
            response_graph,
            URIRef("http://127.0.0.1:9003/comm"),
            ACL.inform,
            AGENTS.TransportistaExpress,
            AGENTS.AgenteDevolucion,
        )

        with patch("agents.agente_devolucion.post_graph", return_value=response):
            result = _request_recogida(
                AGENTS.AgenteDevolucion,
                "http://127.0.0.1:9003/comm",
                devolucion,
                pedido,
                product,
                order_graph,
            )

        self.assertIsNotNone(result)
        courier = next(result.objects(envio, ECSDI.envioRealizadoPor), None)
        self.assertEqual(courier, AGENTS.TransportistaExpress)
        fecha = next(result.objects(devolucion, ECSDI.fechaRecogidaDevolucion), None)
        self.assertIsNotNone(fecha)


if __name__ == "__main__":
    unittest.main()
