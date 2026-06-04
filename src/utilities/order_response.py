"""Extrae resumen de pedido y envíos desde la respuesta RDF del AgenteComerciante."""

from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from .acl import get_message
from .namespaces import ECSDI
from .catalog import format_centro_label
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


def _centro_from_lote(graph: Graph, lote: URIRef | None) -> tuple[str, str, str]:
    if lote is None:
        return "", "", ""
    ciudad = str(next(graph.objects(lote, ECSDI.ciudadCentroLogistico), "") or "")
    center = next(graph.objects(lote, ECSDI.loteOrigenCentro), None)
    centro_id = ""
    nombre = ""
    if center is not None:
        centro_id = str(next(graph.objects(center, ECSDI.idCentroLogistico), "") or "")
        nombre = str(next(graph.objects(center, ECSDI.nombreCentroLogistico), "") or "")
        if not ciudad:
            ciudad = str(next(graph.objects(center, ECSDI.ciudadCentroLogistico), "") or "")
    return centro_id, ciudad, nombre


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
    nombre_cl = ""
    if envio is not None:
        center = next(graph.objects(envio, ECSDI.envioDesdeCentro), None)
        if center is not None:
            nombre_cl = str(next(graph.objects(center, ECSDI.nombreCentroLogistico), "") or "")
    if not centro_id or not ciudad_cl or not nombre_cl:
        fallback_id, fallback_city, fallback_name = _centro_from_lote(graph, lote)
        centro_id = centro_id or fallback_id
        ciudad_cl = ciudad_cl or fallback_city
        nombre_cl = nombre_cl or fallback_name

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
        "nombre_centro": nombre_cl,
        "centro_label": format_centro_label(centro_id, ciudad_cl, nombre_cl),
        "fecha_entrega": str(fecha) if fecha else "",
        "coste_envio": precio,
    }


def extract_envios_internos(graph: Graph, pedido: URIRef) -> list[dict]:
    """Confirmaciones de envío interno enlazadas al pedido."""

    envios: list[dict] = []
    for confirmacion in _iter_confirmaciones_pedido(graph, pedido):
        envios.append(_envio_record_from_confirmacion(graph, confirmacion))
    return envios


def _product_ids_vendor_shipping(graph: Graph, pedido: URIRef) -> list[str]:
    """Productos externos cuyo envío gestiona el vendedor (gestionEnvioExterno=true)."""

    ids: list[str] = []
    for line in graph.objects(pedido, ECSDI.pedidoTieneLinea):
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None or (product, RDF.type, ECSDI.ProductoExterno) not in graph:
            continue
        gestion = next(graph.objects(product, ECSDI.gestionEnvioExterno), Literal(False))
        if str(gestion).lower() not in ("true", "1"):
            continue
        product_id = str(next(graph.objects(product, ECSDI.idProducto), ""))
        if product_id and product_id not in ids:
            ids.append(product_id)
    return ids


def _product_ids_from_envio_comment(graph: Graph, envio: URIRef) -> list[str]:
    comment = str(next(graph.objects(envio, RDFS.comment), ""))
    marker = "producto="
    if marker not in comment:
        return []
    raw = comment.split(marker, 1)[1].strip()
    product_id = raw.split()[0].strip(" ,;")
    return [product_id] if product_id else []


def _envio_externo_record(
    graph: Graph,
    envio: URIRef,
    fallback_productos: list[str] | None = None,
) -> dict:
    vendedor = next(graph.objects(envio, ECSDI.envioExternoGestionadoPor), None)
    productos = _product_ids_from_envio_comment(graph, envio)
    if not productos and fallback_productos:
        productos = list(fallback_productos)
    return {
        "tipo": "externo",
        "vendedor": _uri_tail(vendedor),
        "mensaje": "Gestionado directamente por el vendedor externo",
        "productos": productos,
    }


def extract_envios_externos(graph: Graph, pedido: URIRef) -> list[dict]:
    """Todos los EnvioExterno del pedido (un ticket por envío vendedor)."""

    vendor_products = _product_ids_vendor_shipping(graph, pedido)
    seen: set[str] = set()
    envio_nodes: list[URIRef] = []

    for envio in graph.objects(pedido, ECSDI.pedidoTieneEnvio):
        key = str(envio)
        if key in seen or (envio, RDF.type, ECSDI.EnvioExterno) not in graph:
            continue
        seen.add(key)
        envio_nodes.append(envio)

    for envio in graph.subjects(RDF.type, ECSDI.EnvioExterno):
        key = str(envio)
        if key in seen:
            continue
        if (envio, ECSDI.envioDePedido, pedido) not in graph:
            continue
        seen.add(key)
        envio_nodes.append(envio)

    fallback = vendor_products if len(envio_nodes) <= 1 else None
    envios = [_envio_externo_record(graph, envio, fallback) for envio in envio_nodes]

    if not envios and vendor_products:
        envios.append(
            {
                "tipo": "externo",
                "vendedor": "",
                "mensaje": "Gestionado directamente por el vendedor externo",
                "productos": vendor_products,
            }
        )
    return envios


def extract_envio_externo(graph: Graph, pedido: URIRef) -> dict | None:
    envios = extract_envios_externos(graph, pedido)
    return envios[0] if envios else None


def extract_order_summary(graph: Graph) -> dict:
    """JSON-serializable summary for the web UI and demos."""

    pedido = resolve_pedido(graph)
    factura = next(graph.subjects(RDF.type, ECSDI.Factura), None)
    if pedido is None:
        return {"error": "Respuesta sin pedido"}

    pedido_id = str(next(graph.objects(pedido, ECSDI.idPedido), ""))
    estado = pick_estado_pedido(graph, pedido)
    envios_internos = extract_envios_internos(graph, pedido)
    envios_externos = extract_envios_externos(graph, pedido)
    envio_externo = envios_externos[0] if envios_externos else None
    vendor_product_ids = _product_ids_vendor_shipping(graph, pedido)

    result: dict = {
        "pedido_id": pedido_id,
        "estado": estado,
        "estado_label": estado_label(estado),
        "factura_id": str(next(graph.objects(factura, ECSDI.idFactura), "")) if factura else "",
        "importe": str(next(graph.objects(factura, ECSDI.importeFactura), "0")) if factura else "0",
        "envios_internos": envios_internos,
        "envios_externos": envios_externos,
        "envio_interno": bool(envios_internos),
        "envio_externo": bool(envios_externos),
        "envio_externo_detalle": envio_externo,
        "productos_envio_vendedor": vendor_product_ids,
        "items": [],
        "items_logistica": [],
        "items_envio_vendedor": [],
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
                "nombre_centro": first.get("nombre_centro", ""),
                "centro_label": first.get("centro_label", ""),
            }
        )
    elif envio_externo:
        result["transportista"] = envio_externo.get("vendedor", "")

    vendor_set = set(vendor_product_ids)
    for line in graph.objects(pedido, ECSDI.pedidoTieneLinea):
        product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        product_id = str(next(graph.objects(product, ECSDI.idProducto), ""))
        qty = int(next(graph.objects(line, ECSDI.cantidad), 1))
        if not product_id:
            continue
        item = {"product_id": product_id, "quantity": qty}
        result["items"].append(item)
        if product_id in vendor_set:
            result["items_envio_vendedor"].append(item)
        else:
            result["items_logistica"].append(item)

    return result
