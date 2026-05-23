import argparse

from flask import Flask
from rdflib.namespace import RDF

from utilities.acl import build_failure, build_message, build_not_understood, get_message
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


DEFAULT_AGENT_URI = AGENTS.AgenteVendedorExterno


def create_app(agent_uri=DEFAULT_AGENT_URI):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "AgenteVendedorExterno listo"

    @app.post("/comm")
    def comm():
        # Capacidad: ComunicarConVendedoresExternos (AgenteComerciante)
        # Accion entrante: ComunicarProductosExternosPedidos
        # El comerciante notifica que debe enviarse un producto a una direccion concreta.
        # Se asume que el vendedor siempre puede hacerse cargo (diseño: fire-and-forget).
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(
                    build_not_understood(agent_uri, AGENTS.AgenteComerciante, "Mensaje ACL no reconocido")
                )
            if message.performative != ACL.request:
                return rdf_response(
                    build_not_understood(agent_uri, message.sender, "Se esperaba performativa request")
                )

            action = message.content

            # Accion: ComunicarProductosExternosPedidos
            if (action, RDF.type, ECSDI.ComunicarProductosExternosPedidos) in graph:
                return rdf_response(_handle_aviso_envio(agent_uri, message.sender, action, graph))

            return rdf_response(
                build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteVendedorExterno")
            )
        except Exception as exc:
            return rdf_response(
                build_failure(agent_uri, AGENTS.AgenteComerciante, None, str(exc)), status=500
            )

    return app


def _handle_aviso_envio(agent_uri, sender, action, graph):
    """Percepcion: ComunicarProductosExternosPedidos.

    El comerciante indica al vendedor externo que tiene que enviar un producto
    a una direccion concreta. El vendedor confirma que gestionara el envio.
    Se asume exito siempre (diseño).
    """
    pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    product = next(graph.objects(action, ECSDI.accionSobreProducto), None)
    address = next(graph.objects(action, ECSDI.envioDestinoDir), None)

    product_id = str(next(graph.objects(product, ECSDI.idProducto), product)) if product else "desconocido"
    ciudad = str(next(graph.objects(address, ECSDI.ciudad), "")) if address else ""
    calle = str(next(graph.objects(address, ECSDI.calle), "")) if address else ""

    log(
        "vendedor_externo",
        f"Aviso recibido: pedido={pedido} producto={product_id} destino='{calle}, {ciudad}'"
        f" — envio aceptado (simulado)",
    )

    # ACK: inform confirmando que se hara cargo del envio
    return build_message(graph, action, ACL.inform, agent_uri, sender)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9008)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_VENDEDOR_EXTERNO", advertised_host, args.port)
    registered = register_service(args.dir, service_id, "AGENTE_VENDEDOR_EXTERNO", address, f"vendedor-externo-{args.port}")
    try:
        log(f"vendedor-externo-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app().run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"vendedor-externo-{args.port}")


if __name__ == "__main__":
    main()