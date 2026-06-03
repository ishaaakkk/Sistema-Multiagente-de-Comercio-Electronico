import argparse
from decimal import Decimal

from rdflib.namespace import RDF

from utilities.builders import build_devolucion_request, build_order_message, build_search_message
from utilities.http import post_graph
from utilities.namespaces import AGENTS, ECSDI


def main():
    parser = argparse.ArgumentParser(description="Demo fase 3: compra y devolucion de un producto.")
    parser.add_argument("--catalog-url", default="http://127.0.0.1:9006/comm")
    parser.add_argument("--shop-url", default="http://127.0.0.1:9001/comm")
    parser.add_argument("--devolucion-url", default="http://127.0.0.1:9009/comm")
    parser.add_argument("--pedido-id", default=None, help="Pedido ya completado. Si no se indica, la demo crea uno.")
    parser.add_argument("--product-id", default=None, help="Producto a devolver. Si no se indica, se usa el producto comprado.")
    parser.add_argument("--motivo", default="Producto defectuoso")
    parser.add_argument("--search-name", default="iphone")
    parser.add_argument("--max-price", type=Decimal, default=Decimal("1300"))
    parser.add_argument("--city", default="Barcelona")
    parser.add_argument("--street", default="Carrer Mallorca 401")
    parser.add_argument("--postal-code", default="08013")
    parser.add_argument("--country", default="Espana")
    parser.add_argument("--priority", type=int, default=1)
    parser.add_argument("--payment-method", default="tarjeta", choices=["tarjeta", "paypal", "transferencia"])
    parser.add_argument("--payment-card", default="4111111111111111", help="PAN para cobro con tarjeta (modo demo).")
    args = parser.parse_args()

    pedido_id = args.pedido_id
    product_id = args.product_id

    if not pedido_id and not product_id:
        pedido_id, product_id = _buy_product(args)
    elif not pedido_id or not product_id:
        parser.error("--pedido-id y --product-id deben indicarse juntos")

    response = post_graph(
        args.devolucion_url,
        build_devolucion_request(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteDevolucion,
            pedido_id=pedido_id,
            product_id=product_id,
            motivo=args.motivo,
        ),
    )
    _print_devolucion(response, pedido_id, product_id)


def _buy_product(args) -> tuple[str, str]:
    search_message = build_search_message(
        sender=AGENTS.AsistenteVirtual,
        receiver=AGENTS.AgenteCatalogo,
        constraints={"name": args.search_name, "max_price": args.max_price},
    )
    search_response = post_graph(args.catalog_url, search_message)
    products = list(search_response.objects(None, ECSDI.resultadoContieneProducto))
    if not products:
        raise RuntimeError("No hay productos para comprar antes de la devolucion")

    chosen = products[0]
    product_id = str(next(search_response.objects(chosen, ECSDI.idProducto)))
    price = Decimal(str(next(search_response.objects(chosen, ECSDI.precioProducto), "0")))
    print(f"Producto comprado para la demo: {product_id} - {price} EUR")

    order_message = build_order_message(
        sender=AGENTS.AsistenteVirtual,
        receiver=AGENTS.AgenteComerciante,
        product_quantities={product_id: 1},
        product_prices={product_id: price},
        city=args.city,
        street=args.street,
        postal_code=args.postal_code,
        country=args.country,
        priority=args.priority,
        payment_method=args.payment_method,
        payment_card=args.payment_card,
        catalog_graph=search_response,
    )
    order_response = post_graph(args.shop_url, order_message)
    pedido = next(order_response.subjects(RDF.type, ECSDI.Pedido), None)
    pedido_id = str(next(order_response.objects(pedido, ECSDI.idPedido), ""))
    if not pedido_id:
        raise RuntimeError("El AgenteComerciante no devolvio un idPedido")

    print(f"Pedido completado: {pedido_id}")
    return pedido_id, product_id


def _print_devolucion(response, pedido_id: str, product_id: str) -> None:
    devolucion = next(response.subjects(RDF.type, ECSDI.Devolucion), None)
    accepted = next(response.objects(devolucion, ECSDI.devolucionAceptada), "")
    instructions = next(response.objects(devolucion, ECSDI.instruccionesDevolucion), "")
    pickup = next(response.objects(devolucion, ECSDI.fechaRecogidaDevolucion), "")
    reembolso = next(response.objects(devolucion, ECSDI.devolucionTieneReembolso), None)

    print("\nResolucion de devolucion:")
    print(f"Pedido:   {pedido_id}")
    print(f"Producto: {product_id}")
    print(f"Aceptada: {accepted}")
    print(f"Recogida: {pickup}")
    print(f"Detalle:  {instructions}")

    if reembolso is not None:
        importe = next(response.objects(reembolso, ECSDI.importeOperacion), "")
        estado = next(response.objects(reembolso, ECSDI.estadoOperacion), "")
        ref = next(response.objects(reembolso, ECSDI.referenciaPago), "")
        print(f"Reembolso: {importe} EUR ({estado}) ref={ref}")


if __name__ == "__main__":
    main()
