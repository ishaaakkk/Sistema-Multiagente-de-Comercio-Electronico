"""Vocabulario y utilidades del protocolo CL <-> Transportista (ontologia ecsdipractica)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .acl import build_message
from .catalog import decimal_literal
from .namespaces import ACL, DATA, ECSDI, ECOM, bind_namespaces


def extract_cfp_from_lote(lote_graph: Graph, lote: URIRef) -> tuple[str, str, str]:
    """Deriva comandaId, producteId y ciutatDesti desde un LoteEnvio interno."""

    lote_id = str(next(lote_graph.objects(lote, ECSDI.idLote), ""))
    if not lote_id:
        lote_id = str(lote).rsplit("/", 1)[-1]

    product_id = ""
    for line in lote_graph.objects(lote, ECSDI.loteTieneLinea):
        product = next(lote_graph.objects(line, ECSDI.lineaDeProducto), None)
        if product is None:
            continue
        product_id = str(next(lote_graph.objects(product, ECSDI.idProducto), ""))
        if product_id:
            break

    city = ""
    address = next(lote_graph.objects(lote, ECSDI.loteDestinoDireccion), None)
    if address is not None:
        city = str(next(lote_graph.objects(address, ECSDI.ciudad), ""))
    if not city:
        city = str(next(lote_graph.objects(lote, ECSDI.ciudadCentroLogistico), "Barcelona"))

    return lote_id, product_id or "UNKNOWN", city or "Barcelona"


def iter_transport_offers(graph: Graph):
    seen: set[URIRef] = set()
    for offer in graph.subjects(RDF.type, ECOM.OfertaTransport):
        seen.add(offer)
        yield offer
    for offer in graph.subjects(RDF.type, ECSDI.OfertaTransporte):
        if offer not in seen:
            yield offer


def find_transport_offer(graph: Graph) -> URIRef | None:
    offer = next(graph.subjects(RDF.type, ECOM.OfertaTransport), None)
    if offer is not None:
        return offer
    return next(graph.subjects(RDF.type, ECSDI.OfertaTransporte), None)


def offer_price(graph: Graph, offer: URIRef) -> Decimal:
    for prop in (ECOM.preuTransport, ECSDI.precioOferta):
        value = next(graph.objects(offer, prop), None)
        if value is not None:
            return Decimal(str(value))
    return Decimal("99999")


def offer_max_days(graph: Graph, offer: URIRef) -> int | str:
    days = next(graph.objects(offer, ECOM.terminiDies), None)
    if days is not None:
        return int(days)
    days = next(graph.objects(offer, ECSDI.plazoMaximoDias), None)
    if days is not None:
        return int(days)
    return "?"


def offer_transportista(graph: Graph, offer: URIRef, default: URIRef) -> URIRef:
    for prop in (ECOM.ofertaDeTransportista, ECSDI.ofertaRealizadaPor):
        value = next(graph.objects(offer, prop), None)
        if value is not None:
            return value
    return default


def offer_delivery_datetime(graph: Graph, offer: URIRef) -> str | None:
    for prop in (ECOM.dataPrevista, ECOM.dataPrevistaLliurament, ECSDI.fechaEntregaEstimada):
        value = next(graph.objects(offer, prop), None)
        if value is not None:
            return str(value)
    return None


def offer_is_accepted(graph: Graph, offer: URIRef) -> bool:
    value = next(graph.objects(offer, ECOM.acceptada), None)
    if value is None:
        return True
    return str(value).lower() in ("true", "1")


def set_offer_accepted(graph: Graph, offer: URIRef, accepted: bool) -> None:
    for _, pred, obj in list(graph.triples((offer, ECOM.acceptada, None))):
        graph.remove((offer, pred, obj))
    graph.add((offer, ECOM.acceptada, Literal(accepted, datatype=XSD.boolean)))
    estado = "aceptada" if accepted else "rechazada"
    for _, pred, obj in list(graph.triples((offer, ECSDI.estadoOferta, None))):
        graph.remove((offer, pred, obj))
    if (offer, RDF.type, ECSDI.OfertaTransporte) in graph or (offer, RDF.type, ECOM.OfertaTransport) in graph:
        graph.add((offer, ECSDI.estadoOferta, Literal(estado)))


def build_demanar_oferta_message(
    sender: URIRef,
    receiver: URIRef,
    lote_graph: Graph,
    lote: URIRef,
) -> Graph:
    """CFP: DemanarOfertaTransport con comandaId, producteId, ciutatDesti."""

    comanda_id, product_id, city = extract_cfp_from_lote(lote_graph, lote)
    graph = Graph()
    bind_namespaces(graph)
    for triple in lote_graph:
        graph.add(triple)

    action = DATA[f"action/transport/demanar/{uuid4()}"]
    graph.add((action, RDF.type, ECOM.DemanarOfertaTransport))
    graph.add((action, ECOM.comandaId, Literal(comanda_id)))
    graph.add((action, ECOM.producteId, Literal(product_id)))
    graph.add((action, ECOM.ciutatDesti, Literal(city)))
    graph.add((action, ECSDI.accionSobreLote, lote))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_oferta_transport_message(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    lote_graph: Graph,
    lote: URIRef,
    transportista: URIRef,
    price: Decimal,
    max_days: int,
) -> Graph:
    """Respuesta: OfertaTransport (1 ronda, acceptada=true)."""

    comanda_id, product_id, city = extract_cfp_from_lote(lote_graph, lote)
    graph = Graph()
    bind_namespaces(graph)
    offer = DATA[f"oferta/transport/{uuid4()}"]
    delivery_date = datetime.now() + timedelta(days=max_days)

    graph.add((offer, RDF.type, ECOM.OfertaTransport))
    graph.add((offer, ECOM.comandaId, Literal(comanda_id)))
    graph.add((offer, ECOM.producteId, Literal(product_id)))
    graph.add((offer, ECOM.ciutatDesti, Literal(city)))
    graph.add((offer, ECOM.preuTransport, decimal_literal(price)))
    graph.add((offer, ECOM.terminiDies, Literal(max_days, datatype=XSD.integer)))
    graph.add(
        (
            offer,
            ECOM.dataPrevista,
            Literal(delivery_date.isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )
    graph.add(
        (
            offer,
            ECOM.dataPrevistaLliurament,
            Literal(delivery_date.isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )
    graph.add((offer, ECOM.ofertaDeTransportista, transportista))
    graph.add((offer, ECOM.acceptada, Literal(True, datatype=XSD.boolean)))
    graph.add((offer, ECOM.ofertaId, Literal(str(offer).rsplit("/", 1)[-1])))
    graph.add((offer, ECSDI.ofertaParaLote, lote))
    graph.add((offer, ECSDI.precioOferta, decimal_literal(price)))
    graph.add((offer, ECSDI.plazoMaximoDias, Literal(max_days, datatype=XSD.integer)))
    graph.add(
        (
            offer,
            ECSDI.fechaEntregaEstimada,
            Literal(delivery_date.isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )
    graph.add((offer, ECSDI.estadoOferta, Literal("propuesta")))
    graph.add((offer, ECSDI.respuestaDeAccion, action))
    return build_message(graph, offer, ACL.inform, sender, receiver)
