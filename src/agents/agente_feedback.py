import argparse
from datetime import datetime
from uuid import uuid4

from flask import Flask, jsonify
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message
from utilities.builders import build_valoracion_response
from utilities.catalog import product_uri
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    unregister_service,
)


DEFAULT_AGENT_URI = AGENTS.AgenteFeedback


def create_app(agent_uri=DEFAULT_AGENT_URI):
    app = Flask(__name__)
    opinions_db: list[dict] = []

    @app.get("/")
    def index():
        return "AgenteFeedback listo"

    @app.get("/status")
    def status():
        return jsonify(
            {
                "total": len(opinions_db),
                "pending": [o for o in opinions_db if o["puntuacion"] is None],
                "completed": [o for o in opinions_db if o["puntuacion"] is not None],
            }
        )

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(
                    build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido")
                )
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            if (action, RDF.type, ECSDI.NotificarCompraCompletada) in graph:
                return rdf_response(_handle_notify_purchase(opinions_db, agent_uri, message.sender, action, graph))

            # builders.py construye ECSDI.EnviarOpinion — aceptamos ambos nombres por compatibilidad
            if (action, RDF.type, ECSDI.EnviarOpinion) in graph or (action, RDF.type, ECSDI.RegistrarValoracion) in graph:
                return rdf_response(_handle_registrar_valoracion(opinions_db, agent_uri, message.sender, action, graph))

            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteFeedback"))
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_notify_purchase(
    opinions_db: list[dict],
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Plan: RegistrarCompraParaFuturaOpinion — una entrada pendiente por linea de pedido."""
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return build_failure(agent_uri, sender, action, "Falta accionSobrePedido")

    pedido_id = str(next(graph.objects(pedido, ECSDI.idPedido), ""))
    asistente = next(graph.objects(pedido, ECSDI.pedidoSolicitadoPor), AGENTS.AsistenteVirtual)
    fecha_entrega = _extract_delivery_date(graph)

    lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not lines:
        return build_failure(agent_uri, sender, action, "El pedido no contiene lineas")

    created = 0
    for line in lines:
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        product_id = str(next(graph.objects(product, ECSDI.idProducto), _product_id_from_uri(product)))
        opinions_db.append(
            {
                "pedido_id": pedido_id,
                "product_id": product_id,
                "product_uri": str(product),
                "asistente": str(asistente),
                "fecha_entrega": fecha_entrega,
                "puntuacion": None,
                "comentario": None,
            }
        )
        created += 1

    log("feedback", f"Compra registrada: pedido={pedido_id}, {created} opinion(es) pendiente(s)")
    return build_message(graph, action, ACL.inform, agent_uri, sender)


def _handle_registrar_valoracion(
    opinions_db: list[dict],
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Plan: RegistrarOpinionProducto — completa un registro pendiente con puntuacion y comentario."""
    valoracion = next(graph.objects(action, ECSDI.accionTieneValoracion), None)
    if valoracion is None:
        valoracion = next(graph.subjects(RDF.type, ECSDI.Valoracion), None)
    if valoracion is None:
        return build_failure(agent_uri, sender, action, "Falta la valoracion en RegistrarValoracion")

    pedido_id = str(next(graph.objects(valoracion, ECSDI.valoracionDePedido), ""))
    product = next(graph.objects(valoracion, ECSDI.valoracionDeProducto), None)
    product_id = str(next(graph.objects(product, ECSDI.idProducto), _product_id_from_uri(product))) if product else ""
    puntuacion = int(next(graph.objects(valoracion, ECSDI.puntuacion), 0))
    comentario = str(next(graph.objects(valoracion, ECSDI.comentario), ""))

    record = _find_pending(opinions_db, pedido_id, product_id)
    if record is None:
        return build_failure(
            agent_uri,
            sender,
            action,
            f"No hay opinion pendiente para pedido={pedido_id} producto={product_id}",
        )

    record["puntuacion"] = puntuacion
    record["comentario"] = comentario

    valoracion_graph = Graph()
    bind_namespaces(valoracion_graph)
    stored = DATA[f"valoracion/stored/{uuid4()}"]
    valoracion_graph.add((stored, RDF.type, ECSDI.Valoracion))
    valoracion_graph.add((stored, ECSDI.valoracionDeProducto, product_uri(product_id)))
    valoracion_graph.add((stored, ECSDI.valoracionEnviadaPor, sender))
    valoracion_graph.add((stored, ECSDI.valoracionDePedido, Literal(pedido_id)))
    valoracion_graph.add((stored, ECSDI.puntuacion, Literal(puntuacion, datatype=XSD.integer)))
    valoracion_graph.add((stored, ECSDI.comentario, Literal(comentario)))
    valoracion_graph.add(
        (
            stored,
            ECSDI.fechaValoracion,
            Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )

    log("feedback", f"Valoracion registrada: pedido={pedido_id} producto={product_id} puntuacion={puntuacion}")
    return build_valoracion_response(agent_uri, sender, stored, valoracion_graph)


def _extract_delivery_date(graph: Graph) -> str | None:
    for offer in graph.subjects(RDF.type, ECSDI.OfertaTransporte):
        fecha = next(graph.objects(offer, ECSDI.fechaEntregaEstimada), None)
        if fecha is not None:
            return str(fecha)
    for envio in graph.subjects(RDF.type, ECSDI.EnvioInterno):
        lote = next(graph.objects(envio, ECSDI.envioTieneLote), None)
        if lote is not None:
            for offer in graph.subjects(RDF.type, ECSDI.OfertaTransporte):
                if (offer, ECSDI.ofertaParaLote, lote) in graph:
                    fecha = next(graph.objects(offer, ECSDI.fechaEntregaEstimada), None)
                    if fecha is not None:
                        return str(fecha)
    return None


def _product_id_from_uri(product: URIRef) -> str:
    uri = str(product)
    if "/producto/" in uri:
        return uri.rsplit("/producto/", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def _find_pending(opinions_db: list[dict], pedido_id: str, product_id: str) -> dict | None:
    for record in reversed(opinions_db):
        if record["puntuacion"] is not None:
            continue
        if record["pedido_id"] == pedido_id and record["product_id"] == product_id:
            return record
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9007)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_FEEDBACK", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "AGENTE_FEEDBACK", address, f"feedback-{args.port}")
    try:
        log(f"feedback-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app().run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"feedback-{args.port}")


if __name__ == "__main__":
    main()