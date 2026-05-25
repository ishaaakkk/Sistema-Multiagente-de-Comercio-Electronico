import argparse
from decimal import Decimal

from rdflib.namespace import RDF

from utilities.builders import build_order_message, build_search_message
from utilities.http import post_graph
from utilities.namespaces import AGENTS, ECSDI


def main():
    parser = argparse.ArgumentParser(description="Demo de fase 3: busqueda, compra y envio simple.")
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

    # 3. Pedido → AgenteComerciante con precio y datos completos del producto
    # Se pasa search_response como catalog_graph para que el comerciante
    # pueda clasificar correctamente la linea (interno/externo, gestionEnvioExterno)
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
        catalog_graph=search_response,
    )
    order_response = post_graph(args.shop_url, order_message)

    pedido = next(order_response.subjects(RDF.type, ECSDI.Pedido), None)
    factura = next(order_response.subjects(RDF.type, ECSDI.Factura), None)

    print("\nPedido creado:")
    print(f"Pedido: {next(order_response.objects(pedido, ECSDI.idPedido), pedido)}")
    print(f"Estado: {next(order_response.objects(pedido, ECSDI.estadoPedido), '')}")
    print(f"Factura: {next(order_response.objects(factura, ECSDI.idFactura), factura)}")
    print(f"Importe: {next(order_response.objects(factura, ECSDI.importeFactura), '')} EUR")

    # Envio interno — ConfirmacionEnvio enlazada al pedido
    confirmacion = next(order_response.objects(pedido, ECSDI.pedidoTieneConfirmacion), None)
    if confirmacion:
        envio = next(order_response.objects(confirmacion, ECSDI.confirmacionEnvio), None)
        transportista = next(order_response.objects(envio, ECSDI.envioRealizadoPor), None) if envio else None
        oferta = next(order_response.subjects(RDF.type, ECSDI.OfertaTransporte), None)
        fecha = next(order_response.objects(oferta, ECSDI.fechaEntregaEstimada), None) if oferta else None
        precio_envio = next(order_response.objects(oferta, ECSDI.precioOferta), None) if oferta else None
        print(f"Envio interno: OK")
        print(f"  Transportista: {transportista}")
        print(f"  Fecha estimada: {fecha}")
        print(f"  Coste envio:    {precio_envio} EUR")
    else:
        # Envio externo — EnvioExterno enlazado al pedido
        envio_ext = next(order_response.objects(pedido, ECSDI.pedidoTieneEnvio), None)
        if envio_ext:
            vendedor = next(order_response.objects(envio_ext, ECSDI.envioExternoGestionadoPor), None)
            print(f"Envio externo: el vendedor ({vendedor}) gestiona el envio directamente")
        else:
            print("Envio: no disponible")


if __name__ == "__main__":
    main()
