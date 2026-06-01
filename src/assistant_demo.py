import argparse
import os
import sys
import time
from decimal import Decimal
from uuid import uuid4

from rdflib import Graph, Literal
from rdflib.namespace import RDF, RDFS

from utilities.acl import build_message, get_message
from utilities.builders import (
    build_devolucion_request,
    build_order_message,
    build_search_message,
    build_valoracion_request,
)
from utilities.http import post_graph
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demo de fase 4: busqueda, pedido, pago, feedback, recomendaciones y devolucion."
    )
    parser.add_argument("--catalog-url", default="http://127.0.0.1:9006/comm")
    parser.add_argument("--shop-url", default="http://127.0.0.1:9001/comm")
    parser.add_argument(
        "--order-timeout",
        type=float,
        default=float(os.environ.get("ORDER_TIMEOUT", "45")),
        help="Segundos de espera al comerciante (lotes pendientes + transporte).",
    )
    parser.add_argument("--feedback-url", default="http://127.0.0.1:9007/comm")
    parser.add_argument("--devolucion-url", default="http://127.0.0.1:9009/comm")
    parser.add_argument("--search-name", default="iphone")
    parser.add_argument("--extra-search-name", action="append", default=[], help="Busqueda adicional para pedidos multiproducto.")
    parser.add_argument("--brand", default=None)
    parser.add_argument("--min-price", type=Decimal, default=None)
    parser.add_argument("--max-price", type=Decimal, default=Decimal("1300"))
    parser.add_argument("--min-rating", type=Decimal, default=None)
    parser.add_argument("--product-index", type=int, default=1, help="Primer producto a comprar, empezando en 1.")
    parser.add_argument("--buy-results", type=int, default=1, help="Numero de productos consecutivos a comprar.")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--city", default="Barcelona")
    parser.add_argument("--street", default="Carrer Mallorca 401")
    parser.add_argument("--postal-code", default="08013")
    parser.add_argument("--country", default="Espana")
    parser.add_argument("--priority", type=int, default=1)
    parser.add_argument("--delivery-dist", type=int, default=130)
    parser.add_argument("--payment-method", default="tarjeta", choices=["tarjeta", "paypal", "transferencia"])
    parser.add_argument("--payment-card", default="")
    parser.add_argument("--rate", type=int, default=None, help="Puntuacion 1..5 para valorar el primer producto comprado.")
    parser.add_argument("--comment", default="Valoracion enviada desde assistant_demo.")
    parser.add_argument("--feedback-wait", type=float, default=1.0)
    parser.add_argument("--request-return", action="store_true")
    parser.add_argument("--return-reason", default="Producto defectuoso")
    parser.add_argument("--show-recommendations", action="store_true")
    args = parser.parse_args()

    products, catalog_graph = _search_products(args)
    if not products:
        print("No hay productos para comprar.")
        return 1

    _print_products(products)
    selected = _select_products(products, args.product_index, args.buy_results)
    if not selected:
        print("Seleccion vacia: revisa --product-index y --buy-results.")
        return 1

    product_quantities = {item["id"]: args.quantity for item in selected}
    product_prices = {item["id"]: Decimal(str(item["price"])) for item in selected}
    payment_method = _payment_label(args.payment_method, args.payment_card)

    order_message = build_order_message(
        sender=AGENTS.AsistenteVirtual,
        receiver=AGENTS.AgenteComerciante,
        product_quantities=product_quantities,
        product_prices=product_prices,
        city=args.city,
        street=args.street,
        postal_code=args.postal_code,
        country=args.country,
        priority=args.priority,
        payment_method=payment_method,
        delivery_dist=args.delivery_dist,
        catalog_graph=catalog_graph,
    )
    order_response = post_graph(args.shop_url, order_message, timeout=args.order_timeout)
    failure = _failure_reason(order_response, "El comerciante rechazo el pedido")
    if failure:
        print(f"Pedido rechazado: {failure}")
        return 1

    pedido = next(order_response.subjects(RDF.type, ECSDI.Pedido), None)
    factura = next(order_response.subjects(RDF.type, ECSDI.Factura), None)
    pedido_id = str(next(order_response.objects(pedido, ECSDI.idPedido), ""))

    print("\nPedido creado:")
    print(f"Pedido: {pedido_id or pedido}")
    print(f"Estado: {next(order_response.objects(pedido, ECSDI.estadoPedido), '')}")
    print(f"Factura: {next(order_response.objects(factura, ECSDI.idFactura), factura)}")
    print(f"Importe: {next(order_response.objects(factura, ECSDI.importeFactura), '')} EUR")
    print(f"Pago: {payment_method}")
    _print_shipping(order_response, pedido)

    first_product_id = selected[0]["id"]
    if args.rate is not None:
        _send_rating(args, pedido_id, first_product_id)
    if args.request_return:
        _request_return(args, pedido_id, first_product_id)
    if args.show_recommendations:
        _show_recommendations(args.feedback_url)

    return 0


def _search_products(args) -> tuple[list[dict], Graph]:
    all_products: list[dict] = []
    seen: set[str] = set()
    catalog_graph = Graph()
    bind_namespaces(catalog_graph)

    for search_name in [args.search_name, *args.extra_search_name]:
        constraints = _search_constraints(args, search_name)
        search_message = build_search_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteCatalogo,
            constraints=constraints,
        )
        response = post_graph(args.catalog_url, search_message)
        failure = _failure_reason(response, "El catalogo rechazo la busqueda")
        if failure:
            print(f"Busqueda rechazada ({search_name}): {failure}")
            continue
        for triple in response:
            catalog_graph.add(triple)
        for product in response.objects(None, ECSDI.resultadoContieneProducto):
            product_id = str(next(response.objects(product, ECSDI.idProducto), ""))
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            all_products.append(
                {
                    "id": product_id,
                    "name": str(next(response.objects(product, ECSDI.nombreProducto), "")),
                    "brand": str(next(response.objects(product, ECSDI.marcaProducto), "")),
                    "price": str(next(response.objects(product, ECSDI.precioProducto), "0")),
                    "rating": str(next(response.objects(product, ECSDI.valoracionMedia), "0")),
                    "uri": product,
                }
            )
    return all_products, catalog_graph


def _search_constraints(args, search_name: str) -> dict:
    constraints = {}
    if search_name:
        constraints["name"] = search_name
    if args.brand:
        constraints["brand"] = args.brand
    if args.min_price is not None:
        constraints["min_price"] = args.min_price
    if args.max_price is not None:
        constraints["max_price"] = args.max_price
    if args.min_rating is not None:
        constraints["min_rating"] = args.min_rating
    return constraints


def _select_products(products: list[dict], product_index: int, count: int) -> list[dict]:
    start = max(0, product_index - 1)
    end = start + max(1, count)
    return products[start:end]


def _print_products(products: list[dict]) -> None:
    print("Productos encontrados:")
    for idx, product in enumerate(products, start=1):
        print(
            f"{idx}. {product['name']} [{product['id']}] - "
            f"{product['price']} EUR - valoracion {product['rating']}"
        )


def _print_shipping(order_response: Graph, pedido) -> None:
    confirmations = list(order_response.objects(pedido, ECSDI.pedidoTieneConfirmacion))
    if confirmations:
        print("Envio interno:")
        for idx, confirmacion in enumerate(confirmations, start=1):
            envio = next(order_response.objects(confirmacion, ECSDI.confirmacionEnvio), None)
            transportista = next(order_response.objects(envio, ECSDI.envioRealizadoPor), None) if envio else None
            lote = next(order_response.objects(envio, ECSDI.envioTieneLote), None) if envio else None
            oferta = next(order_response.subjects(ECSDI.ofertaParaLote, lote), None) if lote else None
            fecha = next(order_response.objects(oferta, ECSDI.dataPrevista), None) if oferta else None
            precio_envio = next(order_response.objects(oferta, ECSDI.preuTransport), None) if oferta else None
            print(f"  {idx}. Transportista: {transportista}")
            print(f"     Fecha estimada: {fecha}")
            print(f"     Coste envio:    {precio_envio} EUR")
        return

    envio_ext = next(order_response.objects(pedido, ECSDI.pedidoTieneEnvio), None)
    if envio_ext:
        vendedor = next(order_response.objects(envio_ext, ECSDI.envioExternoGestionadoPor), None)
        print(f"Envio externo: el vendedor ({vendedor}) gestiona el envio directamente")
    else:
        print("Envio: no disponible")


def _send_rating(args, pedido_id: str, product_id: str) -> None:
    if not (1 <= args.rate <= 5):
        print("Valoracion omitida: --rate debe estar entre 1 y 5.")
        return
    if args.feedback_wait > 0:
        time.sleep(args.feedback_wait)
    response = post_graph(
        args.feedback_url,
        build_valoracion_request(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteFeedback,
            pedido_id=pedido_id,
            product_id=product_id,
            puntuacion=args.rate,
            comentario=args.comment,
        ),
    )
    failure = _failure_reason(response, "Feedback rechazo la valoracion")
    if failure:
        print(f"Valoracion rechazada: {failure}")
    else:
        print(f"Valoracion enviada: {product_id} -> {args.rate}/5")


def _request_return(args, pedido_id: str, product_id: str) -> None:
    response = post_graph(
        args.devolucion_url,
        build_devolucion_request(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteDevolucion,
            pedido_id=pedido_id,
            product_id=product_id,
            motivo=args.return_reason,
        ),
    )
    failure = _failure_reason(response, "Devolucion rechazo la solicitud")
    if failure:
        print(f"Devolucion rechazada: {failure}")
        return
    devolucion = next(response.subjects(RDF.type, ECSDI.Devolucion), None)
    accepted = str(next(response.objects(devolucion, ECSDI.devolucionAceptada), "false")).lower() in ("true", "1")
    instructions = str(next(response.objects(devolucion, ECSDI.instruccionesDevolucion), ""))
    pickup = str(next(response.objects(devolucion, ECSDI.fechaRecogidaDevolucion), ""))
    print(f"Devolucion aceptada: {accepted}")
    print(f"Instrucciones: {instructions}")
    if pickup:
        print(f"Recogida: {pickup}")


def _show_recommendations(feedback_url: str) -> None:
    graph = Graph()
    bind_namespaces(graph)
    action = DATA[f"action/recomendaciones/{uuid4()}"]
    graph.add((action, RDF.type, ECSDI.BuscarProductos))
    graph.add((action, ECSDI.tipoBusqueda, Literal("recomendacion")))
    response = post_graph(
        feedback_url,
        build_message(graph, action, ACL.request, AGENTS.AsistenteVirtual, AGENTS.AgenteFeedback),
    )
    failure = _failure_reason(response, "Feedback rechazo la recomendacion")
    if failure:
        print(f"Recomendaciones rechazadas: {failure}")
        return
    recommendations = list(response.subjects(RDF.type, ECSDI.Recomendacion))
    print("\nRecomendaciones:")
    if not recommendations:
        print("  Sin recomendaciones disponibles.")
        return
    for idx, rec in enumerate(recommendations, start=1):
        product = next(response.objects(rec, ECSDI.recomendacionDeProducto), None)
        name = str(next(response.objects(product, ECSDI.nombreProducto), "")) if product else ""
        product_id = str(next(response.objects(product, ECSDI.idProducto), "")) if product else ""
        reason = str(next(response.objects(rec, ECSDI.motivoRecomendacion), ""))
        print(f"  {idx}. {name} [{product_id}] - {reason}")


def _payment_label(method: str, card_number: str) -> str:
    method = (method or "tarjeta").strip()
    if method != "tarjeta":
        return method
    digits = "".join(ch for ch in str(card_number) if ch.isdigit())
    if len(digits) >= 4:
        return f"tarjeta ****{digits[-4:]}"
    return method


def _failure_reason(graph: Graph, default_reason: str) -> str | None:
    message = get_message(graph)
    if message is None or message.performative != ACL.failure:
        return None
    return str(next(graph.objects(None, RDFS.comment), "")) or default_reason


if __name__ == "__main__":
    sys.exit(main())
