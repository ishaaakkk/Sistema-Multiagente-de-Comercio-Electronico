"""Tests de utilidades del Agente Asistente."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.agente_asistente import _acl_failure_payload
from utilities.acl import build_failure
from utilities.namespaces import AGENTS


class AsistenteFailurePayloadTests(unittest.TestCase):
    def test_extracts_acl_failure_reason_for_json_api(self):
        graph = build_failure(
            AGENTS.AgenteComerciante,
            AGENTS.AsistenteVirtual,
            None,
            "pedido incompleto",
        )

        self.assertEqual(
            _acl_failure_payload(graph, "fallback"),
            {"error": "pedido incompleto"},
        )


if __name__ == "__main__":
    unittest.main()
