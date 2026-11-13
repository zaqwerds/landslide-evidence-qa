# -*- coding: utf-8 -*-
"""Load a user-supplied landslide TTL ontology and expose a programmatic interface."""

import os
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict

from rdflib import Graph, RDF, RDFS, OWL, URIRef


class OntologyLoader:
    """Landslide ontology loader."""

    # Default to the ontology uploaded through the web interface.
    DEFAULT_TTL_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "input", "ontology.ttl",
    )

    def __init__(self, ttl_path: str = None):
        self.ttl_path = ttl_path or self.DEFAULT_TTL_PATH
        self.graph = Graph()
        self.base_uri = "http://www.semanticweb.org/94180/ontologies/2023/3/untitled-ontology-8/"

        # Parsed data structures
        self.classes: Dict[str, dict] = {}           # Class name -> {name, parents, children, desc, principle}
        self.object_properties: Dict[str, dict] = {} # Property name -> {name, domains, ranges, super_property, comment}
        self.data_properties: Dict[str, dict] = {}   # Property name -> {name, super_property}
        self.annotation_properties: List[str] = []

        # Derived structures
        self.class_tree: Dict[str, List[str]] = {}   # Parent class -> list of child classes
        self.root_classes: List[str] = []            # Root classes or top-level categories

        self._load()

    # Loading

    def _load(self):
        """Load and parse a Turtle file."""
        if not os.path.exists(self.ttl_path):
            raise FileNotFoundError(f"本体文件不存在: {self.ttl_path}")

        self.graph.parse(self.ttl_path, format='turtle')
        self._extract_classes()
        self._extract_object_properties()
        self._extract_data_properties()
        self._extract_annotation_properties()
        self._build_class_tree()

    def _short(self, uri) -> str:
        """Convert a URI to its short name."""
        if isinstance(uri, URIRef):
            s = str(uri)
            if '#' in s:
                return s.split('#')[-1]
            return s.split('/')[-1]
        return str(uri)

    # Class extraction

    def _extract_classes(self):
        """Extract OWL classes and hierarchy relationships."""
        note_prop = URIRef(self.base_uri + '说明')
        principle_prop = URIRef(self.base_uri + '原理简介')

        parent_map = defaultdict(set)  # child → {parents}

        for cls in self.graph.subjects(RDF.type, OWL.Class):
            name = self._short(cls)
            if name.startswith('N'):  # Skip blank nodes.
                continue

            # Retrieve parent classes.
            parents = []
            for parent in self.graph.objects(cls, RDFS.subClassOf):
                parent_name = self._short(parent)
                if not parent_name.startswith('N'):
                    parents.append(parent_name)
                    parent_map[name].add(parent_name)

            # Retrieve annotations.
            desc = ''
            for d in self.graph.objects(cls, note_prop):
                desc = str(d)

            principle = ''
            for p in self.graph.objects(cls, principle_prop):
                principle = str(p)[:200]

            self.classes[name] = {
                'name': name,
                'parents': parents,
                'desc': desc,
                'principle': principle,
            }

        # Populate children.
        for name in self.classes:
            self.classes[name]['children'] = []
        for child_name, parent_set in parent_map.items():
            if child_name in self.classes:
                for p in parent_set:
                    if p in self.classes:
                        self.classes[p].setdefault('children', []).append(child_name)

    def _build_class_tree(self):
        """Build the class tree and identify roots."""
        # Count references to each class as a parent of subclasses.
        all_children = set()
        for cls_info in self.classes.values():
            for parent in cls_info['parents']:
                all_children.add(parent)

        # Build parent-child relationships.
        for cls_name, cls_info in self.classes.items():
            for parent in cls_info['parents']:
                if parent not in self.class_tree:
                    self.class_tree[parent] = []
                if cls_name not in self.class_tree[parent]:
                    self.class_tree[parent].append(cls_name)

        # Root classes have children, occur in the class list and are not subclasses themselves.
        self.root_classes = sorted([
            name for name in self.class_tree
            if name not in all_children or name in self.classes
        ])

        # If no explicit roots are found, select classes without parents.
        if not self.root_classes:
            self.root_classes = sorted([
                name for name, info in self.classes.items()
                if not info['parents']
            ])

    # Object-property extraction

    def _extract_object_properties(self):
        """Extract object properties."""
        for prop in self.graph.subjects(RDF.type, OWL.ObjectProperty):
            name = self._short(prop)

            domains = [self._short(d) for d in self.graph.objects(prop, RDFS.domain)]
            ranges = [self._short(r) for r in self.graph.objects(prop, RDFS.range)]

            super_prop = ''
            for sp in self.graph.objects(prop, RDFS.subPropertyOf):
                super_prop = self._short(sp)

            comment = ''
            for c in self.graph.objects(prop, RDFS.comment):
                comment = str(c)

            self.object_properties[name] = {
                'name': name,
                'domains': domains,
                'ranges': ranges,
                'super_property': super_prop,
                'comment': comment,
            }

    # Datatype-property extraction

    def _extract_data_properties(self):
        """Extract datatype properties."""
        for prop in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
            name = self._short(prop)

            super_prop = ''
            for sp in self.graph.objects(prop, RDFS.subPropertyOf):
                super_prop = self._short(sp)

            self.data_properties[name] = {
                'name': name,
                'super_property': super_prop,
            }

    # Annotation-property extraction

    def _extract_annotation_properties(self):
        """Extract annotation properties."""
        for prop in self.graph.subjects(RDF.type, OWL.AnnotationProperty):
            self.annotation_properties.append(self._short(prop))

    # Query interface

    def get_class(self, name: str) -> Optional[dict]:
        """Return details of a specified class."""
        return self.classes.get(name)

    def get_class_children(self, name: str) -> List[str]:
        """Return the direct subclasses of a class."""
        return self.class_tree.get(name, [])

    def get_class_descendants(self, name: str, max_depth: int = 5) -> List[str]:
        """Recursively collect all descendant classes."""
        result = []
        children = self.get_class_children(name)
        for child in children:
            result.append(child)
            if max_depth > 1:
                result.extend(self.get_class_descendants(child, max_depth - 1))
        return result

    def get_class_ancestors(self, name: str) -> List[str]:
        """Collect all ancestors of a class."""
        if name not in self.classes:
            return []
        ancestors = []
        for parent in self.classes[name]['parents']:
            ancestors.append(parent)
            ancestors.extend(self.get_class_ancestors(parent))
        return ancestors

    def get_object_property(self, name: str) -> Optional[dict]:
        """Return a specified object property."""
        return self.object_properties.get(name)

    def get_data_property(self, name: str) -> Optional[dict]:
        """Return a specified datatype property."""
        return self.data_properties.get(name)

    def get_properties_by_domain(self, domain_class: str) -> List[str]:
        """Return object properties with the specified domain class."""
        result = []
        for prop_name, prop_info in self.object_properties.items():
            if domain_class in prop_info['domains']:
                result.append(prop_name)
        return result

    def get_properties_by_range(self, range_class: str) -> List[str]:
        """Return object properties whose ranges include the specified class."""
        result = []
        for prop_name, prop_info in self.object_properties.items():
            if range_class in prop_info['ranges']:
                result.append(prop_name)
        return result

    def is_valid_class(self, name: str) -> bool:
        """Check whether a class exists in the ontology."""
        return name in self.classes

    def is_valid_object_property(self, name: str) -> bool:
        """Check whether an object property exists in the ontology."""
        return name in self.object_properties

    def is_valid_data_property(self, name: str) -> bool:
        """Check whether a datatype property exists in the ontology."""
        return name in self.data_properties

    # Statistics

    def summary(self) -> dict:
        """Return ontology statistics."""
        return {
            'total_classes': len(self.classes),
            'total_object_properties': len(self.object_properties),
            'total_data_properties': len(self.data_properties),
            'total_annotation_properties': len(self.annotation_properties),
            'root_classes': self.root_classes,
            'class_tree_depth': self._max_tree_depth(),
        }

    def _max_tree_depth(self) -> int:
        """Compute the maximum depth of the class hierarchy."""
        def depth(name, visited=None):
            if visited is None:
                visited = set()
            if name in visited:
                return 0
            visited.add(name)
            children = self.class_tree.get(name, [])
            if not children:
                return 1
            return 1 + max(depth(c, visited.copy()) for c in children)
        return max((depth(r) for r in self.root_classes), default=0)

    def print_tree(self, name: str = None, indent: int = 0, max_depth: int = 3):
        """Print the class hierarchy."""
        if name is None:
            for root in self.root_classes:
                self.print_tree(root, 0, max_depth)
            return

        prefix = "  " * indent + ("├─ " if indent > 0 else "")
        print(f"{prefix}{name}")
        if indent >= max_depth:
            return
        for child in self.class_tree.get(name, []):
            self.print_tree(child, indent + 1, max_depth)


