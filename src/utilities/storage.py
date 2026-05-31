import json
import threading
from pathlib import Path

from rdflib import Dataset, Graph, URIRef

from .namespaces import DATA, bind_namespaces


DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Persistencia unificada como rdflib.Dataset con grafos nombrados (cap. 6).
# Aunque seguimos exponiendo `load_json`/`save_json` y los TTL individuales
# por compatibilidad, los agentes que quieran trabajar con triples en lugar
# de JSON pueden usar `save_named_graph` / `load_named_graph`, que
# materializa el almacén común en `data/dataset.trig`.
DATASET_PATH = DATA_DIR / "dataset.trig"
_DATASET_LOCK = threading.RLock()


def named_graph_uri(name: str) -> URIRef:
    """URI canónica del grafo nombrado dentro del Dataset compartido."""

    return DATA[f"graph/{_safe_name(name)}"]


def _load_dataset() -> Dataset:
    dataset = Dataset()
    bind_namespaces(dataset)
    if DATASET_PATH.exists():
        try:
            dataset.parse(DATASET_PATH, format="trig")
        except Exception:
            # Si el fichero está corrupto o vacío, ignoramos y arrancamos limpio.
            pass
    return dataset


def load_named_graph(name: str) -> Graph:
    """Devuelve el grafo nombrado `name` del Dataset común.

    Si no existe, devuelve un grafo vacío con los namespaces vinculados.
    """

    uri = named_graph_uri(name)
    with _DATASET_LOCK:
        dataset = _load_dataset()
        graph = Graph()
        bind_namespaces(graph)
        for triple in dataset.graph(uri):
            graph.add(triple)
        return graph


def save_named_graph(name: str, graph: Graph) -> None:
    """Persiste `graph` como grafo nombrado `name` dentro del Dataset común.

    Reemplaza el contenido previo del grafo nombrado (no fusiona).
    """

    uri = named_graph_uri(name)
    with _DATASET_LOCK:
        dataset = _load_dataset()
        target = dataset.graph(uri)
        target.remove((None, None, None))
        for triple in graph:
            target.add(triple)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dataset.serialize(destination=str(DATASET_PATH), format="trig")


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


def list_named_graphs() -> list[str]:
    """Devuelve los nombres de los grafos nombrados presentes en el dataset.

    Útil para depurar y para que la memoria pueda enumerar las fuentes de
    datos en un único lugar (uno de los puntos pedidos por la rúbrica).
    """

    with _DATASET_LOCK:
        dataset = _load_dataset()
        prefix = str(DATA[f"graph/"])
        names: list[str] = []
        for context in dataset.contexts():
            ident = str(getattr(context, "identifier", context))
            if ident.startswith(prefix):
                names.append(ident[len(prefix):])
        return sorted(set(names))
