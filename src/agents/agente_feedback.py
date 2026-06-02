import argparse
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from threading import Lock, Thread
from uuid import uuid4

from flask import Flask, jsonify
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from utilities.acl import build_failure, build_message, build_not_understood, correlate_reply, get_message
from utilities.builders import (
    build_pedir_feedback_request,
    build_recommendation_inform,
    build_valoracion_response,
)
from utilities.catalog import product_uri, update_product_average_rating
from utilities.comm import comm_url as _comm_url
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    search_service,
    unregister_service,
)
from utilities.storage import load_json, save_json, save_named_graph


DEFAULT_AGENT_URI = AGENTS.AgenteFeedback


# Retardo (en segundos) entre la fecha de entrega y la petición proactiva de
# feedback. En producción serían N días; en demo/pruebas se simula con
# FEEDBACK_DELAY_SECONDS para que la petición llegue en pocos segundos.
DEFAULT_FEEDBACK_DELAY_SECONDS = int(os.environ.get("FEEDBACK_DELAY_SECONDS", "60"))

# Periodo (en segundos) entre rondas de recomendación proactiva.
DEFAULT_RECOMMENDATION_PERIOD_SECONDS = int(
    os.environ.get("RECOMMENDATION_PERIOD_SECONDS", "300")
)

# Ventana inicial de espera antes de la primera ronda de recomendación para
# que los demás agentes terminen de levantarse.
DEFAULT_RECOMMENDATION_WARMUP_SECONDS = int(
    os.environ.get("RECOMMENDATION_WARMUP_SECONDS", "30")
)


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    assistant_url: str | None = None,
    feedback_delay_seconds: int = DEFAULT_FEEDBACK_DELAY_SECONDS,
    recommendation_period_seconds: int = DEFAULT_RECOMMENDATION_PERIOD_SECONDS,
    recommendation_warmup_seconds: int = DEFAULT_RECOMMENDATION_WARMUP_SECONDS,
    enable_recommendation_scheduler: bool = True,
):
    """Crea la aplicación Flask del agente feedback/recomendador.

    Responsabilidades (cap. 9 de los apuntes sobre recomendadores):
      * Mantener historial de compras, búsquedas (Protocolo Consulta Catálogo)
        y valoraciones por asistente virtual.
      * Pedir valoración tras la entrega — comportamiento proactivo diferido.
      * Generar recomendaciones periódicas y enviarlas como ACL.inform al
        asistente, además de responder a peticiones puntuales.
    """

    app = Flask(__name__)
    opinions_db: list[dict] = load_json("opinions.json", [])
    searches_db: list[dict] = load_json("searches.json", [])
    db_lock = Lock()

    @app.get("/")
    def index():
        return "AgenteFeedback listo"

    @app.get("/status")
    def status():
        return jsonify(
            {
                "opinions_total": len(opinions_db),
                "opinions_pending": [o for o in opinions_db if o["puntuacion"] is None],
                "opinions_completed": [o for o in opinions_db if o["puntuacion"] is not None],
                "searches_total": len(searches_db),
            }
        )

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(
                    build_not_understood(agent_uri, AGENTS.AsistenteVirtual, "Mensaje ACL no reconocido")
                )
            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))
            if message.performative not in (ACL.request, ACL.inform):
                return reply(build_not_understood(agent_uri, message.sender, "Se esperaba performativa request o inform"))

            action = message.content

            if (action, RDF.type, ECSDI.NotificarCompraCompletada) in graph:
                return reply(
                    _handle_notify_purchase(
                        opinions_db,
                        db_lock,
                        agent_uri,
                        message.sender,
                        action,
                        graph,
                        assistant_url,
                        feedback_delay_seconds,
                    )
                )

            if (action, RDF.type, ECSDI.NotificarBusquedaRealizada) in graph:
                return reply(
                    _handle_notify_search(
                        searches_db, db_lock, agent_uri, message.sender, action, graph
                    )
                )

            if _is_recommendation_request(graph, action):
                return reply(
                    _handle_recommendations(
                        opinions_db,
                        searches_db,
                        agent_uri,
                        message.sender,
                        action,
                    )
                )

            if (action, RDF.type, ECSDI.EnviarOpinion) in graph or (action, RDF.type, ECSDI.RegistrarValoracion) in graph:
                return reply(
                    _handle_registrar_valoracion(
                        opinions_db, db_lock, agent_uri, message.sender, action, graph
                    )
                )

            return reply(build_not_understood(agent_uri, message.sender, "Accion no soportada por AgenteFeedback"))
        except Exception as exc:
            return rdf_response(build_failure(agent_uri, AGENTS.AsistenteVirtual, None, str(exc)), status=500)

    if enable_recommendation_scheduler and assistant_url:
        Thread(
            target=_recommendation_scheduler,
            args=(
                opinions_db,
                searches_db,
                db_lock,
                agent_uri,
                assistant_url,
                recommendation_period_seconds,
                recommendation_warmup_seconds,
            ),
            daemon=True,
        ).start()

    return app


# --- Manejadores de mensajes -------------------------------------------------


def _handle_notify_purchase(
    opinions_db: list[dict],
    db_lock: Lock,
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
    assistant_url: str | None,
    feedback_delay_seconds: int,
) -> Graph:
    """Plan: RegistrarCompraParaFuturaOpinion — una entrada pendiente por linea de pedido."""

    pedido = next(graph.objects(action, ECSDI.notificacionSobrePedido), None)
    if pedido is None:
        pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
    if pedido is None:
        return build_failure(agent_uri, sender, action, "Falta accionSobrePedido")

    pedido_id = str(next(graph.objects(pedido, ECSDI.idPedido), ""))
    asistente = next(graph.objects(pedido, ECSDI.pedidoSolicitadoPor), AGENTS.AsistenteVirtual)
    fecha_entrega = _extract_delivery_date(graph)

    lines = list(graph.objects(pedido, ECSDI.pedidoTieneLinea))
    if not lines:
        return build_failure(agent_uri, sender, action, "El pedido no contiene lineas")

    new_records: list[dict] = []
    with db_lock:
        for line in lines:
            product = next(graph.objects(line, ECSDI.lineaDeProducto), None)
            if product is None:
                continue
            product_id = str(next(graph.objects(product, ECSDI.idProducto), _product_id_from_uri(product)))
            brand = str(next(graph.objects(product, ECSDI.marcaProducto), ""))
            quantity = int(next(graph.objects(line, ECSDI.cantidad), 1))
            record = {
                "pedido_id": pedido_id,
                "product_id": product_id,
                "product_uri": str(product),
                "brand": brand,
                "quantity": quantity,
                "asistente": str(asistente),
                "fecha_entrega": fecha_entrega,
                "fecha_registro": datetime.now().isoformat(timespec="seconds"),
                "puntuacion": None,
                "comentario": None,
                "feedback_solicitado": False,
            }
            opinions_db.append(record)
            new_records.append(record)
        save_json("opinions.json", opinions_db)
        _persist_opinions_rdf(opinions_db)

    log(
        "feedback",
        f"Compra registrada: pedido={pedido_id}, {len(new_records)} opinion(es) pendiente(s) (delay={feedback_delay_seconds}s)",
    )

    if assistant_url:
        _schedule_feedback_requests(
            new_records, opinions_db, db_lock, agent_uri, assistant_url, feedback_delay_seconds
        )

    return build_message(graph, action, ACL.inform, agent_uri, sender)


def _handle_notify_search(
    searches_db: list[dict],
    db_lock: Lock,
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Protocolo Consulta Catálogo: persistir la búsqueda en `searches.json`
    para alimentar el algoritmo de recomendación content-based.
    """

    asistente = next(graph.objects(action, ECSDI.accionSolicitadaPor), AGENTS.AsistenteVirtual)
    fecha = str(
        next(graph.objects(action, ECSDI.fechaBusqueda), Literal(datetime.now().isoformat(timespec="seconds")))
    )

    name = brand = None
    min_price = max_price = min_rating = None
    for restriction in graph.objects(action, ECSDI.accionTieneRestriccion):
        if (restriction, RDF.type, ECSDI.RestriccionNombre) in graph:
            name = str(next(graph.objects(restriction, ECSDI.valorTextoRestriccion), ""))
        elif (restriction, RDF.type, ECSDI.RestriccionMarca) in graph:
            brand = str(next(graph.objects(restriction, ECSDI.valorTextoRestriccion), ""))
        elif (restriction, RDF.type, ECSDI.RestriccionPrecio) in graph:
            v = next(graph.objects(restriction, ECSDI.precioMinimo), None)
            if v is not None:
                min_price = str(v)
            v = next(graph.objects(restriction, ECSDI.precioMaximo), None)
            if v is not None:
                max_price = str(v)
        elif (restriction, RDF.type, ECSDI.RestriccionValoracion) in graph:
            v = next(graph.objects(restriction, ECSDI.valoracionMinima), None)
            if v is not None:
                min_rating = str(v)

    result_nodes = list(graph.objects(action, ECSDI.resultadoContieneProducto))
    products = [str(p) for p in result_nodes]
    result_details = [
        _product_detail_from_graph(graph, product, fallback_brand=brand)
        for product in result_nodes
    ]
    catalog_nodes = set(result_nodes)
    catalog_nodes.update(graph.subjects(RDF.type, ECSDI.Producto))
    catalog_nodes.update(graph.subjects(RDF.type, ECSDI.ProductoInterno))
    catalog_nodes.update(graph.subjects(RDF.type, ECSDI.ProductoExterno))
    catalog_details = [
        _product_detail_from_graph(graph, product)
        for product in sorted(catalog_nodes, key=str)
    ]

    record = {
        "asistente": str(asistente),
        "fecha": fecha,
        "name": name,
        "brand": brand,
        "min_price": min_price,
        "max_price": max_price,
        "min_rating": min_rating,
        "results": products,
        "result_details": result_details,
        "catalog_details": catalog_details,
    }
    with db_lock:
        searches_db.append(record)
        save_json("searches.json", searches_db)
        _persist_searches_rdf(searches_db)

    log(
        "feedback",
        f"Protocolo Consulta Catálogo: búsqueda registrada (asistente={asistente}, marca={brand}, productos={len(products)})",
    )
    return build_message(graph, action, ACL.inform, agent_uri, sender)


def _handle_registrar_valoracion(
    opinions_db: list[dict],
    db_lock: Lock,
    agent_uri: URIRef,
    sender: URIRef,
    action: URIRef,
    graph: Graph,
) -> Graph:
    """Plan: RegistrarOpinionProducto — completa un registro pendiente con puntuacion y comentario."""

    valoracion = next(graph.objects(action, ECSDI.notificacionTieneValoracion), None)
    if valoracion is None:
        valoracion = next(graph.objects(action, ECSDI.accionTieneValoracion), None)
    if valoracion is None:
        valoracion = next(graph.subjects(RDF.type, ECSDI.Valoracion), None)
    if valoracion is None:
        return build_failure(agent_uri, sender, action, "Falta la valoracion en RegistrarValoracion")

    pedido_id = str(next(graph.objects(valoracion, ECSDI.valoracionDePedido), ""))
    product = next(graph.objects(valoracion, ECSDI.valoracionDeProducto), None)
    product_id = str(next(graph.objects(product, ECSDI.idProducto), _product_id_from_uri(product))) if product else ""
    puntuacion = int(next(graph.objects(valoracion, ECSDI.puntuacion), 0))
    comentario = str(next(graph.objects(valoracion, ECSDI.comentario), ""))

    with db_lock:
        record = _find_pending(opinions_db, pedido_id, product_id)
        if record is None:
            return build_failure(
                agent_uri,
                sender,
                action,
                f"No hay opinion pendiente para pedido={pedido_id} producto={product_id}",
            )

        record["puntuacion"] = puntuacion
        record["comentario"] = comentario
        record["fecha_valoracion"] = datetime.now().isoformat(timespec="seconds")
        save_json("opinions.json", opinions_db)
        _persist_opinions_rdf(opinions_db)
        new_average = _average_rating_for_product(opinions_db, product_id)
        if new_average is not None:
            update_product_average_rating(product_id, f"{new_average:.2f}")

    valoracion_graph = Graph()
    bind_namespaces(valoracion_graph)
    stored = DATA[f"valoracion/stored/{uuid4()}"]
    valoracion_graph.add((stored, RDF.type, ECSDI.Valoracion))
    valoracion_graph.add((stored, ECSDI.valoracionDeProducto, product_uri(product_id)))
    valoracion_graph.add((stored, ECSDI.valoracionEnviadaPor, sender))
    valoracion_graph.add((stored, ECSDI.valoracionDePedido, Literal(pedido_id)))
    valoracion_graph.add((stored, ECSDI.puntuacion, Literal(puntuacion, datatype=XSD.integer)))
    valoracion_graph.add((stored, ECSDI.comentario, Literal(comentario)))
    valoracion_graph.add(
        (
            stored,
            ECSDI.fechaValoracion,
            Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime),
        )
    )

    log(
        "feedback",
        f"Valoracion registrada: pedido={pedido_id} producto={product_id} puntuacion={puntuacion}",
    )
    return build_valoracion_response(agent_uri, sender, stored, valoracion_graph)


def _handle_recommendations(
    opinions_db: list[dict],
    searches_db: list[dict],
    agent_uri: URIRef,
    receiver: URIRef,
    action: URIRef,
) -> Graph:
    """Respuesta puntual a una BuscarProductos con tipo=recomendacion.

    Usa el mismo algoritmo content-based que la recomendación proactiva.
    """

    response_node, graph = _build_recommendation_graph(
        opinions_db, searches_db, str(receiver), agent_uri, receiver, action_uri=action, top_n=3
    )
    return build_message(graph, response_node, ACL.inform, agent_uri, receiver)


# --- Algoritmo de recomendación content-based (cap. 9) ----------------------


def _build_recommendation_graph(
    opinions_db: list[dict],
    searches_db: list[dict],
    asistente_uri: str,
    agent_uri: URIRef,
    receiver: URIRef,
    action_uri: URIRef | None,
    top_n: int = 3,
) -> tuple[URIRef, Graph]:
    """Construye un grafo RDF con la respuesta de recomendaciones.

    Algoritmo content-based: para cada candidato producto que el usuario aún
    no ha comprado, calcula un score como:

        score = peso_compra * sum(brand_freq_compras)
              + peso_valoracion * sum(rating_norm)
              + peso_busqueda * sum(brand_freq_busquedas)

    donde el perfil del usuario se construye a partir de su historial de
    compras (con la marca de cada producto), búsquedas (marca/nombre
    consultado) y valoraciones (rating normalizado en [0, 1]). Los productos
    candidatos son aquellos que han aparecido en alguna búsqueda o en alguna
    compra/valoración del propio usuario u otros.
    """

    profile = _user_profile(asistente_uri, opinions_db, searches_db)
    candidates = _candidate_products(asistente_uri, opinions_db, searches_db)

    scored: list[tuple[float, dict]] = []
    for product in candidates:
        score = _score_product(profile, product)
        if score <= 0:
            continue
        scored.append((score, product))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        scored = _neutral_recommendations(candidates, profile["purchased"])
    top = scored[:top_n]

    response = DATA[f"response/recomendaciones/{uuid4()}"]
    graph = _materialize_recommendations_sparql(top, response, receiver, action_uri)

    log("feedback", f"Recomendaciones content-based generadas: {len(top)} candidato(s) para {asistente_uri}")
    return response, graph


_RECOMMENDATION_CONSTRUCT_SPARQL = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ecsdi: <http://www.semanticweb.org/ecsdi/comercio_electronico/>

    CONSTRUCT {
        ?response rdf:type ecsdi:Respuesta .
        ?product rdf:type ecsdi:Producto ;
                 ecsdi:idProducto ?pid ;
                 ecsdi:marcaProducto ?brand ;
                 ecsdi:nombreProducto ?name ;
                 ecsdi:precioProducto ?price ;
                 ecsdi:valoracionMedia ?rating .
    ?rec rdf:type ecsdi:Recomendacion ;
         ecsdi:recomendacionDeProducto ?product ;
         ecsdi:recomendacionParaAsistente ?receiver ;
         ecsdi:puntosRecomendacion ?score ;
         ecsdi:motivoRecomendacion ?motivo ;
         ecsdi:fechaRecomendacion ?fecha .
} WHERE {
    ?rec ecsdi:recomendacionDeProducto ?product ;
         ecsdi:puntosRecomendacion ?score ;
         ecsdi:motivoRecomendacion ?motivo ;
         ecsdi:fechaRecomendacion ?fecha .
        ?product ecsdi:idProducto ?pid .
        OPTIONAL { ?product ecsdi:marcaProducto ?brand }
        OPTIONAL { ?product ecsdi:nombreProducto ?name }
        OPTIONAL { ?product ecsdi:precioProducto ?price }
        OPTIONAL { ?product ecsdi:valoracionMedia ?rating }
    }
    """


def _materialize_recommendations_sparql(
    scored: list[tuple[float, dict]],
    response: URIRef,
    receiver: URIRef,
    action_uri: URIRef | None,
) -> Graph:
    """Materializa el grafo de Recomendacion vía SPARQL CONSTRUCT (cap. 6).

    Construye primero un grafo semilla con los tuples (producto, score) y
    aplica un CONSTRUCT para producir la respuesta normalizada. Esto evita
    repartir la lógica de serialización por todo el código y se documenta
    fácilmente en la memoria como uso real de SPARQL CONSTRUCT.
    """

    seed = Graph()
    bind_namespaces(seed)
    seed.add((response, RDF.type, ECSDI.Respuesta))
    if action_uri is not None:
        seed.add((response, ECSDI.respuestaDeAccion, action_uri))

    now_literal = Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime)
    for score, product in scored:
        product_node = URIRef(product["uri"])
        recommendation = DATA[f"recomendacion/{uuid4()}"]
        seed.add((product_node, ECSDI.idProducto, Literal(product["id"])))
        if product.get("brand"):
            seed.add((product_node, ECSDI.marcaProducto, Literal(product["brand"])))
        if product.get("name"):
            seed.add((product_node, ECSDI.nombreProducto, Literal(product["name"])))
        if product.get("price") is not None:
            seed.add((product_node, ECSDI.precioProducto, Literal(str(product["price"]), datatype=XSD.decimal)))
        if product.get("rating") is not None:
            seed.add((product_node, ECSDI.valoracionMedia, Literal(str(product["rating"]), datatype=XSD.decimal)))
        seed.add((recommendation, ECSDI.recomendacionDeProducto, product_node))
        seed.add((recommendation, ECSDI.recomendacionParaAsistente, receiver))
        seed.add(
            (
                recommendation,
                ECSDI.puntosRecomendacion,
                Literal(f"{score:.3f}", datatype=XSD.decimal),
            )
        )
        seed.add(
            (
                recommendation,
                ECSDI.motivoRecomendacion,
                Literal(f"Content-based score={score:.3f} (compras+valoraciones+busquedas)"),
            )
        )
        seed.add((recommendation, ECSDI.fechaRecomendacion, now_literal))

    materialized = seed.query(
        _RECOMMENDATION_CONSTRUCT_SPARQL, initBindings={"receiver": receiver, "response": response}
    ).graph
    bind_namespaces(materialized)
    # Mantener la cabecera de Respuesta (no sobrevive a través del CONSTRUCT).
    materialized.add((response, RDF.type, ECSDI.Respuesta))
    if action_uri is not None:
        materialized.add((response, ECSDI.respuestaDeAccion, action_uri))
    return materialized


def _user_profile(asistente_uri: str, opinions_db: list[dict], searches_db: list[dict]) -> dict:
    """Construye un perfil del usuario combinando historiales.

    Devuelve:
        brand_counts: Counter de marcas vistas/compradas/buscadas.
        rating_avg_per_brand: media de puntuaciones del usuario por marca.
        purchased_product_ids: set de productos ya comprados (no recomendar).
    """

    brand_counts: Counter = Counter()
    brand_ratings: defaultdict[str, list[int]] = defaultdict(list)
    purchased: set[str] = set()

    for record in opinions_db:
        if record.get("asistente") != asistente_uri:
            continue
        brand = record.get("brand") or ""
        if brand:
            brand_counts[brand] += 1  # peso compra
        purchased.add(record["product_id"])
        if record.get("puntuacion") is not None:
            brand_ratings[brand].append(int(record["puntuacion"]))

    for record in searches_db:
        if record.get("asistente") != asistente_uri:
            continue
        brand = record.get("brand") or ""
        if brand:
            brand_counts[brand] += 0.3  # peso búsqueda menor
        for product in record.get("result_details", []):
            brand = product.get("brand") or ""
            if brand:
                brand_counts[brand] += 0.2

    rating_avg_per_brand = {b: (sum(rs) / len(rs)) for b, rs in brand_ratings.items() if rs}
    return {
        "brand_counts": brand_counts,
        "rating_avg_per_brand": rating_avg_per_brand,
        "purchased": purchased,
    }


def _candidate_products(asistente_uri: str, opinions_db: list[dict], searches_db: list[dict]) -> list[dict]:
    """Reúne los productos vistos (en búsquedas) o comprados (por otros
    asistentes) como candidatos. Los productos comprados por el propio
    asistente se descartan.
    """

    purchased = {r["product_id"] for r in opinions_db if r.get("asistente") == asistente_uri}
    candidates: dict[str, dict] = {}

    for record in opinions_db:
        if record["product_id"] in purchased:
            continue
        candidates.setdefault(
            record["product_id"],
            {
                "id": record["product_id"],
                "uri": record["product_uri"],
                "brand": record.get("brand") or "",
            },
        )

    for record in searches_db:
        for product in record.get("catalog_details", []):
            product_id = product.get("id")
            if not product_id or product_id in purchased:
                continue
            candidates.setdefault(product_id, _normalize_product_candidate(product))

        for product in record.get("result_details", []):
            product_id = product.get("id")
            if not product_id or product_id in purchased:
                continue
            candidates.setdefault(product_id, _normalize_product_candidate(product))

        for uri in record.get("results", []):
            product_id = uri.rsplit("/producto/", 1)[-1] if "/producto/" in uri else uri.rsplit("/", 1)[-1]
            if product_id in purchased:
                continue
            candidates.setdefault(
                product_id,
                {
                    "id": product_id,
                    "uri": uri,
                    "brand": record.get("brand") or "",
                },
            )

    return list(candidates.values())


def _normalize_product_candidate(product: dict) -> dict:
    return {
        "id": str(product.get("id") or ""),
        "uri": str(product.get("uri") or product_uri(str(product.get("id") or ""))),
        "brand": str(product.get("brand") or ""),
        "name": str(product.get("name") or product.get("id") or ""),
        "price": product.get("price"),
        "rating": product.get("rating"),
    }


def _score_product(profile: dict, product: dict) -> float:
    brand = product.get("brand") or ""
    brand_count = float(profile["brand_counts"].get(brand, 0))
    rating_bonus = profile["rating_avg_per_brand"].get(brand, 0) / 5.0  # normalizado a [0, 1]
    # Score combinado: la presencia de la marca en historial pesa más y se
    # bonifica con la valoración media que el usuario ha dado a esa marca.
    return brand_count * (1.0 + rating_bonus)


def _neutral_recommendations(candidates: list[dict], purchased: set[str]) -> list[tuple[float, dict]]:
    """Fallback: ranking neutral por valoración/precio cuando no hay perfil."""

    if not candidates:
        return []
    pool = [p for p in candidates if p.get("id") not in purchased] or candidates
    scored: list[tuple[float, dict]] = []
    for product in pool:
        try:
            rating = float(product.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        try:
            price = float(product.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        # La valoración domina; el precio sólo desempata de forma suave.
        score = max(rating, 0.1) + (1.0 / (1.0 + price) if price > 0 else 0)
        scored.append((score, product))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


# --- Schedulers --------------------------------------------------------------


def _schedule_feedback_requests(
    records: list[dict],
    opinions_db: list[dict],
    db_lock: Lock,
    agent_uri: URIRef,
    assistant_url: str,
    delay_seconds: int,
) -> None:
    """Lanza una petición PedirFeedback diferida (N días post-entrega).

    En producción serían N días después de fecha_entrega; aquí se simula con
    feedback_delay_seconds para que la demo lo dispare en pocos segundos.
    """

    for record in records:
        Thread(
            target=_send_feedback_request_delayed,
            args=(record, opinions_db, db_lock, agent_uri, assistant_url, delay_seconds),
            daemon=True,
        ).start()


def _send_feedback_request_delayed(
    record: dict,
    opinions_db: list[dict],
    db_lock: Lock,
    agent_uri: URIRef,
    assistant_url: str,
    delay_seconds: int,
) -> None:
    target_time = _delivery_target(record, delay_seconds)
    wait = max(0.0, (target_time - datetime.now()).total_seconds())
    if wait > 0:
        log(
            "feedback",
            f"PedirFeedback agendado: pedido={record['pedido_id']} producto={record['product_id']} en {wait:.0f}s",
        )
        time.sleep(wait)
    try:
        message = build_pedir_feedback_request(
            sender=agent_uri,
            receiver=URIRef(record["asistente"]),
            pedido_id=record["pedido_id"],
            product_id=record["product_id"],
            product=URIRef(record["product_uri"]),
        )
        post_graph(assistant_url, message)
        with db_lock:
            record["feedback_solicitado"] = True
            record["fecha_solicitud_feedback"] = datetime.now().isoformat(timespec="seconds")
            save_json("opinions.json", opinions_db)
            _persist_opinions_rdf(opinions_db)
        log(
            "feedback",
            f"PedirFeedback enviado tras delay: pedido={record['pedido_id']} producto={record['product_id']}",
        )
    except Exception as exc:
        log("feedback", f"No se pudo pedir feedback al asistente ({assistant_url}): {exc}")


def _delivery_target(record: dict, delay_seconds: int) -> datetime:
    """Calcula el instante objetivo para enviar PedirFeedback.

    Siempre usa delay desde el momento actual (ahora + delay).
    """

    return datetime.now() + timedelta(seconds=delay_seconds)


def _recommendation_scheduler(
    opinions_db: list[dict],
    searches_db: list[dict],
    db_lock: Lock,
    agent_uri: URIRef,
    assistant_url: str,
    period_seconds: int,
    warmup_seconds: int,
) -> None:
    """Envía Recomendacion como ACL.inform a cada asistente activo cada
    period_seconds. Se calcula una recomendación por asistente conocido en
    los historiales de compras y búsquedas.
    """

    if warmup_seconds > 0:
        time.sleep(warmup_seconds)
    log(
        "feedback",
        f"Recomendador proactivo arrancado (cada {period_seconds}s, warmup {warmup_seconds}s)",
    )
    while True:
        try:
            with db_lock:
                asistentes: set[str] = set()
                for r in opinions_db:
                    if r.get("asistente"):
                        asistentes.add(r["asistente"])
                for r in searches_db:
                    if r.get("asistente"):
                        asistentes.add(r["asistente"])
                snapshot_opinions = list(opinions_db)
                snapshot_searches = list(searches_db)

            for asistente in asistentes:
                try:
                    response_node, graph = _build_recommendation_graph(
                        snapshot_opinions,
                        snapshot_searches,
                        asistente,
                        agent_uri,
                        URIRef(asistente),
                        action_uri=None,
                        top_n=3,
                    )
                    if any(graph.subjects(RDF.type, ECSDI.Recomendacion)):
                        message = build_recommendation_inform(
                            agent_uri, URIRef(asistente), graph, response_node
                        )
                        post_graph(assistant_url, message)
                        log(
                            "feedback",
                            f"Recomendación proactiva enviada a {asistente}",
                        )
                except Exception as exc:
                    log("feedback", f"Error enviando recomendación proactiva a {asistente}: {exc}")
        except Exception as exc:
            log("feedback", f"Scheduler de recomendaciones falló: {exc}")

        time.sleep(period_seconds)


# --- Utilidades --------------------------------------------------------------


def _is_recommendation_request(graph: Graph, action: URIRef) -> bool:
    return (
        (action, RDF.type, ECSDI.BuscarProductos) in graph
        and str(next(graph.objects(action, ECSDI.tipoBusqueda), "")).casefold() == "recomendacion"
    )


def _extract_delivery_date(graph: Graph) -> str | None:
    from utilities.transport_proto import iter_transport_offers, offer_delivery_datetime

    for offer in iter_transport_offers(graph):
        fecha = offer_delivery_datetime(graph, offer)
        if fecha is not None:
            return fecha
    for envio in graph.subjects(RDF.type, ECSDI.EnvioInterno):
        lote = next(graph.objects(envio, ECSDI.envioTieneLote), None)
        if lote is not None:
            for offer in iter_transport_offers(graph):
                if (offer, ECSDI.ofertaParaLote, lote) in graph:
                    fecha = offer_delivery_datetime(graph, offer)
                    if fecha is not None:
                        return str(fecha)
    return None


def _product_id_from_uri(product: URIRef) -> str:
    uri = str(product)
    if "/producto/" in uri:
        return uri.rsplit("/producto/", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def _product_detail_from_graph(graph: Graph, product: URIRef, fallback_brand: str | None = None) -> dict:
    product_id = str(next(graph.objects(product, ECSDI.idProducto), _product_id_from_uri(product)))
    return {
        "id": product_id,
        "uri": str(product),
        "name": str(next(graph.objects(product, ECSDI.nombreProducto), product_id)),
        "brand": str(next(graph.objects(product, ECSDI.marcaProducto), fallback_brand or "")),
        "price": _literal_str(graph, product, ECSDI.precioProducto),
        "rating": _literal_str(graph, product, ECSDI.valoracionMedia),
    }


def _literal_str(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = next(graph.objects(subject, predicate), None)
    return str(value) if value is not None else None


def _find_pending(opinions_db: list[dict], pedido_id: str, product_id: str) -> dict | None:
    for record in reversed(opinions_db):
        if record["puntuacion"] is not None:
            continue
        if record["pedido_id"] == pedido_id and record["product_id"] == product_id:
            return record
    return None


def _average_rating_for_product(opinions_db: list[dict], product_id: str) -> float | None:
    ratings = [
        int(record["puntuacion"])
        for record in opinions_db
        if record.get("product_id") == product_id and record.get("puntuacion") is not None
    ]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9007)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--assistant-url", default=None)
    parser.add_argument(
        "--feedback-delay",
        type=int,
        default=DEFAULT_FEEDBACK_DELAY_SECONDS,
        help="Segundos entre la entrega y el envío de PedirFeedback (simula N días en demo)",
    )
    parser.add_argument(
        "--recommendation-period",
        type=int,
        default=DEFAULT_RECOMMENDATION_PERIOD_SECONDS,
        help="Periodo en segundos entre rondas de recomendación proactiva",
    )
    parser.add_argument(
        "--recommendation-warmup",
        type=int,
        default=DEFAULT_RECOMMENDATION_WARMUP_SECONDS,
        help="Espera inicial en segundos antes de la primera ronda de recomendación",
    )
    parser.add_argument(
        "--no-proactive-recommendation",
        action="store_true",
        default=False,
        help="Deshabilita el scheduler de recomendación periódica",
    )
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)
    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_FEEDBACK", advertised_host, args.port)
    assistant_base = args.assistant_url or search_service(args.dir, "AGENTE_ASISTENTE", service_id) or "http://127.0.0.1:9010"
    assistant_url = _comm_url(assistant_base)
    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_FEEDBACK",
        address,
        f"feedback-{args.port}",
        capabilities=[ECSDI.BuscarProductos],
    )
    try:
        log(
            f"feedback-{args.port}",
            (
                f"listening on {bind_host}:{args.port}, assistant={assistant_url}, "
                f"delay={args.feedback_delay}s, recomm_period={args.recommendation_period}s"
            ),
        )
        create_app(
            assistant_url=assistant_url,
            feedback_delay_seconds=args.feedback_delay,
            recommendation_period_seconds=args.recommendation_period,
            recommendation_warmup_seconds=args.recommendation_warmup,
            enable_recommendation_scheduler=not args.no_proactive_recommendation,
        ).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"feedback-{args.port}")


def _persist_opinions_rdf(opinions_db: list[dict]) -> None:
    """Espejo en RDF (Dataset común) de las opiniones almacenadas en JSON.

    Permite a la memoria y a posibles consumidores externos acceder a la
    misma información usando SPARQL, sin obligar a leer JSON.
    """

    graph = Graph()
    bind_namespaces(graph)
    for idx, record in enumerate(opinions_db):
        node = DATA[f"opinion/{record.get('pedido_id','')}/{record.get('product_id','')}/{idx}"]
        graph.add((node, RDF.type, ECSDI.Valoracion))
        if record.get("product_uri"):
            graph.add((node, ECSDI.valoracionDeProducto, URIRef(record["product_uri"])))
        if record.get("pedido_id"):
            graph.add((node, ECSDI.valoracionDePedido, Literal(record["pedido_id"])))
        if record.get("puntuacion") is not None:
            graph.add((node, ECSDI.puntuacion, Literal(record["puntuacion"], datatype=XSD.integer)))
        if record.get("comentario"):
            graph.add((node, ECSDI.comentario, Literal(record["comentario"])))
        if record.get("asistente"):
            graph.add((node, ECSDI.valoracionEnviadaPor, URIRef(record["asistente"])))
    save_named_graph("opinions", graph)


def _persist_searches_rdf(searches_db: list[dict]) -> None:
    """Espejo en RDF de las búsquedas (protocolo Consulta Catálogo)."""

    graph = Graph()
    bind_namespaces(graph)
    for idx, record in enumerate(searches_db):
        node = DATA[f"busqueda/{idx}"]
        graph.add((node, RDF.type, ECSDI.NotificarBusquedaRealizada))
        graph.add((node, RDF.type, ECSDI.ResultadoBusqueda))
        if record.get("fecha"):
            graph.add((node, ECSDI.fechaBusqueda, Literal(record["fecha"])))
        for product_uri in record.get("results", []):
            graph.add((node, ECSDI.resultadoContieneProducto, URIRef(product_uri)))
    save_named_graph("searches", graph)


if __name__ == "__main__":
    main()
