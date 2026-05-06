from dataclasses import dataclass
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from .namespaces import ACL, DATA, ECSDI, bind_namespaces


@dataclass(frozen=True)
class ACLMessage:
    node: URIRef
    performative: URIRef
    sender: URIRef | None
    receiver: URIRef | None
    content: URIRef | None


def parse_graph(data: str | bytes) -> Graph:
    if isinstance(data, bytes):
        data = data.decode("utf-8")

    graph = Graph()
    bind_namespaces(graph)
    last_error = None
    for rdf_format in ("turtle", "xml", "nt"):
        try:
            graph.parse(data=data, format=rdf_format)
            return graph
        except Exception as exc:
            last_error = exc
            graph = Graph()
            bind_namespaces(graph)
    raise ValueError(f"Could not parse RDF payload: {last_error}")


def serialize_graph(graph: Graph) -> str:
    return graph.serialize(format="turtle")


def build_message(
    content_graph: Graph,
    content_node: URIRef,
    performative: URIRef,
    sender: URIRef | str,
    receiver: URIRef | str,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    for triple in content_graph:
        graph.add(triple)

    msg = DATA[f"message/{uuid4()}"]
    graph.add((msg, RDF.type, ACL.FipaAclMessage))
    graph.add((msg, ACL.performative, performative))
    graph.add((msg, ACL.sender, _uri(sender)))
    graph.add((msg, ACL.receiver, _uri(receiver)))
    graph.add((msg, ACL.content, content_node))
    return graph


def get_message(graph: Graph) -> ACLMessage | None:
    msg = next(graph.subjects(RDF.type, ACL.FipaAclMessage), None)
    if msg is None:
        msg = next(graph.subjects(ACL.performative, None), None)
    if msg is None:
        return None

    return ACLMessage(
        node=msg,
        performative=next(graph.objects(msg, ACL.performative), None),
        sender=next(graph.objects(msg, ACL.sender), None),
        receiver=next(graph.objects(msg, ACL.receiver), None),
        content=next(graph.objects(msg, ACL.content), None),
    )


def build_failure(
    sender: URIRef | str,
    receiver: URIRef | str,
    original_action: URIRef | None,
    reason: str,
    performative: URIRef = ACL.failure,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    response = DATA[f"response/failure/{uuid4()}"]
    graph.add((response, RDF.type, ECSDI.Respuesta))
    graph.add((response, RDFS.comment, Literal(reason)))
    if original_action is not None:
        graph.add((response, ECSDI.respuestaDeAccion, original_action))
    return build_message(graph, response, performative, sender, receiver)


def build_not_understood(sender: URIRef | str, receiver: URIRef | str, reason: str) -> Graph:
    return build_failure(sender, receiver, None, reason, ACL["not-understood"])


def _uri(value: URIRef | str | None) -> URIRef:
    if value is None:
        return DATA["agent/unknown"]
    return value if isinstance(value, URIRef) else URIRef(value)
