"""Extrae resumen de pedido y envíos desde la respuesta RDF del AgenteComerciante."""

from __future__ import annotations

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from .acl import get_message
from .namespaces import ECSDI
from .transport_proto import find_transport_offer, offer_delivery_datetime, offer_price

# Mayor valor = estado más avanzado en el flujo de compra.
_ESTADO_PRIORITY: dict[str, int] = {
    "completado": 4,
    "aceptado_envio_planificado": 3,
    "aceptado_sin_pago": 2,
    "solicitado": 1,
}

_ESTADO_LABELS: dict[str, str] = {
    "completado": "Completado",
    "aceptado_envio_planificado": "Envío planificado",
    "aceptado_sin_pago": "Aceptado (facturado, envío pendiente)",
    "solicitado": "Solicitado",
}

_TRANSPORTISTA_LABELS: dict[str, str] = {
    "transportista-127-0-0-1-9003": "TransportistaExpress",
    "transportista-127-0-0-1-9011": "TransportistaEco",
}


def resolve_pedido(graph: Graph) -> URIRef | None:
    """Identifica el pedido de la respuesta (contenido ACL o único Pedido con idPedido)."""

    message = get_message(graph)
    if message is not None and message.content is not None:
        content = message.content
        if (content, RDF.type, ECSDI.Pedido) in graph:
            return content

    candidates: list[URIRef] = []
    for pedido in graph.subjects(RDF.type, ECSDI.Pedido):
        if next(graph.objects(pedido, ECSDI.idPedido), None) is not None:
            candidates.append(pedido)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return next(graph.subjects(RDF.type, ECSDI.Pedido), None)

    factura = next(graph.subjects(RDF.type, ECSDI.Factura), None)
    if factura is not None:
        linked = next(graph.objects(factura, ECSDI.facturaDePedido), None)
        if linked in candidates:
            return linked

    for confirmacion in graph.subjects(RDF.type, ECSDI.ConfirmacionEnvio):
        envio = next(graph.objects(confirmacion, ECSDI.confirmacionEnvio), None)
        if envio is None:
            continue
        linked = next(graph.objects(envio, ECSDI.envioDePedido), None)
        if linked is not None:
            return linked

    return candidates[0] if candidates else None


def pick_estado_pedido(graph: Graph, pedido: URIRef) -> str:
    estados = [str(value) for value in graph.objects(pedido, ECSDI.estadoPedido)]
    if not estados:
        return ""
    return max(estados, key=lambda estado: _ESTADO_PRIORITY.get(estado, 0))


def estado_label(estado: str) -> str:
    return _ESTADO_LABELS.get(estado, estado.replace("_", " ").capitalize() if estado else "—")


def _uri_tail(uri: URIRef | None) -> str:
    if uri is None:
        return ""
    text = str(uri)
    return text.rsplit("/", 1)[-1]


def _friendly_transportista(uri: URIRef | None) -> str:
    tail = _uri_tail(uri)
    return _TRANSPORTISTA_LABELS.get(tail, tail)


def _centro_from_lote(graph: Graph, lote: URIRef | None) -> tuple[str, str]:
    if lote is None:
        return "", ""
    centro_id = str(next(graph.objects(lote, ECSDI.idCentroLogistico), "") or "")
    ciudad = str(next(graph.objects(lote, ECSDI.ciudadCentroLogistico), "") or "")
    if centro_id and ciudad:
        return centro_id, ciudad
    center = next(graph.objects(lote, ECSDI.loteOrigenCentro), None)
    if center is not None:
        if not centro_id:
            centro_id = str(next(graph.objects(center, ECSDI.idCentroLogistico), "") or "")
        if not ciudad:
            ciudad = str(next(graph.objects(center, ECSDI.ciudadCentroLogistico), "") or "")
    return centro_id, ciudad


def _iter_confirmaciones_pedido(graph: Graph, pedido: URIRef):
    """Confirmaciones enlazadas por pedidoTieneConfirmacion o por envioDePedido."""

    seen: set[str] = set()
    for confirmacion in graph.objects(pedido, ECSDI.pedidoTieneConfirmacion):
        if (confirmacion, RDF.type, ECSDI.ConfirmacionEnvio) not in graph:
            continue
        key = str(confirmacion)
        if key in seen:
            continue
        seen.add(key)
        yield confirmacion

    for confirmacion in graph.subjects(RDF.type, ECSDI.ConfirmacionEnvio):
        key = str(confirmacion)
        if key in seen:
            continue
        envio = next(graph.objects(confirmacion, ECSDI.confirmacionEnvio), None)
        if envio is None:
            continue
        if (envio, ECSDI.envioDePedido, pedido) in graph:
            seen.add(key)
            yield confirmacion


def _envio_record_from_confirmacion(graph: Graph, confirmacion: URIRef) -> dict:
    envio = next(graph.objects(confirmacion, ECSDI.confirmacionEnvio), None)
    transportista = next(graph.objects(envio, ECSDI.envioRealizadoPor), None) if envio else None
    lote = next(graph.objects(envio, ECSDI.envioTieneLote), None) if envio else None
    lote_id = str(next(graph.objects(lote, ECSDI.idLote), "")) if lote else ""
    centro_id = str(next(graph.objects(envio, ECSDI.idCentroLogistico), "")) if envio else ""
    ciudad_cl = str(next(graph.objects(envio, ECSDI.ciudadCentroLogistico), "")) if envio else ""
    if not centro_id or not ciudad_cl:
        fallback_id, fallback_city = _centro_from_lote(graph, lote)
        centro_id = centro_id or fallback_id
        ciudad_cl = ciudad_cl or fallback_city

    oferta = next(graph.subjects(ECSDI.ofertaParaLote, lote), None) if lote is not None else None
    if oferta is None:
        oferta = find_transport_offer(graph)
    fecha = offer_delivery_datetime(graph, oferta) if oferta else None
    precio = str(offer_price(graph, oferta)) if oferta else ""

    return {
        "tipo": "interno",
        "transportista": _friendly_transportista(transportista),
        "lote_id": lote_id,
        "centro_id": centro_id,
        "ciudad_centro": ciudad_cl,
        "fecha_entrega": str(fecha) if fecha else "",
        "coste_envio": precio,
    }


def extract_envios_internos(graph: Graph, pedido: URIRef) -> list[dict]:
    """Confirmaciones de envío interno enlazadas al pedido."""

    envios: list[dict] = []
    for confirmacion in _iter_confirmaciones_pedido(graph, pedido):
        envios.append(_envio_record_from_confirmacion(graph, confirmacion))
    return envios


def extract_envio_externo(graph: Graph, pedido: URIRef) -> dict | None:
    envio = next(graph.objects(pedido, ECSDI.pedidoTieneEnvio), None)
    if envio is None or (envio, RDF.type, ECSDI.EnvioExterno) not in graph:
        return None
    vendedor = next(graph.objects(envio, ECSDI.envioExternoGestionadoPor), None)
    return {
        "tipo": "externo",
        "vendedor": _uri_tail(vendedor),
        "mensaje": "Gestionado directamente por el vendedor externo",
    }


def extract_order_summary(graph: Graph) -> dict:
    """JSON-serializable summary for the web UI and demos."""

    pedido = resolve_pedido(graph)
    factura = next(graph.subjects(RDF.type, ECSDI.Factura), None)
    if pedido is None:
        return {"error": "Respuesta sin pedido"}

    pedido_id = str(next(graph.objects(pedido, ECSDI.idPedido), ""))
    estado = pick_estado_pedido(graph, pedido)
    envios_internos = extract_envios_internos(graph, pedido)
    envio_externo = extract_envio_externo(graph, pedido)

    result: dict = {
        "pedido_id": pedido_id,
        "estado": estado,
        "estado_label": estado_label(estado),
        "factura_id": str(next(graph.objects(factura, ECSDI.idFactura), "")) if factura else "",
        "importe": str(next(graph.objects(factura, ECSDI.importeFactura), "0")) if factura else "0",
        "envios_internos": envios_internos,
        "envio_interno": bool(envios_internos),
        "envio_externo": envio_externo is not None,
        "envio_externo_detalle": envio_externo,
        "items": [],
    }

    if envios_internos:
        first = envios_internos[0]
        result.update(
            {
                "transportista": first.get("transportista", ""),
                "fecha_entrega": first.get("fecha_entrega", ""),
                "coste_envio": first.get("coste_envio", ""),
                "lote_id": first.get("lote_id", ""),
                "centro_id": first.get("centro_id", ""),
                "ciudad_centro": first.get("ciudad_centro", ""),
            }
        )
    elif envio_externo:
        result["transportista"] = envio_externo.get("vendedor", "")

    for line in graph.objects(pedido, ECSDI.pedidoTieneLinea):
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        product_id = str(next(graph.objects(product, ECSDI.idProducto), ""))
        qty = int(next(graph.objects(line, ECSDI.cantidad), 1))
        if product_id:
            result["items"].append({"product_id": product_id, "quantity": qty})

    return result
