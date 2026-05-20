from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .acl import build_message
from .catalog import decimal_literal, product_uri
from .namespaces import ACL, DATA, ECSDI, bind_namespaces


def build_search_message(sender: URIRef, receiver: URIRef, constraints: dict) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/search/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.BuscarProductos))
    graph.add((action, ECSDI.accionSolicitadaPor, sender))

    if constraints.get("name"):
        _add_text_restriction(graph, action, ECSDI.RestriccionNombre, constraints["name"])
    if constraints.get("brand"):
        _add_text_restriction(graph, action, ECSDI.RestriccionMarca, constraints["brand"])
    if constraints.get("min_price") is not None or constraints.get("max_price") is not None:
        restriction = DATA[f"restriction/price/{uuid4()}"]
        graph.add((restriction, RDF.type, ECSDI.RestriccionPrecio))
        if constraints.get("min_price") is not None:
            graph.add((restriction, ECSDI.precioMinimo, decimal_literal(Decimal(str(constraints["min_price"])))))
        if constraints.get("max_price") is not None:
            graph.add((restriction, ECSDI.precioMaximo, decimal_literal(Decimal(str(constraints["max_price"])))))
        graph.add((action, ECSDI.accionTieneRestriccion, restriction))
    if constraints.get("min_rating") is not None:
        restriction = DATA[f"restriction/rating/{uuid4()}"]
        graph.add((restriction, RDF.type, ECSDI.RestriccionValoracion))
        graph.add((restriction, ECSDI.valoracionMinima, decimal_literal(Decimal(str(constraints["min_rating"])))))
        graph.add((action, ECSDI.accionTieneRestriccion, restriction))

    return build_message(graph, action, ACL.request, sender, receiver)


def build_order_message(
    sender: URIRef,
    receiver: URIRef,
    product_quantities: dict[str, int],
    product_prices: dict[str, Decimal],
    city: str,
    street: str,
    postal_code: str,
    country: str,
    priority: int,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    order_id = f"PED-{uuid4().hex[:8].upper()}"
    action = DATA[f"action/order/{uuid4()}"]
    pedido = DATA[f"pedido/{order_id}"]
    address = DATA[f"direccion/{uuid4()}"]

    graph.add((action, RDF.type, ECSDI.RealizarPedido))
    graph.add((action, ECSDI.accionSolicitadaPor, sender))
    graph.add((action, ECSDI.accionSobrePedido, pedido))

    graph.add((pedido, RDF.type, ECSDI.Pedido))
    graph.add((pedido, ECSDI.idPedido, Literal(order_id)))
    graph.add((pedido, ECSDI.pedidoSolicitadoPor, sender))
    graph.add((pedido, ECSDI.pedidoEnviadoA, address))
    graph.add((pedido, ECSDI.prioridadEntrega, Literal(priority, datatype=XSD.integer)))
    graph.add((pedido, ECSDI.estadoPedido, Literal("solicitado")))
    graph.add((pedido, ECSDI.fechaPedido, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    graph.add((address, RDF.type, ECSDI.Direccion))
    graph.add((address, ECSDI.ciudad, Literal(city)))
    graph.add((address, ECSDI.calle, Literal(street)))
    graph.add((address, ECSDI.codigoPostal, Literal(postal_code)))
    graph.add((address, ECSDI.pais, Literal(country)))

    for product_id, quantity in product_quantities.items():
        line = DATA[f"linea/{order_id}/{product_id}"]
        graph.add((line, RDF.type, ECSDI.LineaPedido))
        graph.add((line, ECSDI.lineaDeProducto, product_uri(product_id)))
        graph.add((line, ECSDI.cantidad, Literal(quantity, datatype=XSD.integer)))
        if product_id in product_prices:
            graph.add((line, ECSDI.precioUnitario, decimal_literal(product_prices[product_id])))
        graph.add((pedido, ECSDI.pedidoTieneLinea, line))

    return build_message(graph, action, ACL.request, sender, receiver)


def build_search_response(sender: URIRef, receiver: URIRef, action: URIRef, products: list[URIRef], product_graph: Graph) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    response = DATA[f"response/search/{uuid4()}"]
    graph.add((response, RDF.type, ECSDI.ResultadoBusqueda))
    graph.add((response, ECSDI.respuestaDeAccion, action))
    for product in products:
        graph.add((response, ECSDI.resultadoContieneProducto, product))
        for triple in product_graph.triples((product, None, None)):
            graph.add(triple)
    return build_message(graph, response, ACL.inform, sender, receiver)


def build_transport_request(sender: URIRef, receiver: URIRef, lote_graph: Graph, lote: URIRef) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    for triple in lote_graph:
        graph.add(triple)
    action = DATA[f"action/transport/request/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.SolicitarPresupuestoTransporte))
    graph.add((action, ECSDI.accionSobreLote, lote))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_transport_offer(sender: URIRef, receiver: URIRef, action: URIRef, lote: URIRef, transportista: URIRef, price: Decimal, max_days: int) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    offer = DATA[f"oferta/{uuid4()}"]
    delivery_date = datetime.now() + timedelta(days=max_days)
    graph.add((offer, RDF.type, ECSDI.OfertaTransporte))
    graph.add((offer, ECSDI.ofertaParaLote, lote))
    graph.add((offer, ECSDI.ofertaRealizadaPor, transportista))
    graph.add((offer, ECSDI.precioOferta, decimal_literal(price)))
    graph.add((offer, ECSDI.plazoMaximoDias, Literal(max_days, datatype=XSD.integer)))
    graph.add((offer, ECSDI.fechaEntregaEstimada, Literal(delivery_date.isoformat(timespec="seconds"), datatype=XSD.dateTime)))
    graph.add((offer, ECSDI.estadoOferta, Literal("propuesta")))
    return build_message(graph, offer, ACL.inform, sender, receiver)


def build_shipping_confirmation(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    pedido: URIRef,
    lote: URIRef,
    offer_graph: Graph,
    offer: URIRef,
    transportista: URIRef,
) -> Graph:
    graph = Graph()
    bind_namespaces(graph)
    for triple in offer_graph:
        graph.add(triple)

    envio = DATA[f"envio/{uuid4()}"]
    confirmation = DATA[f"response/shipping/{uuid4()}"]
    graph.add((envio, RDF.type, ECSDI.EnvioInterno))
    graph.add((envio, ECSDI.envioDePedido, pedido))
    graph.add((envio, ECSDI.envioTieneLote, lote))
    graph.add((envio, ECSDI.envioRealizadoPor, transportista))

    graph.add((confirmation, RDF.type, ECSDI.ConfirmacionEnvio))
    graph.add((confirmation, ECSDI.confirmacionEnvio, envio))
    graph.add((confirmation, ECSDI.respuestaDeAccion, action))
    graph.add((confirmation, ECSDI.accionSobreOferta, offer))
    return build_message(graph, confirmation, ACL.inform, sender, receiver)


def build_cobro_request(sender: URIRef, receiver: URIRef, pedido: URIRef, importe: Decimal) -> Graph:
    """Comerciante → AgenteFinanciero: SolicitarCobro (fire-and-forget)."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/cobro/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.SolicitarCobro))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.importeCobro, decimal_literal(importe)))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_notify_purchase_completed(
    sender: URIRef,
    receiver: URIRef,
    order_graph: Graph,
    pedido: URIRef,
) -> Graph:
    """Comerciante → AgenteFeedback: NotificarCompraCompletada (fire-and-forget)."""
    graph = Graph()
    bind_namespaces(graph)
    for triple in order_graph:
        graph.add(triple)
    action = DATA[f"action/notify-purchase/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.NotificarCompraCompletada))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_valoracion_request(
    sender: URIRef,
    receiver: URIRef,
    pedido_id: str,
    product_id: str,
    puntuacion: int,
    comentario: str,
) -> Graph:
    """AsistenteVirtual → AgenteFeedback: RegistrarValoracion."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/valoracion/{uuid4()}"]
    valoracion = DATA[f"valoracion/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.RegistrarValoracion))
    graph.add((action, ECSDI.accionSobreProducto, product_uri(product_id)))
    graph.add((valoracion, RDF.type, ECSDI.Valoracion))
    graph.add((valoracion, ECSDI.valoracionDeProducto, product_uri(product_id)))
    graph.add((valoracion, ECSDI.valoracionEnviadaPor, sender))
    graph.add((valoracion, ECSDI.valoracionDePedido, Literal(pedido_id)))
    graph.add((valoracion, ECSDI.puntuacion, Literal(puntuacion, datatype=XSD.integer)))
    graph.add((valoracion, ECSDI.comentario, Literal(comentario)))
    graph.add((action, ECSDI.accionTieneValoracion, valoracion))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_valoracion_response(
    sender: URIRef,
    receiver: URIRef,
    valoracion: URIRef,
    valoracion_graph: Graph,
) -> Graph:
    """AgenteFeedback → AsistenteVirtual: inform con Valoracion registrada."""
    graph = Graph()
    bind_namespaces(graph)
    for triple in valoracion_graph.triples((valoracion, None, None)):
        graph.add(triple)
    return build_message(graph, valoracion, ACL.inform, sender, receiver)


def _add_text_restriction(graph: Graph, action: URIRef, restriction_type: URIRef, text: str) -> None:
    restriction = DATA[f"restriction/text/{uuid4()}"]
    graph.add((restriction, RDF.type, restriction_type))
    graph.add((restriction, ECSDI.valorTextoRestriccion, Literal(text)))
    graph.add((action, ECSDI.accionTieneRestriccion, restriction))