"""Helpers compartidos de comunicación entre agentes.

* `comm_url`: normaliza una URL base de un agente añadiéndole el sufijo
  `/comm` que es el endpoint estándar donde los agentes aceptan mensajes
  FIPA-ACL.
* `copy_business_graph`: copia el contenido "de negocio" de un grafo RDF
  recibido en un mensaje (todos los triples salvo el envoltorio
  `acl:FipaAclMessage`).
"""

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from .namespaces import ACL


def comm_url(base_url: str) -> str:
    """Normaliza una URL para que apunte al endpoint /comm del agente."""

    if not base_url:
        return base_url
    base_url = base_url.strip()
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


_ACL_WRAPPER_PREDICATES = {
    ACL.performative,
    ACL.sender,
    ACL.receiver,
    ACL.content,
    ACL["conversation-id"],
    ACL["reply-with"],
    ACL["in-reply-to"],
    ACL.protocol,
}


def copy_business_graph(source: Graph, target: Graph) -> None:
    """Copia todos los triples de `source` en `target` excepto los de
    envoltorio FIPA-ACL (sujeto/objeto cuyo tipo es `acl:FipaAclMessage`).

    Util cuando queremos persistir o reenviar el contenido semántico de
    una respuesta sin arrastrar las metadatos de transporte.
    """

    for triple in source:
        s, p, _ = triple
        if p in _ACL_WRAPPER_PREDICATES:
            continue
        if (s, RDF.type, ACL.FipaAclMessage) in source:
            continue
        target.add(triple)


def copy_subject(source: Graph, target: Graph, subject: URIRef) -> None:
    """Copia todos los triples cuyo sujeto es `subject` (cierre 1 nivel)."""

    for triple in source.triples((subject, None, None)):
        target.add(triple)
