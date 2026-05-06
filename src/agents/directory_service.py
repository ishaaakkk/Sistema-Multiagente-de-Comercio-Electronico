import argparse
import json
from random import randint

from flask import Flask, jsonify, request

from utilities.runtime import binding_from_args, configure_flask_logging, log


def create_app(schedule: str = "equaljobs"):
    app = Flask(__name__)
    directory: dict[str, tuple[str, str]] = {}
    loadbalance: dict[str, int] = {}
    prefix = "directorio"

    @app.get("/")
    def index():
        return "DirectoryService listo"

    @app.get("/message")
    def message():
        raw = request.args.get("message", "")
        if "|" not in raw:
            return "ERROR: INVALID MESSAGE"

        msg_type, params = raw.split("|", 1)
        if msg_type == "REGISTER":
            parts = params.split(",", 2)
            if len(parts) != 3:
                return "ERROR: REGISTER INVALID PARAMETERS"
            service_id, service_type, address = parts
            if service_id in directory:
                return "ERROR: ID ALREADY REGISTERED"
            directory[service_id] = (service_type, address)
            loadbalance[service_id] = 0
            log(prefix, f"REGISTER {service_id} type={service_type} @ {address}")
            return "OK: REGISTER SUCCESS"

        if msg_type == "SEARCH":
            found = [(sid, address) for sid, (stype, address) in directory.items() if stype == params]
            if not found:
                log(prefix, f"SEARCH {params} -> NOT FOUND")
                return "ERROR: NOT FOUND"
            if schedule == "equaljobs":
                selected = min(found, key=lambda item: loadbalance[item[0]])
            elif schedule == "random":
                selected = found[randint(0, len(found) - 1)]
            else:
                selected = found[0]
            loadbalance[selected[0]] += 1
            log(prefix, f"SEARCH {params} -> {selected[0]} @ {selected[1]}")
            return "OK: " + selected[1]

        if msg_type == "SEARCHALL":
            found = [address for _, (stype, address) in directory.items() if stype == params]
            if not found:
                return "ERROR: NOT FOUND"
            return "OK: " + json.dumps(found)

        if msg_type == "UNREGISTER":
            if params not in directory:
                return "ERROR: NOT REGISTERED"
            log(prefix, f"UNREGISTER {params}")
            del directory[params]
            loadbalance.pop(params, None)
            return "OK: UNREGISTER SUCCESS"

        return "ERROR: NO SUCH ACTION"

    @app.get("/info")
    def info():
        return jsonify(
            {
                sid: {
                    "type": stype,
                    "address": address,
                    "jobs": loadbalance.get(sid, 0),
                }
                for sid, (stype, address) in directory.items()
            }
        )

    return app


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
