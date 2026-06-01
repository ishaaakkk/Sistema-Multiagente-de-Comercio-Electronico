"""Tests del servicio de directorio FIPA."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal
from rdflib.namespace import RDF

from agents.directory_service import _handle_search
from utilities.acl import get_message
from utilities.namespaces import ACL, AGENTS, DATA, DSO, ECSDI, bind_namespaces


class DirectorySearchTests(unittest.TestCase):
    def test_search_by_capability_only_does_not_emit_null_agent_type(self):
        dsgraph = Graph()
        bind_namespaces(dsgraph)
        agent = AGENTS["transportista-test"]
        dsgraph.add((agent, RDF.type, DSO.AgenteDirectorio))
        dsgraph.add((agent, DSO.Address, Literal("http://127.0.0.1:9103")))
        dsgraph.add((agent, DSO.Capability, ECSDI.DemanarOfertaTransport))

        request = Graph()
        bind_namespaces(request)
        action = DATA["directory/search/test"]
        request.add((action, RDF.type, DSO.BuscarAgente))
        request.add((action, DSO.Capability, ECSDI.DemanarOfertaTransport))

        response = _handle_search(
            dsgraph,
            {},
            request,
            action,
            AGENTS.AgenteComerciante,
            "equaljobs",
            "test-directory",
        )

        message = get_message(response)
        self.assertIsNotNone(message)
        self.assertEqual(message.performative, ACL.inform)
        result = next(response.subjects(RDF.type, DSO.RespuestaBusqueda))
        self.assertEqual(next(response.objects(result, DSO.Uri)), agent)
        self.assertEqual(
            next(response.objects(result, DSO.Capability)),
            ECSDI.DemanarOfertaTransport,
        )
        self.assertEqual(list(response.objects(result, DSO.AgentType)), [])


if __name__ == "__main__":
    unittest.main()
