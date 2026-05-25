# Documentación de la ontología

Este directorio contiene los artefactos generados a partir de
`ontology/comercio_electronico.ttl` y referenciados por la memoria
(criterio 4.2 del guión de la práctica).

## Archivos

- `comercio_electronico.html` — documentación de la ontología generada
  con [pyLODE](https://github.com/RDFLib/pyLODE).
- `comercio_electronico.dot` — diagrama de clases en formato Graphviz
  DOT (jerarquía `isA`, `disjointWith` y propiedades de objeto con
  dominio/rango entre clases).
- `comercio_electronico.png` *(opcional)* — render del DOT usando
  `dot -Tpng`.
- `Pylode/` — versión anterior (entregada en una fase previa).

## Cómo regenerar

```bash
# desde la raíz del repo, con el venv activado
python doc/ontology/generate_docs.py
```

Esto:
1. Genera la documentación HTML con `pylode`.
2. Crea el archivo DOT del grafo de clases.
3. Si `graphviz` (`dot`) está disponible, también genera el PNG.

Si la herramienta `owl2plot` se vuelve a publicar para la asignatura, se
puede usar como alternativa al paso 2:

```bash
owl2plot -i ontology/comercio_electronico.ttl -o doc/ontology/comercio_electronico.png
```
