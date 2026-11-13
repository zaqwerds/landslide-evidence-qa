# -*- coding: utf-8 -*-
"""KGGen-style iterative clustering and deduplication utilities."""

import json
import re
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict
from dataclasses import dataclass, field
import numpy as np

from extraction.event_extractor import Event, EventKnowledge, EventType, EventRelation

# Optional dependency: pinyin processing
try:
    from pypinyin import lazy_pinyin, Style
    _PYIN_AVAILABLE = True
except ImportError:
    _PYIN_AVAILABLE = False

# Optional dependency: edit distance
try:
    import editdistance as _editdistance_lib
    _EDITDIST_AVAILABLE = True
except ImportError:
    _EDITDIST_AVAILABLE = False


@dataclass
class Cluster:
    """Cluster result with a canonical name and its members."""
    cluster_id: str
    canonical_name: str                     # Canonical name
    items: List[str] = field(default_factory=list)  # Cluster members
    cluster_type: str = "entity"            # entity / relation / event
    confidence: float = 0.0


class KGGenStyleCluster:
    """Iteratively deduplicate names using rule and optional embedding/refinement pathways."""

    def __init__(self, llm_caller=None):
        self.llm_caller = llm_caller
        self._embedding_model = None
        self._clusters: List[Cluster] = []

    # Entity clustering

    def cluster_entities(
        self,
        entity_names: List[str],
        entity_types: Dict[str, str] = None,
        max_iterations: int = 5,
        use_llm: bool = False,
        semantic_texts: Dict[str, str] = None,
    ) -> Dict[str, str]:
        """Cluster and deduplicate entities."""
        if len(entity_names) <= 1:
            return {name: name for name in entity_names}

        entity_types = entity_types or {}

        # 1. Rule-based pre-clustering
        clusters = self._rule_based_pre_clustering(entity_names, entity_types)

        # 2. Semantic embedding clustering
        if len(entity_names) > 20:
            clusters = self._semantic_clustering(
                entity_names, clusters, entity_types, semantic_texts or {}
            )

        # 3. Optional LLM-based assessment
        if use_llm and self.llm_caller:
            clusters = self._llm_based_refinement(clusters)

        # 4. Build the name mapping
        mapping = self._build_mapping(clusters, entity_names)

        self._clusters = clusters
        return mapping

    def cluster_events(
        self,
        events: List[Event],
        use_llm: bool = False,
    ) -> Dict[str, str]:
        """Cluster and deduplicate events."""
        event_names = [e.name for e in events]
        event_types = {e.name: e.event_type.value for e in events}
        semantic_texts = {}
        for event in events:
            attributes = " ".join(
                f"{key}:{value}" for key, value in event.attributes.items()
            )
            semantic_texts[event.name] = " ".join(
                part for part in [
                    event.event_type.value,
                    event.name,
                    event.trigger,
                    event.location,
                    event.time,
                    event.description,
                    attributes,
                ] if part
            )
        return self.cluster_entities(
            event_names,
            event_types,
            use_llm=use_llm,
            semantic_texts=semantic_texts,
        )

    def cluster_relations(
        self,
        knowledge: List[EventKnowledge],
        use_llm: bool = False,
    ) -> Dict[str, str]:
        """Cluster and deduplicate relationships."""
        rel_descs = [k.description for k in knowledge if k.description]
        return self.cluster_entities(rel_descs, use_llm=use_llm)

    # Rule-based clustering

    def _rule_based_pre_clustering(
        self,
        names: List[str],
        types: Dict[str, str],
    ) -> List[Cluster]:
        """Pre-cluster candidates using deterministic rules."""
        clusters = []
        processed = set()

        # Normalize the name.
        normalized_map = {}
        for name in names:
            normalized = self._normalize_name(name)
            normalized_map[name] = normalized

        # Group by type and normalized name; never merge different types merely because names are similar.
        # For example, a village location and the landslide named after that village are distinct.
        groups = defaultdict(list)
        for name in names:
            key = (types.get(name, ""), normalized_map[name])
            groups[key].append(name)

        for key, group in groups.items():
            canonical = self._select_canonical_name(group, types)
            cluster = Cluster(
                cluster_id=f"cl_{len(clusters):03d}",
                canonical_name=canonical,
                items=group,
                cluster_type="entity",
                confidence=1.0 if len(group) == 1 else 0.9,
            )
            clusters.append(cluster)

        # Pinyin-based clustering handles homophonic variants.
        clusters = self._pinyin_based_clustering(clusters, types)

        # Edit-distance clustering
        clusters = self._edit_distance_clustering(clusters, types)

        # Longest-common-substring clustering
        clusters = self._common_substring_clustering(clusters, types)

        # Merge highly overlapping candidates only within the same type.
        clusters = self._merge_similar_clusters(clusters, types)

        return clusters

    def _pinyin_based_clustering(
        self,
        clusters: List[Cluster],
        types: Dict[str, str],
    ) -> List[Cluster]:
        """Cluster homophonic name variants using pinyin similarity."""
        if not _PYIN_AVAILABLE:
            return clusters

        if len(clusters) <= 1:
            return clusters

        merged = []
        merged_indices = set()

        # Precompute each cluster's pinyin.
        pinyin_cache = {}
        for c in clusters:
            try:
                pinyin_cache[c.canonical_name] = ''.join(
                    lazy_pinyin(c.canonical_name, style=Style.NORMAL)
                )
            except Exception:
                pinyin_cache[c.canonical_name] = c.canonical_name.lower()

        for i, c1 in enumerate(clusters):
            if i in merged_indices:
                continue
            current = c1

            for j, c2 in enumerate(clusters):
                if j <= i or j in merged_indices:
                    continue

                p1 = pinyin_cache.get(c1.canonical_name, '')
                p2 = pinyin_cache.get(c2.canonical_name, '')

                # Identical pinyin can indicate homophonic variants.
                if p1 and p2 and p1 == p2 and len(p1) > 2:
                    t1 = types.get(c1.canonical_name, '')
                    t2 = types.get(c2.canonical_name, '')
                    if t1 == t2 or not t1 or not t2:
                        current.items.extend(c2.items)
                        current.canonical_name = min(
                            current.canonical_name, c2.canonical_name, key=len
                        )
                        merged_indices.add(j)

            merged.append(current)

        return merged

    def _edit_distance_clustering(
        self,
        clusters: List[Cluster],
        types: Dict[str, str],
        threshold: float = 0.8,
    ) -> List[Cluster]:
        """Cluster names using edit distance."""
        if len(clusters) <= 1:
            return clusters

        merged = []
        merged_indices = set()

        # Compute edit-distance similarity.
        def _edit_similarity(a: str, b: str) -> float:
            if _EDITDIST_AVAILABLE:
                try:
                    dist = _editdistance_lib.eval(a, b)
                    max_len = max(len(a), len(b))
                    if max_len == 0:
                        return 1.0
                    return 1.0 - (dist / max_len)
                except Exception:
                    pass
            # Fallback: local Levenshtein-distance implementation
            return self._levenshtein_similarity(a, b)

        for i, c1 in enumerate(clusters):
            if i in merged_indices:
                continue
            current = c1

            for j, c2 in enumerate(clusters):
                if j <= i or j in merged_indices:
                    continue

                t1 = types.get(c1.canonical_name, '')
                t2 = types.get(c2.canonical_name, '')

                # Consider edit-distance merges only within the same type.
                if t1 and t2 and t1 != t2:
                    continue

                sim = _edit_similarity(c1.canonical_name, c2.canonical_name)
                if sim >= threshold:
                    current.items.extend(c2.items)
                    current.canonical_name = min(
                        current.canonical_name, c2.canonical_name, key=len
                    )
                    merged_indices.add(j)

            merged.append(current)

        return merged

    def _levenshtein_similarity(self, a: str, b: str) -> float:
        """Compute Levenshtein similarity without an external distance library."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0

        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(2)]

        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            dp[1][0] = i
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[1][j] = dp[0][j - 1]
                else:
                    dp[1][j] = 1 + min(dp[0][j], dp[1][j - 1], dp[0][j - 1])
            dp[0], dp[1] = dp[1], dp[0]

        dist = dp[0][n]
        max_len = max(m, n)
        return 1.0 - (dist / max_len)

    def _common_substring_clustering(
        self,
        clusters: List[Cluster],
        types: Dict[str, str],
        min_lcs_length: int = 3,
    ) -> List[Cluster]:
        """Cluster using longest common substrings."""
        if len(clusters) <= 1:
            return clusters

        merged = []
        merged_indices = set()

        def _lcs_length(a: str, b: str) -> int:
            """Compute the length of the longest common substring."""
            if not a or not b:
                return 0
            m, n = len(a), len(b)
            dp = [[0] * (n + 1) for _ in range(2)]
            max_len = 0
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if a[i - 1] == b[j - 1]:
                        dp[1][j] = dp[0][j - 1] + 1
                        max_len = max(max_len, dp[1][j])
                    else:
                        dp[1][j] = 0
                dp[0], dp[1] = dp[1], dp[0]
            return max_len

        for i, c1 in enumerate(clusters):
            if i in merged_indices:
                continue
            current = c1

            for j, c2 in enumerate(clusters):
                if j <= i or j in merged_indices:
                    continue

                t1 = types.get(c1.canonical_name, '')
                t2 = types.get(c2.canonical_name, '')

                # Consider substring merges only within the same type.
                if t1 and t2 and t1 != t2:
                    continue

                lcs = _lcs_length(c1.canonical_name, c2.canonical_name)
                if lcs > min_lcs_length:
                    current.items.extend(c2.items)
                    current.canonical_name = min(
                        current.canonical_name, c2.canonical_name, key=len
                    )
                    merged_indices.add(j)

            merged.append(current)

        return merged

    def _normalize_name(self, name: str) -> str:
        """Normalize a candidate name."""
        # Remove punctuation.
        name = re.sub(r'[，。、；：！？""''（）【】《》\s]', '', name)
        # Remove common suffixes.
        for suffix in ['滑坡', '滑坡体', '滑体', '滑坡区', '滑坡隐患点']:
            if name.endswith(suffix) and len(name) > len(suffix) + 2:
                name = name[:-len(suffix)]
        # Convert to lowercase.
        name = name.lower()
        return name

    def _select_canonical_name(
        self,
        names: List[str],
        types: Dict[str, str],
    ) -> str:
        """Prefer informative, type-specific canonical names rather than always taking the shortest."""
        if not names:
            return ""

        def score(name: str) -> Tuple[int, int, int]:
            event_type = types.get(name, "")
            type_bonus = 0
            if event_type == EventType.DISASTER.value and any(
                token in name for token in ("滑坡", "崩塌", "泥石流", "变形", "裂缝")
            ):
                type_bonus = 3
                if name.endswith(("滑坡", "崩塌", "泥石流")):
                    type_bonus += 2
                if name.endswith(("滑坡体", "滑坡灾害", "滑坡隐患")):
                    type_bonus -= 1
            elif event_type == EventType.RESPONSE.value and any(
                token in name for token in ("治理", "防治", "监测", "预警", "处置")
            ):
                type_bonus = 3
            elif event_type == EventType.CONDITION.value and any(
                token in name for token in ("降雨", "地质", "水文", "地下水", "坡度")
            ):
                type_bonus = 3

            # Very short names may be locations or triggers; prefer complete event names of 3-20 characters.
            complete_bonus = 2 if 3 <= len(name) <= 20 else 0
            noise_penalty = -2 if any(token in name for token in ("隐患", "相关", "情况")) else 0
            return type_bonus + complete_bonus + noise_penalty, len(name), -names.index(name)

        return max(names, key=score)

    def _merge_similar_clusters(
        self,
        clusters: List[Cluster],
        types: Dict[str, str],
    ) -> List[Cluster]:
        """Merge eligible similar clusters."""
        if len(clusters) <= 1:
            return clusters

        merged = []
        merged_indices = set()

        for i, c1 in enumerate(clusters):
            if i in merged_indices:
                continue
            current = c1

            for j, c2 in enumerate(clusters):
                if j <= i or j in merged_indices:
                    continue

                # Check whether merging is allowed.
                t1 = types.get(c1.canonical_name, '')
                t2 = types.get(c2.canonical_name, '')

                if self._can_merge(c1.canonical_name, c2.canonical_name, t1, t2):
                    current.items.extend(c2.items)
                    current.canonical_name = min(
                        current.canonical_name, c2.canonical_name, key=len
                    )
                    merged_indices.add(j)

            merged.append(current)

        return merged

    def _can_merge(self, name1: str, name2: str, type1: str, type2: str) -> bool:
        """Check whether two names are eligible for merging."""
        n1 = self._normalize_name(name1)
        n2 = self._normalize_name(name2)

        # Do not merge different, nonempty types.
        if type1 and type2 and type1 != type2:
            return False

        # Exact match
        if n1 == n2:
            return True

        # One name contains the other.
        if len(n1) > 3 and len(n2) > 3:
            if n1 in n2 or n2 in n1:
                return True

        # Same type and high character overlap
        if type1 and type2 and type1 == type2:
            if len(n1) > 4 and len(n2) > 4:
                shared = sum(1 for c in n1 if c in n2)
                if shared / max(len(n1), len(n2)) > 0.7:
                    return True

        # Jaccard similarity over character sets
        if len(n1) > 3 and len(n2) > 3:
            if self._jaccard_similarity(n1, n2) > 0.65:
                return True

        return False

    def _jaccard_similarity(self, s1: str, s2: str) -> float:
        """Compute Jaccard similarity over character sets."""
        set1 = set(s1)
        set2 = set(s2)
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    # Clustering by type

    def cluster_by_type(
        self,
        items: List[Any],
        type_key: str = "event_type",
        name_key: str = "name",
    ) -> Dict[str, List[str]]:
        """Cluster within event types; do not merge different types."""
        from collections import defaultdict

        type_groups = defaultdict(list)
        type_names = defaultdict(list)

        for item in items:
            if hasattr(item, type_key):
                etype = str(getattr(item, type_key))
                ename = str(getattr(item, name_key))
            elif isinstance(item, dict):
                etype = str(item.get(type_key, 'unknown'))
                ename = str(item.get(name_key, ''))
            else:
                etype = 'unknown'
                ename = str(item)

            type_groups[etype].append(ename)
            type_names[etype].append(ename)

        # Cluster independently within each type.
        result = {}
        for etype, names in type_groups.items():
            if len(names) <= 1:
                result[etype] = list(names)
                continue

            type_map = {n: etype for n in names}
            mapping = self.cluster_entities(names, type_map)
            # Deduplicate and select canonical names.
            canonical_set = set(mapping.values())
            result[etype] = sorted(canonical_set)

        return result

    # Canonical attribute extraction

    def extract_canonical_attributes(
        self,
        events: List[Event],
        cluster_mapping: Dict[str, str],
    ) -> Dict[str, Dict[str, Tuple[str, float]]]:
        """Collect canonical attributes from cluster members."""
        from collections import defaultdict

        # Group by canonical name.
        canonical_groups = defaultdict(list)
        for event in events:
            canonical = cluster_mapping.get(event.name, event.name)
            canonical_groups[canonical].append(event)

        result = {}
        for canonical, group in canonical_groups.items():
            attr_candidates = defaultdict(list)

            # Collect candidate attribute values.
            for event in group:
                for attr_name, attr_value in event.attributes.items():
                    attr_candidates[attr_name].append((attr_value, event.confidence))

            # Keep the value with the highest confidence.
            best_attrs = {}
            for attr_name, candidates in attr_candidates.items():
                best = max(candidates, key=lambda x: x[1])
                best_attrs[attr_name] = best

            result[canonical] = best_attrs

        return result

    # Semantic clustering

    def _semantic_clustering(
        self,
        names: List[str],
        existing_clusters: List[Cluster],
        types: Dict[str, str],
        semantic_texts: Dict[str, str],
    ) -> List[Cluster]:
        """Cluster same-type candidates using semantic embeddings."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            print("⚠️ sentence-transformers 未安装，跳过语义聚类")
            return existing_clusters

        if self._embedding_model is None:
            try:
                self._embedding_model = SentenceTransformer(
                    'paraphrase-multilingual-MiniLM-L12-v2'
                )
            except Exception:
                print("⚠️ 无法加载 Sentence-BERT 模型，跳过语义聚类")
                return existing_clusters

        # Collect names to cluster.
        all_names = []
        for c in existing_clusters:
            all_names.append(c.canonical_name)

        if len(all_names) <= 2:
            return existing_clusters

        try:
            # Generate embeddings.
            texts = [
                semantic_texts.get(name, name)
                for name in all_names
            ]
            embeddings = self._embedding_model.encode(texts)

            # DBSCAN-equivalent neighborhood expansion: eps=0.15, or cosine similarity >=0.85.
            # min_samples=2; retain points without same-type neighbors as singletons.
            neighbors: Dict[int, Set[int]] = defaultdict(set)
            for i in range(len(all_names)):
                for j in range(i + 1, len(all_names)):
                    type_i = types.get(all_names[i], "")
                    type_j = types.get(all_names[j], "")
                    if type_i and type_j and type_i != type_j:
                        continue
                    if self._cosine_similarity(embeddings[i], embeddings[j]) >= 0.85:
                        neighbors[i].add(j)
                        neighbors[j].add(i)

            visited: Set[int] = set()
            merged: List[Cluster] = []
            for start in range(len(all_names)):
                if start in visited:
                    continue
                component = []
                stack = [start]
                while stack:
                    idx = stack.pop()
                    if idx in visited:
                        continue
                    visited.add(idx)
                    component.append(idx)
                    stack.extend(neighbors.get(idx, set()) - visited)

                component_clusters = [existing_clusters[idx] for idx in component]
                items = [item for cluster in component_clusters for item in cluster.items]
                canonical = self._select_canonical_name(items, types)
                merged.append(Cluster(
                    cluster_id=f"sem_{len(merged):03d}",
                    canonical_name=canonical,
                    items=list(dict.fromkeys(items)),
                    cluster_type="event",
                    confidence=0.85 if len(component) > 1 else component_clusters[0].confidence,
                ))

            return merged

        except Exception as e:
            print(f"⚠️ 语义聚类失败: {e}")
            return existing_clusters

    def _cosine_similarity(self, a, b) -> float:
        """Compute cosine similarity."""
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    # LLM-based assessment

    def _llm_based_refinement(self, clusters: List[Cluster]) -> List[Cluster]:
        """Refine candidate merges through the optional refinement pathway."""
        if not self.llm_caller or len(clusters) <= 1:
            return clusters

        # Build candidate merge pairs.
        candidates = []
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                name1 = clusters[i].canonical_name
                name2 = clusters[j].canonical_name
                if self._normalize_name(name1) == self._normalize_name(name2):
                    continue
                if len(name1) > 3 and len(name2) > 3:
                    if name1 in name2 or name2 in name1:
                        candidates.append((i, j, name1, name2))

        # Assess each candidate pair using the LLM pathway.
        from extraction.event_extractor import OntologyGuidedEventExtractor

        merged = []
        merged_set = set()

        for i, j, name1, name2 in candidates:
            if i in merged_set or j in merged_set:
                continue

            # Simple refinement: merge highly similar names directly.
            # This avoids additional LLM-call costs.
            shared_chars = sum(1 for c in name1 if c in name2)
            if shared_chars / max(len(name1), len(name2)) > 0.8:
                clusters[i].items.extend(clusters[j].items)
                merged_set.add(j)

        return [c for idx, c in enumerate(clusters) if idx not in merged_set]

    # Name-mapping construction

    def _build_mapping(
        self,
        clusters: List[Cluster],
        original_names: List[str],
    ) -> Dict[str, str]:
        """Map original names to cluster canonical names."""
        mapping = {}

        for cluster in clusters:
            for item in cluster.items:
                mapping[item] = cluster.canonical_name

        # Ensure every original name has a mapping.
        for name in original_names:
            if name not in mapping:
                mapping[name] = name

        return mapping

    # Cluster report

    def generate_cluster_report(
        self,
        output_format: str = "json",
        output_path: str = None,
    ) -> str:
        """Generate a report with details of every cluster."""
        if not self._clusters:
            report = {
                'status': 'empty',
                'total_clusters': 0,
                'total_items': 0,
                'clusters': [],
                'stats': {},
            }
        else:
            clusters_detail = []
            for c in self._clusters:
                clusters_detail.append({
                    'cluster_id': c.cluster_id,
                    'canonical_name': c.canonical_name,
                    'items': c.items,
                    'item_count': len(c.items),
                    'cluster_type': c.cluster_type,
                    'confidence': c.confidence,
                    'has_duplicates': len(c.items) > 1,
                    'dedup_ratio': len(c.items) / len(set(c.items)) if c.items else 1.0,
                })

            report = {
                'status': 'ok',
                'total_clusters': len(self._clusters),
                'total_items': sum(len(c.items) for c in self._clusters),
                'clusters': clusters_detail,
                'stats': self.get_cluster_stats(),
            }

        # Write the output file.
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        if output_format == "dict":
            return report

        return json.dumps(report, ensure_ascii=False, indent=2)

    # Statistics

    def get_cluster_stats(self) -> dict:
        """Return clustering statistics."""
        if not self._clusters:
            return {}

        total_items = sum(len(c.items) for c in self._clusters)
        avg_size = total_items / len(self._clusters) if self._clusters else 0
        max_size = max(len(c.items) for c in self._clusters) if self._clusters else 0

        return {
            'total_clusters': len(self._clusters),
            'total_items': total_items,
            'avg_cluster_size': round(avg_size, 2),
            'max_cluster_size': max_size,
            'reduction_ratio': round(total_items / len(self._clusters), 2) if self._clusters else 0,
        }


