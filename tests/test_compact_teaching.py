"""Compact lessons retain complete coverage, persistence and validation."""
from contextlib import closing
import copy
import unittest

from core import Store, validate_teaching
from generation import Jobs, TEACHING_PLAN, TEACHING
from fixtures import pdf_fixture
from test_core import test_directory


class CompactTeachingTests(unittest.TestCase):
    def test_related_topics_share_one_saved_lesson_and_resume_without_calls(self):
        with test_directory() as folder, closing(Store(folder)) as store:
            course = store.create("Compact lesson")
            store.add_pdf(course["id"], "notes.pdf", "material", pdf_fixture())
            course["modules"] = [dict(id="m1", title="Related ideas", topics=["A", "B"], prerequisites=[])]
            store.save(course)
            class Provider:
                calls = 0
                def generate(self, prompt, schema, validator):
                    self.calls += 1
                    if schema == TEACHING_PLAN:
                        return validator(dict(overview="A and B together", objectives=["Connect A and B"],
                            lessons=[dict(id="l1", title="Connected explanation", topics=["A", "B"], concepts=["Connection"], gaps=[])]))
                    if schema != TEACHING:
                        raise AssertionError("Unexpected task")
                    return validator(dict(overview="A and B", objectives=["Connect A and B"], sections=[
                        dict(title="Connected ideas", body="A complete explanation with a worked example of A and B.", kind="concept", sources=[])], coverage_notes=""))
            provider = Provider()
            jobs = Jobs(store, provider)
            jobs._packages(course["id"])
            self.assertEqual(2, provider.calls)
            saved = store.course(course["id"])["modules"][0]["package"]
            self.assertEqual(1, len(saved["sections"]))
            self.assertEqual({"A", "B"}, {r["topic"] for r in saved["coverage_map"]})
            restored = store.import_course(store.export(course["id"]))
            jobs._packages(restored["id"])
            self.assertEqual(2, provider.calls)
            for field in ("sections", "teaching_plan", "coverage_map", "assessment_status"):
                self.assertEqual(saved[field], restored["modules"][0]["package"][field])

    def test_compact_structure_still_rejects_empty_teaching_and_invalid_citations(self):
        valid = dict(overview="Overview", objectives=["Learn"], sections=[
            dict(title="Explanation", body="Useful teaching", kind="concept", sources=[])], coverage_notes="")
        for changes in (dict(sections=[]), dict(sections=[dict(valid["sections"][0], body="")]),
                        dict(sections=[dict(valid["sections"][0], sources=[dict(doc_id="invented", page=1)])])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_teaching(dict(copy.deepcopy(valid), **changes), set())


if __name__ == "__main__":
    unittest.main()
