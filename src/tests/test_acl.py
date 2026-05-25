"""Tests sobre el envoltorio FIPA-ACL (utilities/acl.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from utilities.acl import (
    build_failure,
    build_message,
    build_not_understood,
    build_reply,
    get_message,
)
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces


class AclMessageTests(unittest.TestCase):
    def _make_action(self):
        g = Graph()
        bind_namespaces(g)
        action = DATA["test/action/1"]
        g.add((action, RDF.type, ECSDI.BuscarProductos))
        return g, action

    def test_build_and_parse_request_message(self):
        graph, action = self._make_action()
        msg = build_message(
            graph,
            action,
            ACL.request,
            AGENTS.AsistenteVirtual,
            AGENTS.AgenteCatalogo,
        )
        parsed = get_message(msg)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.performative, ACL.request)
        self.assertEqual(parsed.sender, AGENTS.AsistenteVirtual)
        self.assertEqual(parsed.receiver, AGENTS.AgenteCatalogo)
        self.assertEqual(parsed.content, action)
        self.assertIsNotNone(parsed.conversation_id)

    def test_reply_inherits_conversation_id(self):
        graph, action = self._make_action()
        req = build_message(
            graph,
            action,
            ACL.request,
            AGENTS.AsistenteVirtual,
            AGENTS.AgenteCatalogo,
            conversation_id="conv-42",
            reply_with="msg-1",
        )
        req_parsed = get_message(req)
        reply_graph, content = self._make_action()
        reply = build_reply(
            req_parsed,
            reply_graph,
            content,
            ACL.inform,
            AGENTS.AgenteCatalogo,
        )
        reply_parsed = get_message(reply)
        self.assertEqual(reply_parsed.conversation_id, "conv-42")
        self.assertEqual(reply_parsed.in_reply_to, "msg-1")

    def test_failure_and_not_understood_messages(self):
        fail = build_failure(AGENTS.AgenteCatalogo, AGENTS.AsistenteVirtual, None, "boom")
        nu = build_not_understood(AGENTS.AgenteCatalogo, AGENTS.AsistenteVirtual, "no compr.")
        self.assertEqual(get_message(fail).performative, ACL.failure)
        self.assertEqual(get_message(nu).performative, ACL["not-understood"])


if __name__ == "__main__":
    unittest.main()
