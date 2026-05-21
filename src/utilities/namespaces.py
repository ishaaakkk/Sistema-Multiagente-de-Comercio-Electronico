from rdflib import Namespace
from rdflib.namespace import FOAF, RDF, RDFS, XSD

ECSDI = Namespace("http://www.semanticweb.org/ecsdi/comercio_electronico/")
ACL = Namespace("http://www.nuin.org/ontology/fipa/acl#")
AGENTS = Namespace("http://www.semanticweb.org/ecsdi/agents/")
DATA = Namespace("http://www.semanticweb.org/ecsdi/comercio_electronico/instances/")
DSO = Namespace("http://www.semanticweb.org/ecsdi/directory/")


def bind_namespaces(graph):
    graph.bind("ecsdi", ECSDI)
    graph.bind("acl", ACL)
    graph.bind("agents", AGENTS)
    graph.bind("data", DATA)
    graph.bind("dso", DSO)
    graph.bind("foaf", FOAF)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    return graph