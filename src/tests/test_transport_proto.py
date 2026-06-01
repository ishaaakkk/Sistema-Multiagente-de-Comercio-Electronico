"""Tests del protocolo CL-transportista (vocabulario ECSDI unificado)."""



import sys

import unittest

from decimal import Decimal

from pathlib import Path



sys.path.insert(0, str(Path(__file__).resolve().parents[1]))



from rdflib import Graph, Literal

from rdflib.namespace import RDF



from utilities.builders import build_transport_offer, build_transport_request

from utilities.namespaces import AGENTS, ECSDI, bind_namespaces

from utilities.transport_proto import (

    extract_cfp_from_lote,

    find_transport_offer,

    offer_price,

)





class TransportProtoTests(unittest.TestCase):

    def _sample_lote(self) -> tuple[Graph, object]:

        graph = Graph()

        bind_namespaces(graph)

        from utilities.namespaces import DATA



        lote = DATA["lote/test"]

        product = DATA["producto/P-TEST"]

        line = DATA["linea/test"]

        address = DATA["direccion/test"]



        graph.add((lote, RDF.type, ECSDI.LoteEnvio))

        graph.add((lote, ECSDI.idLote, Literal("LOT-TEST")))

        graph.add((lote, ECSDI.pesoTotalLote, Literal("2.0")))

        graph.add((lote, ECSDI.prioridadLote, Literal(2)))

        graph.add((lote, ECSDI.loteTieneLinea, line))

        graph.add((line, ECSDI.lineaDeProducto, product))

        graph.add((product, ECSDI.idProducto, Literal("P-TEST")))

        graph.add((lote, ECSDI.loteDestinoDireccion, address))

        graph.add((address, ECSDI.ciudad, Literal("Barcelona")))

        return graph, lote



    def test_cfp_uses_demanar_oferta_transport(self):

        lote_graph, lote = self._sample_lote()

        msg = build_transport_request(AGENTS.CentroLogisticoBarcelona, AGENTS.TransportistaExpress, lote_graph, lote)

        action = next(msg.subjects(RDF.type, ECSDI.DemanarOfertaTransport))

        self.assertEqual(str(next(msg.objects(action, ECSDI.comandaId))), "LOT-TEST")

        self.assertEqual(str(next(msg.objects(action, ECSDI.producteId))), "P-TEST")

        self.assertEqual(str(next(msg.objects(action, ECSDI.ciutatDesti))), "Barcelona")



    def test_offer_uses_oferta_transport(self):

        lote_graph, lote = self._sample_lote()

        action = next(

            build_transport_request(

                AGENTS.CentroLogisticoBarcelona, AGENTS.TransportistaExpress, lote_graph, lote

            ).subjects(RDF.type, ECSDI.DemanarOfertaTransport)

        )

        offer_msg = build_transport_offer(

            AGENTS.TransportistaExpress,

            AGENTS.CentroLogisticoBarcelona,

            action,

            lote_graph,

            lote,

            AGENTS.TransportistaExpress,

            Decimal("12.50"),

            3,

        )

        offer = find_transport_offer(offer_msg)

        self.assertIsNotNone(offer)

        self.assertIn((offer, RDF.type, ECSDI.OfertaTransport), offer_msg)

        self.assertEqual(offer_price(offer_msg, offer), Decimal("12.50"))





if __name__ == "__main__":

    unittest.main()

