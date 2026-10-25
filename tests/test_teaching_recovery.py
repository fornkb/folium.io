"""Recover completed explanations with misplaced citation metadata, preserving text."""
import copy
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from configuration import Settings
from core import Store, validate_teaching
from generation import Gemini, Jobs, SCOPED_TEACHING
from fixtures import pdf_fixture
from test_core import test_directory
from test_scope import ScopeProvider


class TeachingRecoveryTests(unittest.TestCase):
    def lesson(self, doc_id):
        return dict(overview="Quantifier explanation", objectives=["Apply quantifier duality"], sections=[
            dict(title="Quantifiers", body="A generated explanation with a worked example: \\(x=1\\).",
                 kind="concept", provenance="generated", sources=[dict(doc_id=doc_id, page=1)])], coverage_notes="")

    def test_generation_normalizes_only_known_generated_citations_without_rewriting(self):
        value = self.lesson("notes")
        original = copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError, "cannot carry"):
            validate_teaching(copy.deepcopy(value), {("notes", 1)})
        normalized = validate_teaching(value, {("notes", 1)}, normalize_generated_sources=True)
        self.assertEqual([], normalized["sections"][0]["sources"])
        original["sections"][0]["sources"] = []
        self.assertEqual(original, normalized)
        validate_teaching(normalized, {("notes", 1)})

    def test_unknown_citations_and_malformed_metadata_still_fail(self):
        for sources in ([dict(doc_id="invented", page=1)], [dict(doc_id="notes", page=999)],
                        [dict(doc_id="notes", page=True)], ["invalid"], "invalid"):
            with self.subTest(sources=sources), self.assertRaisesRegex(ValueError, "citation"):
                value = self.lesson("notes")
                value["sections"][0]["sources"] = sources
                validate_teaching(value, {("notes", 1)}, normalize_generated_sources=True)

    def test_excerpt_citations_are_retained_and_required(self):
        value = self.lesson("notes")
        value["sections"][0].update(provenance="source_excerpt", body="Exact original wording")
        self.assertEqual(value, validate_teaching(copy.deepcopy(value), {("notes", 1)}, normalize_generated_sources=True))
        value["sections"][0]["sources"] = []
        with self.assertRaisesRegex(ValueError, "excerpt needs a citation"):
            validate_teaching(value, {("notes", 1)}, normalize_generated_sources=True)

    def test_failed_raw_lesson_resumes_after_restart_and_backup_without_another_request(self):
        with test_directory() as folder, patch("configuration.environment_values", return_value={}):
            store = Store(folder)
            course = store.create("Citation metadata recovery")
            doc = store.add_pdf(course["id"], "notes.pdf", "material", pdf_fixture())
            Jobs(store, ScopeProvider())._outline(course["id"])
            settings = Settings(folder, env_file=Path(folder) / "absent.env")
            settings.save(dict(api_key="synthetic-key"))
            raw_lesson = self.lesson(doc["id"])
            raw_response = json.dumps(dict(candidates=[dict(finishReason="STOP", content=dict(parts=[dict(text=json.dumps(raw_lesson))]))])).encode()

            class RoutedProvider(ScopeProvider):
                strict = True
                def generate(self, prompt, schema, validator):
                    if schema == SCOPED_TEACHING:
                        check = (lambda value: validate_teaching(value, {(doc["id"], 1)})) if self.strict else validator
                        return Gemini(store, settings).generate(prompt, schema, check)
                    return super().generate(prompt, schema, validator)

            provider = RoutedProvider()
            with patch("generation.urllib.request.urlopen", return_value=io.BytesIO(raw_response)) as network, patch("generation.time.sleep"):
                with self.assertRaisesRegex(ValueError, "cannot carry"):
                    Jobs(store, provider)._packages(course["id"])
                self.assertEqual(1, network.call_count)
            self.assertIn("plan", store.course(course["id"])["modules"][0]["preparation"])
            store.close()
            store = Store(folder)
            provider.strict = False
            with patch("generation.urllib.request.urlopen", side_effect=AssertionError("Saved complete lesson must be reused")) as network:
                Jobs(store, provider)._packages(course["id"])
                saved = store.course(course["id"])
                package = saved["modules"][0]["package"]
                self.assertEqual(raw_lesson["sections"][0]["body"], package["sections"][0]["body"])
                self.assertEqual("generated", package["sections"][0]["provenance"])
                self.assertEqual([], package["sections"][0]["sources"])
                self.assertEqual(saved["modules"][0]["source_ranges"], package["topic_locations"])
                restored = store.import_course(store.export(course["id"]))
                Jobs(store, provider)._packages(restored["id"])
                self.assertEqual(package["sections"], restored["modules"][0]["package"]["sections"])
                self.assertEqual(0, network.call_count)
            originals = [json.loads(row[0]) for row in store.db.execute("SELECT data FROM cache WHERE key LIKE 'raw:%'")]
            self.assertTrue(any(json.loads(row["text"]).get("sections", [{}])[0].get("sources") for row in originals))
            store.close()


if __name__ == "__main__":
    unittest.main()
