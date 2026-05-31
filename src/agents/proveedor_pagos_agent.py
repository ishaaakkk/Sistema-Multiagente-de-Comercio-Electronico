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
        return "ProveedorPagosAgent listo"

    @app.post("/comm")
    def comm():
        # Plan: CobrarAlUsuario / ReembolsoAlUsuario / PagarProdsExternos (AgenteFinanciero)
        # Percepción: ConfirmacionTransaccionProveedorPagos
        # El ProveedorPagos es externo al sistema multiagente; simula el cobro real
        # y devuelve ConfirmacionTransaccion al AgenteFinanciero.
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

            # Accion: Realizar Transaccion — simula el cobro y genera ConfirmacionTransaccion
            operation_type = _operation_type(graph, operacion)
            metodo_pago = next(graph.objects(action, ECSDI.metodoPago), None)
            if metodo_pago is None:
                metodo_pago = next(graph.objects(operacion, ECSDI.metodoPago), None)
            response = _build_confirmacion(agent_uri, message.sender, action, operacion, operation_type, importe, metodo_pago)
            log("pagos", f"Operacion confirmada: {importe} EUR para operacion {operacion}")
            return reply(response)

        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AgenteFinanciero, None, str(exc)), status=500)

    return app


def _build_confirmacion(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    operacion: URIRef,
    operation_type: URIRef,
    importe: Decimal,
    metodo_pago=None,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)

    confirmacion = DATA[f"response/pago/{uuid4()}"]
    graph.add((confirmacion, RDF.type, ECSDI.ConfirmacionTransaccion))
    graph.add((confirmacion, ECSDI.confirmacionDeOperacion, operacion))
    graph.add((confirmacion, ECSDI.respuestaDeAccion, action))

    # Actualizamos el estado de la operación en el grafo de respuesta
    graph.add((operacion, RDF.type, operation_type))
    graph.add((operacion, ECSDI.idOperacionPago, Literal(f"OP-{uuid4().hex[:8].upper()}")))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("confirmada")))
    graph.add((operacion, ECSDI.referenciaPago, Literal(f"PAY-{uuid4().hex[:10].upper()}")))
    graph.add((operacion, ECSDI.fechaOperacion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))
    if metodo_pago is not None:
        graph.add((operacion, ECSDI.metodoPago, Literal(str(metodo_pago))))

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
