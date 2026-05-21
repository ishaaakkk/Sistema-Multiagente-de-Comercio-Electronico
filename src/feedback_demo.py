import argparse
import json
from decimal import Decimal
from urllib.request import urlopen

from rdflib.namespace import RDF

from utilities.builders import build_notify_purchase_completed, build_order_message, build_valoracion_request
from utilities.http import post_graph
from utilities.namespaces import AGENTS, ECSDI


def main():
    parser = argparse.ArgumentParser(description="Demo basica de AgenteFeedback: notificar compra y valorar.")
    parser.add_argument("--feedback-url", default="http://127.0.0.1:9007/comm")
    parser.add_argument("--pedido-id", default=None, help="ID de pedido (si no se simula notificacion)")
    parser.add_argument("--product-id", default="P-IPHONE19")
    parser.add_argument("--puntuacion", type=int, default=5)
    parser.add_argument("--comentario", default="Muy buen producto, entrega correcta.")
    parser.add_argument(
        "--simulate-notify",
        action="store_true",
        help="Envia NotificarCompraCompletada con un pedido de prueba antes de valorar",
    )
    args = parser.parse_args()

    pedido_id = args.pedido_id

    if args.simulate_notify or pedido_id is None:
        order_message = build_order_message(
            sender=AGENTS.AsistenteVirtual,
            receiver=AGENTS.AgenteComerciante,
            product_quantities={args.product_id: 1},
            product_prices={args.product_id: Decimal("1199.00")},
            city="Barcelona",
            street="Carrer Mallorca 401",
            postal_code="08013",
            country="Espana",
            priority=1,
        )
        pedido = next(order_message.subjects(RDF.type, ECSDI.Pedido), None)
        pedido_id = str(next(order_message.objects(pedido, ECSDI.idPedido), ""))
        notify_graph = build_notify_purchase_completed(
            AGENTS.AgenteComerciante,
            AGENTS.AgenteFeedback,
            order_message,
            pedido,
        )
        post_graph(args.feedback_url, notify_graph)
        print(f"Notificacion de compra enviada (pedido simulado: {pedido_id})")

    if not pedido_id:
        print("Falta pedido-id o usar --simulate-notify")
        return

    valoracion_message = build_valoracion_request(
        sender=AGENTS.AsistenteVirtual,
        receiver=AGENTS.AgenteFeedback,
        pedido_id=pedido_id,
        product_id=args.product_id,
        puntuacion=args.puntuacion,
        comentario=args.comentario,
    )
    response = post_graph(args.feedback_url, valoracion_message)

    valoracion = next(response.subjects(RDF.type, ECSDI.Valoracion), None)
    print("\nValoracion registrada:")
    print(f"  Producto: {next(response.objects(valoracion, ECSDI.valoracionDeProducto), '')}")
    print(f"  Puntuacion: {next(response.objects(valoracion, ECSDI.puntuacion), '')}")
    print(f"  Comentario: {next(response.objects(valoracion, ECSDI.comentario), '')}")

    status_url = args.feedback_url.replace("/comm", "/status")
    with urlopen(status_url) as resp:
        status = json.loads(resp.read().decode())
    print(f"\nEstado OpinionesDB: {status['total']} total, {len(status['pending'])} pendientes, {len(status['completed'])} completadas")


if __name__ == "__main__":
    main()
