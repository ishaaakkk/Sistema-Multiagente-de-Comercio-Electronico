import argparse
from threading import Thread

from flask import Flask
from rdflib.namespace import RDF

from utilities.acl import build_failure, build_message, build_not_understood, get_message
from utilities.builders import build_operacion_pago_request
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.namespaces import ACL, AGENTS, ECSDI
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


def create_app(agent_uri=DEFAULT_AGENT_URI, payments_url="http://127.0.0.1:9004/comm"):
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
                return rdf_response(build_not_understood(agent_uri, AGENTS.TiendaAgent, "Mensaje ACL no reconocido"))
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Capacidad CobrarAlUsuario — Plan: RealizarCobro
            # Msg entrante: SolicitarCobro (AgenteComerciante → AgenteFinanciero)
            if (action, RDF.type, ECSDI.SolicitarCobro) in graph:
                return _handle_cobro(graph, agent_uri, message.sender, action, payments_url)

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
            return rdf_response(build_failure(agent_uri, AGENTS.TiendaAgent, None, str(exc)), status=500)

    return app


def _handle_cobro(graph, agent_uri, sender, action, payments_url):
    """Plan: RealizarCobro (AgenteComerciante / FinalizarCompra).

    Recibe SolicitarCobro del Comerciante (TiendaAgent) una vez el pedido
    ya está en envío (InformarDatosEnvio → RealizarCobro en el diseño).
    Fire-and-forget: ACK inmediato al Comerciante; el cobro real al
    ProveedorPagos ocurre en hilo separado (Realizar Transaccion).
    Se asume que siempre va bien (diseño).
    """
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    importe = next(graph.objects(action, ECSDI.importeCobro), None)

    if pedido is None or importe is None:
        return rdf_response(build_failure(agent_uri, sender, action, "Faltan pedido o importe en SolicitarCobro"))

    # Plan: RealizarCobro → SolicitarCobro → ProveedorPagos (asíncrono)
    Thread(
        target=_ejecutar_cobro,
        args=(agent_uri, pedido, importe, payments_url),
        daemon=True,
    ).start()

    log("financiero", f"Cobro iniciado para pedido {pedido}, importe {importe}")

    # ACK inmediato — NotificarCobroFinalizado interno hacia FinalizarPedido
    ack = build_message(graph, action, ACL.inform, agent_uri, sender)
    return rdf_response(ack)


def _ejecutar_cobro(agent_uri, pedido, importe, payments_url):
    """Plan: CobrarAlUsuario — Accion: Realizar Transaccion (AgenteFinanciero).

    Llama al ProveedorPagos con SolicitarOperacionPago + CobroCliente
    y espera ConfirmacionTransaccionProveedorPagos (percepción del diseño).
    """
    try:
        from decimal import Decimal
        cobro_message, _ = build_operacion_pago_request(agent_uri, AGENTS.ProveedorPagos, pedido, Decimal(str(importe)))
        response = post_graph(payments_url, cobro_message)
        confirmacion = next(response.subjects(RDF.type, ECSDI.ConfirmacionTransaccion), None)
        log("financiero", f"Cobro completado para pedido {pedido}: confirmacion={confirmacion}")
    except Exception as exc:
        log("financiero", f"ERROR en cobro asíncrono para pedido {pedido}: {exc}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9005)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--payments-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    payments_base = args.payments_url or search_service(args.dir, "PROVEEDOR_PAGOS") or "http://127.0.0.1:9004"
    payments_url = payments_base if payments_base.endswith("/comm") else payments_base.rstrip("/") + "/comm"
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_FINANCIERO", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "AGENTE_FINANCIERO", address, f"financiero-{args.port}")
    try:
        log(f"financiero-{args.port}", f"listening on {bind_host}:{args.port}, payments={payments_url}")
        create_app(payments_url=payments_url).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"financiero-{args.port}")


if __name__ == "__main__":
    main()