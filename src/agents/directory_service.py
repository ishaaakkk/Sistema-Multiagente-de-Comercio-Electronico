import argparse
import json
from random import randint
from uuid import uuid4

from flask import Flask, jsonify
from rdflib import Graph, Literal
from rdflib.namespace import FOAF, RDF

from utilities.acl import build_message, build_not_understood, get_message, parse_graph, serialize_graph
from utilities.http import graph_from_request, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, DSO, bind_namespaces
from utilities.runtime import binding_from_args, configure_flask_logging, log


def create_app(schedule: str = "equaljobs"):
    app = Flask(__name__)

    # Grafo RDF de registro — equivalente al dsgraph del profesor
    dsgraph = Graph()
    bind_namespaces(dsgraph)

    loadbalance: dict[str, int] = {}
    prefix = "directorio"

    @app.get("/")
    def index():
        return "DirectoryService listo"

    @app.post("/comm")
    def comm():
        """Punto de entrada FIPA-ACL para registro y busqueda de agentes.

        Acciones soportadas:
          DSO.RegistrarAgente   — registra un agente en el directorio
          DSO.BuscarAgente      — busca un agente por tipo (con balanceo de carga)
          DSO.BuscarTodosAgentes — devuelve TODOS los agentes de un tipo
          DSO.EliminarAgente    — elimina un agente del directorio
        """
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(build_not_understood(AGENTS.DirectoryService, message.sender if message else AGENTS.Unknown, "Mensaje ACL no reconocido"))
            if message.performative != ACL.request:
                return rdf_response(build_not_understood(AGENTS.DirectoryService, message.sender, "Se esperaba performativa request"))

            action = message.content

            if (action, RDF.type, DSO.RegistrarAgente) in graph:
                return rdf_response(_handle_register(dsgraph, loadbalance, graph, action, message.sender, prefix))

            if (action, RDF.type, DSO.BuscarAgente) in graph:
                return rdf_response(_handle_search(dsgraph, loadbalance, graph, action, message.sender, schedule, prefix))

            # Nueva accion: devuelve todos los agentes del tipo indicado
            if (action, RDF.type, DSO.BuscarTodosAgentes) in graph:
                return rdf_response(_handle_search_all(dsgraph, graph, action, message.sender, prefix))

            if (action, RDF.type, DSO.EliminarAgente) in graph:
                return rdf_response(_handle_unregister(dsgraph, loadbalance, graph, action, message.sender, prefix))

            return rdf_response(build_not_understood(AGENTS.DirectoryService, message.sender, "Accion de directorio no reconocida"))

        except Exception as exc:
            log(prefix, f"ERROR en /comm: {exc}")
            return rdf_response(build_not_understood(AGENTS.DirectoryService, AGENTS.Unknown, str(exc)), 500)

    @app.get("/info")
    def info():
        """Muestra el estado del directorio en formato JSON."""
        agents = {}
        for agent_uri in set(dsgraph.subjects(RDF.type, FOAF.Agent)):
            name = str(next(dsgraph.objects(agent_uri, FOAF.name), ""))
            address = str(next(dsgraph.objects(agent_uri, DSO.Address), ""))
            agent_type = str(next(dsgraph.objects(agent_uri, DSO.AgentType), ""))
            agents[str(agent_uri)] = {
                "name": name,
                "type": agent_type,
                "address": address,
                "jobs": loadbalance.get(str(agent_uri), 0),
            }
        return jsonify(agents)

    return app


def _handle_register(dsgraph, loadbalance, graph, action, sender, prefix):
    """Registra un agente en el directorio RDF.

    Acepta opcionalmente una o varias `dso:Capability` cuyo valor es una URI
    de la ontología ECSDI (por ejemplo `ecsdi:BuscarEnCatalogo`). Esto
    aproxima el registro a un perfil de servicio OWL-S (cap. 8.5.2 de los
    apuntes): un agente declara qué acciones de la ontología sabe atender.
    """

    agent_uri = next(graph.objects(action, DSO.Uri), None)
    agent_name = next(graph.objects(action, FOAF.name), None)
    agent_address = next(graph.objects(action, DSO.Address), None)
    agent_type = next(graph.objects(action, DSO.AgentType), None)

    if None in (agent_uri, agent_name, agent_address, agent_type):
        return _build_response(ACL.failure, action, sender, "Faltan campos en RegistrarAgente")

    if (agent_uri, RDF.type, FOAF.Agent) in dsgraph:
        return _build_response(ACL.failure, action, sender, f"Agente ya registrado: {agent_uri}")

    dsgraph.add((agent_uri, RDF.type, FOAF.Agent))
    dsgraph.add((agent_uri, FOAF.name, agent_name))
    dsgraph.add((agent_uri, DSO.Address, agent_address))
    dsgraph.add((agent_uri, DSO.AgentType, agent_type))
    capabilities = list(graph.objects(action, DSO.Capability))
    for capability in capabilities:
        dsgraph.add((agent_uri, DSO.Capability, capability))
    loadbalance[str(agent_uri)] = 0

    log(
        prefix,
        f"REGISTER {agent_name} type={agent_type} caps={[str(c) for c in capabilities]} @ {agent_address}",
    )
    return _build_response(ACL.confirm, action, sender)


def _handle_search(dsgraph, loadbalance, graph, action, sender, schedule, prefix):
    """Busca un agente por tipo o capacidad (con balanceo de carga).

    Si la acción incluye `dso:Capability` (URI de la ontología), filtra
    además por la capacidad declarada por el agente en el registro. Devuelve
    una sola dirección.
    """
    agent_type = next(graph.objects(action, DSO.AgentType), None)
    requested_capability = next(graph.objects(action, DSO.Capability), None)
    if agent_type is None and requested_capability is None:
        return _build_response(ACL.failure, action, sender, "Falta DSO.AgentType o DSO.Capability en BuscarAgente")

    if requested_capability is not None:
        candidates_by_cap = {
            uri for uri in dsgraph.subjects(DSO.Capability, requested_capability)
            if (uri, RDF.type, FOAF.Agent) in dsgraph
        }
    else:
        candidates_by_cap = None

    if agent_type is not None:
        candidates_by_type = {
            uri for uri in dsgraph.subjects(DSO.AgentType, agent_type)
            if (uri, RDF.type, FOAF.Agent) in dsgraph
        }
    else:
        candidates_by_type = None

    if candidates_by_cap is not None and candidates_by_type is not None:
        candidates = list(candidates_by_cap & candidates_by_type)
    else:
        candidates = list(candidates_by_cap or candidates_by_type or [])

    if not candidates:
        log(prefix, f"SEARCH {agent_type} -> NOT FOUND")
        return _build_response(ACL.failure, action, sender, f"No hay agentes de tipo {agent_type}")

    if schedule == "equaljobs":
        selected = min(candidates, key=lambda u: loadbalance.get(str(u), 0))
    elif schedule == "random":
        selected = candidates[randint(0, len(candidates) - 1)]
    else:
        selected = candidates[0]

    loadbalance[str(selected)] = loadbalance.get(str(selected), 0) + 1
    address = next(dsgraph.objects(selected, DSO.Address), None)

    log(prefix, f"SEARCH {agent_type} -> {selected} @ {address}")

    response_graph = Graph()
    bind_namespaces(response_graph)
    result = DATA[f"directory/response/{uuid4()}"]
    response_graph.add((result, RDF.type, DSO.RespuestaBusqueda))
    response_graph.add((result, DSO.Uri, selected))
    response_graph.add((result, DSO.Address, address))
    response_graph.add((result, DSO.AgentType, agent_type))
    return build_message(response_graph, result, ACL.inform, AGENTS.DirectoryService, sender)


def _handle_search_all(dsgraph, graph, action, sender, prefix):
    """Devuelve TODOS los agentes registrados de un tipo o capacidad.

    Soporta también filtrado por `dso:Capability` (URI), siguiendo el mismo
    criterio que `_handle_search`. Usado por el centro logístico para
    contactar con todos los transportistas y comparar sus ofertas.
    """
    agent_type = next(graph.objects(action, DSO.AgentType), None)
    requested_capability = next(graph.objects(action, DSO.Capability), None)
    if agent_type is None and requested_capability is None:
        return _build_response(ACL.failure, action, sender, "Falta DSO.AgentType o DSO.Capability en BuscarTodosAgentes")

    if requested_capability is not None:
        candidates_by_cap = {
            uri for uri in dsgraph.subjects(DSO.Capability, requested_capability)
            if (uri, RDF.type, FOAF.Agent) in dsgraph
        }
    else:
        candidates_by_cap = None

    if agent_type is not None:
        candidates_by_type = {
            uri for uri in dsgraph.subjects(DSO.AgentType, agent_type)
            if (uri, RDF.type, FOAF.Agent) in dsgraph
        }
    else:
        candidates_by_type = None

    if candidates_by_cap is not None and candidates_by_type is not None:
        candidates = list(candidates_by_cap & candidates_by_type)
    else:
        candidates = list(candidates_by_cap or candidates_by_type or [])

    if not candidates:
        log(prefix, f"SEARCH_ALL {agent_type} -> NOT FOUND")
        return _build_response(ACL.failure, action, sender, f"No hay agentes de tipo {agent_type}")

    response_graph = Graph()
    bind_namespaces(response_graph)

    # Un nodo raiz para el mensaje; los resultados individuales cuelgan de el
    root = DATA[f"directory/response/all/{uuid4()}"]
    response_graph.add((root, RDF.type, DSO.RespuestaBusquedaMultiple))
    response_graph.add((root, DSO.AgentType, agent_type))

    for uri in candidates:
        address = next(dsgraph.objects(uri, DSO.Address), None)
        if address is None:
            continue
        result = DATA[f"directory/response/{uuid4()}"]
        response_graph.add((result, RDF.type, DSO.RespuestaBusqueda))
        response_graph.add((result, DSO.Uri, uri))
        response_graph.add((result, DSO.Address, address))
        response_graph.add((result, DSO.AgentType, agent_type))
        response_graph.add((root, DSO.resultadoContiene, result))

    log(prefix, f"SEARCH_ALL {agent_type} -> {len(candidates)} agente(s)")
    return build_message(response_graph, root, ACL.inform, AGENTS.DirectoryService, sender)


def _handle_unregister(dsgraph, loadbalance, graph, action, sender, prefix):
    """Elimina un agente del directorio RDF."""
    agent_uri = next(graph.objects(action, DSO.Uri), None)
    if agent_uri is None:
        return _build_response(ACL.failure, action, sender, "Falta DSO.Uri en EliminarAgente")

    if (agent_uri, RDF.type, FOAF.Agent) not in dsgraph:
        return _build_response(ACL.failure, action, sender, f"Agente no registrado: {agent_uri}")

    dsgraph.remove((agent_uri, None, None))
    loadbalance.pop(str(agent_uri), None)
    log(prefix, f"UNREGISTER {agent_uri}")
    return _build_response(ACL.confirm, action, sender)


def _build_response(performative, action, receiver, reason=None):
    graph = Graph()
    bind_namespaces(graph)
    response = DATA[f"directory/ack/{uuid4()}"]
    graph.add((response, RDF.type, DSO.RespuestaDirectorio))
    graph.add((response, DSO.respuestaDeAccion, action))
    if reason:
        from rdflib import Literal
        graph.add((response, DSO.motivo, Literal(reason)))
    return build_message(graph, response, performative, AGENTS.DirectoryService, receiver)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--schedule", choices=["equaljobs", "random", "first"], default="equaljobs")
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    log("directorio", f"listening on {bind_host}:{args.port}, advertised host={advertised_host}")
    create_app(schedule=args.schedule).run(host=bind_host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()