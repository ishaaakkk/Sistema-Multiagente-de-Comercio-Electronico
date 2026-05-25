#!/usr/bin/env python3
"""Regenera la documentación HTML de la ontología (pyLODE) y un diagrama
de clases en Graphviz DOT a partir de `ontology/comercio_electronico.ttl`.

Pensado para incluir tanto la documentación como el grafo en la memoria
(criterio 4.2 del guión de la práctica). Si `pylode` no está instalado se
ignora silenciosamente. Si `graphviz/dot` no está instalado se deja el
archivo `.dot` generado para que el usuario lo renderice cuando pueda.

Uso:

    python doc/ontology/generate_docs.py

Salida:
  - doc/ontology/comercio_electronico.html       (pyLODE)
  - doc/ontology/comercio_electronico.dot        (Graphviz DOT)
  - doc/ontology/comercio_electronico.png        (si dot está disponible)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDFS, RDF

ROOT = Path(__file__).resolve().parents[2]
ONTO = ROOT / "ontology" / "comercio_electronico.ttl"
OUT_DIR = ROOT / "doc" / "ontology"
HTML_OUT = OUT_DIR / "comercio_electronico.html"
DOT_OUT = OUT_DIR / "comercio_electronico.dot"
PNG_OUT = OUT_DIR / "comercio_electronico.png"


def run_pylode() -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "pylode", str(ONTO), "-o", str(HTML_OUT)],
            check=True,
        )
        print(f"[ok] pyLODE → {HTML_OUT.relative_to(ROOT)}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[warn] no se pudo ejecutar pyLODE: {exc}")


def _short(uri: URIRef) -> str:
    text = str(uri)
    if "#" in text:
        text = text.rsplit("#", 1)[-1]
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text or str(uri)


def generate_dot() -> None:
    graph = Graph()
    graph.parse(ONTO, format="turtle")

    classes: set[URIRef] = set()
    for cls in graph.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef):
            classes.add(cls)

    subclass_edges: list[tuple[URIRef, URIRef]] = []
    for sub in classes:
        for sup in graph.objects(sub, RDFS.subClassOf):
            if isinstance(sup, URIRef) and sup in classes:
                subclass_edges.append((sub, sup))

    disjoint_edges: list[tuple[URIRef, URIRef]] = []
    for s, o in graph.subject_objects(OWL.disjointWith):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and s in classes and o in classes:
            disjoint_edges.append((s, o))

    object_props: list[tuple[URIRef, URIRef, URIRef]] = []
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = next(graph.objects(prop, RDFS.domain), None)
        rng = next(graph.objects(prop, RDFS.range), None)
        if isinstance(domain, URIRef) and isinstance(rng, URIRef) and domain in classes and rng in classes:
            object_props.append((prop, domain, rng))

    lines = [
        "digraph ECSDI {",
        "    rankdir=BT;",
        "    node [shape=box, style=\"rounded,filled\", fillcolor=\"#f5f5ff\", fontname=\"Helvetica\"];",
        "    edge [fontsize=10, fontname=\"Helvetica\"];",
    ]
    for cls in sorted(classes, key=lambda x: _short(x).lower()):
        label = _short(cls)
        lines.append(f'    "{label}";')
    for sub, sup in subclass_edges:
        lines.append(f'    "{_short(sub)}" -> "{_short(sup)}" [label="isA", color="#3355cc"];')
    for a, b in disjoint_edges:
        lines.append(f'    "{_short(a)}" -> "{_short(b)}" [label="disjoint", style=dashed, color="#cc3333", arrowhead=none];')
    for prop, dom, rng in object_props:
        lines.append(f'    "{_short(dom)}" -> "{_short(rng)}" [label="{_short(prop)}", color="#444444"];')
    lines.append("}")

    DOT_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] Graphviz DOT → {DOT_OUT.relative_to(ROOT)}")


def render_png() -> None:
    dot_bin = shutil.which("dot")
    if not dot_bin:
        print("[warn] graphviz (`dot`) no encontrado; deja el .dot para renderizar después")
        return
    try:
        subprocess.run([dot_bin, "-Tpng", str(DOT_OUT), "-o", str(PNG_OUT)], check=True)
        print(f"[ok] PNG → {PNG_OUT.relative_to(ROOT)}")
    except subprocess.CalledProcessError as exc:
        print(f"[warn] dot falló: {exc}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_pylode()
    generate_dot()
    render_png()


if __name__ == "__main__":
    main()
