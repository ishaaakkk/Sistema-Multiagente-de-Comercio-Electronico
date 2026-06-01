import argparse
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import build_provider_payment_request
from utilities.catalog import decimal_literal
from utilities.comm import comm_url as _comm_url
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.payment import normalize_card_digits
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


DEFAULT_AGENT_URI = AGENTS.AgenteFinanciero
DEFAULT_PROVIDER_TIMEOUT = 15.0


def create_app(agent_uri=DEFAULT_AGENT_URI, provider_url: str | None = None):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return f"AgenteFinanciero listo — proveedor={provider_url or 'no configurado'}"

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, AGENTS.AgenteComerciante, "Mensaje ACL no reconocido"))

            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))

            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            if (action, RDF.type, ECSDI.SolicitarCobro) in graph:
                return reply(_handle_cobro(graph, agent_uri, message.sender, action, provider_url))

            if (action, RDF.type, ECSDI.SolicitarReembolso) in graph:
                return reply(
                    _handle_operacion_pago(graph, agent_uri, message.sender, action, ECSDI.ReembolsoCliente, "reembolso", provider_url)
                )

            if (action, RDF.type, ECSDI.PagarProductoExterno) in graph:
                return reply(
                    _handle_operacion_pago(
                        graph, agent_uri, message.sender, action, ECSDI.PagoVendedorExterno, "pago_externo", provider_url
                    )
                )

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteFinanciero"))

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AgenteComerciante, None, str(exc)), status=500)

    return app


def _payment_fields(graph: Graph, action: URIRef, operacion: URIRef | None) -> tuple[str, str]:
    metodo = str(next(graph.objects(action, ECSDI.metodoPago), "tarjeta")).strip().lower()
    tarjeta = ""
    if operacion is not None:
        tarjeta = normalize_card_digits(str(next(graph.objects(operacion, ECSDI.tarjeta), "")))
    if not tarjeta:
        tarjeta = normalize_card_digits(str(next(graph.objects(action, ECSDI.tarjeta), "")))
    return metodo, tarjeta


def _handle_cobro(graph, agent_uri, sender, action, provider_url: str | None):
    """Cobro sincrono contra ProveedorPagos cuando esta configurado."""

    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    importe = next(graph.objects(action, ECSDI.importeCobro), None)
    operacion = next(graph.objects(action, ECSDI.accionTieneOperacionPago), None)

    if pedido is None or importe is None:
        return build_failure(agent_uri, sender, action, "Faltan pedido o importe en SolicitarCobro")

    amount = Decimal(str(importe))
    metodo_pago, tarjeta = _payment_fields(graph, action, operacion)

    if not provider_url:
        return build_failure(agent_uri, sender, action, "Proveedor de pagos no configurado")

    if operacion is None:
        return build_failure(agent_uri, sender, action, "Falta operacion de pago para el proveedor")

    provider_response = _request_provider_payment(
        provider_url, agent_uri, sender, action, operacion, ECSDI.CobroCliente, amount, metodo_pago, tarjeta
    )
    if provider_response is None:
        return build_failure(agent_uri, sender, action, "No se pudo contactar con el proveedor de pagos")

    msg = get_message(provider_response)
    if msg is None:
        return build_failure(agent_uri, sender, action, "Respuesta invalida del proveedor de pagos")
    if msg.performative == ACL.failure:
        reason = str(next(provider_response.objects(None, RDFS.comment), "")) or "Cobro rechazado por el proveedor"
        return build_failure(agent_uri, sender, action, reason)

    log("financiero", f"Cobro confirmado pedido={pedido} importe={amount} metodo={metodo_pago}")
    return provider_response


def _handle_operacion_pago(graph, agent_uri, sender, action, operation_type, tag, provider_url: str | None):
    operacion = next(graph.objects(action, ECSDI.accionTieneOperacionPago), None)
    importe = None
    if operacion is not None:
        importe = next(graph.objects(operacion, ECSDI.importeOperacion), None)
    if importe is None:
        importe = next(graph.objects(action, ECSDI.importeCobro), None)
    if importe is None:
        return build_failure(agent_uri, sender, action, "Falta importe de la operacion")

    amount = Decimal(str(importe))
    if amount <= 0:
        return build_failure(agent_uri, sender, action, "Importe de la operacion invalido")

    if operacion is None:
        operacion = DATA[f"pago/{tag}/{uuid4()}"]

    metodo_pago, tarjeta = _payment_fields(graph, action, operacion)

    if provider_url:
        provider_response = _request_provider_payment(
            provider_url, agent_uri, sender, action, operacion, operation_type, amount, metodo_pago, tarjeta
        )
        if provider_response is not None:
            msg = get_message(provider_response)
            if msg and msg.performative == ACL.failure:
                reason = str(next(provider_response.objects(None, RDFS.comment), "")) or f"{tag} rechazado"
                return build_failure(agent_uri, sender, action, reason)
            log("financiero", f"{tag} confirmado por proveedor: importe={amount}")
            return provider_response
        return build_failure(agent_uri, sender, action, "Proveedor de pagos no disponible")

    return build_failure(agent_uri, sender, action, "Proveedor de pagos no configurado")


def _request_provider_payment(
    provider_url: str,
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    operacion: URIRef,
    operation_type: URIRef,
    amount: Decimal,
    metodo_pago: str,
    tarjeta: str = "",
) -> Graph | None:
    try:
        request = build_provider_payment_request(
            agent_uri,
            AGENTS.ProveedorPagos,
            action,
            operacion,
            operation_type,
            amount,
            metodo_pago,
            tarjeta or None,
        )
        provider_response = post_graph(provider_url, request, timeout=DEFAULT_PROVIDER_TIMEOUT)
        msg = get_message(provider_response)
        if not msg:
            return None
        if msg.performative not in (ACL.inform, ACL.failure):
            return None

        response_graph = Graph()
        bind_namespaces(response_graph)
        for triple in provider_response:
            s, p, _ = triple
            if p in (ACL.performative, ACL.sender, ACL.receiver, ACL.content):
                continue
            if (s, RDF.type, ACL.FipaAclMessage) in provider_response:
                continue
            response_graph.add(triple)

        if msg.performative == ACL.failure:
            return build_message(response_graph, msg.content or action, ACL.failure, agent_uri, receiver)

        confirmation = next(response_graph.subjects(RDF.type, ECSDI.ConfirmacionTransaccion), DATA[f"response/pago/{uuid4()}"])
        response_graph.add((confirmation, ECSDI.respuestaDeAccion, action))
        response_graph.add((operacion, RDF.type, operation_type))
        return build_message(response_graph, confirmation, ACL.inform, agent_uri, receiver)
    except Exception as exc:
        log("financiero", f"Error con ProveedorPagos ({provider_url}): {exc}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9005)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--provider-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_FINANCIERO", advertised_host, args.port)
    provider_base = args.provider_url or search_service(args.dir, "PROVEEDOR_PAGOS", service_id) or "http://127.0.0.1:9004"
    provider_url = _comm_url(provider_base)
    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_FINANCIERO",
        address,
        f"financiero-{args.port}",
        capabilities=[
            ECSDI.SolicitarCobro,
            ECSDI.SolicitarReembolso,
            ECSDI.PagarProductoExterno,
        ],
    )
    try:
        log(f"financiero-{args.port}", f"listening on {bind_host}:{args.port}, provider={provider_url}")
        create_app(provider_url=provider_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"financiero-{args.port}")


if __name__ == "__main__":
    main()
