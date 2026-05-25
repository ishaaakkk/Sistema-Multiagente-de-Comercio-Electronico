import json
from pathlib import Path

from rdflib import Graph

from .namespaces import bind_namespaces


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_json(name: str, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(name: str, value) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_graph(name: str) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    path = DATA_DIR / name
    if path.exists():
        graph.parse(path, format="turtle")
    return graph


def save_graph(name: str, graph: Graph) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(DATA_DIR / name), format="turtle")


def load_graph_collection(folder: str) -> dict[str, Graph]:
    base = DATA_DIR / folder
    result: dict[str, Graph] = {}
    if not base.exists():
        return result
    for path in base.glob("*.ttl"):
        graph = Graph()
        bind_namespaces(graph)
        graph.parse(path, format="turtle")
        result[path.stem] = graph
    return result


def save_graph_item(folder: str, key: str, graph: Graph) -> None:
    base = DATA_DIR / folder
    base.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(base / f"{_safe_name(key)}.ttl"), format="turtle")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
