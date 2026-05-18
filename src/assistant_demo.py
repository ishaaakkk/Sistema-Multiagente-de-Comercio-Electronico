import argparse
from decimal import Decimal

from rdflib.namespace import RDF

from utilities.builders import build_order_message, build_search_message
from utilities.http import post_graph
from utilities.namespaces import AGENTS, ECSDI


def main():
    parser = argparse.ArgumentParser(description="Demo de fase 2: busqueda y compra simple.")
    parser.add_argument("--catalog-url", default="http://127.0.0.1:9006/comm")
    parser.add_argument("--shop-url", default="http://127.0.0.1:9001/comm")
    parser.add_argument("--search-name", default="iphone")
    parser.add_argument("--max-price", type=Decimal, default=Decimal("1300"))
    parser.add_argument("--city", default="Barcelona")
    parser.add_argument("--street", default="Carrer Mallorca 401")
    parser.add_argument("--postal-code", default="08013")
    parser.add_argument("--country", default="Espana")
    parser.add_argument("--priority", type=int, default=1)
    args = parser.parse_args()

    # 1. Busqueda → AgenteCatalogo
    search_message = build_search_message(
        sender=AGENTS.AsistenteVirtual,
        receiver=AGENTS.AgenteCatalogo,
        constraints={"name": args.search_name, "max_price": args.max_price},
    )
    search_response = post_graph(args.catalog_url, search_message)
    products = list(search_response.objects(None, ECSDI.resultadoContieneProducto))

    print("Productos encontrados:")
    for idx, product in enumerate(products, start=1):
        name = next(search_response.objects(product, ECSDI.nombreProducto), "")
        price = next(search_response.objects(product, ECSDI.precioProducto), "")
        print(f"{idx}. {name} ({product}) - {price} EUR")

    if not products:
        print("No hay productos para comprar.")
        return

    # 2. El asistente elige el primer producto y conoce su precio del catalogo
    chosen = products[0]
    product_id = str(next(search_response.objects(chosen, ECSDI.idProducto)))
    price = Decimal(str(next(search_response.objects(chosen, ECSDI.precioProducto), "0")))

    # 3. Pedido → AgenteComerciante (TiendaAgent) con precio incluido en cada linea
    order_message = build_order_message(
        sender=AGENTS.AsistenteVirtual,
        receiver=AGENTS.TiendaAgent,
        product_quantities={product_id: 1},
        product_prices={product_id: price},
        city=args.city,
        street=args.street,
        postal_code=args.postal_code,
        country=args.country,
        priority=args.priority,
    )
    order_response = post_graph(args.shop_url, order_message)

    pedido = next(order_response.subjects(RDF.type, ECSDI.Pedido), None)
    factura = next(order_response.subjects(RDF.type, ECSDI.Factura), None)
    confirmacion = next(order_response.subjects(RDF.type, ECSDI.ConfirmacionEnvio), None)
    print("\nPedido creado:")
    print(f"Pedido: {next(order_response.objects(pedido, ECSDI.idPedido), pedido)}")
    print(f"Estado: {next(order_response.objects(pedido, ECSDI.estadoPedido), '')}")
    print(f"Factura: {next(order_response.objects(factura, ECSDI.idFactura), factura)}")
    print(f"Importe: {next(order_response.objects(factura, ECSDI.importeFactura), '')} EUR")
    print(f"Confirmacion envio: {confirmacion}")


if __name__ == "__main__":
    main()