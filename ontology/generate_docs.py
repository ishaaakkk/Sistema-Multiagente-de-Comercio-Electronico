#!/usr/bin/env python3
"""Generate ontology documentation and class diagrams in this directory.

Outputs:
  - comercio_electronico.html: pyLODE ontology documentation.
  - comercio_electronico.dot: Graphviz class diagram source.
  - comercio_electronico.png: rendered PNG diagram if graphviz is available.
  - comercio_electronico.svg: rendered SVG diagram if graphviz is available.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_DIR = Path(__file__).resolve().parent
ONTOLOGY = ONTOLOGY_DIR / "comercio_electronico.ttl"
HTML_OUT = ONTOLOGY_DIR / "comercio_electronico.html"
DOT_OUT = ONTOLOGY_DIR / "comercio_electronico.dot"
PNG_OUT = ONTOLOGY_DIR / "comercio_electronico.png"
SVG_OUT = ONTOLOGY_DIR / "comercio_electronico.svg"


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def run_pylode() -> None:
    subprocess.run(
        [sys.executable, "-m", "pylode", str(ONTOLOGY), "-o", str(HTML_OUT)],
        check=True,
    )
    print(f"[ok] pyLODE -> {_rel(HTML_OUT)}")


def _short(uri: URIRef) -> str:
    text = str(uri)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    return text.rsplit("/", 1)[-1]


def _node_id(uri: URIRef) -> str:
    return _short(uri).replace('"', r"\"")


def generate_dot() -> None:
    graph = Graph()
    graph.parse(ONTOLOGY, format="turtle")

    classes: set[URIRef] = {
        cls for cls in graph.subjects(RDF.type, OWL.Class) if isinstance(cls, URIRef)
    }

    subclass_edges: list[tuple[URIRef, URIRef]] = []
    for sub in classes:
        for sup in graph.objects(sub, RDFS.subClassOf):
            if isinstance(sup, URIRef) and sup in classes:
                subclass_edges.append((sub, sup))

    disjoint_edges: list[tuple[URIRef, URIRef]] = []
    for left, right in graph.subject_objects(OWL.disjointWith):
        if (
            isinstance(left, URIRef)
            and isinstance(right, URIRef)
            and left in classes
            and right in classes
        ):
            disjoint_edges.append((left, right))

    object_properties: list[tuple[URIRef, URIRef, URIRef]] = []
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = next(graph.objects(prop, RDFS.domain), None)
        range_ = next(graph.objects(prop, RDFS.range), None)
        if (
            isinstance(domain, URIRef)
            and isinstance(range_, URIRef)
            and domain in classes
            and range_ in classes
        ):
            object_properties.append((prop, domain, range_))

    lines = [
        "digraph ComercioElectronico {",
        "    graph [rankdir=BT, overlap=false, splines=true];",
        '    node [shape=box, style="rounded,filled", fillcolor="#f6f8ff", color="#6c7893", fontname="Helvetica"];',
        '    edge [fontsize=10, fontname="Helvetica"];',
    ]

    for cls in sorted(classes, key=lambda item: _short(item).lower()):
        lines.append(f'    "{_node_id(cls)}";')

    for sub, sup in sorted(subclass_edges, key=lambda edge: (_short(edge[0]), _short(edge[1]))):
        lines.append(
            f'    "{_node_id(sub)}" -> "{_node_id(sup)}" '
            '[label="isA", color="#2f5597"];'
        )

    for left, right in sorted(disjoint_edges, key=lambda edge: (_short(edge[0]), _short(edge[1]))):
        lines.append(
            f'    "{_node_id(left)}" -> "{_node_id(right)}" '
            '[label="disjoint", style=dashed, color="#c0392b", arrowhead=none];'
        )

    for prop, domain, range_ in sorted(
        object_properties,
        key=lambda item: (_short(item[1]), _short(item[2]), _short(item[0])),
    ):
        lines.append(
            f'    "{_node_id(domain)}" -> "{_node_id(range_)}" '
            f'[label="{_node_id(prop)}", color="#4d4d4d"];'
        )

    lines.append("}")
    DOT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ok] Graphviz DOT -> {_rel(DOT_OUT)}")


def render_diagrams() -> None:
    dot = shutil.which("dot")
    if dot is None:
        print("[warn] graphviz dot not found; only DOT was generated")
        return

    subprocess.run([dot, "-Tpng", str(DOT_OUT), "-o", str(PNG_OUT)], check=True)
    print(f"[ok] PNG -> {_rel(PNG_OUT)}")

    subprocess.run([dot, "-Tsvg", str(DOT_OUT), "-o", str(SVG_OUT)], check=True)
    print(f"[ok] SVG -> {_rel(SVG_OUT)}")


def main() -> None:
    run_pylode()
    generate_dot()
    render_diagrams()


if __name__ == "__main__":
    main()
