import argparse
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import build_transport_offer
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.transport_proto import find_transport_offer, set_offer_accepted
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

# Tarifas por defecto (se sobreescriben via argparse)
DEFAULT_TARIFA_BASE = Decimal("4.50")
DEFAULT_TARIFA_KG = Decimal("1.75")
DEFAULT_TARIFA_DIA = Decimal("0.80")


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    tarifa_base: Decimal = DEFAULT_TARIFA_BASE,
    tarifa_kg: Decimal = DEFAULT_TARIFA_KG,
    tarifa_dia: Decimal = DEFAULT_TARIFA_DIA,
):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return (
            f"TransportistaAgent listo — "
            f"tarifa_base={tarifa_base} €, tarifa_kg={tarifa_kg} €/kg, tarifa_dia={tarifa_dia} €/dia"
        )

    @app.post("/comm")
    def comm():
        # Plan: ProponerEnvioTransportistas → SeleccionOfertaIniciales (AgenteLogistico / NegociarConTransportistas)
        # Accion: DemanarOfertaTransport — CFP con comandaId/producteId/ciutatDesti
        # y accionSobreLote; responde OfertaTransport (1 ronda, sin contraoferta).
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido"))
            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))

            # Cierre de Contract Net: aceptaciones y rechazos son informativos para el
            # transportista; permiten al ganador comprometer recursos y al perdedor liberarlos.
            if message.performative in (ACL["accept-proposal"], ACL["reject-proposal"]):
                offer = find_transport_offer(graph)
                if offer is not None:
                    accepted = message.performative == ACL["accept-proposal"]
                    set_offer_accepted(graph, offer, accepted)
                    outcome = "ACEPTADA" if accepted else "RECHAZADA"
                    log(str(agent_uri).split("/")[-1], f"Contract Net cierre: oferta {outcome} ({offer})")
                    return reply(build_message(graph, offer, ACL.inform, agent_uri, message.sender))

            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content
            if (action, RDF.type, ECSDI.SolicitarRecogidaDevolucion) in graph:
                return reply(_handle_recogida_devolucion(agent_uri, message.sender, action, graph))

            if (action, RDF.type, ECSDI.DemanarOfertaTransport) not in graph:
                return reply(build_not_understood(agent_uri, message.sender, "Accion de transporte no soportada"))

            lote = next(graph.objects(action, ECSDI.accionSobreLote), None)
            if lote is None:
                return reply(build_failure(agent_uri, message.sender, action, "Falta el lote de envio"))

            weight = Decimal(str(next(graph.objects(lote, ECSDI.pesoTotalLote), "1.0")))
            priority = int(next(graph.objects(lote, ECSDI.prioridadLote), 3))
            max_days = _days_for_priority(priority)

            # Precio = tarifa_base + peso * tarifa_kg + dias * tarifa_dia
            price = tarifa_base + weight * tarifa_kg + Decimal(max_days) * tarifa_dia

            log(
                str(agent_uri).split("/")[-1],
                f"Oferta: peso={weight}kg prioridad={priority} dias={max_days} precio={price:.2f}€"
            )

            response = build_transport_offer(
                sender=URIRef(agent_uri),
                receiver=message.sender,
                action=action,
                lote_graph=graph,
                lote=lote,
                transportista=URIRef(agent_uri),
                price=price.quantize(Decimal("0.01")),
                max_days=max_days,
            )
            return reply(response)
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    return app


def _handle_recogida_devolucion(agent_uri: URIRef, receiver: URIRef, action: URIRef, graph: Graph) -> Graph:
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    product = next(graph.objects(action, ECSDI.accionSobreProducto), None)
    devolucion = next(graph.subjects(RDF.type, ECSDI.Devolucion), None)
    if devolucion is None:
        devolucion = DATA[f"devolucion/{datetime.now().timestamp()}"]

    pickup_date = datetime.now() + timedelta(days=1)
    response_graph = Graph()
    bind_namespaces(response_graph)
    envio = DATA[f"envio/devolucion/{datetime.now().timestamp()}"]
    response_graph.add((devolucion, RDF.type, ECSDI.Devolucion))
    response_graph.add((devolucion, ECSDI.fechaRecogidaDevolucion, Literal(pickup_date.isoformat(timespec="seconds"), datatype=XSD.dateTime)))
    if pedido is not None:
        response_graph.add((devolucion, ECSDI.devolucionDePedido, pedido))
        response_graph.add((envio, ECSDI.envioDePedido, pedido))
    if product is not None:
        response_graph.add((devolucion, ECSDI.devolucionDeProducto, product))
    response_graph.add((envio, RDF.type, ECSDI.EnvioDevolucion))
    response_graph.add((envio, ECSDI.envioRealizadoPor, URIRef(agent_uri)))

    log(str(agent_uri).split("/")[-1], f"Recogida devolucion aceptada: pedido={pedido} producto={product}")
    return build_message(response_graph, devolucion, ACL.inform, agent_uri, receiver)


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
    # Tarifas configurables para poder lanzar multiples instancias con condiciones distintas
    parser.add_argument(
        "--tarifa-base", type=Decimal, default=DEFAULT_TARIFA_BASE,
        help="Coste fijo por envio en euros (default: 4.50)",
    )
    parser.add_argument(
        "--tarifa-kg", type=Decimal, default=DEFAULT_TARIFA_KG,
        help="Coste por kg en euros (default: 1.75)",
    )
    parser.add_argument(
        "--tarifa-dia", type=Decimal, default=DEFAULT_TARIFA_DIA,
        help="Coste adicional por dia de plazo en euros (default: 0.80)",
    )
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("TRANSPORTISTA", advertised_host, args.port)
    agent_uri = AGENTS[service_id]
    registered = register_service(
        args.dir,
        service_id,
        "TRANSPORTISTA",
        address,
        f"transportista-{args.port}",
        capabilities=[
            ECSDI.DemanarOfertaTransport,
            ECSDI.SolicitarRecogidaDevolucion,
        ],
    )
    try:
        log(
            f"transportista-{args.port}",
            f"listening on {bind_host}:{args.port} — "
            f"tarifa_base={args.tarifa_base}€ tarifa_kg={args.tarifa_kg}€/kg tarifa_dia={args.tarifa_dia}€/dia"
        )
        create_app(
            agent_uri=agent_uri,
            tarifa_base=args.tarifa_base,
            tarifa_kg=args.tarifa_kg,
            tarifa_dia=args.tarifa_dia,
        ).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"transportista-{args.port}")


if __name__ == "__main__":
    main()
