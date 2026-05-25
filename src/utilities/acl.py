from dataclasses import dataclass
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from .namespaces import ACL, DATA, ECSDI, bind_namespaces


@dataclass(frozen=True)
class ACLMessage:
    """Envoltorio FIPA-ACL leído de un grafo entrante.

    Incluye los parámetros FIPA-ACL del cap. 2.3.1 de los apuntes:
    sender, receiver, performative, content, conversation-id, reply-with
    e in-reply-to.
    """

    node: URIRef
    performative: URIRef
    sender: URIRef | None
    receiver: URIRef | None
    content: URIRef | None
    conversation_id: str | None = None
    reply_with: str | None = None
    in_reply_to: str | None = None
    protocol: URIRef | None = None


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
    conversation_id: str | None = None,
    reply_with: str | None = None,
    in_reply_to: str | None = None,
    protocol: URIRef | None = None,
) -> Graph:
    """Envuelve un grafo de contenido en un mensaje FIPA-ACL.

    Los parámetros opcionales corresponden a los parámetros FIPA-ACL del
    cap. 2.3.1 de los apuntes y permiten correlacionar peticiones y
    respuestas (necesario p.ej. para el Contract Net con transportistas y
    para la petición de feedback).
    """

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
    if conversation_id is None:
        conversation_id = str(uuid4())
    graph.add((msg, ACL["conversation-id"], Literal(conversation_id)))
    if reply_with is not None:
        graph.add((msg, ACL["reply-with"], Literal(reply_with)))
    if in_reply_to is not None:
        graph.add((msg, ACL["in-reply-to"], Literal(in_reply_to)))
    if protocol is not None:
        graph.add((msg, ACL.protocol, protocol))
    return graph


def get_message(graph: Graph) -> ACLMessage | None:
    msg = next(graph.subjects(RDF.type, ACL.FipaAclMessage), None)
    if msg is None:
        msg = next(graph.subjects(ACL.performative, None), None)
    if msg is None:
        return None

    conv = next(graph.objects(msg, ACL["conversation-id"]), None)
    reply_with = next(graph.objects(msg, ACL["reply-with"]), None)
    in_reply_to = next(graph.objects(msg, ACL["in-reply-to"]), None)
    protocol = next(graph.objects(msg, ACL.protocol), None)
    return ACLMessage(
        node=msg,
        performative=next(graph.objects(msg, ACL.performative), None),
        sender=next(graph.objects(msg, ACL.sender), None),
        receiver=next(graph.objects(msg, ACL.receiver), None),
        content=next(graph.objects(msg, ACL.content), None),
        conversation_id=str(conv) if conv is not None else None,
        reply_with=str(reply_with) if reply_with is not None else None,
        in_reply_to=str(in_reply_to) if in_reply_to is not None else None,
        protocol=protocol if protocol is not None else None,
    )


def build_reply(
    request: ACLMessage,
    content_graph: Graph,
    content_node: URIRef,
    performative: URIRef,
    sender: URIRef | str,
) -> Graph:
    """Construye una respuesta correlacionada con el mensaje original.

    Conserva el conversation-id y rellena in-reply-to con el reply-with del
    mensaje original, siguiendo FIPA-ACL.
    """

    receiver = request.sender
    if receiver is None:
        raise ValueError("El mensaje de petición no tiene sender; no se puede responder")
    return build_message(
        content_graph,
        content_node,
        performative,
        sender,
        receiver,
        conversation_id=request.conversation_id,
        in_reply_to=request.reply_with,
        protocol=request.protocol,
    )


def build_failure(
    sender: URIRef | str,
    receiver: URIRef | str,
    original_action: URIRef | None,
    reason: str,
    performative: URIRef = ACL.failure,
    conversation_id: str | None = None,
    in_reply_to: str | None = None,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    response = DATA[f"response/failure/{uuid4()}"]
    graph.add((response, RDF.type, ECSDI.Respuesta))
    graph.add((response, RDFS.comment, Literal(reason)))
    if original_action is not None:
        graph.add((response, ECSDI.respuestaDeAccion, original_action))
    return build_message(
        graph,
        response,
        performative,
        sender,
        receiver,
        conversation_id=conversation_id,
        in_reply_to=in_reply_to,
    )


def build_not_understood(
    sender: URIRef | str,
    receiver: URIRef | str,
    reason: str,
    conversation_id: str | None = None,
    in_reply_to: str | None = None,
) -> Graph:
    return build_failure(
        sender,
        receiver,
        None,
        reason,
        ACL["not-understood"],
        conversation_id=conversation_id,
        in_reply_to=in_reply_to,
    )


def _uri(value: URIRef | str | None) -> URIRef:
    if value is None:
        return DATA["agent/unknown"]
    return value if isinstance(value, URIRef) else URIRef(value)
