"""Regression fixtures for slide decoration and teaching in PDF annotations."""
import copy
import io
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText, Link
from pypdf.generic import DecodedStreamObject, NameObject, NumberObject
from PIL import Image

from core import Store
from generation import Jobs
from visual import inspect_documents, select_pages, page_results
from fixtures import pdf_fixture
from test_core import test_directory
from test_visual import add_image, raster, VisualProvider


def decorated_slides(*, background_only=False):
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_fixture())))
    logo = Image.new("RGB", (80, 80), "darkgreen")
    for page in writer.pages:
        # The header straddles the old 16% limit; its full-page white background
        # previously counted as the large path required for a teaching diagram.
        commands = DecodedStreamObject()
        small_shapes = b"30 700 20 65 re f 55 700 20 65 re f 80 700 20 65 re f 105 700 20 65 re f"
        if background_only:
            small_shapes = b"80 500 20 20 re f 120 500 20 20 re f 160 500 20 20 re f 200 500 20 20 re f"
        commands.set_data(b"1 1 1 rg 0 0 595 842 re f 0 0 0 rg " + small_shapes + page.get_contents().get_data())
        page[NameObject("/Contents")] = writer._add_object(commands)
        if not background_only:
            add_image(writer, page, logo, "Footer", (1, 0, 72, 135.65))
    logo.close()
    if not background_only:
        teaching = raster(4)
        add_image(writer, writer.pages[2], teaching, "Teaching", (80, 180, 400, 350))
        teaching.close()
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class VisualTriageTests(unittest.TestCase):
    def setup_course(self, folder, raw):
        store = Store(folder)
        course = store.create("Triage regression")
        doc = store.add_pdf(course["id"], "slides.pdf", "material", raw)
        return store, course, doc

    def inspect(self, store, cid, **kwargs):
        return inspect_documents(store.docs(cid), lambda did: store.document(did)[0], **kwargs)

    def test_near_boundary_footer_and_header_do_not_select_every_slide(self):
        with test_directory() as folder:
            store, c, doc = self.setup_course(folder, decorated_slides())
            old = self.inspect(store, c["id"], inspection_version=1)
            self.assertTrue(all(row["selected"] for row in old["pages"]))
            revised = self.inspect(store, c["id"])
            self.assertEqual([3], [row["page"] for row in revised["pages"] if row["selected"]])
            self.assertTrue(all(row["ignored_images"] == 1 and len(row["masks"]) == 1 for row in revised["pages"]))
            store.close()

    def test_background_fill_does_not_turn_small_shapes_into_a_diagram(self):
        with test_directory() as folder:
            store, c, doc = self.setup_course(folder, decorated_slides(background_only=True))
            old = self.inspect(store, c["id"], inspection_version=1)
            self.assertTrue(all(row["selected"] for row in old["pages"]))
            self.assertFalse(any(row["selected"] for row in self.inspect(store, c["id"])["pages"]))
            store.close()

    def test_teaching_annotations_are_selected_but_hidden_annotations_and_links_are_not(self):
        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(pdf_fixture())))
        writer.add_annotation(0, FreeText(text="Important worked example", rect=(80, 180, 500, 600)))
        hidden = FreeText(text="Hidden draft", rect=(80, 180, 500, 600))
        hidden[NameObject("/F")] = NumberObject(2)
        writer.add_annotation(1, hidden)
        writer.add_annotation(2, Link(rect=(80, 180, 500, 600), url="https://example.invalid"))
        raw = io.BytesIO()
        writer.write(raw)
        with test_directory() as folder:
            store, c, doc = self.setup_course(folder, raw.getvalue())
            revised = self.inspect(store, c["id"])
            self.assertEqual([1], [row["page"] for row in revised["pages"] if row["selected"]])
            self.assertIn("annotations", revised["pages"][0]["reason"])
            store.close()

    def test_explicit_reinspection_refreshes_unreviewed_cached_suggestions(self):
        with test_directory() as folder:
            store, c, doc = self.setup_course(folder, decorated_slides())
            old = self.inspect(store, c["id"], inspection_version=1)
            store.update(c["id"], lambda course: course.update(visual=old))
            jobs = Jobs(store, VisualProvider(store, doc["id"]))
            self.assertEqual(old, jobs._inspect(c["id"]))
            with patch("generation.inspect_documents", wraps=inspect_documents) as inspect:
                revised = jobs._inspect(c["id"], refresh=True)
            inspect.assert_called_once()
            self.assertEqual([3], [row["page"] for row in revised["pages"] if row["selected"]])
            store.close()

    def test_reinspection_preserves_reviewed_choices(self):
        with test_directory() as folder:
            store, c, doc = self.setup_course(folder, decorated_slides())
            previous = self.inspect(store, c["id"], inspection_version=1)
            select_pages(previous, [])
            store.update(c["id"], lambda course: course.update(visual=previous))
            revised = Jobs(store, VisualProvider(store, doc["id"]))._inspect(c["id"], refresh=True)
            self.assertFalse(any(row["selected"] for row in revised["pages"]))
            self.assertTrue(revised["selection_reviewed"])
            store.close()

    def test_legacy_analysis_survives_backup_reinspection_and_another_backup(self):
        with test_directory() as folder:
            store, c, doc = self.setup_course(folder, decorated_slides())
            previous = self.inspect(store, c["id"], inspection_version=1)
            select_pages(previous, [dict(doc_id=row["doc_id"], page=row["page"]) for row in previous["pages"]])
            store.update(c["id"], lambda course: course.update(visual=previous))
            fake = VisualProvider(store, doc["id"])
            Jobs(store, fake)._visual(c["id"])
            saved = copy.deepcopy(store.course(c["id"])["visual"]["batches"])
            restored = store.import_course(store.export(c["id"]))
            self.assertEqual(len(previous["pages"]), len(page_results(restored["visual"])))
            revised = Jobs(store, fake)._inspect(c["id"], refresh=True)
            self.assertEqual(saved, revised["batches"])
            self.assertEqual(2, revised["inspection_version"])
            twice = store.import_course(store.export(c["id"]))
            self.assertEqual(len(previous["pages"]), len(page_results(twice["visual"])))
            store.close()


if __name__ == "__main__":
    unittest.main()
