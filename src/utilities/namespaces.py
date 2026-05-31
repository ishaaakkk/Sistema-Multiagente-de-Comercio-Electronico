from rdflib import Namespace
from rdflib.namespace import RDF, RDFS, XSD

ECSDI = Namespace("http://www.semanticweb.org/ecsdi/comercio_electronico/")
# Ontologia de interoperabilidad CL <-> Transportista (grupo ecsdipractica).
ECOM = Namespace("http://www.semanticweb.org/ecsdipractica/ontology#")
ACL = Namespace("http://www.nuin.org/ontology/fipa/acl#")
AGENTS = Namespace("http://www.semanticweb.org/ecsdi/agents/")
DATA = Namespace("http://www.semanticweb.org/ecsdi/comercio_electronico/instances/")
DSO = Namespace("http://www.semanticweb.org/ecsdi/directory/")


def bind_namespaces(graph):
    graph.bind("ecsdi", ECSDI)
    graph.bind("ecom", ECOM)
    graph.bind("acl", ACL)
    graph.bind("agents", AGENTS)
    graph.bind("data", DATA)
    graph.bind("dso", DSO)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    return graph
