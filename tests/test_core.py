import copy
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import create_server
from core import Store, grade, module_state, review_card, validate_outline, validate_package
from generation import Gemini, Jobs, ProviderError, Settings, source_pages, OUTLINE
from sample import SPECS, sample_package, seed_sample

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "tmp").mkdir(exist_ok=True)

def test_directory():
    folder = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
    assert Path(folder.name).resolve().is_relative_to((ROOT / "tmp").resolve())
    return folder


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = test_directory()
        self.store = Store(self.temp.name)
        self.course = self.store.create("Test course")
        self.doc = self.store.add_pdf(self.course["id"], "notes.pdf", "material", (ROOT / "sample_sources/Course-notes.pdf").read_bytes())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def module(self):
        module = {k:copy.deepcopy(SPECS[0][k]) for k in ("id", "title", "description", "topics", "prerequisites")}
        module["package"] = sample_package(SPECS[0], self.doc["id"], 1)
        return module

    def test_pdf_text_and_duplicate_detection(self):
        self.assertIn("Complexity", self.doc["pages"][0])
        same = self.store.add_pdf(self.course["id"], "renamed.pdf", "material", (ROOT / "sample_sources/Course-notes.pdf").read_bytes())
        self.assertEqual(self.doc["id"], same["id"])
        self.assertEqual(1, len(self.store.docs(self.course["id"])))

    def test_invalid_pdf_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid PDF"):
            self.store.add_pdf(self.course["id"], "fake.pdf", "material", b"fake")

    def test_outline_cycles_and_missing_parents(self):
        modules = [dict(id="a", title="A", topics=["A1"], prerequisites=["b"]),
                   dict(id="b", title="B", topics=["B1"], prerequisites=["a"])]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_outline(modules)
        modules[0]["prerequisites"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_outline(modules)

    def test_citations_must_match_supplied_pages(self):
        package = self.module()["package"]
        validate_package(package, {(self.doc["id"],1)})
        package["sections"][0]["sources"][0]["page"] = 999
        with self.assertRaisesRegex(ValueError, "citation"):
            validate_package(package, {(self.doc["id"],1)})

    def test_bad_answer_key_rejected(self):
        package = self.module()["package"]
        package["questions"][0]["correct_index"] = 90
        with self.assertRaisesRegex(ValueError, "answer key"):
            validate_package(package, {(self.doc["id"],1)})

    def test_scoring_and_mastery_are_separate_from_reading(self):
        module = self.module()
        module["read"] = True
        self.assertEqual("learning", module_state(module))
        answers = {q["id"]:q["correct_index"] for q in module["package"]["questions"] if q["type"] == "objective"}
        self.assertEqual(4, grade(module, answers)["correct"])
        self.assertEqual("learning", module_state(module))
        grade(module, answers)
        self.assertEqual("mastered", module_state(module))
        with self.assertRaises(ValueError):
            grade(module, {})

    def test_review_schedule_is_persistent(self):
        self.course["modules"] = [self.module()]
        result = review_card(self.course, "m1", 0, "easy")
        self.assertEqual(3, result["interval"])
        self.store.save(self.course)
        self.assertEqual(result, self.store.course(self.course["id"])["reviews"]["m1:0"])

    def test_backup_round_trip_and_no_credentials(self):
        self.course.update(modules=[self.module()], status="ready")
        self.course["modules"][0].update(notes="My own note", bookmarked=True)
        self.store.save(self.course)
        Settings(self.store.root).save(dict(api_key="secret-key"))
        backup = self.store.export(self.course["id"])
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            self.assertNotIn(b"secret-key", z.read("folium.json"))
        restored = self.store.import_course(backup)
        self.assertNotEqual(restored["id"], self.course["id"])
        self.assertEqual("My own note", restored["modules"][0]["notes"])
        new_doc = self.store.docs(restored["id"])[0]
        self.assertNotEqual(self.doc["id"], new_doc["id"])
        self.assertEqual(new_doc["id"], restored["modules"][0]["package"]["sections"][0]["sources"][0]["doc_id"])

    def test_backup_rejects_forged_source_id(self):
        self.course.update(modules=[self.module()],status="ready")
        self.store.save(self.course)
        raw=self.store.export(self.course["id"])
        with zipfile.ZipFile(io.BytesIO(raw)) as original:
            manifest=json.loads(original.read("folium.json"))
            manifest["course"]["modules"][0]["package"]["sections"][0]["sources"][0]["doc_id"]="0000000000000000"
            altered=io.BytesIO()
            with zipfile.ZipFile(altered,"w") as z:
                for name in original.namelist():
                    z.writestr(name,json.dumps(manifest) if name=="folium.json" else original.read(name))
        with self.assertRaisesRegex(ValueError,"citation"):
            self.store.import_course(altered.getvalue())

    def test_invalid_backup_rejected(self):
        with self.assertRaises(ValueError):
            self.store.import_course(b"not a zip")

    def test_import_preserves_unfinished_generation(self):
        self.course.update(modules=[self.module()],status="outline")
        self.store.save(self.course)
        restored=self.store.import_course(self.store.export(self.course["id"]))
        self.assertEqual("outline",restored["status"])

    def test_import_rejects_bad_history_before_saving(self):
        self.course.update(modules=[self.module()],status="ready")
        self.course["modules"][0]["attempts"]=[dict(correct="wrong",total=4)]
        self.store.save(self.course)
        count=len(self.store.courses())
        with self.assertRaisesRegex(ValueError,"practice score"):
            self.store.import_course(self.store.export(self.course["id"]))
        self.assertEqual(count,len(self.store.courses()))

    def test_retrieval_keeps_physical_page_metadata(self):
        selected = source_pages([self.doc], "binary search trees", budget=1500)
        self.assertTrue(selected)
        self.assertLessEqual(sum(len(p["text"]) for p in selected), 1500)
        self.assertEqual(self.doc["id"], selected[0]["doc_id"])
        self.assertTrue(1 <= selected[0]["page"] <= len(self.doc["pages"]))

    def test_provider_cache_survives_restart(self):
        settings = Settings(self.store.root)
        settings.save(dict(api_key="test-only", interval=3))
        provider = Gemini(self.store, settings)
        raw = json.dumps(dict(candidates=[dict(finishReason="STOP", content=dict(parts=[dict(text='{"ok": true}')]))])).encode()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)) as request:
            value = provider.generate("one prompt", {"type":"OBJECT"})
            self.assertTrue(value["ok"])
            self.assertEqual(1, request.call_count)
        self.store.close()
        self.store=Store(self.temp.name)
        # A new provider instance must use the durable response without any network call.
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected API call")):
            self.assertEqual(value, Gemini(self.store, settings).generate("one prompt", {"type":"OBJECT"}))

    def test_quota_error_is_actionable_without_key_exposure(self):
        settings = Settings(self.store.root)
        settings.save(dict(api_key="secret-key"))
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("",429,"quota",{},None)):
            with self.assertRaisesRegex(ProviderError, "Completed work is saved") as error:
                Gemini(self.store, settings).generate("x", {})
        self.assertNotIn("secret-key", str(error.exception))

    def test_resume_skips_saved_modules(self):
        module = self.module()
        missing = copy.deepcopy(module)
        missing.update(id="m2", title="Next module")
        del missing["package"]
        self.course["modules"] = [module, missing]
        self.store.save(self.course)
        class Fake:
            calls = 0
            def generate(_, prompt, schema, validator):
                _.calls += 1
                return validator(copy.deepcopy(module["package"]))
        fake = Fake()
        jobs = Jobs(self.store, fake)
        jobs._packages(self.course["id"])
        self.assertEqual(1, fake.calls)
        jobs._packages(self.course["id"])
        self.assertEqual(1, fake.calls)
        self.assertEqual("ready", self.store.course(self.course["id"])["status"])

    def test_restart_marks_inflight_work_paused(self):
        self.course["job"] = dict(state="running", stage="lessons")
        self.store.save(self.course)
        Jobs(self.store, None)
        self.assertEqual("paused", self.store.course(self.course["id"])["job"]["state"])

    def test_sample_citations_point_to_matching_section_pages(self):
        seed_sample(self.store)
        demo = next(c for c in self.store.courses() if c["demo"])
        docs = {d["id"]:d for d in self.store.docs(demo["id"])}
        for module in demo["modules"]:
            for section in module["package"]["sections"]:
                ref = section["sources"][0]
                self.assertIn(section["title"], docs[ref["doc_id"]]["pages"][ref["page"]-1])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = test_directory()
        cls.server = create_server(cls.temp.name, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.store.close()
        cls.temp.cleanup()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.url+path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type":"application/json", **(headers or {})})
        with urllib.request.urlopen(req) as result:
            return json.load(result)

    def test_health_and_seeded_course(self):
        self.assertTrue(self.request("/api/health")["ok"])
        courses = self.request("/api/courses")
        self.assertTrue(courses[0]["demo"])
        self.assertEqual(6, len(courses[0]["modules"]))

    def test_settings_never_return_key(self):
        self.request("/api/settings", dict(api_key="do-not-return-this"))
        settings = self.request("/api/settings")
        self.assertTrue(settings["has_key"])
        self.assertNotIn("api_key", settings)

    def test_cross_origin_writes_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/settings", {}, {"Origin":"https://unrelated.example"})
        self.assertEqual(403, error.exception.code)

    def test_studying_and_quizzing_do_not_contact_provider(self):
        course = self.request("/api/courses")[0]
        module = course["modules"][0]
        answers = {q["id"]:q["correct_index"] for q in module["package"]["questions"] if q["type"] == "objective"}
        with patch.object(self.server.jobs.provider, "generate", side_effect=AssertionError("Unexpected API call")):
            self.request(f"/api/courses/{course['id']}/modules/{module['id']}/progress", dict(read=True, notes="Saved locally"))
            result = self.request(f"/api/courses/{course['id']}/modules/{module['id']}/quiz", dict(answers=answers))
            self.assertEqual(4, result["result"]["correct"])

    def upload(self,title,files):
        boundary="folium-test-boundary"
        parts=[]
        for key,value in dict(title=title,roles=json.dumps([f[2] for f in files])).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        for name,raw,role in files:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()+raw+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        req=urllib.request.Request(self.url+"/api/courses",data=b''.join(parts),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def wait_job(self,cid):
        for _ in range(160):
            course=self.request("/api/courses/"+cid)
            if course["job"]["state"]!="running":return course
            time.sleep(.03)
        self.fail("The test preparation job did not finish.")

    def test_upload_outline_generate_study_end_to_end(self):
        course=self.upload("Integration course",[("notes.pdf",(ROOT/"sample_sources/Course-notes.pdf").read_bytes(),"material")])
        cid=course["id"]
        doc=course["documents"][0]
        def generate(prompt,schema,validator):
            if schema==OUTLINE:
                return validator(dict(description="Test outline",modules=[dict(id="m1",title="Complexity",description="Growth",topics=["Big O"],prerequisites=[])]))
            return validator(sample_package(SPECS[0],doc["id"],1))
        with patch.object(self.server.jobs.provider,"generate",side_effect=generate) as provider:
            self.request(f"/api/courses/{cid}/prepare",dict(action="outline"))
            course=self.wait_job(cid)
            self.assertEqual("outline",course["status"])
            self.request(f"/api/courses/{cid}/outline",dict(modules=course["modules"]))
            self.request(f"/api/courses/{cid}/prepare",dict(action="generate"))
            course=self.wait_job(cid)
            self.assertEqual("ready",course["status"])
            self.assertEqual(2,provider.call_count)
            self.request(f"/api/courses/{cid}/prepare",dict(action="generate"))
            self.assertEqual(2,provider.call_count)
        text=self.request(f"/api/documents/{doc['id']}/pages/1")
        self.assertIn("Complexity",text["text"])
        with urllib.request.urlopen(self.url+f"/api/documents/{doc['id']}/pages/1.png") as response:
            self.assertTrue(response.read().startswith(b'\x89PNG\r\n\x1a\n'))

    def test_upload_failure_rolls_back_new_course(self):
        count=len(self.request("/api/courses"))
        with self.assertRaises(urllib.error.HTTPError):
            self.upload("Bad upload",[("good.pdf",(ROOT/"sample_sources/Course-outline.pdf").read_bytes(),"syllabus"),("bad.pdf",b"bad","material")])
        self.assertEqual(count,len(self.request("/api/courses")))

    def test_invalid_source_page_rejected(self):
        c=self.request("/api/courses")[0]
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(f"/api/documents/{c['documents'][0]['id']}/pages/999")
        self.assertEqual(400,error.exception.code)


if __name__ == "__main__":
    unittest.main()
