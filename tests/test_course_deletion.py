"""Recoverable deletion, job exclusion, and local HTTP boundaries."""
import hashlib
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import create_server
from core import review_card
from fixtures import seed_test_course
from test_core import test_directory


class CourseDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = test_directory()
        self.server = create_server(self.temp.name, 0, env_file=Path(self.temp.name)/"absent.env")
        self.store = self.server.store
        self.course = seed_test_course(self.store)
        self.other = seed_test_course(self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.temp.cleanup()

    def request(self, path, body=None, **headers):
        request = urllib.request.Request(self.url+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type":"application/json", **headers})
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return raw if response.headers.get_content_type() == "application/zip" else json.loads(raw)

    def test_deletion_cleans_workspace_and_preserves_complete_recovery_and_other_course(self):
        cid = self.course["id"]
        def study(c):
            c["modules"][0].update(notes="Keep these notes", read=True, bookmarked=True)
            review_card(c, "m1", 0, "good")
        self.store.update(cid, study, study_module="m1")
        self.server.settings.save(dict(api_key="synthetic-private-key"))
        docs = self.store.docs(cid)
        other_hashes = {d["id"]:hashlib.sha256(self.store.document(d["id"])[0].read_bytes()).hexdigest()
                        for d in self.store.docs(self.other["id"])}
        preview = self.store.root/"page_previews"/(docs[0]["id"]+"-1.png")
        preview.parent.mkdir(exist_ok=True)
        preview.write_bytes(b"Disposable preview")
        derived = self.store.root/"visual_analysis"/cid
        derived.mkdir(parents=True)
        (derived/"derived.jpg").write_bytes(b"Disposable derived image")
        result = self.request(f"/api/courses/{cid}/delete", dict(confirm=cid))
        self.assertEqual(cid, result["deleted"])
        self.assertFalse(result["cleanup_pending"])
        self.assertEqual([self.other["id"]], [c["id"] for c in self.request("/api/courses")])
        for table, column in (("courses","id"),("documents","course_id"),("study_state","course_id"),("course_summaries","id")):
            self.assertEqual(0, self.store.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?",(cid,)).fetchone()[0])
        for doc in docs:
            self.assertFalse((self.store.root/"documents"/(doc["id"]+".pdf")).exists())
            self.assertEqual(0, self.store.db.execute("SELECT COUNT(*) FROM document_stats WHERE doc_id=?",(doc["id"],)).fetchone()[0])
        self.assertFalse(preview.exists())
        self.assertFalse(derived.exists())
        recovery = self.request(result["recovery_url"])
        with zipfile.ZipFile(io.BytesIO(recovery)) as archive:
            self.assertNotIn("synthetic-private-key", archive.read("folium.json").decode())
        restored = self.store.import_course(recovery)
        self.assertEqual("Keep these notes", restored["modules"][0]["notes"])
        self.assertTrue(restored["modules"][0]["read"])
        self.assertTrue(restored["modules"][0]["bookmarked"])
        self.assertEqual(6, len(restored["modules"]))
        self.assertTrue(restored["reviews"])
        self.assertEqual(other_hashes, {d["id"]:hashlib.sha256(self.store.document(d["id"])[0].read_bytes()).hexdigest()
                        for d in self.store.docs(self.other["id"])})

    def test_confirm_and_origin_required_and_active_job_cannot_be_deleted(self):
        cid = self.course["id"]
        for body, headers, status in (({}, {}, 400), (dict(confirm=cid), dict(Origin="https://example.invalid"), 403)):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(f"/api/courses/{cid}/delete", body, **headers)
            self.assertEqual(status, error.exception.code)
        self.server.jobs.active.add(cid)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(f"/api/courses/{cid}/delete", dict(confirm=cid))
            self.assertEqual(400, error.exception.code)
            self.assertIn("still running", error.exception.read().decode())
        finally:
            self.server.jobs.active.discard(cid)
        self.assertEqual(6, len(self.store.course(cid)["modules"]))
        self.assertFalse(list((self.store.root/"backups").glob("*-deleted-*")))

    def test_failed_recovery_copy_keeps_course_and_source_files(self):
        cid = self.course["id"]
        paths = [self.store.document(d["id"])[0] for d in self.store.docs(cid)]
        with patch.object(self.store,"backup",side_effect=OSError("No storage available")):
            with self.assertRaises(OSError):
                self.store.delete_course(cid)
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertEqual(6, len(self.store.course(cid)["modules"]))

    def test_recovery_download_cannot_read_settings_or_traverse_paths(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/recovery/../settings.json")
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/recovery/"+self.course["id"]+"-deleted-"+"a"*16+".folium.zip")


if __name__ == "__main__":
    unittest.main()
