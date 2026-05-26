import argparse
import time
from threading import Thread

from flask import Flask
from rdflib.namespace import RDF

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import build_external_product_registration
from utilities.comm import comm_url as _comm_url
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
            def reply(response_graph):
                return rdf_response(correlate_reply(response_graph, message))
            if message.performative != ACL.request:
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request"))

            action = message.content

            # Accion: ComunicarProductosExternosPedidos
            if (action, RDF.type, ECSDI.ComunicarProductosExternosPedidos) in graph:
                return reply(_handle_aviso_envio(agent_uri, message.sender, action, graph))

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteVendedorExterno"))
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


def _default_external_products():
    return [
        {
            "id": "P-CARGADOR-GAN",
            "nombre": "Cargador GaN 65W",
            "marca": "Voltix",
            "descripcion": "Cargador USB-C de 65W anunciado por vendedor externo",
            "precio": "29.90",
            "valoracion": "4.4",
            "peso": "0.18",
            "gestion_envio_externo": True,
        }
    ]


def _announce_products_delayed(
    directory_url: str | None,
    catalog_url: str | None,
    service_id: str,
    agent_uri,
    products: list[dict],
    retries: int = 30,
    delay_seconds: float = 1.0,
) -> None:
    """Anuncia productos externos al catálogo cuando el catálogo esté disponible."""

    for attempt in range(1, retries + 1):
        target_base = catalog_url
        if not target_base and directory_url:
            target_base = search_service(
                directory_url,
                "AGENTE_CATALOGO",
                service_id,
                capability=ECSDI.DarAltaProductoExterno,
            )

        if target_base:
            try:
                target_url = _comm_url(target_base)
                message = build_external_product_registration(
                    agent_uri,
                    AGENTS.AgenteCatalogo,
                    products,
                )
                response = post_graph(target_url, message)
                msg = get_message(response)
                if msg and msg.performative == ACL.inform:
                    log("vendedor_externo", f"Alta externa enviada al catálogo ({len(products)} producto(s))")
                    return
                log("vendedor_externo", f"Alta externa rechazada: {msg.performative if msg else 'sin ACL'}")
            except Exception as exc:
                log("vendedor_externo", f"Alta externa pendiente ({attempt}/{retries}): {exc}")

        time.sleep(delay_seconds)

    log("vendedor_externo", "No se pudo anunciar productos externos al catálogo")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9008)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--catalog-url", default=None)
    parser.add_argument("--announce-products", action="store_true", default=False)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_VENDEDOR_EXTERNO", advertised_host, args.port)
    agent_uri = AGENTS[service_id]
    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_VENDEDOR_EXTERNO",
        address,
        f"vendedor-externo-{args.port}",
        capabilities=[ECSDI.ComunicarProductosExternosPedidos],
    )
    if args.announce_products:
        Thread(
            target=_announce_products_delayed,
            args=(
                args.dir,
                args.catalog_url,
                service_id,
                agent_uri,
                _default_external_products(),
            ),
            daemon=True,
        ).start()
    try:
        log(f"vendedor-externo-{args.port}", f"listening on {bind_host}:{args.port}")
        create_app(agent_uri=agent_uri).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"vendedor-externo-{args.port}")


if __name__ == "__main__":
    main()
