"""Durable personal text marks without AI or large teaching rewrites."""
import copy
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest.mock import patch

from annotations import validate_marks
from app import create_server
from core import Store
from fixtures import seed_test_course
from test_core import test_directory


def mark(identity="a"*32):
    return dict(id=identity, style="highlight", color="amber", segments=[dict(
        block="section:0", start=0, end=12, exact="Core concept", prefix="", suffix=" explained",
        signature="100:abc12345")])


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = test_directory()
        self.server = create_server(self.temp.name, 0)
        self.store = self.server.store
        self.course = seed_test_course(self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.path = f"/api/courses/{self.course['id']}/modules/m1/annotations"
        self.network = patch("generation.Gemini.generate", side_effect=AssertionError("Study actions cannot call AI"))
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.store.db.set_trace_callback(None)
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.temp.cleanup()

    def request(self, path, body=None):
        req = urllib.request.Request(self.url+path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_marks_persist_without_rewriting_teaching_and_backup_round_trip(self):
        before = copy.deepcopy(self.course["modules"][0]["package"])
        queries = []
        self.store.db.set_trace_callback(queries.append)
        response = self.request(self.path, dict(operation="upsert", annotation=mark()))
        self.assertFalse(any("INSERT OR REPLACE INTO courses" in q or q.startswith("UPDATE courses ") for q in queries))
        patch_module = response["course"]["modules"][0]
        self.assertEqual([mark()], patch_module["annotations"])
        self.assertNotIn("package", patch_module)
        self.assertNotIn("notes", patch_module)
        path = self.path.replace("/annotations", "/progress")
        response = self.request(path, dict(notes="Personal notes remain independent", read=True))
        self.assertNotIn("annotations", response["course"]["modules"][0])
        saved = self.store.course(self.course["id"])
        self.assertEqual(before, saved["modules"][0]["package"])
        self.assertEqual([mark()], saved["modules"][0]["annotations"])
        reopened = Store(self.temp.name)
        try:
            self.assertEqual([mark()], reopened.course(saved["id"])["modules"][0]["annotations"])
        finally:
            reopened.close()
        restored = self.store.import_course(self.store.export(saved["id"]))
        self.assertEqual([mark()], restored["modules"][0]["annotations"])
        self.assertEqual("Personal notes remain independent", restored["modules"][0]["notes"])
        self.assertTrue(restored["modules"][0]["read"])
        summary = self.store.summary(saved["id"])
        self.assertNotIn("annotations", summary["modules"][0])

    def test_idempotent_edits_and_removal_preserve_other_marks(self):
        first = mark()
        second = mark("b"*32)
        self.request(self.path, dict(operation="upsert", annotation=first))
        self.request(self.path, dict(operation="upsert", annotation=second))
        first.update(style="underline", color="blue")
        self.request(self.path, dict(operation="upsert", annotation=first))
        saved = self.store.course(self.course["id"])["modules"][0]
        self.assertEqual([first, second], saved["annotations"])
        for _ in range(2):
            self.request(self.path, dict(operation="delete", id=first["id"]))
        self.assertEqual([second], self.store.course(self.course["id"])["modules"][0]["annotations"])

    def test_invalid_anchors_and_styles_rejected_before_saving(self):
        invalid = []
        for change in (dict(id="<script>"), dict(style="html"), dict(color="red"), dict(segments=[])):
            invalid.append(dict(mark(), **change))
        for change in (dict(block="section:999"), dict(end=1000), dict(start=True), dict(exact=""),
                       dict(signature="bad"), dict(prefix="x"*33), dict(exact="\ud800")):
            bad = mark();bad["segments"][0].update(change);invalid.append(bad)
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(self.path, dict(operation="upsert", annotation=bad))
            self.assertEqual(400, error.exception.code)
        self.assertNotIn("annotations", self.store.course(self.course["id"])["modules"][0])

    def test_utf16_offsets_and_bounded_backup_validation(self):
        value = mark();value["segments"][0].update(exact="A😀", end=3)
        self.request(self.path, dict(operation="upsert", annotation=value))
        with self.assertRaises(ValueError):
            validate_marks([mark(f"{i:032x}") for i in range(501)], self.course["modules"][0])
        archive = self.store.export(self.course["id"])
        altered = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(altered, "w") as target:
            for name in source.namelist():
                raw = source.read(name)
                if name == "folium.json":
                    manifest = json.loads(raw)
                    manifest["course"]["modules"][0]["annotations"][0]["segments"][0]["block"] = "missing"
                    raw = json.dumps(manifest).encode()
                target.writestr(name, raw)
        before = len(self.store.courses())
        with self.assertRaisesRegex(ValueError, "saved lesson content"):
            self.store.import_course(altered.getvalue())
        self.assertEqual(before, len(self.store.courses()))

    def test_recoverable_course_deletion_keeps_marks_in_recovery(self):
        self.request(self.path, dict(operation="upsert", annotation=mark()))
        info = self.server.jobs.delete_course(self.course["id"])
        restored = self.store.import_course((self.store.root / "backups" / info["recovery_backup"]).read_bytes())
        self.assertEqual([mark()], restored["modules"][0]["annotations"])


if __name__ == "__main__":
    unittest.main()
