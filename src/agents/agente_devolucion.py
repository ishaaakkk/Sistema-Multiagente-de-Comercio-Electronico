import argparse
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from flask import Flask, jsonify
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import (
    build_completed_order_info_request,
    build_reembolso_request,
)
from utilities.catalog import decimal_literal, product_uri
from utilities.comm import comm_url as _comm_url
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
from utilities.storage import load_json, save_json, save_named_graph


DEFAULT_AGENT_URI = AGENTS.AgenteDevolucion
RETURN_WINDOW_DAYS = 15
DEFAULT_PICKUP_DAYS = int(os.environ.get("DEVOLUCION_PICKUP_DAYS", "1"))


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    shop_url="http://127.0.0.1:9001/comm",
    financiero_url="http://127.0.0.1:9005/comm",
):
    app = Flask(__name__)
    devoluciones_db: list[dict] = load_json("devoluciones.json", [])

    @app.get("/")
    def index():
        return "AgenteDevolucion listo"

    @app.get("/status")
    def status():
        return jsonify({"total": len(devoluciones_db), "devoluciones": devoluciones_db})

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido"))
            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))
            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content
            if (action, RDF.type, ECSDI.SolicitarDevolucion) in graph:
                return reply(
                    _handle_devolucion(
                        devoluciones_db,
                        agent_uri,
                        message.sender,
                        action,
                        graph,
                        shop_url,
                        financiero_url,
                    )
                )

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteDevolucion"))
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_devolucion(
    devoluciones_db: list[dict],
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    request_graph: Graph,
    shop_url: str,
    financiero_url: str,
) -> Graph:
    devolucion, pedido, product, motivo = _extract_request(request_graph, action)
    if pedido is None or product is None:
        return build_failure(agent_uri, receiver, action, "Faltan pedido o producto en SolicitarDevolucion")

    order_graph = _fetch_order_info(agent_uri, pedido, request_graph, shop_url)
    if order_graph is None:
        return _build_resolution(
            agent_uri,
            receiver,
            action,
            devolucion,
            pedido,
            product,
            motivo,
            accepted=False,
            reason="No se ha encontrado el pedido completado para validar la devolucion",
        )

    line = _find_order_line(order_graph, pedido, product)
    if line is None:
        return _build_resolution(
            agent_uri,
            receiver,
            action,
            devolucion,
            pedido,
            product,
            motivo,
            accepted=False,
            reason="El producto no pertenece al pedido indicado",
        )

    delivery_date = _extract_delivery_date(order_graph) or _extract_datetime(order_graph, pedido, ECSDI.fechaPedido)
    fallback_reception = _extract_reception_hint(motivo)
    if not _return_allowed(motivo, delivery_date or fallback_reception):
        return _build_resolution(
            agent_uri,
            receiver,
            action,
            devolucion,
            pedido,
            product,
            motivo,
            accepted=False,
            reason=f"El motivo indicado exige estar dentro de los {RETURN_WINDOW_DAYS} dias desde la recepcion",
        )

    pickup_graph = _simulate_mensajeria_interna(devolucion, pedido, product)
    pickup_date = _pickup_date_from_graph(pickup_graph) or datetime.now() + timedelta(days=DEFAULT_PICKUP_DAYS)
    log(
        "devolucion",
        f"Mensajeria interna (mock): recogida confirmada pedido={_pedido_id(order_graph, pedido)} "
        f"fecha={pickup_date.isoformat(timespec='seconds')}",
    )

    importe = _line_amount(order_graph, line, product)
    reembolso_graph = _request_reembolso(agent_uri, financiero_url, devolucion, pedido, product, importe)
    if reembolso_graph is None:
        return _build_resolution(
            agent_uri,
            receiver,
            action,
            devolucion,
            pedido,
            product,
            motivo,
            accepted=False,
            reason="Recogida confirmada, pero no se pudo confirmar el reembolso con el AgenteFinanciero",
            pickup_date=pickup_date,
            pickup_graph=pickup_graph,
        )

    response = _build_resolution(
        agent_uri,
        receiver,
        action,
        devolucion,
        pedido,
        product,
        motivo,
        accepted=True,
        reason="Devolucion aceptada",
        importe=importe,
        pickup_date=pickup_date,
        reembolso_graph=reembolso_graph,
        pickup_graph=pickup_graph,
    )
    devoluciones_db.append(
        {
            "pedido_id": _pedido_id(order_graph, pedido),
            "product_id": _product_id(order_graph, product),
            "motivo": motivo,
            "aceptada": True,
            "importe": str(importe),
            "fecha_recogida": pickup_date.isoformat(timespec="seconds"),
            "reembolso_confirmado": True,
        }
    )
    save_json("devoluciones.json", devoluciones_db)
    _persist_devoluciones_rdf(devoluciones_db)
    log("devolucion", f"Devolucion aceptada pedido={_pedido_id(order_graph, pedido)} producto={_product_id(order_graph, product)} importe={importe}")
    return response


def _extract_request(graph: Graph, action: URIRef) -> tuple[URIRef, URIRef | None, URIRef | None, str]:
    devolucion = next(graph.subjects(RDF.type, ECSDI.Devolucion), None)
    if devolucion is None:
        devolucion = DATA[f"devolucion/DEV-{uuid4().hex[:8].upper()}"]
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    product = next(graph.objects(action, ECSDI.accionSobreProducto), None)
    if pedido is None:
        pedido = next(graph.objects(devolucion, ECSDI.devolucionDePedido), None)
    if product is None:
        product = next(graph.objects(devolucion, ECSDI.devolucionDeProducto), None)
    motivo = str(next(graph.objects(devolucion, ECSDI.motivoDevolucion), "Producto defectuoso"))
    return devolucion, pedido, product, motivo


def _fetch_order_info(agent_uri: URIRef, pedido: URIRef, request_graph: Graph, shop_url: str) -> Graph | None:
    pedido_id = _pedido_id(request_graph, pedido)
    if not pedido_id:
        return None
    try:
        message = build_completed_order_info_request(agent_uri, AGENTS.AgenteComerciante, pedido_id)
        response = post_graph(shop_url, message)
        msg = get_message(response)
        if msg and msg.performative == ACL.inform:
            return response
    except Exception as exc:
        log("devolucion", f"No se pudo consultar pedido en comerciante: {exc}")

    # Permite demos unitarias en las que el propio mensaje trae el grafo del pedido.
    if list(request_graph.objects(pedido, ECSDI.pedidoTieneLinea)):
        return request_graph
    return None


def _request_reembolso(
    agent_uri: URIRef,
    financiero_url: str,
    devolucion: URIRef,
    pedido: URIRef,
    product: URIRef,
    importe: Decimal,
) -> Graph | None:
    try:
        message = build_reembolso_request(agent_uri, AGENTS.AgenteFinanciero, devolucion, pedido, product, importe)
        response = post_graph(financiero_url, message)
        msg = get_message(response)
        if msg and msg.performative == ACL.inform:
            return response
    except Exception as exc:
        log("devolucion", f"No se pudo solicitar reembolso: {exc}")
    return None


def _simulate_mensajeria_interna(
    devolucion: URIRef,
    pedido: URIRef,
    product: URIRef,
    pickup_days: int = DEFAULT_PICKUP_DAYS,
) -> Graph:
    """Mock MensajeriaInternaConfirma (PDT): siempre confirma y devuelve fecha de recogida."""

    pickup_date = datetime.now() + timedelta(days=pickup_days)
    graph = Graph()
    bind_namespaces(graph)
    envio = DATA[f"envio/devolucion/{uuid4()}"]
    graph.add((devolucion, RDF.type, ECSDI.Devolucion))
    graph.add((devolucion, ECSDI.devolucionDePedido, pedido))
    graph.add((devolucion, ECSDI.devolucionDeProducto, product))
    graph.add(
        (
            devolucion,
            ECSDI.fechaRecogidaDevolucion,
            Literal(pickup_date.isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )
    graph.add((envio, RDF.type, ECSDI.EnvioDevolucion))
    graph.add((envio, ECSDI.envioDePedido, pedido))
    graph.add((envio, ECSDI.envioRealizadoPor, AGENTS.MensajeriaInterna))
    graph.add((envio, RDFS.comment, Literal(f"TRACK-DEV-{uuid4().hex[:10].upper()}")))
    return graph


def _build_resolution(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    devolucion: URIRef,
    pedido: URIRef,
    product: URIRef,
    motivo: str,
    accepted: bool,
    reason: str,
    importe: Decimal | None = None,
    pickup_date: datetime | None = None,
    reembolso_graph: Graph | None = None,
    pickup_graph: Graph | None = None,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    response = DATA[f"response/devolucion/{uuid4()}"]

    graph.add((devolucion, RDF.type, ECSDI.Devolucion))
    graph.add((devolucion, ECSDI.devolucionDePedido, pedido))
    graph.add((devolucion, ECSDI.devolucionDeProducto, product))
    graph.add((devolucion, ECSDI.motivoDevolucion, Literal(motivo)))
    graph.add((devolucion, ECSDI.devolucionAceptada, Literal(accepted, datatype=XSD.boolean)))
    graph.add((devolucion, ECSDI.fechaSolicitudDevolucion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))
    graph.add((devolucion, ECSDI.instruccionesDevolucion, Literal(reason if not accepted else "Entregar el paquete al mensajero asignado en la fecha indicada.")))
    if pickup_date is not None:
        graph.add((devolucion, ECSDI.fechaRecogidaDevolucion, Literal(pickup_date.isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    graph.add((response, RDF.type, ECSDI.ResolucionDevolucion))
    graph.add((response, ECSDI.respuestaDeAccion, action))
    graph.add((response, ECSDI.resolucionDeDevolucion, devolucion))
    graph.add((response, RDFS.comment, Literal(reason)))

    if importe is not None:
        graph.add((response, ECSDI.importeOperacion, decimal_literal(importe)))

    if reembolso_graph is not None:
        _add_business_triples(reembolso_graph, graph)
        operacion = next(reembolso_graph.subjects(RDF.type, ECSDI.ReembolsoCliente), None)
        if operacion is not None:
            graph.add((devolucion, ECSDI.devolucionTieneReembolso, operacion))

    if pickup_graph is not None:
        _add_business_triples(pickup_graph, graph)

    if accepted and not list(graph.subjects(RDF.type, ECSDI.EnvioDevolucion)):
        envio = DATA[f"envio/devolucion/{uuid4()}"]
        graph.add((envio, RDF.type, ECSDI.EnvioDevolucion))
        graph.add((envio, ECSDI.envioDePedido, pedido))
        graph.add((envio, ECSDI.envioRealizadoPor, AGENTS.MensajeriaInterna))

    return build_message(graph, response, ACL.inform, sender, receiver)


_FIND_LINE_SPARQL = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ecsdi: <http://www.semanticweb.org/ecsdi/comercio_electronico/>

SELECT ?line WHERE {
    ?pedido ecsdi:pedidoTieneLinea ?line .
    ?line   ecsdi:lineaDeProducto ?lineProduct .
    OPTIONAL { ?lineProduct ecsdi:idProducto ?lineProductId }
    FILTER (
        ?lineProduct = ?product ||
        (BOUND(?productId) && BOUND(?lineProductId) && STR(?lineProductId) = STR(?productId))
    )
}
LIMIT 1
"""


def _find_order_line(graph: Graph, pedido: URIRef, product: URIRef) -> URIRef | None:
    """Encuentra la línea del pedido que contiene el producto solicitado.

    Implementado como SPARQL SELECT (cap. 6) sobre el grafo del pedido. Si la
    URI del producto no coincide, busca por idProducto en una OPTIONAL.
    """

    init_bindings = {"pedido": pedido, "product": product}
    target_id = _product_id(graph, product)
    if target_id:
        init_bindings["productId"] = Literal(target_id)
    for row in graph.query(_FIND_LINE_SPARQL, initBindings=init_bindings):
        return row.line
    return None


def _add_business_triples(source: Graph, target: Graph) -> None:
    for triple in source:
        s, p, _ = triple
        if p in (ACL.performative, ACL.sender, ACL.receiver, ACL.content):
            continue
        if (s, RDF.type, ACL.FipaAclMessage) in source:
            continue
        target.add(triple)


def _line_amount(graph: Graph, line: URIRef, product: URIRef) -> Decimal:
    quantity = int(next(graph.objects(line, ECSDI.cantidad), 1))
    price = next(graph.objects(line, ECSDI.precioUnitario), None)
    if price is None:
        price = next(graph.objects(product, ECSDI.precioProducto), "0")
    return Decimal(str(price)) * quantity


def _return_allowed(motivo: str, delivery_date: datetime | None) -> bool:
    normalized = motivo.casefold()
    immediate_reasons = ("defect", "defectuos", "equivoc", "incorrect", "roto", "dany", "dañ")
    if any(reason in normalized for reason in immediate_reasons):
        return True
    expectation_reasons = ("no satisface", "expectativa", "expectation", "no cumple")
    if any(reason in normalized for reason in expectation_reasons):
        if delivery_date is None:
            return False
        return datetime.now() <= delivery_date + timedelta(days=RETURN_WINDOW_DAYS)
    if delivery_date is None:
        return True
    return datetime.now() <= delivery_date + timedelta(days=RETURN_WINDOW_DAYS)


def _extract_reception_hint(motivo: str) -> datetime | None:
    marker = "recepcion="
    idx = motivo.find(marker)
    if idx < 0:
        return None
    raw = motivo[idx + len(marker):].split(")", 1)[0].strip()
    if not raw:
        return None
    # Acepta fechas en formato YYYY-MM-DD desde la interfaz.
    return _parse_datetime(f"{raw}T00:00:00")


def _extract_delivery_date(graph: Graph) -> datetime | None:
    from utilities.transport_proto import iter_transport_offers, offer_delivery_datetime

    for offer in iter_transport_offers(graph):
        value = offer_delivery_datetime(graph, offer)
        if value is not None:
            parsed = _parse_datetime(str(value))
            if parsed is not None:
                return parsed
    return None


def _pickup_date_from_graph(graph: Graph | None) -> datetime | None:
    if graph is None:
        return None
    for devolucion in graph.subjects(RDF.type, ECSDI.Devolucion):
        value = next(graph.objects(devolucion, ECSDI.fechaRecogidaDevolucion), None)
        if value is not None:
            parsed = _parse_datetime(str(value))
            if parsed is not None:
                return parsed
    return None


def _extract_datetime(graph: Graph, subject: URIRef, predicate: URIRef) -> datetime | None:
    value = next(graph.objects(subject, predicate), None)
    return _parse_datetime(str(value)) if value is not None else None


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _pedido_id(graph: Graph, pedido: URIRef | None) -> str:
    if pedido is None:
        return ""
    value = next(graph.objects(pedido, ECSDI.idPedido), None)
    if value is not None:
        return str(value)
    uri = str(pedido)
    return uri.rsplit("/pedido/", 1)[-1] if "/pedido/" in uri else uri.rsplit("/", 1)[-1]


def _product_id(graph: Graph, product: URIRef | None) -> str:
    if product is None:
        return ""
    value = next(graph.objects(product, ECSDI.idProducto), None)
    if value is not None:
        return str(value)
    uri = str(product)
    return uri.rsplit("/producto/", 1)[-1] if "/producto/" in uri else uri.rsplit("/", 1)[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9009)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--shop-url", default=None)
    parser.add_argument("--financiero-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_DEVOLUCION", advertised_host, args.port)

    shop_base = args.shop_url or search_service(args.dir, "AGENTE_COMERCIANTE", service_id) or "http://127.0.0.1:9001"
    financiero_base = args.financiero_url or search_service(args.dir, "AGENTE_FINANCIERO", service_id) or "http://127.0.0.1:9005"
    shop_url = _comm_url(shop_base)
    financiero_url = _comm_url(financiero_base)
    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_DEVOLUCION",
        address,
        f"devolucion-{args.port}",
        capabilities=[ECSDI.SolicitarDevolucion],
    )
    try:
        log(
            f"devolucion-{args.port}",
            f"listening on {bind_host}:{args.port}, shop={shop_url}, financiero={financiero_url}, "
            f"mensajeria=mock({DEFAULT_PICKUP_DAYS}d)",
        )
        create_app(shop_url=shop_url, financiero_url=financiero_url).run(
            host=bind_host, port=args.port, debug=False, use_reloader=False
        )
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"devolucion-{args.port}")


def _persist_devoluciones_rdf(devoluciones_db: list[dict]) -> None:
    """Espejo RDF (Dataset común) de las devoluciones almacenadas en JSON."""

    graph = Graph()
    bind_namespaces(graph)
    for idx, record in enumerate(devoluciones_db):
        node = DATA[f"devolucion/{record.get('pedido_id','')}/{record.get('product_id','')}/{idx}"]
        graph.add((node, RDF.type, ECSDI.Devolucion))
        if record.get("pedido_id"):
            pedido = DATA[f"pedido/{record['pedido_id']}"]
            graph.add((pedido, RDF.type, ECSDI.Pedido))
            graph.add((pedido, ECSDI.idPedido, Literal(record["pedido_id"])))
            graph.add((node, ECSDI.devolucionDePedido, pedido))
        if record.get("product_id"):
            product = product_uri(record["product_id"])
            graph.add((product, RDF.type, ECSDI.Producto))
            graph.add((product, ECSDI.idProducto, Literal(record["product_id"])))
            graph.add((node, ECSDI.devolucionDeProducto, product))
        if record.get("motivo"):
            graph.add((node, ECSDI.motivoDevolucion, Literal(record["motivo"])))
        if record.get("aceptada") is not None:
            graph.add((node, ECSDI.devolucionAceptada, Literal(record["aceptada"], datatype=XSD.boolean)))
        if record.get("importe"):
            operacion = DATA[f"pago/reembolso/{record.get('pedido_id','')}/{record.get('product_id','')}/{idx}"]
            graph.add((operacion, RDF.type, ECSDI.ReembolsoCliente))
            graph.add((operacion, ECSDI.importeOperacion, decimal_literal(Decimal(str(record["importe"])))))
            graph.add((operacion, ECSDI.estadoOperacion, Literal("confirmada")))
            graph.add((node, ECSDI.devolucionTieneReembolso, operacion))
        if record.get("fecha_recogida"):
            graph.add((node, ECSDI.fechaRecogidaDevolucion, Literal(record["fecha_recogida"], datatype=XSD.dateTime)))
    save_named_graph("returns", graph)


if __name__ == "__main__":
    main()
