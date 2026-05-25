"""Tests unitarios sobre utilities/comm.py."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from utilities.comm import comm_url, copy_business_graph, copy_subject
from utilities.namespaces import ACL, ECSDI, bind_namespaces


class CommUrlTests(unittest.TestCase):
    def test_appends_comm_when_missing(self):
        self.assertEqual(comm_url("http://localhost:9000"), "http://localhost:9000/comm")

    def test_keeps_comm_when_present(self):
        self.assertEqual(comm_url("http://localhost:9000/comm"), "http://localhost:9000/comm")

    def test_strips_trailing_slash(self):
        self.assertEqual(comm_url("http://localhost:9000/"), "http://localhost:9000/comm")

    def test_empty_passthrough(self):
        self.assertEqual(comm_url(""), "")


class CopyBusinessGraphTests(unittest.TestCase):
    def test_skips_acl_envelope_predicates(self):
        source = Graph()
        bind_namespaces(source)
        msg = URIRef("http://test/msg/1")
        action = URIRef("http://test/action/1")
        source.add((msg, RDF.type, ACL.FipaAclMessage))
        source.add((msg, ACL.performative, ACL.request))
        source.add((msg, ACL.sender, URIRef("http://test/sender")))
        source.add((msg, ACL.receiver, URIRef("http://test/receiver")))
        source.add((msg, ACL.content, action))
        source.add((action, RDF.type, ECSDI.BuscarProductos))
        source.add((action, ECSDI.accionSolicitadaPor, URIRef("http://test/sender")))

        target = Graph()
        copy_business_graph(source, target)

        self.assertIn((action, RDF.type, ECSDI.BuscarProductos), target)
        self.assertIn((action, ECSDI.accionSolicitadaPor, URIRef("http://test/sender")), target)
        self.assertNotIn((msg, RDF.type, ACL.FipaAclMessage), target)
        self.assertNotIn((msg, ACL.performative, ACL.request), target)


class CopySubjectTests(unittest.TestCase):
    def test_copies_subject_triples_only(self):
        src = Graph()
        s = URIRef("http://test/s")
        s2 = URIRef("http://test/other")
        src.add((s, RDF.type, ECSDI.Pedido))
        src.add((s, ECSDI.idPedido, Literal("P-1")))
        src.add((s2, RDF.type, ECSDI.Pedido))

        target = Graph()
        copy_subject(src, target, s)

        self.assertIn((s, RDF.type, ECSDI.Pedido), target)
        self.assertIn((s, ECSDI.idPedido, Literal("P-1")), target)
        self.assertNotIn((s2, RDF.type, ECSDI.Pedido), target)


if __name__ == "__main__":
    unittest.main()
