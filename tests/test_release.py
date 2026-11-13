"""Offline regression checks; no live API, database or original report is required."""
from __future__ import annotations

import csv
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from rdflib import Graph

from extraction.value_normalizer import normalize_measurement
from qa.answer_generator import EvidenceAnswerGenerator
from qa.modality_router import ModalityRouter
from qa.models import Evidence, QAResult, QueryAnalysis, collect_media_supports

ROOT = Path(__file__).resolve().parents[1]


class NormalizationTests(unittest.TestCase):
    def test_header_unit_and_raw_value(self):
        result = normalize_measurement("0.40", "位移速率(mm/月)")
        self.assertEqual(result["raw"], "0.40")
        self.assertEqual(result["value"], .4)
        self.assertEqual(result["unit"], "mm/月")

    def test_range(self):
        result = normalize_measurement("5～15cm")
        self.assertTrue(result["is_range"])
        self.assertEqual(result["value"], [5., 15.])
        self.assertEqual(result["unit"], "cm")

    def test_multiplier(self):
        self.assertEqual(normalize_measurement("1.7×10⁴m³")["value"], 17000.)


class QuestionAndModelTests(unittest.TestCase):
    def setUp(self):
        self.analysis = QueryAnalysis("表2中MON-B的位移是多少？", ["table"], "parameter")
        self.evidence = Evidence("T1", "table", "table_demo", "表2", "MON-B: 0.40 mm/月", metadata={
            "structured_rows": [{"row_index": 2, "cells": [{"header": "监测点", "raw_text": "MON-B"}, {"header": "位移速率", "raw_text": "0.40", "unit": "mm/月"}]}]})

    def test_explicit_reference_routing(self):
        result = ModalityRouter().analyze(self.analysis.question)
        self.assertIn("table", result.modalities)
        self.assertEqual(result.explicit_table_ref, "表2")

    def test_missing_evidence_never_calls_api(self):
        generator = EvidenceAnswerGenerator(api_key="")
        with patch("requests.post") as post:
            answer, used = generator.generate(self.analysis.question, self.analysis, [])
        self.assertFalse(used)
        self.assertTrue(answer)
        self.assertFalse(generator.last_call_metadata["api_called"])
        post.assert_not_called()

    def test_no_key_returns_evidence_list(self):
        generator = EvidenceAnswerGenerator(api_key="")
        with patch("requests.post") as post:
            answer, used = generator.generate(self.analysis.question, self.analysis, [self.evidence])
        self.assertFalse(used)
        self.assertIn("T1", answer)
        post.assert_not_called()

    def test_mock_request_payload_and_metadata(self):
        generator = EvidenceAnswerGenerator(api_key="offline-test-placeholder")
        response = Mock()
        response.json.return_value = {"model": "mock-model", "id": "mock-response", "usage": {"prompt_tokens": 10, "completion_tokens": 4}, "choices": [{"message": {"content": "0.40 mm/月 [T1]"}}]}
        with patch("requests.post", return_value=response) as post:
            answer, used = generator.generate(self.analysis.question, self.analysis, [self.evidence], table_format="structured")
        self.assertTrue(used)
        self.assertIn("T1", answer)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(kwargs["json"]["temperature"], .1)
        self.assertEqual(kwargs["json"]["max_tokens"], 900)
        self.assertNotIn("top_p", kwargs["json"])
        self.assertEqual(kwargs["timeout"], 60)
        self.assertEqual(generator.last_call_metadata["response_model"], "mock-model")
        self.assertTrue(generator.last_call_metadata["api_success"])

    def test_mock_failure_is_not_llm_success(self):
        generator = EvidenceAnswerGenerator(api_key="offline-test-placeholder")
        with patch("requests.post", side_effect=requests.exceptions.RequestException("offline simulated failure")):
            answer, used = generator.generate(self.analysis.question, self.analysis, [self.evidence])
        self.assertTrue(answer)
        self.assertFalse(used)
        self.assertFalse(generator.last_call_metadata["api_success"])

    def test_representations_keep_same_cell_values(self):
        generator = EvidenceAnswerGenerator(api_key="")
        structured = generator._serialize_evidence([self.evidence], "structured")
        flattened = generator._serialize_evidence([self.evidence], "flattened")
        for value in ("MON-B", "0.40", "mm/月"):
            self.assertIn(value, structured)
            self.assertIn(value, flattened)
        self.assertNotEqual(structured, flattened)

    def test_generation_modes_keep_same_evidence_serialization(self):
        generator = EvidenceAnswerGenerator(api_key="")
        constrained = generator._build_prompt(self.analysis.question, self.analysis, [self.evidence], "", generation_mode="constrained", table_format="structured")
        free = generator._build_prompt(self.analysis.question, self.analysis, [self.evidence], "", generation_mode="free", table_format="structured")
        serialized = generator._serialize_evidence([self.evidence], "structured")
        self.assertIn(serialized, constrained)
        self.assertIn(serialized, free)
        self.assertNotEqual(constrained, free)

    def test_invalid_generation_mode(self):
        with self.assertRaises(ValueError):
            EvidenceAnswerGenerator(api_key="").generate("q", self.analysis, [], generation_mode="invalid")

    def test_result_has_independent_metadata_defaults(self):
        first = QAResult("q", "a", self.analysis, [])
        second = QAResult("q", "a", self.analysis, [])
        first.retrieval_info["test"] = True
        self.assertEqual(second.retrieval_info, {})
        self.assertEqual(second.generation_info, {})

    def test_media_support_deduplication(self):
        supports = collect_media_supports([self.evidence, self.evidence])
        self.assertEqual(len(supports), 1)
        self.assertEqual(supports[0]["source_id"], "table_demo")


class ReleaseMaterialTests(unittest.TestCase):
    def test_demo_ontology_parses(self):
        self.assertGreater(len(Graph().parse(ROOT / "examples/demo_ontology.ttl", format="turtle")), 0)

    def test_released_record_counts(self):
        for relative, expected in [("02_five_system_benchmark/answers_and_scores.csv", 500), ("03_three_run_ablation/answers_and_scores.csv", 690), ("01_benchmark/questions_and_reference_answers.csv", 100)]:
            with (ROOT / "paper_data" / relative).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), expected)


if __name__ == "__main__":
    unittest.main()
