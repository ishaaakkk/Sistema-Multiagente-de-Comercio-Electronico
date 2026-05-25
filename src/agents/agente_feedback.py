import argparse
from datetime import datetime
from threading import Thread
from uuid import uuid4

from flask import Flask, jsonify
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message
from utilities.builders import build_pedir_feedback_request, build_valoracion_response
from utilities.catalog import product_uri
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    search_service,
    unregister_service,
)
from utilities.storage import load_json, save_json


DEFAULT_AGENT_URI = AGENTS.AgenteFeedback


def create_app(agent_uri=DEFAULT_AGENT_URI, assistant_url: str | None = None):
    app = Flask(__name__)
    opinions_db: list[dict] = load_json("opinions.json", [])

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
            if message.performative not in (ACL.request, ACL.inform):
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request o inform"))

            action = message.content

            if (action, RDF.type, ECSDI.NotificarCompraCompletada) in graph:
                return rdf_response(_handle_notify_purchase(opinions_db, agent_uri, message.sender, action, graph, assistant_url))

            if (action, RDF.type, ECSDI.PeticionProductosCandidatos) in graph:
                return rdf_response(_handle_recommendations(opinions_db, agent_uri, message.sender, action))

            # EnviarOpinion/RegistrarValoracion son comunicaciones informativas, no acciones de API.
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
    assistant_url: str | None,
) -> Graph:
    """Plan: RegistrarCompraParaFuturaOpinion — una entrada pendiente por linea de pedido."""
    pedido = next(graph.objects(action, ECSDI.notificacionSobrePedido), None)
    if pedido is None:
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
    new_records: list[dict] = []
    for line in lines:
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        product_id = str(next(graph.objects(product, ECSDI.idProducto), _product_id_from_uri(product)))
        record = {
            "pedido_id": pedido_id,
            "product_id": product_id,
            "product_uri": str(product),
            "asistente": str(asistente),
            "fecha_entrega": fecha_entrega,
            "puntuacion": None,
            "comentario": None,
            "feedback_solicitado": False,
        }
        opinions_db.append(record)
        new_records.append(record)
        created += 1

    log("feedback", f"Compra registrada: pedido={pedido_id}, {created} opinion(es) pendiente(s)")
    save_json("opinions.json", opinions_db)
    if assistant_url:
        _schedule_feedback_requests(new_records, opinions_db, agent_uri, assistant_url)
    return build_message(graph, action, ACL.inform, agent_uri, sender)


def _schedule_feedback_requests(records: list[dict], opinions_db: list[dict], agent_uri: URIRef, assistant_url: str) -> None:
    """Lanza peticiones PedirFeedback de forma asíncrona para no bloquear la compra."""
    for record in records:
        Thread(target=_send_feedback_request, args=(record, opinions_db, agent_uri, assistant_url), daemon=True).start()


def _send_feedback_request(record: dict, opinions_db: list[dict], agent_uri: URIRef, assistant_url: str) -> None:
    try:
        message = build_pedir_feedback_request(
            sender=agent_uri,
            receiver=URIRef(record["asistente"]),
            pedido_id=record["pedido_id"],
            product_id=record["product_id"],
            product=URIRef(record["product_uri"]),
        )
        post_graph(assistant_url, message)
        record["feedback_solicitado"] = True
        record["fecha_solicitud_feedback"] = datetime.now().isoformat(timespec="seconds")
        save_json("opinions.json", opinions_db)
        log("feedback", f"PedirFeedback enviado: pedido={record['pedido_id']} producto={record['product_id']}")
    except Exception as exc:
        log("feedback", f"No se pudo pedir feedback al asistente ({assistant_url}): {exc}")


def _handle_registrar_valoracion(
    opinions_db: list[dict],
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Plan: RegistrarOpinionProducto — completa un registro pendiente con puntuacion y comentario."""
    valoracion = next(graph.objects(action, ECSDI.notificacionTieneValoracion), None)
    if valoracion is None:
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
    record["fecha_valoracion"] = datetime.now().isoformat(timespec="seconds")
    save_json("opinions.json", opinions_db)

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


def _handle_recommendations(
    opinions_db: list[dict],
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
) -> Graph:
    """Devuelve productos candidatos a partir de valoraciones conocidas."""
    graph = Graph()
    bind_namespaces(graph)
    response = DATA[f"response/recomendaciones/{uuid4()}"]
    graph.add((response, RDF.type, ECSDI.RespuestaProductosCandidatos))
    graph.add((response, ECSDI.respuestaDeAccion, action))

    candidates = [r for r in opinions_db if r.get("puntuacion") is not None]
    candidates.sort(key=lambda r: int(r.get("puntuacion") or 0), reverse=True)
    if not candidates:
        candidates = opinions_db[-3:]

    seen = set()
    for record in candidates[:3]:
        product_id = record["product_id"]
        if product_id in seen:
            continue
        seen.add(product_id)
        product = URIRef(record["product_uri"])
        recommendation = DATA[f"recomendacion/{uuid4()}"]
        score = record.get("puntuacion") or 3
        graph.add((product, RDF.type, ECSDI.Producto))
        graph.add((product, ECSDI.idProducto, Literal(product_id)))
        graph.add((recommendation, RDF.type, ECSDI.Recomendacion))
        graph.add((recommendation, ECSDI.recomendacionDeProducto, product))
        graph.add((recommendation, ECSDI.recomendacionParaAsistente, receiver))
        graph.add((recommendation, ECSDI.puntosRecomendacion, Literal(str(score), datatype=XSD.decimal)))
        graph.add((recommendation, ECSDI.motivoRecomendacion, Literal("Candidato basado en historial de compras y valoraciones")))
        graph.add((recommendation, ECSDI.fechaRecomendacion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    log("feedback", f"Recomendaciones generadas: {len(seen)} candidato(s)")
    return build_message(graph, response, ACL.inform, agent_uri, receiver)


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
    parser.add_argument("--assistant-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_FEEDBACK", advertised_host, args.port)
    assistant_base = args.assistant_url or search_service(args.dir, "AGENTE_ASISTENTE", service_id) or "http://127.0.0.1:9010"
    assistant_url = _comm_url(assistant_base)
    registered = register_service(args.dir, service_id, "AGENTE_FEEDBACK", address, f"feedback-{args.port}")
    try:
        log(f"feedback-{args.port}", f"listening on {bind_host}:{args.port}, assistant={assistant_url}")
        create_app(assistant_url=assistant_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"feedback-{args.port}")


def _comm_url(base_url: str) -> str:
    return base_url if base_url.endswith("/comm") else base_url.rstrip("/") + "/comm"


if __name__ == "__main__":
    main()
