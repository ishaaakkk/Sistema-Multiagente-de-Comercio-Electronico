import argparse
from datetime import datetime
from decimal import Decimal
from threading import Thread
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, get_message
from utilities.catalog import decimal_literal
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


DEFAULT_AGENT_URI = AGENTS.AgenteFinanciero


def create_app(agent_uri=DEFAULT_AGENT_URI):
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
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Capacidad CobrarAlUsuario — Plan: RealizarCobro
            # Msg entrante: SolicitarCobro (AgenteComerciante → AgenteFinanciero)
            if (action, RDF.type, ECSDI.SolicitarCobro) in graph:
                return _handle_cobro(graph, agent_uri, message.sender, action)

            # Capacidad ReembolsoAlUsuario — Plan: ReembolsoAlUsuario (pendiente de implementar)
            # Msg entrante: SolicitarReembolso (AgenteDevolucion → AgenteFinanciero)
            if (action, RDF.type, ECSDI.SolicitarReembolso) in graph:
                return rdf_response(
                    build_not_understood(agent_uri, message.sender, "ReembolsoAlUsuario: pendiente de implementar")
                )

            # Capacidad PagarProdsExternos — Plan: PagarProdsExternos (pendiente de implementar)
            # Msg entrante: PagarProdExterno (AgenteComerciante → AgenteFinanciero)
            if (action, RDF.type, ECSDI.PagarProductoExterno) in graph:
                return rdf_response(
                    build_not_understood(agent_uri, message.sender, "PagarProdsExternos: pendiente de implementar")
                )

            return rdf_response(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteFinanciero"))

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AgenteComerciante, None, str(exc)), status=500)

    return app


def _handle_cobro(graph, agent_uri, sender, action):
    """Plan: RealizarCobro (AgenteComerciante / FinalizarCompra).

    Recibe SolicitarCobro del Comerciante una vez el pedido ya esta en envio.
    Fire-and-forget: ACK inmediato; la transaccion con el proveedor externo
    se simula en hilo separado. Se asume que siempre va bien (diseno).
    """
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    importe = next(graph.objects(action, ECSDI.importeCobro), None)

    if pedido is None or importe is None:
        return rdf_response(build_failure(agent_uri, sender, action, "Faltan pedido o importe en SolicitarCobro"))

    # Accion: Realizar Transaccion — se lanza en hilo para no bloquear la respuesta
    Thread(
        target=_realizar_transaccion,
        args=(pedido, Decimal(str(importe))),
        daemon=True,
    ).start()

    log("financiero", f"Cobro iniciado para pedido {pedido}, importe {importe}")

    # ACK inmediato — NotificarCobroFinalizado interno hacia FinalizarPedido
    ack = build_message(graph, action, ACL.inform, agent_uri, sender)
    return rdf_response(ack)


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
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_FINANCIERO", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "AGENTE_FINANCIERO", address, f"financiero-{args.port}")
    try:
        log(f"financiero-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app().run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"financiero-{args.port}")


if __name__ == "__main__":
    main()