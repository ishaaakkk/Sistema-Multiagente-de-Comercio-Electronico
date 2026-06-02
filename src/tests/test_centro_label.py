"""Etiqueta de centro logístico coherente en tiquets."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF

from tests.fixtures.catalog_fixtures import build_catalog_graph
from utilities.catalog import center_uri, format_centro_label, stamp_operating_center
from utilities.namespaces import DATA, ECSDI, bind_namespaces
from utilities.order_response import _centro_from_lote


class CentroLabelTests(unittest.TestCase):
    def test_format_centro_label(self):
        self.assertEqual(
            format_centro_label("CL-MAD", "Madrid", "Centro Logístico Madrid"),
            "Centro Logístico Madrid (CL-MAD)",
        )

    def test_centro_from_lote_uses_operating_center_metadata(self):
        graph = Graph()
        bind_namespaces(graph)
        center = center_uri("CL-BCN")
        for triple in build_catalog_graph().triples((center, None, None)):
            graph.add(triple)
        stamp_operating_center(graph, center, "CL-MAD", "Madrid")
        lote = DATA["lote/test-label"]
        graph.add((lote, RDF.type, ECSDI.LoteEnvio))
        graph.add((lote, ECSDI.loteOrigenCentro, center))
        graph.add((lote, ECSDI.ciudadCentroLogistico, Literal("Madrid")))

        centro_id, ciudad, nombre = _centro_from_lote(graph, lote)
        self.assertEqual(centro_id, "CL-MAD")
        self.assertEqual(ciudad, "Madrid")
        self.assertEqual(nombre, "Centro Logístico Madrid")


if __name__ == "__main__":
    unittest.main()
