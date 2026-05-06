import logging
import socket
import time

import requests
from requests import ConnectionError


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
    if not directory_url:
        return False

    message = f"REGISTER|{service_id},{service_type},{address}"
    for _ in range(60):
        try:
            response = requests.get(f"{directory_url}/message", params={"message": message}, timeout=2).text
            if response.startswith("OK"):
                log(prefix, f"registered as {service_type} at {address}")
                return True
            log(prefix, f"directory rejected registration: {response}")
            return False
        except ConnectionError:
            time.sleep(0.2)
    log(prefix, "directory registration timed out")
    return False


def unregister_service(directory_url: str | None, service_id: str, prefix: str) -> None:
    if not directory_url:
        return
    try:
        requests.get(f"{directory_url}/message", params={"message": f"UNREGISTER|{service_id}"}, timeout=2)
        log(prefix, "unregistered from directory")
    except Exception as exc:
        log(prefix, f"could not unregister cleanly: {exc}")


def search_service(directory_url: str | None, service_type: str) -> str | None:
    if not directory_url:
        return None
    try:
        response = requests.get(f"{directory_url}/message", params={"message": f"SEARCH|{service_type}"}, timeout=4).text
        if response.startswith("OK: "):
            return response[4:]
    except Exception:
        return None
    return None
