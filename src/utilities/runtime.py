import logging
import socket
import time

import requests
from requests import ConnectionError
from rdflib import Graph, Literal
from rdflib.namespace import FOAF, RDF


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


def register_service(directory_url: str | None, service_id: str, service_type: str, address: str, prefix: str) -> bool:
    """Registra el agente en el directorio via FIPA-ACL (DSO.RegistrarAgente).
    Usando post_graph en lugar de GET con query string.
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
    graph.add((action, FOAF.name, Literal(service_id)))
    graph.add((action, DSO.Address, Literal(address)))
    graph.add((action, DSO.AgentType, Literal(service_type)))
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


def search_service(directory_url: str | None, service_type: str) -> str | None:
    """Busca un agente por tipo en el directorio via FIPA-ACL (DSO.BuscarAgente).
    Respuesta esperada: ACL.inform con DSO.RespuestaBusqueda que contiene DSO.Address.
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
        graph.add((action, DSO.AgentType, Literal(service_type)))
        message = build_message(graph, action, ACL.request, AGENTS.Unknown, AGENTS.DirectoryService)
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