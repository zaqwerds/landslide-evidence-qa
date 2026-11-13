# schema/__init__.py
# Landslide ontology schema layer
# Use the supplied landslide TTL ontology as the schema source.

from .ontology_loader import OntologyLoader
from .schema_config import SchemaConfig

__all__ = ['OntologyLoader', 'SchemaConfig']
