"""LotesEnviosDB pendientes por centro logístico (agrupar → esperar → seleccionar)."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .catalog import decimal_literal, persist_lote, stamp_operating_center
from .namespaces import DATA, ECSDI, bind_namespaces
from .storage import DATA_DIR, save_graph_item, save_named_graph

PENDING_ROOT = DATA_DIR / "pending_lotes"
ESTADO_PENDIENTE_ENVIO = "pendiente_envio"
ESTADO_EN_TRANSITO = "en_negociacion_transporte"
DIST_ZONE_SIZE = int(os.environ.get("LOT_DIST_ZONE_SIZE", "200"))
DEFAULT_LOT_DEBOUNCE_SECONDS = float(os.environ.get("LOT_DEBOUNCE_SECONDS", "90"))
DEFAULT_LOT_URGENT_DEBOUNCE_SECONDS = float(os.environ.get("LOT_URGENT_DEBOUNCE", "5"))


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def _center_dir(center_id: str) -> Path:
    return PENDING_ROOT / _safe_name(center_id)


def _meta_path(center_id: str, lote_id: str) -> Path:
    return _center_dir(center_id) / f"{_safe_name(lote_id)}.meta.json"


def _ttl_path(center_id: str, lote_id: str) -> Path:
    return _center_dir(center_id) / f"{_safe_name(lote_id)}.ttl"


def destination_key(graph: Graph, pedido: URIRef) -> str:
    """Clave detallada de dirección (depuración); no se usa para agrupar lotes."""

    address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is None:
        return "unknown"
    parts: list[str] = []
    for pred in (ECSDI.calle, ECSDI.ciudad, ECSDI.codigoPostal, ECSDI.pais, ECSDI.dist):
        value = next(graph.objects(address, pred), None)
        if value is not None:
            parts.append(str(value))
    return "|".join(parts) if parts else str(address)


def _delivery_dist(graph: Graph, pedido: URIRef) -> int:
    address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is None:
        return 0
    dist_raw = next(graph.objects(address, ECSDI.dist), 0)
    try:
        return max(0, int(dist_raw))
    except (TypeError, ValueError):
        return 0


def dist_zone(dist: int, zone_size: int = DIST_ZONE_SIZE) -> int:
    """Banda de distancia: 0-199 → 0, 200-399 → 1, …"""

    return max(0, dist) // zone_size


def grouping_key(center_id: str, graph: Graph, pedido: URIRef) -> str:
    """Clave de agrupación: centro + ciudad + banda de dist (misma zona logística)."""

    address = next(graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is None:
        return f"{center_id}|unknown|zone-0"
    city = str(next(graph.objects(address, ECSDI.ciudad), "unknown")).casefold()
    zone = dist_zone(_delivery_dist(graph, pedido))
    return f"{center_id}|{city}|zone-{zone}"


def touch_lote_activity(center_id: str, lote_id: str) -> None:
    """Reinicia la ventana de agrupación (debounce) del lote."""

    meta = load_pending_meta(center_id, lote_id)
    meta["last_activity_at"] = time.time()
    save_pending_meta(center_id, lote_id, meta)


def count_lote_lines(graph: Graph, lote: URIRef) -> int:
    return len(list(graph.objects(lote, ECSDI.loteTieneLinea)))


def lote_priority(graph: Graph, lote: URIRef) -> int:
    return int(next(graph.objects(lote, ECSDI.prioridadLote), 3))


def list_pending_lote_ids(center_id: str) -> list[str]:
    base = _center_dir(center_id)
    if not base.exists():
        return []
    return sorted(path.stem for path in base.glob("*.ttl"))


def load_pending_meta(center_id: str, lote_id: str) -> dict:
    path = _meta_path(center_id, lote_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_pending_meta(center_id: str, lote_id: str, meta: dict) -> None:
    base = _center_dir(center_id)
    base.mkdir(parents=True, exist_ok=True)
    _meta_path(center_id, lote_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pending_lote(center_id: str, lote_id: str) -> tuple[Graph, URIRef] | None:
    path = _ttl_path(center_id, lote_id)
    if not path.exists():
        return None
    graph = Graph()
    bind_namespaces(graph)
    graph.parse(path, format="turtle")
    lote = next(graph.subjects(RDF.type, ECSDI.LoteEnvio), None)
    if lote is None:
        return None
    return graph, lote


def save_pending_lote(center_id: str, lote_id: str, graph: Graph) -> None:
    base = _center_dir(center_id)
    base.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(_ttl_path(center_id, lote_id)), format="turtle")
    save_named_graph(f"pending_lotes/{center_id}/{lote_id}", graph)


def delete_pending_lote(center_id: str, lote_id: str) -> None:
    ttl = _ttl_path(center_id, lote_id)
    meta = _meta_path(center_id, lote_id)
    if ttl.exists():
        ttl.unlink()
    if meta.exists():
        meta.unlink()


def find_open_lote(
    center_id: str,
    grouping_key_value: str,
    max_lines: int,
    additional_lines: int,
) -> tuple[str, Graph, URIRef] | None:
    """Busca un lote abierto con la misma zona logística y capacidad libre."""

    for lote_id in list_pending_lote_ids(center_id):
        meta = load_pending_meta(center_id, lote_id)
        if meta.get("estado") != ESTADO_PENDIENTE_ENVIO:
            continue
        stored_key = meta.get("grouping_key") or meta.get("destination_key")
        if stored_key != grouping_key_value:
            continue
        loaded = load_pending_lote(center_id, lote_id)
        if loaded is None:
            continue
        graph, lote = loaded
        if count_lote_lines(graph, lote) + additional_lines > max_lines:
            continue
        return lote_id, graph, lote
    return None


def _copy_subject(source: Graph, target: Graph, subject: URIRef) -> None:
    for triple in source.triples((subject, None, None)):
        target.add(triple)


def _copy_product_context(source: Graph, target: Graph, product: URIRef) -> None:
    _copy_subject(source, target, product)
    for stock in source.subjects(ECSDI.stockDeProducto, product):
        _copy_subject(source, target, stock)
        center = next(source.objects(stock, ECSDI.stockEnCentro), None)
        if center is not None:
            _copy_subject(source, target, center)


def _recalculate_lote_weight(graph: Graph, lote: URIRef) -> None:
    weight = Decimal("0")
    for line in graph.objects(lote, ECSDI.loteTieneLinea):
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        quantity = int(next(graph.objects(line, ECSDI.cantidad), 1))
        product_weight = Decimal(str(next(graph.objects(product, ECSDI.pesoProducto), "0")))
        weight += product_weight * quantity
    for _, pred, obj in list(graph.triples((lote, ECSDI.pesoTotalLote, None))):
        graph.remove((lote, pred, obj))
    graph.add((lote, ECSDI.pesoTotalLote, decimal_literal(weight)))


def create_pending_lote(
    order_graph: Graph,
    pedido: URIRef,
    lines: list[URIRef],
    center: URIRef,
    center_id: str,
    center_city: str,
    comerciante_url: str,
    action: URIRef,
    comerciante_uri: str | None = None,
) -> tuple[str, Graph, URIRef]:
    graph = Graph()
    bind_namespaces(graph)
    lote = DATA[f"lote/{uuid4()}"]
    lote_id = f"LOT-{uuid4().hex[:8].upper()}"
    dest = destination_key(order_graph, pedido)
    group_key = grouping_key(center_id, order_graph, pedido)
    zone = dist_zone(_delivery_dist(order_graph, pedido))
    priority = int(next(order_graph.objects(pedido, ECSDI.prioridadEntrega), 3))
    now = time.time()

    graph.add((lote, RDF.type, ECSDI.LoteEnvio))
    graph.add((lote, ECSDI.idLote, Literal(lote_id)))
    graph.add((lote, ECSDI.loteOrigenCentro, center))
    _copy_subject(order_graph, graph, center)
    stamp_operating_center(graph, center, center_id, center_city)
    graph.add((lote, ECSDI.estadoLote, Literal(ESTADO_PENDIENTE_ENVIO)))
    graph.add((lote, ECSDI.prioridadLote, Literal(priority, datatype=XSD.integer)))
    graph.add((lote, ECSDI.ciudadCentroLogistico, Literal(center_city)))

    address = next(order_graph.objects(pedido, ECSDI.pedidoEnviadoA), None)
    if address is not None:
        graph.add((lote, ECSDI.loteDestinoDireccion, address))
        _copy_subject(order_graph, graph, address)

    _append_lines_to_lote(graph, lote, order_graph, pedido, lines, comerciante_url, action)
    save_pending_lote(center_id, lote_id, graph)
    save_pending_meta(
        center_id,
        lote_id,
        {
            "estado": ESTADO_PENDIENTE_ENVIO,
            "grouping_key": group_key,
            "dist_zone": zone,
            "destination_key": dest,
            "prioridad": priority,
            "pedidos": [],
            "comerciante_url": comerciante_url,
            "last_activity_at": now,
        },
    )
    _register_pedido_in_meta(
        center_id, lote_id, order_graph, pedido, comerciante_url, action, comerciante_uri
    )
    return lote_id, graph, lote


def _pedido_records_from_meta(meta: dict) -> list[dict]:
    return list(meta.get("pedidos") or [])


def _register_pedido_in_meta(
    center_id: str,
    lote_id: str,
    order_graph: Graph,
    pedido: URIRef,
    comerciante_url: str,
    action: URIRef,
    comerciante_uri: str | None = None,
) -> None:
    meta = load_pending_meta(center_id, lote_id)
    pedido_id = str(next(order_graph.objects(pedido, ECSDI.idPedido), ""))
    if not pedido_id:
        pedido_id = str(pedido).rsplit("/", 1)[-1]
    records = _pedido_records_from_meta(meta)
    if not any(r.get("pedido_id") == pedido_id for r in records):
        records.append(
            {
                "pedido_id": pedido_id,
                "pedido_uri": str(pedido),
                "action_uri": str(action),
                "comerciante_url": comerciante_url,
                "comerciante_uri": comerciante_uri,
            }
        )
    meta["pedidos"] = records
    meta["prioridad"] = min(int(meta.get("prioridad", 3)), int(next(order_graph.objects(pedido, ECSDI.prioridadEntrega), 3)))
    save_pending_meta(center_id, lote_id, meta)


def append_lines_to_pending_lote(
    center_id: str,
    lote_id: str,
    graph: Graph,
    lote: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    lines: list[URIRef],
    comerciante_url: str,
    action: URIRef,
    comerciante_uri: str | None = None,
) -> Graph:
    _append_lines_to_lote(graph, lote, order_graph, pedido, lines, comerciante_url, action)
    priority = int(next(order_graph.objects(pedido, ECSDI.prioridadEntrega), 3))
    current = lote_priority(graph, lote)
    if priority < current:
        for _, pred, obj in list(graph.triples((lote, ECSDI.prioridadLote, None))):
            graph.remove((lote, pred, obj))
        graph.add((lote, ECSDI.prioridadLote, Literal(priority, datatype=XSD.integer)))
    save_pending_lote(center_id, lote_id, graph)
    _register_pedido_in_meta(
        center_id, lote_id, order_graph, pedido, comerciante_url, action, comerciante_uri
    )
    meta = load_pending_meta(center_id, lote_id)
    meta["prioridad"] = min(int(meta.get("prioridad", 3)), priority)
    meta["last_activity_at"] = time.time()
    save_pending_meta(center_id, lote_id, meta)
    return graph


def _append_lines_to_lote(
    graph: Graph,
    lote: URIRef,
    order_graph: Graph,
    pedido: URIRef,
    lines: list[URIRef],
    comerciante_url: str,
    action: URIRef,
) -> None:
    graph.add((pedido, RDF.type, ECSDI.Pedido))
    for triple in order_graph.triples((pedido, None, None)):
        if triple[1] != ECSDI.pedidoTieneLinea or triple[2] in lines:
            graph.add(triple)
    for line in lines:
        graph.add((lote, ECSDI.loteTieneLinea, line))
        _copy_subject(order_graph, graph, line)
        product = next(order_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is not None:
            _copy_product_context(order_graph, graph, product)
    _recalculate_lote_weight(graph, lote)


def _lote_idle_seconds(meta: dict, now: float | None = None) -> float:
    reference = now if now is not None else time.time()
    last = float(meta.get("last_activity_at", 0))
    return max(0.0, reference - last)


def _lote_debounce_threshold(priority: int, debounce_seconds: float, urgent_debounce_seconds: float) -> float:
    if priority <= 1:
        return urgent_debounce_seconds
    return debounce_seconds


def describe_pending_lote(center_id: str, lote_id: str, now: float | None = None) -> dict:
    """Metadatos de un lote pendiente para status/depuración."""

    meta = load_pending_meta(center_id, lote_id)
    loaded = load_pending_lote(center_id, lote_id)
    line_count = 0
    if loaded is not None:
        graph, lote = loaded
        line_count = count_lote_lines(graph, lote)
    reference = now if now is not None else time.time()
    priority = int(meta.get("prioridad", 3))
    idle = _lote_idle_seconds(meta, reference)
    threshold = _lote_debounce_threshold(
        priority, DEFAULT_LOT_DEBOUNCE_SECONDS, DEFAULT_LOT_URGENT_DEBOUNCE_SECONDS
    )
    return {
        "lote_id": lote_id,
        "estado": meta.get("estado"),
        "prioridad": priority,
        "grouping_key": meta.get("grouping_key"),
        "dist_zone": meta.get("dist_zone"),
        "destination_key": meta.get("destination_key"),
        "lineas": line_count,
        "pedidos": [p.get("pedido_id") for p in meta.get("pedidos", [])],
        "idle_seconds": round(idle, 1),
        "ready_for_dispatch": idle >= threshold and meta.get("estado") == ESTADO_PENDIENTE_ENVIO,
    }


def select_lotes_for_dispatch(
    center_id: str,
    debounce_seconds: float = DEFAULT_LOT_DEBOUNCE_SECONDS,
    urgent_debounce_seconds: float = DEFAULT_LOT_URGENT_DEBOUNCE_SECONDS,
    now: float | None = None,
) -> list[tuple[str, Graph, URIRef]]:
    """Plan SeleccionarLotesAEntregar: lotes inactivos listos, ordenados por urgencia."""

    reference = now if now is not None else time.time()
    candidates: list[tuple[int, float, str, Graph, URIRef]] = []
    for lote_id in list_pending_lote_ids(center_id):
        meta = load_pending_meta(center_id, lote_id)
        if meta.get("estado") != ESTADO_PENDIENTE_ENVIO:
            continue
        loaded = load_pending_lote(center_id, lote_id)
        if loaded is None:
            continue
        graph, lote = loaded
        priority = int(meta.get("prioridad", lote_priority(graph, lote)))
        idle = _lote_idle_seconds(meta, reference)
        threshold = _lote_debounce_threshold(priority, debounce_seconds, urgent_debounce_seconds)
        if idle < threshold:
            continue
        candidates.append((priority, float(meta.get("last_activity_at", 0)), lote_id, graph, lote))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [(lote_id, graph, lote) for _, _, lote_id, graph, lote in candidates]


def mark_lote_in_transit(center_id: str, lote_id: str) -> None:
    meta = load_pending_meta(center_id, lote_id)
    meta["estado"] = ESTADO_EN_TRANSITO
    save_pending_meta(center_id, lote_id, meta)
    loaded = load_pending_lote(center_id, lote_id)
    if loaded is None:
        return
    graph, lote = loaded
    for _, pred, obj in list(graph.triples((lote, ECSDI.estadoLote, None))):
        graph.remove((lote, pred, obj))
    graph.add((lote, ECSDI.estadoLote, Literal(ESTADO_EN_TRANSITO)))
    save_pending_lote(center_id, lote_id, graph)


def finalize_dispatched_lote(center_id: str, lote_id: str, lote_graph: Graph, lote: URIRef) -> None:
    """Mueve el lote de pendientes al histórico LotesEnviosDB."""

    for _, pred, obj in list(lote_graph.triples((lote, ECSDI.estadoLote, None))):
        lote_graph.remove((lote, pred, obj))
    lote_graph.add((lote, ECSDI.estadoLote, Literal("enviado")))
    persist_lote(lote_graph, lote)
    delete_pending_lote(center_id, lote_id)
