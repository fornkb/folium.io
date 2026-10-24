"""Regressions reproduced during the everyday-use/performance audit."""
import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from configuration import Settings
from core import Store
from generation import Gemini, Jobs, scoped_excerpts, TEACHING_PLAN, TEACHING
from fixtures import pdf_fixture, lesson_fixture, TEST_MODULES
from test_core import test_directory


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = test_directory()
        self.store = Store(self.temp.name)
        self.course = self.store.create("Audit fixture")
        self.doc = self.store.add_pdf(self.course["id"], "notes.pdf", "material", pdf_fixture())
        self.course["modules"] = [dict(id="m1", title="Complexity", topics=TEST_MODULES[0]["topics"], prerequisites=[],
            package=lesson_fixture(TEST_MODULES[0], self.doc["id"], 1))]
        self.store.save(self.course)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_429_tries_the_next_distinct_key_in_the_same_request(self):
        settings = Settings(self.store.root, env_file=self.store.root / "absent.env")
        with patch("configuration.environment_values", return_value={}):
            settings.save(dict(api_key="audit-one", api_key_2="audit-two"))
            seen = []
            def respond(request, **kwargs):
                seen.append(request.get_header("X-goog-api-key"))
                if len(seen) == 1:
                    raise urllib.error.HTTPError(request.full_url, 429, "quota", {}, None)
                return io.BytesIO(json.dumps(dict(candidates=[dict(content=dict(parts=[dict(text='{"ok":true}')]))])).encode())
            with patch("generation.urllib.request.urlopen", side_effect=respond), patch("generation.time.sleep"):
                self.assertTrue(Gemini(self.store, settings).generate("test", {})["ok"])
            self.assertEqual(["audit-one", "audit-two"], seen)

    def test_vision_model_environment_value_is_honored(self):
        path = self.store.root / "vision.env"
        path.write_text("GEMINI_MODEL=gemini-teaching\nGEMINI_VISION_MODEL=gemini-vision\n")
        with patch("configuration.environment_values", return_value={}):
            self.assertEqual("gemini-vision", Settings(self.store.root, env_file=path).get()["vision_model"])

    def test_adjacent_source_passages_support_a_boundary_quotation(self):
        quote = "Target quotation explains the important convention across a former excerpt boundary."
        doc = dict(id="doc", name="notes.pdf", role="material", pages=["x " * 880 + quote + " tail" * 500])
        module = dict(source_ranges=[dict(doc_id="doc", start_page=1, end_page=1)])
        selected = scoped_excerpts([doc], module, "Target quotation convention boundary")
        self.assertTrue(any(quote in p["text"] for p in selected))
        self.assertLessEqual(sum(len(p["text"]) for p in selected), 12000)

    def test_scanned_paper_pages_are_reported_without_inference(self):
        class Never:
            def generate(*args):
                raise AssertionError("Image-only papers must not silently invoke a model")
        doc = dict(id=self.doc["id"], name="Scan.pdf", role="pyq", pages=[""])
        Jobs(self.store, Never())._pyqs(self.course["id"], [doc])
        coverage = self.store.course(self.course["id"]).get("pyq_coverage", {})
        self.assertEqual(1, coverage.get("unreadable_pages"))
        self.assertTrue(coverage.get("issues"))

    def test_paper_mapping_omits_teaching_dump_and_assigns_unique_ids(self):
        paper = self.store.add_pdf(self.course["id"], "exam.pdf", "pyq", pdf_fixture("exam"))
        self.course["modules"][0]["package"]["sections"][0]["body"] = "PRIVATE_TEACHING_SENTINEL" * 4000
        self.store.save(self.course)
        captured = []
        class Fake:
            def generate(self, prompt, schema, validator):
                captured.append(prompt)
                return validator(dict(questions=[dict(question=q, module_ids=["m1"], year="", number="", marks="", solution="Generated")
                                                  for q in ("Core concept", "Formal definition")]))
        Jobs(self.store, Fake())._pyqs(self.course["id"], [paper])
        self.assertFalse("PRIVATE_TEACHING_SENTINEL" in captured[0])
        self.assertLess(len(captured[0]), 10000)
        questions = self.store.course(self.course["id"])["pyqs"]
        self.assertEqual(len(questions), len({q["id"] for q in questions}))

    def test_legacy_lesson_source_context_is_bounded(self):
        course = self.store.create("Legacy missing")
        self.store.add_pdf(course["id"], "large.pdf", "material", pdf_fixture())
        course["modules"] = [dict(id="m1", title="Complexity", topics=["Topic A"], prerequisites=[])]
        self.store.save(course)
        fake_doc = dict(id=self.store.docs(course["id"])[0]["id"], name="large.pdf", role="material",
                        pages=[("Topic A content " * 1000) for _ in range(12)])
        captured = []
        doc_id = fake_doc["id"]
        class Fake:
            def generate(self, prompt, schema, validator):
                captured.append((schema, prompt))
                if schema == TEACHING_PLAN:
                    return validator(dict(overview="Overview", objectives=["Learn"], lessons=[dict(id="l1", title="Topic A", topics=["Topic A"], concepts=["Topic A"], gaps=[])]))
                return validator(lesson_fixture(TEST_MODULES[0], doc_id, 1))
        with patch.object(self.store, "docs", return_value=[fake_doc]):
            Jobs(self.store, Fake())._packages(course["id"])
        lesson = next(prompt for schema, prompt in captured if schema == TEACHING)
        self.assertLess(len(lesson), 18000)

    def test_document_course_lookup_uses_an_index(self):
        plan = self.store.db.execute("EXPLAIN QUERY PLAN SELECT id FROM documents WHERE course_id=?", (self.course["id"],)).fetchall()
        self.assertTrue(any("INDEX" in str(row).upper() for row in plan))


if __name__ == "__main__":
    unittest.main()
