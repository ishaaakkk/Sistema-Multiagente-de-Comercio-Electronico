from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from .acl import build_message
from .catalog import decimal_literal, product_uri
from .payment import normalize_card_digits
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
    payment_method: str = "tarjeta",
    payment_card: str | None = None,
    delivery_dist: int = 130,
    catalog_graph: Graph | None = None,
) -> Graph:
    """Construye el mensaje RealizarPedido para el AgenteComerciante.

    Si se pasa catalog_graph, copia los triples del producto y su contexto de
    stock/centro logistico para que el comerciante y el centro logistico puedan
    clasificar y validar el pedido sin consultar de nuevo el catalogo.
    """
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
    method = (payment_method or "tarjeta").strip().lower()
    graph.add((pedido, ECSDI.metodoPago, Literal(method)))
    if method == "tarjeta":
        card_digits = normalize_card_digits(payment_card)
        if card_digits:
            graph.add((pedido, ECSDI.tarjeta, Literal(card_digits)))
    graph.add((pedido, ECSDI.estadoPedido, Literal("solicitado")))
    graph.add((pedido, ECSDI.fechaPedido, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    graph.add((address, RDF.type, ECSDI.Direccion))
    graph.add((address, ECSDI.ciudad, Literal(city)))
    graph.add((address, ECSDI.calle, Literal(street)))
    graph.add((address, ECSDI.codigoPostal, Literal(postal_code)))
    graph.add((address, ECSDI.pais, Literal(country)))
    graph.add((address, ECSDI.dist, Literal(delivery_dist, datatype=XSD.integer)))

    for product_id, quantity in product_quantities.items():
        pnode = product_uri(product_id)
        line = DATA[f"linea/{order_id}/{product_id}"]
        graph.add((line, RDF.type, ECSDI.LineaPedido))
        graph.add((line, ECSDI.lineaDeProducto, pnode))
        graph.add((line, ECSDI.cantidad, Literal(quantity, datatype=XSD.integer)))
        if product_id in product_prices:
            graph.add((line, ECSDI.precioUnitario, decimal_literal(product_prices[product_id])))
        graph.add((pedido, ECSDI.pedidoTieneLinea, line))

        # Copiar todos los triples del producto desde el catalogo para que el
        # comerciante pueda clasificar la linea (interno/externo, gestionEnvioExterno...)
        if catalog_graph is not None:
            for triple in catalog_graph.triples((pnode, None, None)):
                graph.add(triple)
            _copy_stock_context(catalog_graph, graph, pnode)

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
        _copy_stock_context(product_graph, graph, product)
    return build_message(graph, response, ACL.inform, sender, receiver)

def build_busqueda_realizada_notification(
    sender: URIRef,
    receiver: URIRef,
    solicitante: URIRef,
    constraints: dict,
    products: list[URIRef],
) -> Graph:
    """AgenteCatalogo → AgenteFeedback: NotificarBusquedaRealizada.

    Protocolo Consulta Catálogo: informa al agente de feedback de los
    productos devueltos en una búsqueda de compra para alimentar el
    sistema de recomendación periódica.
    """
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/busqueda-realizada/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.NotificarBusquedaRealizada))
    graph.add((action, ECSDI.notificacionSolicitadaPor, solicitante))

    if constraints.get("name"):
        _add_text_restriction(graph, action, ECSDI.RestriccionNombre, constraints["name"])
    if constraints.get("brand"):
        _add_text_restriction(graph, action, ECSDI.RestriccionMarca, constraints["brand"])

    for product in products:
        graph.add((action, ECSDI.notificacionContieneProducto, product))

    return build_message(graph, action, ACL.inform, sender, receiver)

def build_logistics_request(sender: URIRef, receiver: URIRef, order_graph: Graph, pedido: URIRef) -> Graph:
    """AgenteComerciante -> CentroLogistico: AvisarCL."""
    graph = Graph()
    bind_namespaces(graph)
    _copy_business_graph(order_graph, graph)
    action = DATA[f"action/logistica/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.AvisarCL))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_transport_request(sender: URIRef, receiver: URIRef, lote_graph: Graph, lote: URIRef) -> Graph:
    from .transport_proto import build_demanar_oferta_message

    return build_demanar_oferta_message(sender, receiver, lote_graph, lote)


def build_recogida_devolucion_request(
    sender: URIRef,
    receiver: URIRef,
    devolucion: URIRef,
    pedido: URIRef,
    product: URIRef,
    source_graph: Graph,
) -> Graph:
    """Solicita al transportista la recogida de un producto devuelto."""
    graph = Graph()
    bind_namespaces(graph)
    _copy_business_graph(source_graph, graph)
    action = DATA[f"action/devolucion/recogida/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.SolicitarRecogidaDevolucion))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.accionSobreProducto, product))
    graph.add((devolucion, RDF.type, ECSDI.Devolucion))
    graph.add((devolucion, ECSDI.devolucionDePedido, pedido))
    graph.add((devolucion, ECSDI.devolucionDeProducto, product))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_transport_offer(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    lote_graph: Graph,
    lote: URIRef,
    transportista: URIRef,
    price: Decimal,
    max_days: int,
) -> Graph:
    from .transport_proto import build_oferta_transport_message

    return build_oferta_transport_message(
        sender, receiver, action, lote_graph, lote, transportista, price, max_days
    )


def build_aviso_cl_acceptance(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    pedido: URIRef,
    lote: URIRef,
    lote_graph: Graph,
    fulfilled_lines: list[URIRef],  # noqa: ARG001 — líneas ya materializadas en lote_graph
) -> Graph:
    """CentroLogistico → Comerciante: líneas aceptadas en lote pendiente de envío."""

    graph = Graph()
    bind_namespaces(graph)
    for triple in lote_graph:
        graph.add(triple)

    response = DATA[f"response/aviso-cl/{uuid4()}"]
    graph.add((response, RDF.type, ECSDI.Respuesta))
    graph.add((response, ECSDI.respuestaDeAccion, action))
    graph.add((response, ECSDI.accionSobrePedido, pedido))
    graph.add((response, ECSDI.accionSobreLote, lote))
    graph.add((lote, ECSDI.estadoLote, Literal("pendiente_envio")))
    return build_message(graph, response, ACL.inform, sender, receiver)


def build_shipping_confirmation(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    pedido: URIRef,
    lote: URIRef,
    offer_graph: Graph,
    offer: URIRef,
    transportista: URIRef,
    center_id: str | None = None,
    center_city: str | None = None,
    center: URIRef | None = None,
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

    if center is None:
        center = next(graph.objects(lote, ECSDI.loteOrigenCentro), None)
    if center is not None:
        graph.add((envio, ECSDI.envioDesdeCentro, center))
        if center_id is None:
            center_id = str(next(graph.objects(center, ECSDI.idCentroLogistico), "") or "")
    if center_id:
        graph.add((envio, ECSDI.idCentroLogistico, Literal(center_id)))
    if center_city is None:
        center_city = str(next(graph.objects(lote, ECSDI.ciudadCentroLogistico), "") or "")
    if center_city:
        graph.add((envio, ECSDI.ciudadCentroLogistico, Literal(center_city)))

    graph.add((confirmation, RDF.type, ECSDI.ConfirmacionEnvio))
    graph.add((confirmation, ECSDI.confirmacionEnvio, envio))
    graph.add((confirmation, ECSDI.respuestaDeAccion, action))
    graph.add((confirmation, ECSDI.respuestaSobreOferta, offer))
    graph.add((pedido, ECSDI.pedidoTieneConfirmacion, confirmation))
    graph.set((pedido, ECSDI.estadoPedido, Literal("aceptado_envio_planificado")))
    return build_message(graph, confirmation, ACL.inform, sender, receiver)


def build_pedir_feedback_request(
    sender: URIRef,
    receiver: URIRef,
    pedido_id: str,
    product_id: str,
    product: URIRef,
) -> Graph:
    """AgenteFeedback -> AsistenteVirtual: PedirFeedback."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/pedir-feedback/{uuid4()}"]
    pedido = _pedido_uri(pedido_id)
    graph.add((action, RDF.type, ECSDI.PedirFeedback))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.accionSobreProducto, product))
    graph.add((pedido, RDF.type, ECSDI.Pedido))
    graph.add((pedido, ECSDI.idPedido, Literal(pedido_id)))
    graph.add((product, RDF.type, ECSDI.Producto))
    graph.add((product, ECSDI.idProducto, Literal(product_id)))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_cobro_request(
    sender: URIRef,
    receiver: URIRef,
    pedido: URIRef,
    importe: Decimal,
    metodo_pago: str | None = None,
    tarjeta: str | None = None,
) -> Graph:
    """Comerciante → AgenteFinanciero: SolicitarCobro (fire-and-forget)."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/cobro/{uuid4()}"]
    operacion = DATA[f"pago/cobro/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.SolicitarCobro))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.importeCobro, decimal_literal(importe)))
    graph.add((action, ECSDI.accionTieneOperacionPago, operacion))
    graph.add((operacion, RDF.type, ECSDI.CobroCliente))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("solicitada")))
    if metodo_pago is not None:
        graph.add((action, ECSDI.metodoPago, Literal(str(metodo_pago))))
        graph.add((operacion, ECSDI.metodoPago, Literal(str(metodo_pago))))
    if tarjeta:
        graph.add((action, ECSDI.tarjeta, Literal(str(tarjeta))))
        graph.add((operacion, ECSDI.tarjeta, Literal(str(tarjeta))))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_provider_payment_request(
    sender: URIRef,
    receiver: URIRef,
    original_action: URIRef,
    operacion: URIRef,
    operation_type: URIRef,
    importe: Decimal,
    metodo_pago: str | None = None,
    tarjeta: str | None = None,
) -> Graph:
    """AgenteFinanciero -> ProveedorPagos: SolicitarOperacionPago."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/proveedor-pagos/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.SolicitarOperacionPago))
    graph.add((action, ECSDI.accionTieneOperacionPago, operacion))
    graph.add((action, ECSDI.respuestaDeAccion, original_action))
    graph.add((operacion, RDF.type, operation_type))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("solicitada")))
    if metodo_pago is not None:
        graph.add((action, ECSDI.metodoPago, Literal(str(metodo_pago))))
        graph.add((operacion, ECSDI.metodoPago, Literal(str(metodo_pago))))
    if tarjeta:
        graph.add((action, ECSDI.tarjeta, Literal(str(tarjeta))))
        graph.add((operacion, ECSDI.tarjeta, Literal(str(tarjeta))))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_notify_purchase_completed(
    sender: URIRef,
    receiver: URIRef,
    order_graph: Graph,
    pedido: URIRef,
) -> Graph:
    """Plan: FinalizarPedido → NotificarCompraCompletada (AgenteComerciante → AgenteFeedback).

    Mensaje informativo: comunica al AgenteFeedback que una compra se ha completado
    para que registre el pedido en OpinionesDB con opinion=NULL.
    Se incluye el grafo completo del pedido para que Feedback tenga toda la info.
    """
    graph = Graph()
    bind_namespaces(graph)
    for triple in order_graph:
        s, p, o = triple
        if p not in (ACL.performative, ACL.sender, ACL.receiver, ACL.content):
            if not (s, RDF.type, ACL.FipaAclMessage) in order_graph:
                graph.add(triple)
    action = DATA[f"action/feedback/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.NotificarCompraCompletada))
    graph.add((action, ECSDI.notificacionSobrePedido, pedido))
    return build_message(graph, action, ACL.inform, sender, receiver)


def build_busqueda_realizada_notification(
    sender: URIRef,
    receiver: URIRef,
    asistente: URIRef,
    constraints: dict,
    product_uris: list[URIRef],
    product_graph: Graph | None = None,
) -> Graph:
    """Protocolo Consulta Catálogo (AgenteCatalogo → AgenteFeedback).

    Notificación informativa que indica que se ha procesado una BuscarProductos.
    Lleva el AsistenteVirtual originador, las restricciones aplicadas y los
    productos devueltos para que el agente feedback pueda construir el historial
    de búsquedas y alimentar el algoritmo de recomendación (cap. 9).
    """

    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/busqueda-realizada/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.NotificarBusquedaRealizada))
    graph.add((action, ECSDI.accionSolicitadaPor, asistente))
    graph.add(
        (
            action,
            ECSDI.fechaBusqueda,
            Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )

    if constraints.get("name"):
        _add_text_restriction(graph, action, ECSDI.RestriccionNombre, constraints["name"])
    if constraints.get("brand"):
        _add_text_restriction(graph, action, ECSDI.RestriccionMarca, constraints["brand"])
    if constraints.get("min_price") is not None or constraints.get("max_price") is not None:
        restriction = DATA[f"restriction/price/{uuid4()}"]
        graph.add((restriction, RDF.type, ECSDI.RestriccionPrecio))
        if constraints.get("min_price") is not None:
            graph.add(
                (restriction, ECSDI.precioMinimo, decimal_literal(Decimal(str(constraints["min_price"]))))
            )
        if constraints.get("max_price") is not None:
            graph.add(
                (restriction, ECSDI.precioMaximo, decimal_literal(Decimal(str(constraints["max_price"]))))
            )
        graph.add((action, ECSDI.accionTieneRestriccion, restriction))
    if constraints.get("min_rating") is not None:
        restriction = DATA[f"restriction/rating/{uuid4()}"]
        graph.add((restriction, RDF.type, ECSDI.RestriccionValoracion))
        graph.add(
            (
                restriction,
                ECSDI.valoracionMinima,
                decimal_literal(Decimal(str(constraints["min_rating"]))),
            )
        )
        graph.add((action, ECSDI.accionTieneRestriccion, restriction))

    snapshot_products = set(product_uris)
    if product_graph is not None:
        snapshot_products.update(product_graph.subjects(RDF.type, ECSDI.Producto))
        snapshot_products.update(product_graph.subjects(RDF.type, ECSDI.ProductoInterno))
        snapshot_products.update(product_graph.subjects(RDF.type, ECSDI.ProductoExterno))

    for product in product_uris:
        graph.add((action, ECSDI.resultadoContieneProducto, product))

    # Además de las URIs devueltas, el Feedback necesita metadatos para poder
    # recomendar sin volver a consultar el catálogo.
    if product_graph is not None:
        for product in snapshot_products:
            for triple in product_graph.triples((product, None, None)):
                graph.add(triple)

    return build_message(graph, action, ACL.inform, sender, receiver)


def build_external_product_registration(
    sender: URIRef,
    receiver: URIRef,
    products: list[dict],
) -> Graph:
    """AgenteVendedorExterno -> AgenteCatalogo: DarAltaProductoExterno."""

    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/catalogo/alta-externa/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.DarAltaProductoExterno))

    for product_data in products:
        product_id = str(product_data["id"])
        product = URIRef(product_data.get("uri", product_uri(product_id)))
        graph.add((action, ECSDI.accionSobreProducto, product))
        graph.add((product, RDF.type, ECSDI.Producto))
        graph.add((product, RDF.type, ECSDI.ProductoExterno))
        graph.add((product, ECSDI.idProducto, Literal(product_id)))
        graph.add((product, ECSDI.nombreProducto, Literal(product_data.get("nombre", product_id))))

        if product_data.get("marca"):
            graph.add((product, ECSDI.marcaProducto, Literal(product_data["marca"])))
        if product_data.get("descripcion"):
            graph.add((product, ECSDI.descripcionProducto, Literal(product_data["descripcion"])))

        price = Decimal(str(product_data.get("precio", "0")))
        graph.add((product, ECSDI.precioProducto, decimal_literal(price)))

        rating = Decimal(str(product_data.get("valoracion", "0")))
        graph.add((product, ECSDI.valoracionMedia, decimal_literal(rating)))

        weight = Decimal(str(product_data.get("peso", "1.0")))
        graph.add((product, ECSDI.pesoProducto, decimal_literal(weight)))

        graph.add(
            (
                product,
                ECSDI.gestionEnvioExterno,
                Literal(bool(product_data.get("gestion_envio_externo", True)), datatype=XSD.boolean),
            )
        )
        graph.add((product, ECSDI.productoOfrecidoPor, sender))

        if product_data.get("fecha_llegada"):
            graph.add((product, ECSDI.fechaLlegadaProductoExterno, Literal(product_data["fecha_llegada"], datatype=XSD.dateTime)))

    return build_message(graph, action, ACL.request, sender, receiver)


def build_recommendation_inform(
    sender: URIRef,
    receiver: URIRef,
    recommendation_graph: Graph,
    response_node: URIRef,
) -> Graph:
    """AgenteFeedback → AsistenteVirtual: inform proactivo con Recomendacion.

    Envuelve el grafo de Recomendacion ya construido por el recomendador en
    un mensaje FIPA-ACL inform. No requiere respuesta del asistente.
    """

    return build_message(recommendation_graph, response_node, ACL.inform, sender, receiver)


def build_completed_order_info_request(sender: URIRef, receiver: URIRef, pedido_id: str) -> Graph:
    """AgenteDevolucion → AgenteComerciante: PeticionInfoPedidoCompletado."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/order-info/{uuid4()}"]
    pedido = _pedido_uri(pedido_id)
    graph.add((action, RDF.type, ECSDI.PeticionInfoPedidoCompletado))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((pedido, RDF.type, ECSDI.Pedido))
    graph.add((pedido, ECSDI.idPedido, Literal(_pedido_id_from_uri(pedido))))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_completed_order_info_response(
    sender: URIRef,
    receiver: URIRef,
    action: URIRef,
    order_graph: Graph,
    pedido: URIRef,
) -> Graph:
    """AgenteComerciante → AgenteDevolucion: RespuestaInfoPedidoCompletado."""
    graph = Graph()
    bind_namespaces(graph)
    _copy_business_graph(order_graph, graph)
    response = DATA[f"response/order-info/{uuid4()}"]
    graph.add((response, RDF.type, ECSDI.RespuestaInfoPedidoCompletado))
    graph.add((response, ECSDI.respuestaDeAccion, action))
    graph.add((response, ECSDI.respuestaSobrePedido, pedido))
    return build_message(graph, response, ACL.inform, sender, receiver)


def build_devolucion_request(
    sender: URIRef,
    receiver: URIRef,
    pedido_id: str,
    product_id: str,
    motivo: str,
) -> Graph:
    """AsistenteVirtual → AgenteDevolucion: SolicitarDevolucion."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/devolucion/{uuid4()}"]
    devolucion_id = f"DEV-{uuid4().hex[:8].upper()}"
    devolucion = DATA[f"devolucion/{devolucion_id}"]
    pedido = _pedido_uri(pedido_id)
    product = product_uri(product_id)

    graph.add((action, RDF.type, ECSDI.SolicitarDevolucion))
    graph.add((action, ECSDI.accionSolicitadaPor, sender))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.accionSobreProducto, product))

    graph.add((devolucion, RDF.type, ECSDI.Devolucion))
    graph.add((devolucion, ECSDI.idDevolucion, Literal(devolucion_id)))
    graph.add((devolucion, ECSDI.devolucionDePedido, pedido))
    graph.add((devolucion, ECSDI.devolucionDeProducto, product))
    graph.add((devolucion, ECSDI.motivoDevolucion, Literal(motivo)))
    graph.add((devolucion, ECSDI.fechaSolicitudDevolucion, Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)))

    graph.add((pedido, RDF.type, ECSDI.Pedido))
    graph.add((pedido, ECSDI.idPedido, Literal(_pedido_id_from_uri(pedido))))
    graph.add((product, RDF.type, ECSDI.Producto))
    graph.add((product, ECSDI.idProducto, Literal(product_id)))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_reembolso_request(
    sender: URIRef,
    receiver: URIRef,
    devolucion: URIRef,
    pedido: URIRef,
    product: URIRef,
    importe: Decimal,
    payment_method: str | None = None,
    payment_card: str | None = None,
) -> Graph:
    """AgenteDevolucion → AgenteFinanciero: SolicitarReembolso."""
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/reembolso/{uuid4()}"]
    operacion = DATA[f"pago/reembolso/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.SolicitarReembolso))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.accionSobreProducto, product))
    graph.add((action, ECSDI.accionTieneOperacionPago, operacion))
    method = (payment_method or "transferencia").strip().lower()
    graph.add((action, ECSDI.metodoPago, Literal(method)))
    graph.add((operacion, RDF.type, ECSDI.ReembolsoCliente))
    graph.add((operacion, ECSDI.idOperacionPago, Literal(f"RB-{uuid4().hex[:8].upper()}")))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.metodoPago, Literal(method)))
    if method == "tarjeta":
        card_digits = normalize_card_digits(payment_card)
        if card_digits:
            graph.add((action, ECSDI.tarjeta, Literal(card_digits)))
            graph.add((operacion, ECSDI.tarjeta, Literal(card_digits)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("solicitada")))
    graph.add((devolucion, ECSDI.devolucionTieneReembolso, operacion))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_valoracion_request(
    sender: URIRef,
    receiver: URIRef,
    pedido_id: str,
    product_id: str,
    puntuacion: int,
    comentario: str,
) -> Graph:
    """AsistenteVirtual → AgenteFeedback: EnviarOpinion.

    Plan: RegistrarOpinionProducto (AgenteFeedback / ObtenerOpinionProductoComprado).
    Es una comunicacion informativa: lleva enlazada la Valoracion enviada.
    """
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/valoracion/{uuid4()}"]
    valoracion = DATA[f"valoracion/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.EnviarOpinion))
    graph.add((action, ECSDI.notificacionSobreProducto, product_uri(product_id)))
    graph.add((action, ECSDI.notificacionTieneValoracion, valoracion))
    graph.add((valoracion, RDF.type, ECSDI.Valoracion))
    graph.add((valoracion, ECSDI.valoracionDeProducto, product_uri(product_id)))
    graph.add((valoracion, ECSDI.valoracionEnviadaPor, sender))
    graph.add((valoracion, ECSDI.valoracionDePedido, Literal(pedido_id)))
    graph.add((valoracion, ECSDI.puntuacion, Literal(puntuacion, datatype=XSD.integer)))
    graph.add((valoracion, ECSDI.comentario, Literal(comentario)))
    return build_message(graph, action, ACL.inform, sender, receiver)


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


def build_pago_externo_request(
    sender: URIRef,
    receiver: URIRef,
    pedido: URIRef,
    product: URIRef,
    vendedor: URIRef,
    importe: Decimal,
) -> Graph:
    """AgenteComerciante → AgenteFinanciero: PagarProductoExterno.

    Plan: ComunicarVendedoresExternos (AgenteComerciante / ComunicarConVendedoresExternos).
    Msg saliente: PagarProductoExterno.
    """
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/pago/externo/{uuid4()}"]
    operacion = DATA[f"pago/externo/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.PagarProductoExterno))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.accionSobreProducto, product))
    graph.add((action, ECSDI.importeCobro, decimal_literal(importe)))
    graph.add((action, ECSDI.vendedorDestinatario, vendedor))
    graph.add((action, ECSDI.accionTieneOperacionPago, operacion))
    graph.add((operacion, RDF.type, ECSDI.PagoVendedorExterno))
    graph.add((operacion, ECSDI.importeOperacion, decimal_literal(importe)))
    graph.add((operacion, ECSDI.estadoOperacion, Literal("solicitada")))
    return build_message(graph, action, ACL.request, sender, receiver)


def build_aviso_vendedor_externo(
    sender: URIRef,
    receiver: URIRef,
    pedido: URIRef,
    product: URIRef,
    address: URIRef | None,
    address_graph: Graph | None,
) -> Graph:
    """AgenteComerciante → AgenteVendedorExterno: ComunicarProductosExternosPedidos.

    Plan: ComunicarVendedoresExternos (AgenteComerciante / ComunicarConVendedoresExternos).
    Solo se llama cuando gestionEnvioExterno=true; se le dice al vendedor
    el producto pedido y donde tiene que enviarlo.
    Fire-and-forget: se asume que siempre va bien (diseño).
    """
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/aviso/vendedor/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.ComunicarProductosExternosPedidos))
    graph.add((action, ECSDI.accionSobrePedido, pedido))
    graph.add((action, ECSDI.accionSobreProducto, product))
    if address is not None:
        graph.add((action, ECSDI.envioDestinoDir, address))
        if address_graph is not None:
            for triple in address_graph.triples((address, None, None)):
                graph.add(triple)
    return build_message(graph, action, ACL.request, sender, receiver)


def _add_text_restriction(graph: Graph, action: URIRef, restriction_type: URIRef, text: str) -> None:
    restriction = DATA[f"restriction/text/{uuid4()}"]
    graph.add((restriction, RDF.type, restriction_type))
    graph.add((restriction, ECSDI.valorTextoRestriccion, Literal(text)))
    graph.add((action, ECSDI.accionTieneRestriccion, restriction))


def _copy_business_graph(source: Graph, target: Graph) -> None:
    # Delegamos en la versión canónica en utilities/comm.py para evitar
    # divergencias entre módulos.
    from .comm import copy_business_graph as _copy

    _copy(source, target)


def _copy_stock_context(source: Graph, target: Graph, product: URIRef) -> None:
    for stock in source.subjects(ECSDI.stockDeProducto, product):
        for triple in source.triples((stock, None, None)):
            target.add(triple)
        center = next(source.objects(stock, ECSDI.stockEnCentro), None)
        if center is not None:
            for triple in source.triples((center, None, None)):
                target.add(triple)


def _pedido_uri(pedido_id: str) -> URIRef:
    if pedido_id.startswith("http://") or pedido_id.startswith("https://"):
        return URIRef(pedido_id)
    return DATA[f"pedido/{pedido_id}"]


def _pedido_id_from_uri(pedido: URIRef) -> str:
    uri = str(pedido)
    if "/pedido/" in uri:
        return uri.rsplit("/pedido/", 1)[-1]
    return uri.rsplit("/", 1)[-1]
