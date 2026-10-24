"""Storage and HTTP payload regressions, using isolated synthetic courses."""
import json
import threading
import unittest
import urllib.request

from app import create_server
from core import Store
from fixtures import seed_test_course
from test_core import test_directory


class StorageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = test_directory()
        self.server = create_server(self.temp.name, 0)
        self.store = self.server.store
        self.course = seed_test_course(self.store)
        self.course["modules"][0]["package"]["sections"][0]["body"] = "LARGE_SAVED_TEACHING" * 30000
        self.store.save(self.course)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.store.db.set_trace_callback(None)
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.temp.cleanup()

    def request(self, path, body=None):
        req = urllib.request.Request(self.url+path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_minor_study_updates_do_not_rewrite_teaching_or_return_it(self):
        queries = []
        self.store.db.set_trace_callback(queries.append)
        value = self.request(f"/api/courses/{self.course['id']}/modules/m1/progress", dict(read=True, notes="Keep this note"))
        self.assertFalse(any("INSERT OR REPLACE INTO courses" in q or q.startswith("UPDATE courses ") for q in queries))
        self.assertFalse("LARGE_SAVED_TEACHING" in json.dumps(value))
        self.assertTrue(value["course"].get("study_patch"))
        saved = self.store.course(self.course["id"])
        self.assertEqual("Keep this note", saved["modules"][0]["notes"])
        reopened = Store(self.temp.name)
        try:
            self.assertEqual("Keep this note", reopened.course(self.course["id"])["modules"][0]["notes"])
        finally:
            reopened.close()
        restored = self.store.import_course(self.store.export(self.course["id"]))
        self.assertEqual("Keep this note", restored["modules"][0]["notes"])
        self.assertTrue(restored["modules"][0]["read"])

    def test_library_index_omits_teaching_and_does_not_read_pdf_text(self):
        queries = []
        self.store.db.set_trace_callback(queries.append)
        index = self.request("/api/courses")
        self.assertFalse("LARGE_SAVED_TEACHING" in json.dumps(index))
        self.assertLess(len(json.dumps(index)), 20000)
        self.assertTrue(index[0].get("summary"))
        self.assertTrue(index[0]["modules"][0]["package"]["flashcards"])
        self.assertFalse(any("name,role,pages,digest" in q for q in queries))
        detail = self.request(f"/api/courses/{self.course['id']}")
        self.assertTrue("LARGE_SAVED_TEACHING" in detail["modules"][0]["package"]["sections"][0]["body"])

    def test_legacy_embedded_study_state_is_preserved_and_overlaid(self):
        c = self.store.course(self.course["id"])
        c["modules"][0].update(read=True, notes="Legacy note")
        # Emulate a database row created before study-state separation.
        with self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO courses VALUES (?,?)", (c["id"], json.dumps(c)))
            if self.store.db.execute("SELECT name FROM sqlite_master WHERE name='study_state'").fetchone():
                self.store.db.execute("DELETE FROM study_state WHERE course_id=?", (c["id"],))
        self.assertEqual("Legacy note", self.store.course(c["id"])["modules"][0]["notes"])
        self.request(f"/api/courses/{c['id']}/modules/m1/progress", dict(notes="New note", read=False))
        saved = self.store.course(c["id"])
        self.assertEqual("New note", saved["modules"][0]["notes"])
        self.assertFalse(saved["modules"][0]["read"])


if __name__ == "__main__":
    unittest.main()
