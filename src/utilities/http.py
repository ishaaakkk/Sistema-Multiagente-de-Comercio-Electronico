from flask import Response, request
import requests

from .acl import parse_graph, serialize_graph


def graph_from_request():
    payload = request.get_data(as_text=True)
    if not payload and "content" in request.values:
        payload = request.values["content"]
    if not payload:
        raise ValueError("Request does not contain an RDF payload")
    return parse_graph(payload)


def rdf_response(graph, status=200):
    return Response(serialize_graph(graph), status=status, mimetype="text/turtle")


def post_graph(url, graph, timeout=8):
    response = requests.post(
        url,
        data=serialize_graph(graph).encode("utf-8"),
        headers={"Content-Type": "text/turtle", "Accept": "text/turtle"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_graph(response.text)
