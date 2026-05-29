"""Tests de persistencia LotesEnviosDB."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF

from utilities.catalog import persist_lote
from utilities.namespaces import DATA, ECSDI, bind_namespaces
from utilities.storage import DATA_DIR, load_graph_collection, load_named_graph


class LotePersistenceTests(unittest.TestCase):
    def setUp(self):
        lotes_dir = DATA_DIR / "lotes"
        if lotes_dir.exists():
            for path in lotes_dir.glob("*.ttl"):
                path.unlink()

    def test_persist_lote_writes_ttl_and_named_graph(self):
        graph = Graph()
        bind_namespaces(graph)
        lote = DATA["lote/test-persist"]
        graph.add((lote, RDF.type, ECSDI.LoteEnvio))
        graph.add((lote, ECSDI.idLote, Literal("LOT-TEST01")))
        graph.add((lote, ECSDI.estadoLote, Literal("pendiente_transportista")))

        persist_lote(graph, lote)

        collection = load_graph_collection("lotes")
        self.assertIn("LOT-TEST01", collection)
        named = load_named_graph("lotes/LOT-TEST01")
        self.assertIn((lote, RDF.type, ECSDI.LoteEnvio), named)


if __name__ == "__main__":
    unittest.main()
