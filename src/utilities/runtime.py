import logging
import socket
import time

import requests
from requests import ConnectionError
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF


def log(prefix: str, message: str) -> None:
    print(f"[{prefix}] {message}", flush=True)


def configure_flask_logging(verbose: bool) -> None:
    if not verbose:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)


def binding_from_args(open_server: bool, host: str, hostaddr: str | None) -> tuple[str, str]:
    if open_server:
        bind_host = "0.0.0.0"
        advertised_host = hostaddr if hostaddr else socket.gethostname()
    else:
        bind_host = host
        advertised_host = hostaddr if hostaddr else host
    return bind_host, advertised_host


def agent_address(hostaddr: str, port: int) -> str:
    return f"http://{hostaddr}:{port}"


def agent_id(service_type: str, hostaddr: str, port: int) -> str:
    safe_host = hostaddr.replace(".", "-").replace(":", "-")
    return f"{service_type.lower()}-{safe_host}-{port}"


def register_service(
    directory_url: str | None,
    service_id: str,
    service_type: str,
    address: str,
    prefix: str,
    capabilities: list[URIRef] | None = None,
) -> bool:
    """Registra el agente en el directorio via FIPA-ACL (DSO.RegistrarAgente).

    `capabilities` es una lista opcional de URIs de la ontología (por ejemplo
    `ECSDI.BuscarProductos`) que el agente declara saber atender. Esto
    aproxima el registro a un perfil de servicio OWL-S (cap. 8.5.2 de los
    apuntes) y permite buscar agentes por capacidad además de por tipo.

    Respuesta esperada: ACL.confirm.
    """

    if not directory_url:
        return False

    from utilities.acl import build_message, get_message
    from utilities.http import post_graph
    from utilities.namespaces import ACL, AGENTS, DATA, DSO, bind_namespaces
    from uuid import uuid4

    agent_uri = AGENTS[service_id]
    comm_url = directory_url if directory_url.endswith("/comm") else directory_url.rstrip("/") + "/comm"

    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"directory/register/{uuid4()}"]
    graph.add((action, RDF.type, DSO.RegistrarAgente))
    graph.add((action, DSO.Uri, agent_uri))
    graph.add((action, DSO.Name, Literal(service_id)))
    graph.add((action, DSO.Address, Literal(address)))
    graph.add((action, DSO.AgentType, Literal(service_type)))
    for capability in capabilities or []:
        graph.add((action, DSO.Capability, capability))
    message = build_message(graph, action, ACL.request, agent_uri, AGENTS.DirectoryService)

    for _ in range(60):
        try:
            response = post_graph(comm_url, message)
            msg = get_message(response)
            if msg and msg.performative == ACL.confirm:
                log(prefix, f"registered as {service_type} at {address}")
                return True
            log(prefix, f"directory rejected registration: {msg.performative if msg else 'no message'}")
            return False
        except ConnectionError:
            time.sleep(0.2)
        except Exception as exc:
            log(prefix, f"registration error: {exc}")
            return False

    log(prefix, "directory registration timed out")
    return False


def unregister_service(directory_url: str | None, service_id: str, prefix: str) -> None:
    """Elimina el agente del directorio via FIPA-ACL (DSO.EliminarAgente)."""
    if not directory_url:
        return

    from utilities.acl import build_message
    from utilities.http import post_graph
    from utilities.namespaces import ACL, AGENTS, DATA, DSO, bind_namespaces
    from uuid import uuid4

    agent_uri = AGENTS[service_id]
    comm_url = directory_url if directory_url.endswith("/comm") else directory_url.rstrip("/") + "/comm"

    try:
        graph = Graph()
        bind_namespaces(graph)
        action = DATA[f"directory/unregister/{uuid4()}"]
        graph.add((action, RDF.type, DSO.EliminarAgente))
        graph.add((action, DSO.Uri, agent_uri))
        message = build_message(graph, action, ACL.request, agent_uri, AGENTS.DirectoryService)
        post_graph(comm_url, message)
        log(prefix, "unregistered from directory")
    except Exception as exc:
        log(prefix, f"could not unregister cleanly: {exc}")


def search_service(
    directory_url: str | None,
    service_type: str | None = None,
    requester: str | URIRef | None = None,
    capability: URIRef | None = None,
) -> str | None:
    """Busca un agente por tipo o capacidad en el directorio.

    Si se pasa `capability` (URI), el directorio filtra adicionalmente por
    `dso:Capability` declarada en el registro (perfil de servicio OWL-S,
    cap. 8.5.2). Respuesta esperada: ACL.inform con DSO.RespuestaBusqueda.
    """
    if not directory_url:
        return None

    from utilities.acl import build_message, get_message
    from utilities.http import post_graph
    from utilities.namespaces import ACL, AGENTS, DATA, DSO, bind_namespaces
    from uuid import uuid4

    comm_url = directory_url if directory_url.endswith("/comm") else directory_url.rstrip("/") + "/comm"

    try:
        graph = Graph()
        bind_namespaces(graph)
        action = DATA[f"directory/search/{uuid4()}"]
        graph.add((action, RDF.type, DSO.BuscarAgente))
        if service_type is not None:
            graph.add((action, DSO.AgentType, Literal(service_type)))
        if capability is not None:
            graph.add((action, DSO.Capability, capability))
        message = build_message(graph, action, ACL.request, _requester_uri(requester), AGENTS.DirectoryService)
        response = post_graph(comm_url, message)

        msg = get_message(response)
        if msg and msg.performative == ACL.inform:
            result = next(response.subjects(RDF.type, DSO.RespuestaBusqueda), None)
            if result is not None:
                address = next(response.objects(result, DSO.Address), None)
                if address is not None:
                    return str(address)
    except Exception:
        return None
    return None


def search_all_services(
    directory_url: str | None,
    service_type: str | None = None,
    requester: str | URIRef | None = None,
    capability: URIRef | None = None,
) -> list[str]:
    """Busca TODOS los agentes de un tipo o capacidad en el directorio.

    A diferencia de search_service (que devuelve uno con balanceo de carga),
    esta función devuelve las direcciones de todos los agentes registrados.
    Soporta filtrado por capacidad (URI de la ontología) además de por
    `agent_type`.

    Respuesta esperada: ACL.inform con uno o mas DSO.RespuestaBusqueda.
    """

    if not directory_url:
        return []

    from utilities.acl import build_message, get_message
    from utilities.http import post_graph
    from utilities.namespaces import ACL, AGENTS, DATA, DSO, bind_namespaces
    from uuid import uuid4

    comm_url = directory_url if directory_url.endswith("/comm") else directory_url.rstrip("/") + "/comm"

    try:
        graph = Graph()
        bind_namespaces(graph)
        action = DATA[f"directory/search/all/{uuid4()}"]
        graph.add((action, RDF.type, DSO.BuscarTodosAgentes))
        if service_type is not None:
            graph.add((action, DSO.AgentType, Literal(service_type)))
        if capability is not None:
            graph.add((action, DSO.Capability, capability))
        message = build_message(graph, action, ACL.request, _requester_uri(requester), AGENTS.DirectoryService)
        response = post_graph(comm_url, message)

        msg = get_message(response)
        if msg and msg.performative == ACL.inform:
            addresses = []
            for result in response.subjects(RDF.type, DSO.RespuestaBusqueda):
                address = next(response.objects(result, DSO.Address), None)
                if address is not None:
                    addresses.append(str(address))
            return addresses
    except Exception:
        return []
    return []


def _requester_uri(requester: str | URIRef | None) -> URIRef:
    if requester is None:
        from utilities.namespaces import AGENTS
        return AGENTS.Unknown
    if isinstance(requester, URIRef):
        return requester
    from utilities.namespaces import AGENTS
    return AGENTS[requester]
