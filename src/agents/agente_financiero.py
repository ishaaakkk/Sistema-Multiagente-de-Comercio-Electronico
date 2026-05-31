import argparse
from datetime import datetime
from decimal import Decimal
from threading import Thread
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import build_provider_payment_request
from utilities.catalog import decimal_literal
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


DEFAULT_AGENT_URI = AGENTS.AgenteFinanciero


def create_app(agent_uri=DEFAULT_AGENT_URI, provider_url: str | None = None):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "AgenteFinanciero listo"

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

            # Capacidad CobrarAlUsuario — Plan: RealizarCobro
            # Msg entrante: SolicitarCobro (AgenteComerciante → AgenteFinanciero)
            if (action, RDF.type, ECSDI.SolicitarCobro) in graph:
                return reply(_handle_cobro(graph, agent_uri, message.sender, action, provider_url))

            # Capacidad ReembolsoAlUsuario — Plan: ReembolsoAlUsuario
            # Msg entrante: SolicitarReembolso (AgenteDevolucion → AgenteFinanciero)
            if (action, RDF.type, ECSDI.SolicitarReembolso) in graph:
                return reply(_handle_operacion_pago(graph, agent_uri, message.sender, action, ECSDI.ReembolsoCliente, "reembolso", provider_url))

            # Capacidad PagarProdsExternos — Plan: PagarProdsExternos
            # Msg entrante: PagarProductoExterno (AgenteComerciante → AgenteFinanciero)
            if (action, RDF.type, ECSDI.PagarProductoExterno) in graph:
                return reply(_handle_operacion_pago(graph, agent_uri, message.sender, action, ECSDI.PagoVendedorExterno, "pago_externo", provider_url))

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteFinanciero"))

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AgenteComerciante, None, str(exc)), status=500)

    return app


def _handle_cobro(graph, agent_uri, sender, action, provider_url: str | None):
    """Plan: RealizarCobro (AgenteComerciante / FinalizarCompra).

    Recibe SolicitarCobro del Comerciante una vez el pedido ya esta en envio.
    Fire-and-forget: ACK inmediato; la transaccion con el proveedor externo
    se simula en hilo separado. Se asume que siempre va bien (diseno).
    """
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    importe = next(graph.objects(action, ECSDI.importeCobro), None)
    operacion = next(graph.objects(action, ECSDI.accionTieneOperacionPago), None)

    if pedido is None or importe is None:
        return build_failure(agent_uri, sender, action, "Faltan pedido o importe en SolicitarCobro")

    # Accion: Realizar Transaccion — se lanza en hilo para no bloquear la respuesta
    amount = Decimal(str(importe))
    if provider_url and operacion is not None:
        Thread(
            target=_realizar_transaccion_proveedor,
            args=(provider_url, agent_uri, action, operacion, ECSDI.CobroCliente, amount, pedido),
            daemon=True,
        ).start()
    else:
        Thread(
            target=_realizar_transaccion,
            args=(pedido, amount),
            daemon=True,
        ).start()

    log("financiero", f"Cobro iniciado para pedido {pedido}, importe {importe}")

    # ACK inmediato — NotificarCobroFinalizado interno hacia FinalizarPedido
    return build_message(graph, action, ACL.inform, agent_uri, sender)


def _handle_operacion_pago(graph, agent_uri, sender, action, operation_type, tag, provider_url: str | None):
    """Confirma reembolsos y pagos a vendedores externos de forma simulada."""
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

    if provider_url:
        provider_response = _request_provider_payment(provider_url, agent_uri, sender, action, operacion, operation_type, amount)
        if provider_response is not None:
            log("financiero", f"{tag} confirmado por proveedor: importe={amount}")
            return provider_response
        log("financiero", f"Proveedor no disponible para {tag}; usando simulacion local")

    response_graph = Graph()
    bind_namespaces(response_graph)
    confirmation = DATA[f"response/pago/{uuid4()}"]
    response_graph.add((confirmation, RDF.type, ECSDI.ConfirmacionTransaccion))
    response_graph.add((confirmation, ECSDI.confirmacionDeOperacion, operacion))
    response_graph.add((confirmation, ECSDI.respuestaDeAccion, action))
    response_graph.add((operacion, RDF.type, operation_type))
    response_graph.add((operacion, ECSDI.idOperacionPago, Literal(f"OP-{uuid4().hex[:8].upper()}")))
    response_graph.add((operacion, ECSDI.importeOperacion, decimal_literal(amount)))
    response_graph.add((operacion, ECSDI.estadoOperacion, Literal("confirmada")))
    response_graph.add((operacion, ECSDI.referenciaPago, Literal(f"PAY-{uuid4().hex[:10].upper()}")))
    response_graph.add((operacion, ECSDI.fechaOperacion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    log("financiero", f"{tag} confirmado: importe={amount} ref={next(response_graph.objects(operacion, ECSDI.referenciaPago))}")
    return build_message(response_graph, confirmation, ACL.inform, agent_uri, sender)


def _request_provider_payment(
    provider_url: str,
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
    operacion: URIRef,
    operation_type: URIRef,
    amount: Decimal,
) -> Graph | None:
    try:
        request = build_provider_payment_request(agent_uri, AGENTS.ProveedorPagos, action, operacion, operation_type, amount)
        provider_response = post_graph(provider_url, request)
        msg = get_message(provider_response)
        if not msg or msg.performative != ACL.inform:
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
        confirmation = next(response_graph.subjects(RDF.type, ECSDI.ConfirmacionTransaccion), DATA[f"response/pago/{uuid4()}"])
        response_graph.add((confirmation, ECSDI.respuestaDeAccion, action))
        response_graph.add((operacion, RDF.type, operation_type))
        return build_message(response_graph, confirmation, ACL.inform, agent_uri, receiver)
    except Exception as exc:
        log("financiero", f"Error con ProveedorPagos ({provider_url}): {exc}")
        return None


def _realizar_transaccion_proveedor(
    provider_url: str,
    agent_uri: URIRef,
    action: URIRef,
    operacion: URIRef,
    operation_type: URIRef,
    importe: Decimal,
    pedido: URIRef,
) -> None:
    response = _request_provider_payment(provider_url, agent_uri, AGENTS.AgenteComerciante, action, operacion, operation_type, importe)
    if response is None:
        _realizar_transaccion(pedido, importe)
        return
    ref = next(response.objects(operacion, ECSDI.referenciaPago), "")
    log("financiero", f"Transaccion proveedor completada: pedido={pedido} importe={importe} ref={ref}")


def _realizar_transaccion(pedido: URIRef, importe: Decimal) -> None:
    """Accion: Realizar Transaccion — Percepcion: ConfirmacionTransaccionProveedorPagos.

    Simula el cobro con el proveedor de pagos externo. En produccion aqui
    iria la llamada real a la pasarela de pago. Se asume exito siempre.
    """
    operacion = DATA[f"pago/cobro/{uuid4()}"]
    graph = Graph()
    bind_namespaces(graph)
    graph.add((operacion, RDF.type, ECSDI.CobroCliente))
    graph.add((operacion, ECSDI.idOperacionPago, Literal(f"OP-{uuid4().hex[:8].upper()}")))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("confirmada")))
    graph.add((operacion, ECSDI.referenciaPago, Literal(f"PAY-{uuid4().hex[:10].upper()}")))
    graph.add((operacion, ECSDI.fechaOperacion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    ref = next(graph.objects(operacion, ECSDI.referenciaPago))
    log("financiero", f"Transaccion completada: pedido={pedido} importe={importe} ref={ref}")


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
    provider_base = args.provider_url or search_service(args.dir, "PROVEEDOR_PAGOS", service_id)
    provider_url = _comm_url(provider_base) if provider_base else None
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
        log(f"financiero-{args.port}", f"listening on {bind_host}:{args.port}, provider={provider_url or 'simulado'}")
        create_app(provider_url=provider_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"financiero-{args.port}")


if __name__ == "__main__":
    main()
