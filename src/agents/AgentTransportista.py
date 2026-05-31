"""Transportista del grupo externo, adaptado al runtime ECSDI (directorio + Turtle ACL).

Mantiene la logica de precio fijo del agente original; solo cambia el arranque,
el registro en el directorio y el intercambio RDF con el Centro Logistico.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from uuid import uuid4

from flask import Flask
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import (
    build_failure,
    build_message,
    build_not_understood,
    correlate_reply,
    get_message,
)
from utilities.catalog import decimal_literal
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECOM, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    unregister_service,
)
from utilities.transport_proto import (
    build_oferta_transport_message,
    extract_cfp_from_lote,
    find_transport_offer,
    set_offer_accepted,
)

DEFAULT_PORT = 9013
DEFAULT_PREU = Decimal("5.50")
DEFAULT_DIES = 3


def create_app(
    agent_uri: URIRef,
    transportista_entity: URIRef,
    preu: Decimal = DEFAULT_PREU,
    dies: int = DEFAULT_DIES,
):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return (
            f"AgentTransportista (externo) — preu={preu} EUR, dies={dies} | "
            f"ontologia ecom:DemanarOfertaTransport / ecom:OfertaTransport"
        )

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(
                    build_not_understood(agent_uri, AGENTS.CentroLogisticoBarcelona, "Mensaje ACL no reconocido")
                )

            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))

            # Cierre Contract Net (1 ronda): actualizar ecom:acceptada
            if message.performative in (ACL["accept-proposal"], ACL["reject-proposal"]):
                offer = find_transport_offer(graph)
                if offer is not None:
                    accepted = message.performative == ACL["accept-proposal"]
                    set_offer_accepted(graph, offer, accepted)
                    log(
                        str(agent_uri).split("/")[-1],
                        f"Oferta {'ACEPTADA' if accepted else 'RECHAZADA'}",
                    )
                    return reply(build_message(graph, offer, ACL.inform, agent_uri, message.sender))
                return reply(build_not_understood(agent_uri, message.sender, "Oferta no encontrada"))

            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba request o accept/reject-proposal"))

            action = message.content
            if (action, RDF.type, ECOM.DemanarOfertaTransport) not in graph:
                return reply(build_not_understood(agent_uri, message.sender, "Accion DemanarOfertaTransport esperada"))

            lote = next(graph.objects(action, ECSDI.accionSobreLote), None)
            if lote is not None:
                comanda_id, product_id, city = extract_cfp_from_lote(graph, lote)
            else:
                comanda_id = str(next(graph.objects(action, ECOM.comandaId), ""))
                product_id = str(next(graph.objects(action, ECOM.producteId), ""))
                city = str(next(graph.objects(action, ECOM.ciutatDesti), "Barcelona"))

            if not comanda_id or not product_id:
                return reply(build_failure(agent_uri, message.sender, action, "Faltan comandaId o producteId"))

            if lote is None:
                lote_graph = Graph()
                bind_namespaces(lote_graph)
                lote = DATA[f"lote/extern/{uuid4()}"]
                lote_graph.add((lote, RDF.type, ECSDI.LoteEnvio))
                lote_graph.add((lote, ECSDI.idLote, Literal(comanda_id)))
                lote_graph.add((lote, ECSDI.pesoTotalLote, decimal_literal(Decimal("1"))))
                lote_graph.add((lote, ECSDI.prioridadLote, Literal(3, datatype=XSD.integer)))
                address = DATA[f"direccion/extern/{uuid4()}"]
                product = DATA[f"producto/{product_id}"]
                line = DATA[f"linea/extern/{uuid4()}"]
                lote_graph.add((lote, ECSDI.loteDestinoDireccion, address))
                lote_graph.add((address, ECSDI.ciudad, Literal(city)))
                lote_graph.add((lote, ECSDI.loteTieneLinea, line))
                lote_graph.add((line, ECSDI.lineaDeProducto, product))
                lote_graph.add((product, ECSDI.idProducto, Literal(product_id)))
            else:
                lote_graph = graph

            log(
                str(agent_uri).split("/")[-1],
                f"Oferta {preu} EUR / {dies} dies — {comanda_id} {product_id} -> {city}",
            )
            return reply(
                build_oferta_transport_message(
                    agent_uri,
                    message.sender,
                    action,
                    lote_graph,
                    lote,
                    transportista_entity,
                    preu,
                    dies,
                )
            )
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.CentroLogisticoBarcelona, None, str(exc)), status=500)

    return app


def main():
    parser = argparse.ArgumentParser(description="Transportista externo (grupo ecsdipractica)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--dir", default=None, help="URL del directorio (ej. http://127.0.0.1:9000)")
    parser.add_argument("--preu", type=float, default=float(DEFAULT_PREU))
    parser.add_argument("--dies", type=int, default=DEFAULT_DIES)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("TRANSPORTISTA", advertised_host, args.port)
    agent_uri = AGENTS[service_id]
    transportista_entity = ECOM[f"transportista-{args.port}"]

    preu = Decimal(str(args.preu)).quantize(Decimal("0.01"))
    registered = register_service(
        args.dir,
        service_id,
        "TRANSPORTISTA",
        address,
        f"transportista-extern-{args.port}",
        capabilities=[ECOM.DemanarOfertaTransport],
    )
    try:
        log(
            f"transportista-extern-{args.port}",
            f"listening on {bind_host}:{args.port} — preu={preu} EUR dies={args.dies} dir={args.dir}",
        )
        create_app(agent_uri=agent_uri, transportista_entity=transportista_entity, preu=preu, dies=args.dies).run(
            host=bind_host,
            port=args.port,
            debug=False,
            use_reloader=False,
        )
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"transportista-extern-{args.port}")


if __name__ == "__main__":
    main()
