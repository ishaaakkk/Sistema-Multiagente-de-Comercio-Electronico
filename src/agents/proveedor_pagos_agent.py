import argparse
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.catalog import decimal_literal
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.payment import mask_card, normalize_card_digits, payment_method_label, validate_card_payment
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    unregister_service,
)


DEFAULT_AGENT_URI = AGENTS.ProveedorPagos


def create_app(agent_uri=DEFAULT_AGENT_URI):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "ProveedorPagosAgent listo (cobro con tarjeta / paypal / transferencia)"

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, AGENTS.AgenteFinanciero, "Mensaje ACL no reconocido"))

            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))

            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content
            if (action, RDF.type, ECSDI.SolicitarOperacionPago) not in graph:
                return reply(build_not_understood(agent_uri, message.sender, "Accion de pago no soportada"))

            operacion = next(graph.objects(action, ECSDI.accionTieneOperacionPago), None)
            if operacion is None:
                return reply(build_failure(agent_uri, message.sender, action, "Falta la operacion de pago"))

            importe = Decimal(str(next(graph.objects(operacion, ECSDI.importeOperacion), "0")))
            if importe <= 0:
                return reply(build_failure(agent_uri, message.sender, action, "Importe de pago invalido"))

            operation_type = _operation_type(graph, operacion)
            metodo_pago = _read_metodo_pago(graph, action, operacion)
            tarjeta = _read_tarjeta(graph, action, operacion)

            error = _validate_payment(metodo_pago, tarjeta)
            if error:
                log("pagos", f"Operacion rechazada: {error} ({payment_method_label(metodo_pago, tarjeta)})")
                return reply(build_failure(agent_uri, message.sender, action, error))

            response = _build_confirmacion(
                agent_uri,
                message.sender,
                action,
                operacion,
                operation_type,
                importe,
                metodo_pago,
                tarjeta,
            )
            log(
                "pagos",
                f"Operacion confirmada: {importe} EUR — {payment_method_label(metodo_pago, tarjeta)} ref operacion {operacion}",
            )
            return reply(response)

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AgenteFinanciero, None, str(exc)), status=500)

    return app


def _read_metodo_pago(graph: Graph, action: URIRef, operacion: URIRef) -> str:
    for subject in (action, operacion):
        value = next(graph.objects(subject, ECSDI.metodoPago), None)
        if value is not None:
            return str(value).strip().lower()
    return "tarjeta"


def _read_tarjeta(graph: Graph, action: URIRef, operacion: URIRef) -> str:
    for subject in (action, operacion):
        value = next(graph.objects(subject, ECSDI.tarjeta), None)
        if value is not None:
            return normalize_card_digits(str(value))
    return ""


def _validate_payment(metodo_pago: str, tarjeta: str) -> str | None:
    method = (metodo_pago or "tarjeta").strip().lower()
    if method == "tarjeta":
        ok, message = validate_card_payment(tarjeta)
        return None if ok else message
    if method in ("paypal", "transferencia"):
        return None
    return f"Metodo de pago no soportado: {metodo_pago}"


def _build_confirmacion(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    operacion: URIRef,
    operation_type: URIRef,
    importe: Decimal,
    metodo_pago: str,
    tarjeta: str = "",
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)

    confirmacion = DATA[f"response/pago/{uuid4()}"]
    graph.add((confirmacion, RDF.type, ECSDI.ConfirmacionTransaccion))
    graph.add((confirmacion, ECSDI.confirmacionDeOperacion, operacion))
    graph.add((confirmacion, ECSDI.respuestaDeAccion, action))

    graph.add((operacion, RDF.type, operation_type))
    graph.add((operacion, ECSDI.idOperacionPago, Literal(f"OP-{uuid4().hex[:8].upper()}")))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("confirmada")))
    graph.add((operacion, ECSDI.referenciaPago, Literal(f"PAY-{uuid4().hex[:10].upper()}")))
    graph.add((operacion, ECSDI.fechaOperacion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))
    graph.add((operacion, ECSDI.metodoPago, Literal(metodo_pago)))
    if tarjeta:
        graph.add((operacion, ECSDI.tarjeta, Literal(mask_card(tarjeta))))

    return build_message(graph, confirmacion, ACL.inform, sender, receiver)


def _operation_type(graph: Graph, operacion: URIRef) -> URIRef:
    for operation_type in (ECSDI.CobroCliente, ECSDI.ReembolsoCliente, ECSDI.PagoVendedorExterno):
        if (operacion, RDF.type, operation_type) in graph:
            return operation_type
    return ECSDI.CobroCliente


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9004)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("PROVEEDOR_PAGOS", advertised_host, args.port)
    registered = register_service(
        args.dir,
        service_id,
        "PROVEEDOR_PAGOS",
        address,
        f"pagos-{args.port}",
        capabilities=[ECSDI.SolicitarOperacionPago],
    )
    try:
        log(f"pagos-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app().run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"pagos-{args.port}")


if __name__ == "__main__":
    main()
