"""Teaching/practice separation, portable resumption, and unchanged saved content."""
import copy
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from core import Store, validate_package, validate_assessment
from configuration import Settings
from generation import (Jobs, Gemini, ProviderError, TEACHING_PLAN, TEACHING,
                        SCOPED_TEACHING, ASSESSMENT, assessment_units)
from fixtures import lesson_fixture, TEST_MODULES, pdf_fixture
from test_core import test_directory


class SplitProvider:
    def __init__(self, doc_id):
        self.doc_id = doc_id
        self.calls = []
        self.fail_second_practice = False

    def generate(self, prompt, schema, validator):
        self.calls.append((schema, prompt))
        if schema == TEACHING_PLAN:
            return validator(dict(overview="Module overview", objectives=["Apply A and B"], lessons=[
                dict(id=f"l{i+1}", title=topic, topics=[topic], concepts=[topic], gaps=[])
                for i, topic in enumerate(["A", "B"])]))
        if schema in (TEACHING, SCOPED_TEACHING):
            topic = "A" if "Lesson: A\n" in prompt else "B"
            return validator(dict(overview="Lesson overview", objectives=[f"Apply {topic}"],
                sections=[dict(title=f"{topic} {kind}", body=f"Saved {topic} explanation {i}: \\(x={i}\\).",
                               kind=kind, sources=[dict(doc_id=self.doc_id, page=1)])
                          for i, kind in enumerate(["concept", "formula", "example"])], coverage_notes=""))
        if schema == ASSESSMENT:
            teaching = json.loads(prompt.split("SAVED TEACHING\n")[1].split("\n\n")[0])
            topic = teaching["topics"][0]
            if topic == "B" and self.fail_second_practice:
                raise ProviderError("Quota pause")
            result = lesson_fixture(TEST_MODULES[0], self.doc_id, 1)
            for q in result["questions"]:
                q["topic"] = topic
            return validator(dict(questions=result["questions"], flashcards=result["flashcards"]))
        raise AssertionError("Unexpected generation stage")


class TeachingFirstTests(unittest.TestCase):
    def prepare(self, folder):
        store = Store(folder)
        self.addCleanup(store.close)
        course = store.create("Synthetic teaching course")
        doc = store.add_pdf(course["id"], "notes.pdf", "material", pdf_fixture())
        course["modules"] = [dict(id="m1", title="Complexity", topics=["A", "B"], prerequisites=[])]
        store.save(course)
        fake = SplitProvider(doc["id"])
        jobs = Jobs(store, fake)
        jobs._packages(course["id"])
        return store, course["id"], fake, jobs

    def test_teaching_succeeds_without_questions_or_cards_and_is_reused(self):
        with test_directory() as folder:
            store, cid, fake, jobs = self.prepare(folder)
            module = store.course(cid)["modules"][0]
            self.assertEqual([TEACHING_PLAN, TEACHING, TEACHING], [s for s, _ in fake.calls])
            self.assertEqual("missing", module["package"]["assessment_status"])
            self.assertEqual([], module["package"]["questions"])
            self.assertEqual([], module["package"]["flashcards"])
            self.assertIn("Saved A explanation", fake.calls[-1][1])
            before = copy.deepcopy(module["package"])
            jobs._packages(cid)
            self.assertEqual(3, len(fake.calls))
            self.assertEqual(before, store.course(cid)["modules"][0]["package"])
            # Uploaded papers are also deferred instead of adding calls to teaching.
            store.add_pdf(cid, "exam.pdf", "pyq", pdf_fixture("exam"))
            jobs._packages(cid)
            self.assertEqual(3, len(fake.calls))
            store.close()

    def test_practice_receives_complete_saved_teaching_and_does_not_modify_it(self):
        with test_directory() as folder:
            store, cid, fake, jobs = self.prepare(folder)
            before = store.course(cid)["modules"][0]["package"]
            units = assessment_units(store.course(cid)["modules"][0])
            jobs._practice(cid, "m1")
            after = store.course(cid)["modules"][0]["package"]
            self.assertEqual("ready", after["assessment_status"])
            for field in ("sections", "overview", "objectives", "teaching_plan", "generation_version"):
                self.assertEqual(before[field], after[field])
            for unit, (_, prompt) in zip(units, fake.calls[3:]):
                actual = json.loads(prompt.split("SAVED TEACHING\n")[1].split("\n\n")[0])
                self.assertEqual(unit["teaching"], actual)
                self.assertNotIn("doc_id", actual["sections"][0])
            self.assertEqual(len(after["questions"]), len({q["id"] for q in after["questions"]}))
            calls = len(fake.calls)
            jobs._practice(cid, "m1")
            self.assertEqual(calls, len(fake.calls))
            store.close()

    def test_prerequisites_are_taught_before_dependents_without_reordering_the_outline(self):
        with test_directory() as folder:
            store = Store(folder)
            c = store.create("Prerequisite order")
            doc = store.add_pdf(c["id"], "notes.pdf", "material", pdf_fixture())
            c["modules"] = [dict(id="child", title="Application", topics=["A", "B"], prerequisites=["parent"]),
                            dict(id="parent", title="Foundation", topics=["A", "B"], prerequisites=[])]
            store.save(c)
            fake = SplitProvider(doc["id"])
            Jobs(store, fake)._packages(c["id"])
            self.assertIn("Module: Foundation", fake.calls[0][1])
            self.assertIn('"title": "Foundation"', fake.calls[4][1].split("SAVED EARLIER TEACHING")[1])
            self.assertEqual(["child", "parent"], [m["id"] for m in store.course(c["id"])["modules"]])
            store.close()

    def test_practice_resumes_after_restart_and_backup_without_repeating_saved_work(self):
        with test_directory() as folder:
            store, cid, fake, jobs = self.prepare(folder)
            fake.fail_second_practice = True
            with self.assertRaises(ProviderError):
                jobs._practice(cid, "m1")
            self.assertEqual({"l1"}, set(store.course(cid)["modules"][0]["practice_preparation"]["lessons"]))
            restored = store.import_course(store.export(cid))
            self.assertIn("practice_preparation", restored["modules"][0])
            store.close()
            store = Store(folder)
            self.addCleanup(store.close)
            doc_id = store.docs(restored["id"])[0]["id"]
            fresh = SplitProvider(doc_id)
            Jobs(store, fresh)._practice(restored["id"], "m1")
            self.assertEqual([ASSESSMENT], [schema for schema, _ in fresh.calls])
            self.assertEqual("ready", store.course(restored["id"])["modules"][0]["package"]["assessment_status"])
            fake.fail_second_practice = False
            Jobs(store, fake)._practice(cid, "m1")
            self.assertEqual(1, sum(schema == ASSESSMENT and '"lesson": "A"' in prompt for schema, prompt in fake.calls))
            store.close()

    def test_invalid_assessment_preserves_teaching_and_completed_stages(self):
        with test_directory() as folder:
            store, cid, fake, jobs = self.prepare(folder)
            before = store.course(cid)["modules"][0]["package"]
            class Bad:
                def generate(self, prompt, schema, validator):
                    result = lesson_fixture(TEST_MODULES[0], fake.doc_id, 1)
                    result["questions"][0]["topic"] = "Not taught"
                    return validator(result)
            with self.assertRaisesRegex(ValueError, "assigned topic"):
                Jobs(store, Bad())._practice(cid, "m1")
            self.assertEqual(before, store.course(cid)["modules"][0]["package"])
            result = lesson_fixture(TEST_MODULES[0], fake.doc_id, 1)
            result["questions"][0]["options"] = ["A", "B"]
            with self.assertRaisesRegex(ValueError, "four distinct"):
                validate_assessment(result, TEST_MODULES[0]["topics"])
            store.close()

    def test_legacy_saved_packages_and_unfinished_lessons_are_preserved(self):
        with test_directory() as folder:
            store = Store(folder)
            c = store.create("Legacy")
            doc = store.add_pdf(c["id"], "notes.pdf", "material", pdf_fixture())
            package = lesson_fixture(TEST_MODULES[0], doc["id"], 1)
            saved = copy.deepcopy(package)
            c["modules"] = [dict(id="m1", title="Saved", topics=TEST_MODULES[0]["topics"], prerequisites=[], package=package)]
            store.save(c)
            class Never:
                def generate(*args):
                    raise AssertionError("Saved material must not trigger inference")
            jobs = Jobs(store, Never())
            jobs._packages(c["id"])
            jobs._practice(c["id"])
            self.assertEqual(saved, store.course(c["id"])["modules"][0]["package"])
            c["modules"] = [dict(id="m1", title="Legacy unfinished", topics=TEST_MODULES[0]["topics"], prerequisites=[],
                preparation=dict(version="old", plan=dict(overview="Old plan", objectives=["Learn"], lessons=[
                    dict(id="l1", title="Saved lesson", topics=TEST_MODULES[0]["topics"], concepts=["A"], gaps=[])]), lessons={"l1": saved}))]
            store.save(c)
            jobs._packages(c["id"])
            self.assertEqual(saved["sections"][0]["body"], store.course(c["id"])["modules"][0]["package"]["sections"][0]["body"])
            store.close()

    def test_backup_rejects_practice_for_changed_teaching(self):
        with test_directory() as folder:
            store, cid, fake, jobs = self.prepare(folder)
            fake.fail_second_practice = True
            with self.assertRaises(ProviderError):
                jobs._practice(cid)
            source = zipfile.ZipFile(io.BytesIO(store.export(cid)))
            manifest = json.loads(source.read("folium.json"))
            manifest["course"]["modules"][0]["package"]["sections"][0]["body"] = "Changed teaching"
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as target:
                for name in source.namelist():
                    target.writestr(name, json.dumps(manifest) if name == "folium.json" else source.read(name))
            before = len(store.courses())
            with self.assertRaisesRegex(ValueError, "does not match"):
                store.import_course(out.getvalue())
            self.assertEqual(before, len(store.courses()))
            store.close()

    def test_missing_practice_state_cannot_hide_invalid_saved_assessments(self):
        package = lesson_fixture(TEST_MODULES[0], "doc", 1)
        package["assessment_status"] = "missing"
        with self.assertRaisesRegex(ValueError, "empty question"):
            validate_package(package, {("doc", 1)})

    def test_provider_uses_default_sampling_and_retains_truncated_diagnostics(self):
        with test_directory() as folder:
            store = Store(folder)
            settings = Settings(folder)
            settings.save(dict(api_key="synthetic-key"))
            response = dict(candidates=[dict(content=dict(parts=[dict(text='{"sections":')]), finishReason="MAX_TOKENS")], usageMetadata=dict(candidatesTokenCount=24))
            with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as network:
                with self.assertRaisesRegex(ValueError, "interrupted"):
                    Gemini(store, settings).generate("Teach", TEACHING)
            request = json.loads(network.call_args.args[0].data)
            self.assertNotIn("temperature", request["generationConfig"])
            self.assertIn("first time", request["systemInstruction"]["parts"][0]["text"])
            cached = json.loads(store.db.execute("SELECT data FROM cache").fetchone()[0])
            self.assertEqual("MAX_TOKENS", cached["finish_reason"])
            store.close()


if __name__ == "__main__":
    unittest.main()
