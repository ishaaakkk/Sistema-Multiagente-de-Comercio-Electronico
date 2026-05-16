import argparse
from decimal import Decimal

from flask import Flask
from rdflib import URIRef
from rdflib.namespace import RDF

from utilities.acl import build_failure, build_not_understood, get_message
from utilities.builders import build_transport_offer
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, ECSDI
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    unregister_service,
)


DEFAULT_AGENT_URI = AGENTS.TransportistaExpress


def create_app(agent_uri=DEFAULT_AGENT_URI):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "TransportistaAgent listo"

    @app.post("/comm")
    def comm():
        # Plan: ProponerEnvioTransportistas → SeleccionOfertaIniciales (AgenteLogistico / NegociarConTransportistas)
        # Accion: ProponerLoteAEntregar — recibe SolicitarPresupuestoTransporte con un LoteEnvio
        # y devuelve OfertaTransporte con precio y plazo calculados según peso y prioridad.
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido"))
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content
            if (action, RDF.type, ECSDI.SolicitarPresupuestoTransporte) not in graph:
                return rdf_response(build_not_understood(agent_uri, message.sender, "Accion de transporte no soportada"))

            lote = next(graph.objects(action, ECSDI.accionSobreLote), None)
            if lote is None:
                return rdf_response(build_failure(agent_uri, message.sender, action, "Falta el lote de envio"))

            weight = Decimal(str(next(graph.objects(lote, ECSDI.pesoTotalLote), "1.0")))
            priority = int(next(graph.objects(lote, ECSDI.prioridadLote), 3))
            max_days = _days_for_priority(priority)
            price = Decimal("4.50") + weight * Decimal("1.75") + Decimal(max_days) * Decimal("0.80")

            response = build_transport_offer(
                sender=URIRef(agent_uri),
                receiver=message.sender,
                action=action,
                lote=lote,
                transportista=URIRef(agent_uri),
                price=price.quantize(Decimal("0.01")),
                max_days=max_days,
            )
            return rdf_response(response)
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _days_for_priority(priority: int) -> int:
    if priority <= 1:
        return 1
    if priority == 2:
        return 3
    return 5


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9003)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("TRANSPORTISTA", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "TRANSPORTISTA", address, f"transportista-{args.port}")
    try:
        log(f"transportista-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app().run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"transportista-{args.port}")


if __name__ == "__main__":
    main()