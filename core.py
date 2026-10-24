"""Persistent local course data. No provider calls are made in this module."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import sqlite3
import threading
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pypdf import PdfReader

STUDY_FIELDS = ("read", "bookmarked", "notes", "attempts", "question_evidence")

def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex[:16]


def clean(value, limit=1000):
    return safe_text(str(value or "")).strip()[:limit]


def safe_text(text):
    """Recover valid surrogate pairs and replace broken PDF glyphs, preserving math."""
    text = str(text).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "documents").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "folium.db", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, course_id TEXT NOT NULL,
              name TEXT, role TEXT, pages TEXT, digest TEXT);
            CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS documents_by_course ON documents(course_id);
            CREATE TABLE IF NOT EXISTS study_state(course_id TEXT NOT NULL, module_id TEXT NOT NULL,
              updated TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(course_id,module_id));
            CREATE TABLE IF NOT EXISTS course_summaries(id TEXT PRIMARY KEY, updated TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS document_stats(doc_id TEXT PRIMARY KEY, page_count INTEGER NOT NULL,
              readable_pages INTEGER NOT NULL, text_warning_pages INTEGER NOT NULL);
        """)
        self.db.commit()
        self._repair_extraction()

    def _repair_extraction(self):
        changes, stats = [], []
        for doc_id, raw in self.db.execute("SELECT id,pages FROM documents"):
            pages = json.loads(raw)
            repaired = [safe_text(p) for p in pages]
            if pages != repaired:
                changes.append((json.dumps(repaired), doc_id))
            stats.append((doc_id, len(repaired), sum(bool(p.strip()) for p in repaired), sum("\ufffd" in p for p in repaired)))
        if changes:
            folder = self.root / "backups"
            folder.mkdir(exist_ok=True)
            # Retain the exact previous text and course state before the one-time repair.
            backup = sqlite3.connect(folder / ("before-text-repair-" + uid() + ".db"))
            self.db.backup(backup)
            backup.close()
            with self.db:
                self.db.executemany("UPDATE documents SET pages=? WHERE id=?", changes)
        # Small metadata rows avoid decoding every PDF's text for library/detail views.
        with self.db:
            self.db.executemany("INSERT INTO document_stats VALUES (?,?,?,?) ON CONFLICT(doc_id) DO UPDATE SET "
                "page_count=excluded.page_count,readable_pages=excluded.readable_pages,text_warning_pages=excluded.text_warning_pages "
                "WHERE page_count!=excluded.page_count OR readable_pages!=excluded.readable_pages OR text_warning_pages!=excluded.text_warning_pages", stats)

    def _save_doc_stats(self, doc_id, pages):
        self.db.execute("INSERT OR REPLACE INTO document_stats VALUES (?,?,?,?)",
                        (doc_id, len(pages), sum(bool(p.strip()) for p in pages), sum("\ufffd" in p for p in pages)))

    def document_metadata(self, course_id):
        with self.lock:
            rows = self.db.execute("SELECT d.id,d.name,d.role,s.page_count,s.readable_pages,s.text_warning_pages "
                "FROM documents d LEFT JOIN document_stats s ON s.doc_id=d.id WHERE d.course_id=? ORDER BY d.rowid", (course_id,)).fetchall()
        return [dict(zip(("id", "name", "role", "page_count", "readable_pages", "text_warning_pages"), row)) for row in rows]

    def _write_study(self, course, only_module=None):
        for module in course["modules"]:
            if only_module is not None and module["id"] != only_module:
                continue
            data = {key: module[key] for key in STUDY_FIELDS if key in module}
            data["reviews"] = {key: value for key, value in course.get("reviews", {}).items() if key.startswith(module["id"] + ":")}
            self.db.execute("INSERT INTO study_state VALUES (?,?,?,?) ON CONFLICT(course_id,module_id) "
                "DO UPDATE SET updated=excluded.updated,data=excluded.data WHERE data!=excluded.data",
                (course["id"], module["id"], course["updated"], json.dumps(data, ensure_ascii=False)))

    def _hydrate_study(self, course):
        modules = {m["id"]: m for m in course["modules"]}
        for mid, updated, raw in self.db.execute("SELECT module_id,updated,data FROM study_state WHERE course_id=?", (course["id"],)):
            if mid not in modules:
                continue
            data = json.loads(raw)
            for key in STUDY_FIELDS:
                modules[mid].pop(key, None)
            modules[mid].update({key: data[key] for key in STUDY_FIELDS if key in data})
            course["reviews"] = {key: value for key, value in course.get("reviews", {}).items() if not key.startswith(mid + ":")}
            course["reviews"].update(data.get("reviews", {}))
            course["updated"] = max(course["updated"], updated)
        return course

    def _write_summary(self, course):
        summary = {key: course[key] for key in ("id", "title", "description", "status", "created", "updated", "demo", "job")}
        summary.update(summary=True, documents=self.document_metadata(course["id"]), reviews=course.get("reviews", {}), modules=[])
        for module in course["modules"]:
            row = {key: module[key] for key in ("id", "title", "description", "topics", "prerequisites", "read", "bookmarked") if key in module}
            row.update(state=module_state(module), evidence=assessment_evidence(module))
            if module.get("package"):
                row["package"] = dict(flashcards=module["package"].get("flashcards", []),
                                      assessment_status=module["package"].get("assessment_status"))
            summary["modules"].append(row)
        self.db.execute("INSERT OR REPLACE INTO course_summaries VALUES (?,?,?)", (course["id"], course["updated"], json.dumps(summary, ensure_ascii=False)))
        return summary

    def summaries(self):
        with self.lock, self.db:
            missing = self.db.execute("SELECT c.data FROM courses c LEFT JOIN course_summaries s ON s.id=c.id WHERE s.id IS NULL").fetchall()
            for row in missing:
                self._write_summary(self._hydrate_study(json.loads(row[0])))
            return [json.loads(row[0]) for row in self.db.execute("SELECT s.data FROM course_summaries s JOIN courses c ON c.id=s.id ORDER BY s.updated DESC,s.id")]

    def summary(self, course_id):
        with self.lock, self.db:
            row = self.db.execute("SELECT s.data FROM course_summaries s JOIN courses c ON c.id=s.id WHERE s.id=?", (course_id,)).fetchone()
            return json.loads(row[0]) if row else self._write_summary(self.course(course_id))

    def study_patch(self, course, module_id):
        module = next(m for m in course["modules"] if m["id"] == module_id)
        row = {key: module[key] for key in STUDY_FIELDS if key in module}
        row.update(id=module_id, state=module_state(module), evidence=assessment_evidence(module))
        return dict(id=course["id"], updated=course["updated"], study_patch=True, modules=[row],
                    reviews={key: value for key, value in course.get("reviews", {}).items() if key.startswith(module_id+":")})

    def close(self):
        self.db.close()

    def create(self, title, description="", demo=False):
        course = dict(id=uid(), title=clean(title, 120) or "Untitled course",
                      description=clean(description, 500), created=now(), updated=now(),
                      status="uploaded", modules=[], pyqs=[], pyq_batches=[], reviews={},
                      demo=demo, job=None, warnings=[])
        self.save(course)
        return course

    def save(self, course):
        with self.lock, self.db:
            course["updated"] = now()
            self._write_study(course)
            saved = dict(course, reviews={}, modules=[{key: value for key, value in module.items() if key not in STUDY_FIELDS} for module in course["modules"]])
            self.db.execute("INSERT OR REPLACE INTO courses VALUES (?,?)",
                            (course["id"], json.dumps(saved, ensure_ascii=False)))
            self._write_summary(course)

    def course(self, course_id):
        with self.lock:
            row = self.db.execute("SELECT data FROM courses WHERE id=?", (course_id,)).fetchone()
            if not row:
                raise ValueError("Course not found.")
            return self._hydrate_study(json.loads(row[0]))

    def update(self, course_id, mutate, *, study_module=None):
        with self.lock, self.db:
            course = self.course(course_id)
            result = mutate(course)
            if study_module is None:
                self.save(course)
            else:
                course["updated"] = now()
                self._write_study(course, study_module)
                self._write_summary(course)
            return result if result is not None else course

    def courses(self):
        with self.lock:
            rows = self.db.execute("SELECT data FROM courses ORDER BY rowid DESC").fetchall()
            return [self._hydrate_study(json.loads(row[0])) for row in rows]

    def docs(self, course_id):
        with self.lock:
            rows = self.db.execute("SELECT id,name,role,pages,digest FROM documents WHERE course_id=? ORDER BY rowid",
                                   (course_id,)).fetchall()
        return [dict(id=r[0], name=r[1], role=r[2], pages=json.loads(r[3]), digest=r[4]) for r in rows]

    def public(self, course_id):
        course = self.course(course_id)
        course["documents"] = [dict(d, annotations=[n for n in course.get("source_annotations", []) if n["doc_id"] == d["id"]])
                               for d in self.document_metadata(course_id)]
        if course.get("scope"):
            from scope import coverage, records_for
            course["scope_coverage"] = coverage(course["scope"])
            course["scope_records"] = records_for(course["scope"])
            # The browser needs review records, not internal batch responses and merges.
            course.pop("scope")
        if course.get("visual"):
            from visual import page_results
            visual=course["visual"];results=page_results(visual)
            for doc in course["documents"]:
                doc["visually_analyzed_pages"]=sum(r["doc_id"]==doc["id"] and r["selected"] and (r["doc_id"],r["page"]) in results for r in visual["pages"])
            course["visual"] = dict(version=visual["version"],fingerprint=visual["fingerprint"],
                selection_reviewed=visual["selection_reviewed"],model=visual.get("model"),batch_ids=list(visual["batches"]),
                pages=[dict(**{k:r[k] for k in ("doc_id","page","state","reason","selected","ignored_images")},
                            result=results.get((r["doc_id"],r["page"]),{}).get("status")) for r in visual["pages"]])
        return course

    def add_pdf(self, course_id, name, role, content):
        if role not in ("material", "syllabus", "pyq"):
            raise ValueError("Choose a valid document type.")
        if not content.startswith(b"%PDF-") or len(content) > 25 * 1024 * 1024:
            raise ValueError("Upload a valid PDF smaller than 25 MB.")
        digest = hashlib.sha256(content).hexdigest()
        with self.lock:
            row = self.db.execute("SELECT id,name,role,pages,digest FROM documents WHERE course_id=? AND digest=?", (course_id, digest)).fetchone()
        if row:
            return dict(id=row[0], name=row[1], role=row[2], pages=json.loads(row[3]), digest=row[4])
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("This PDF is password protected. Upload an unlocked copy.")
            if not 1 <= len(reader.pages) <= 600:
                raise ValueError("Use PDFs with 600 pages or fewer for this prototype.")
            pages = [safe_text(p.extract_text() or "").strip() for p in reader.pages]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("This PDF could not be read. Try exporting it as a new PDF.") from exc
        if sum(len(p) for p in pages) > 3_000_000:
            raise ValueError("This PDF contains too much text. Split it into smaller files.")
        doc = dict(id=uid(), name=Path(name.replace("\\", "/")).name[:180], role=role,
                   pages=pages, digest=digest)
        self._save_doc(course_id, doc, content)
        return doc

    def _save_doc(self, course_id, doc, content):
        path = self.root / "documents" / (doc["id"] + ".pdf")
        path.write_bytes(content)
        with self.lock, self.db:
            self.db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                            (doc["id"], course_id, doc["name"], doc["role"],
                             json.dumps(doc["pages"]), doc["digest"]))
            self._save_doc_stats(doc["id"], doc["pages"])
            self._write_summary(self.course(course_id))

    def document(self, doc_id):
        with self.lock:
            row = self.db.execute("SELECT course_id,name FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row or not re.fullmatch(r"[a-f0-9]{16}", doc_id):
            raise ValueError("Document not found.")
        return self.root / "documents" / (doc_id + ".pdf"), row[1]

    def cached(self, key):
        with self.lock:
            row = self.db.execute("SELECT data FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (key, json.dumps(value)))

    def export(self, course_id):
        course = self.course(course_id)
        course["job"] = None
        docs = self.docs(course_id)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("folium.json", json.dumps(dict(version=1, course=course, documents=docs)))
            for doc in docs:
                z.write(self.document(doc["id"])[0], "documents/" + doc["id"] + ".pdf")
        return stream.getvalue()

    def backup(self, course_id, reason="before-change"):
        folder = self.root / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / (course_id + "-" + reason + "-" + uid() + ".folium.zip")
        path.write_bytes(self.export(course_id))
        return path

    def extend(self, course_id, new_modules):
        with self.lock:
            course = self.course(course_id)
            combined = validate_outline(course["modules"] + new_modules)
            if len(combined) == len(course["modules"]):
                raise ValueError("Add at least one missing module.")
            if course.get("scope"):
                from scope import review_outline, review_signature
                exclusions = [row for row in course.get("scope_exclusions", [])
                              if not any(row["scope_id"] in m.get("scope_ids", []) for m in combined)]
                review_outline(course, combined, exclusions, self.docs(course_id))
                course["scope_exclusions"] = exclusions
                course["scope_review"] = review_signature(combined, exclusions, course["scope"]["fingerprint"])
            self.backup(course_id, "before-extension")
            course["modules"].extend(combined[len(course["modules"]):])
            if course.get("scope"):
                from generation import scope_document_coverage
                course["document_coverage"] = scope_document_coverage(course, self.docs(course_id))
            course["status"] = "outline"
            course["job"] = None
            self.save(course)
            return course

    def import_course(self, content):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                infos = z.infolist()
                if len(infos) > 65 or sum(i.file_size for i in infos) > 150 * 1024 * 1024:
                    raise ValueError("This backup is too large.")
                manifest = json.loads(z.read("folium.json"))
                if manifest.get("version") != 1:
                    raise ValueError("This backup version is not supported.")
                original = manifest["course"]
                docs = manifest["documents"]
                if not isinstance(docs, list) or len(docs) > 60:
                    raise ValueError("Invalid backup documents.")
                raw_modules = original.get("modules", [])
                modules = validate_outline(raw_modules) if raw_modules else []
                original_docs = {d["id"]: d for d in docs}
                if len(original_docs) != len(docs):
                    raise ValueError("Duplicate document IDs in backup.")
                prepared = []
                id_map = {}
                # Parse and validate source bytes before creating any course.
                for doc in docs:
                    if not re.fullmatch(r"[a-f0-9]{16}", doc["id"]):
                        raise ValueError("Invalid document ID in backup.")
                    raw = z.read("documents/" + doc["id"] + ".pdf")
                    if len(raw) > 25 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
                        raise ValueError("Invalid PDF in backup.")
                    pages = [safe_text(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(raw)).pages]
                    if not 1 <= len(pages) <= 600 or sum(map(len, pages)) > 3_000_000:
                        raise ValueError("Invalid page count in backup.")
                    new_id = uid()
                    id_map[doc["id"]] = new_id
                    prepared.append((dict(id=new_id, name=clean(Path(doc["name"].replace("\\", "/")).name, 180),
                                          role=doc["role"] if doc["role"] in ("material", "syllabus", "pyq") else "material",
                                          pages=pages, digest=hashlib.sha256(raw).hexdigest()), raw))
                allowed = {(old, p + 1) for old, d in original_docs.items()
                           for p in range(len(next(n[0]["pages"] for n in prepared if n[0]["id"] == id_map[old])))}
                source_docs = [dict(d, id=old) for old in original_docs for d, _ in prepared if d["id"] == id_map[old]]
                original_text = {(d["id"], i+1): " ".join(text.split()) for d in source_docs for i, text in enumerate(d["pages"])}
                if original.get("visual"):
                    from visual import validate_saved_visual, visual_records, visual_status
                    source_bytes={old:raw for old in original_docs for d,raw in prepared if d["id"]==id_map[old]}
                    validate_saved_visual(original["visual"],source_docs,lambda doc_id:source_bytes[doc_id])
                    if original.get("scope") and (original["scope"].get("visual_records",[]) != visual_records(original["visual"]) or original["scope"].get("visual_status",[]) != visual_status(original["visual"])):
                        raise ValueError("The saved scope does not match visual analysis.")
                elif original.get("scope",{}).get("visual_records") or original.get("scope",{}).get("visual_status"):
                    raise ValueError("The saved scope is missing its visual analysis.")
                def validate_original_quotes(package):
                    for section in package["sections"]:
                        if section.get("provenance") == "source_excerpt" and not all(" ".join(section["body"].split()) in original_text[(ref["doc_id"],ref["page"])] for ref in section["sources"]):
                            raise ValueError("A saved source quotation does not match the original PDF text.")
                if original.get("scope"):
                    from scope import validate_saved_scope, review_outline, review_signature
                    validate_saved_scope(original["scope"], source_docs)
                    if modules:
                        review_outline(original, modules, original.get("scope_exclusions", []), source_docs)
                    if original.get("scope_review") and original["scope_review"] != review_signature(modules, original.get("scope_exclusions", []), original["scope"]["fingerprint"]):
                        raise ValueError("Invalid reviewed scope in backup.")
                from scope import validate_ranges
                for module in modules:
                    if "source_ranges" in module:
                        validate_ranges(module["source_ranges"], source_docs)
                    old_module = original["modules"][next(i for i,m in enumerate(original["modules"]) if m["id"] == module["id"])]
                    pkg = old_module.get("package")
                    if pkg:
                        validate_package(pkg, allowed)
                        validate_original_quotes(pkg)
                        if "topic_locations" in pkg:
                            validate_ranges(pkg["topic_locations"], source_docs)
                        module["package"] = pkg
                    preparation = old_module.get("preparation")
                    if preparation and not pkg:
                        from generation import validate_plan
                        validate_plan(preparation["plan"], module["topics"], module.get("scope_ids") if original.get("scope") else None)
                        lesson_ids = {l["id"] for l in preparation["plan"]["lessons"]}
                        if not isinstance(preparation.get("lessons"), dict) or any(lid not in lesson_ids for lid in preparation["lessons"]):
                            raise ValueError("Invalid unfinished lessons in backup.")
                        for part in preparation["lessons"].values():
                            validate_package(part, allowed)
                            validate_original_quotes(part)
                            if "topic_locations" in part:
                                validate_ranges(part["topic_locations"], source_docs)
                        module["preparation"] = preparation
                    if "practice_preparation" in old_module:
                        from generation import validate_practice_preparation
                        if not pkg or pkg.get("assessment_status") != "missing":
                            raise ValueError("Unfinished practice needs saved teaching awaiting practice.")
                        module["practice_preparation"] = validate_practice_preparation(module, old_module["practice_preparation"])
                module_ids = {m["id"] for m in modules}
                for row in original.get("document_coverage", []):
                    if not isinstance(row,dict) or row.get("doc_id") not in original_docs or not isinstance(row.get("module_ids"),list) or any(mid not in module_ids for mid in row["module_ids"]):
                        raise ValueError("Invalid source coverage in backup.")
                for note in original.get("source_annotations", []):
                    if not isinstance(note,dict) or (note.get("doc_id"),note.get("page")) not in allowed or not isinstance(note.get("message"),str) or not isinstance(note.get("module_ids"),list) or any(mid not in module_ids for mid in note["module_ids"]):
                        raise ValueError("Invalid source clarification in backup.")
                pyqs = original.get("pyqs", [])
                if not isinstance(pyqs,list):
                    raise ValueError("Invalid past-paper questions in backup.")
                for question in pyqs:
                    if not isinstance(question,dict) or not isinstance(question.get("question"),str) or (question.get("doc_id"),question.get("page")) not in allowed or not isinstance(question.get("module_ids"),list) or any(mid not in module_ids for mid in question["module_ids"]):
                        raise ValueError("A past-paper reference in this backup is invalid.")
                reviews = original.get("reviews", {})
                if not isinstance(reviews,dict):
                    raise ValueError("Invalid review history in backup.")
                for key,review in reviews.items():
                    if not isinstance(review,dict) or type(review.get("interval")) is not int or not 0 <= review["interval"] <= 60:
                        raise ValueError("Invalid review schedule in backup.")
                    try:
                        parsed = datetime.fromisoformat(review["due"])
                        if parsed.tzinfo is None:
                            raise ValueError()
                    except (KeyError,TypeError,ValueError):
                        raise ValueError("Invalid review date in backup.") from None
                for old in original["modules"]:
                    evidence = old.get("question_evidence")
                    if evidence is not None and (not isinstance(evidence,dict) or not isinstance(evidence.get("version"),str) or not isinstance(evidence.get("first"),dict) or len(evidence["first"])>100 or any(not isinstance(key,str) or type(value) is not bool for key,value in evidence["first"].items())):
                        raise ValueError("Invalid first-encounter evidence in backup.")
                    if not isinstance(old.get("notes",""),str) or len(old.get("notes","")) > 30000:
                        raise ValueError("Invalid personal notes in backup.")
                    attempts = old.get("attempts", [])
                    if not isinstance(attempts,list) or len(attempts)>30:
                        raise ValueError("Invalid practice history in backup.")
                    for attempt in attempts:
                        if not isinstance(attempt,dict) or type(attempt.get("total")) is not int or type(attempt.get("correct")) is not int or not 1 <= attempt["total"] <= 100 or not 0 <= attempt["correct"] <= attempt["total"]:
                            raise ValueError("Invalid practice score in backup.")
                def remap(obj):
                    if isinstance(obj, dict):
                        return {k: id_map.get(v, v) if k == "doc_id" else remap(v) for k,v in obj.items()}
                    if isinstance(obj, list):
                        return [remap(v) for v in obj]
                    return obj
                course = self.create(original.get("title", "Imported course"), original.get("description", ""))
                course.update(modules=remap(modules), pyqs=remap(pyqs),
                              reviews=reviews, demo=bool(original.get("demo", False)))
                for field in ("document_coverage", "generation_version", "corrections", "warnings", "source_annotations", "scope", "scope_exclusions", "visual"):
                    if field in original:
                        course[field] = remap(original[field])
                if original.get("scope_review"):
                    course["scope_review"] = review_signature(course["modules"], course.get("scope_exclusions", []), course["scope"]["fingerprint"])
                for module, old in zip(course["modules"], original["modules"]):
                    for field in ("read", "bookmarked", "notes", "attempts", "question_evidence"):
                        if field in old:
                            module[field] = old[field]
                course["status"] = "ready" if original.get("status") == "ready" and modules and all(m.get("package") for m in modules) else "outline" if modules else "uploaded"
                # Preserve PYQ-stage completion when resuming an imported course.
                course["pyq_batches"] = [id_map.get(x.split(":")[0], x.split(":")[0]) + ":" + x.split(":", 1)[1]
                                         for x in original.get("pyq_batches", []) if ":" in x]
                if "pyq_coverage" in original:
                    from generation import paper_coverage
                    course["pyq_coverage"] = paper_coverage([d for d, _ in prepared], course["pyq_batches"])
                for doc, raw in prepared:
                    self._save_doc(course["id"], doc, raw)
                self.save(course)
                return course
        except (KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError, StopIteration) as exc:
            raise ValueError("This is not a valid Folium course backup.") from exc


def validate_outline(modules):
    if not isinstance(modules, list) or not 1 <= len(modules) <= 20:
        raise ValueError("The outline needs between 1 and 20 modules.")
    result = []
    for i, m in enumerate(modules):
        if not isinstance(m, dict):
            raise ValueError("Invalid module in outline.")
        mid = clean(m.get("id"), 40) or f"m{i+1}"
        topics = m.get("topics", [])
        if not clean(m.get("title")) or not isinstance(topics, list) or not 1 <= len(topics) <= 20:
            raise ValueError("Every module needs a title and 1 to 20 topics.")
        result.append(dict(id=mid, title=clean(m["title"], 150), description=clean(m.get("description"), 600),
                           topics=[clean(t, 150) for t in topics if clean(t)],
                           prerequisites=list(dict.fromkeys(m.get("prerequisites", [])))))
        for key in ("scope_ids", "source_ranges", "scope_notes"):
            if key in m:
                result[-1][key] = copy.deepcopy(m[key])
        if not result[-1]["topics"]:
            raise ValueError("Every module needs at least one topic.")
    ids = {m["id"] for m in result}
    if len(ids) != len(result):
        raise ValueError("Module IDs must be unique.")
    graph = {m["id"]: m["prerequisites"] for m in result}
    seen, visiting = set(), set()
    def visit(mid):
        if mid in visiting:
            raise ValueError("Prerequisites form a cycle. Remove one of the links.")
        if mid in seen:
            return
        visiting.add(mid)
        for parent in graph[mid]:
            if parent not in ids:
                raise ValueError("A prerequisite points to a missing module.")
            visit(parent)
        visiting.remove(mid)
        seen.add(mid)
    for mid in ids:
        visit(mid)
    return result


def validate_teaching(pkg, allowed):
    if not isinstance(pkg, dict) or not clean(pkg.get("overview")):
        raise ValueError("The generated lesson is incomplete. Resume to retry this module.")
    if not isinstance(pkg.get("sections"), list) or not pkg["sections"]:
        raise ValueError("The generated lesson needs teaching content.")
    if not isinstance(pkg.get("objectives"), list) or not pkg["objectives"] or not all(isinstance(x,str) and x.strip() for x in pkg["objectives"]):
        raise ValueError("The generated lesson needs clear learning objectives.")
    if not isinstance(pkg.get("diagrams", []), list):
        raise ValueError("The lesson diagrams could not be read.")
    for diagram in pkg.get("diagrams", []):
        if not isinstance(diagram,dict) or not isinstance(diagram.get("nodes"),list) or not 2 <= len(diagram["nodes"]) <= 8 or not all(isinstance(x,str) for x in diagram["nodes"]):
            raise ValueError("A lesson diagram has an invalid structure.")
    for sec in pkg["sections"]:
        if not isinstance(sec,dict) or sec.get("kind") not in ("concept","example","formula","pitfall","recap"):
            raise ValueError("A lesson section has an invalid format.")
        if not isinstance(sec.get("title"), str) or not isinstance(sec.get("body"), str) or not clean(sec.get("title")) or not clean(sec.get("body")):
            raise ValueError("The generated lesson has an empty section.")
        if not isinstance(sec.get("sources", []), list):
            raise ValueError("Invalid lesson citation list.")
        if "provenance" in sec and sec["provenance"] not in ("generated", "source_excerpt"):
            raise ValueError("Invalid lesson provenance.")
        if sec.get("provenance") == "generated" and sec.get("sources"):
            raise ValueError("Generated teaching cannot carry source-support citations.")
        if sec.get("provenance") == "source_excerpt" and not sec.get("sources"):
            raise ValueError("A source excerpt needs a citation.")
        for ref in sec.get("sources", []):
            if not isinstance(ref, dict) or type(ref.get("page")) is not int or (ref.get("doc_id"), ref.get("page")) not in allowed:
                raise ValueError("A generated citation did not match a supplied source page. Resume to retry.")
    if not isinstance(pkg.get("coverage_notes", ""), str):
        raise ValueError("Invalid teaching coverage notes.")
    return pkg


def validate_assessment(pkg, topics=None):
    if not isinstance(pkg, dict):
        raise ValueError("The practice response is incomplete.")
    questions = pkg.get("questions", [])
    if not isinstance(questions, list) or not questions:
        raise ValueError("No practice questions were generated.")
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError("A generated practice question is incomplete.")
        q["id"] = f"q{i+1}"
        if q.get("type") not in ("objective", "subjective") or not clean(q.get("question")) or not clean(q.get("solution")):
            raise ValueError("A generated practice question is incomplete.")
        if q["type"] == "objective":
            opts = q.get("options", [])
            answer = q.get("correct_index")
            if not isinstance(opts, list) or not 2 <= len(opts) <= 6 or type(answer) is not int or not 0 <= answer < len(opts):
                raise ValueError("A practice question has an invalid answer key.")
            if any(not isinstance(opt, str) or not opt.strip() for opt in opts) or len({" ".join(opt.split()) for opt in opts}) != len(opts):
                raise ValueError("Practice options must be distinct and nonempty.")
        if topics is not None:
            if q.get("topic") not in topics:
                raise ValueError("A practice question was not mapped to an assigned topic.")
            if q["type"] == "objective" and len(q["options"]) != 4:
                raise ValueError("Each objective question needs four distinct options.")
            if q["type"] == "subjective" and (q.get("options") != [] or q.get("correct_index") != -1):
                raise ValueError("Written problems must use empty options and index -1.")
    if not any(q["type"] == "objective" for q in questions):
        raise ValueError("The question bank needs objective questions.")
    if topics is not None and any(not any(q["type"] == "objective" and q["topic"] == topic for q in questions) for topic in topics):
        raise ValueError("Practice is missing an assigned topic.")
    if not isinstance(pkg.get("flashcards"), list) or not pkg["flashcards"]:
        raise ValueError("No revision cards were generated.")
    for card in pkg["flashcards"]:
        if not isinstance(card, dict) or not clean(card.get("front")) or not clean(card.get("back")):
            raise ValueError("A revision card is incomplete.")
    return pkg


def validate_package(pkg, allowed):
    validate_teaching(pkg, allowed)
    status = pkg.get("assessment_status")
    if status not in (None, "missing", "ready"):
        raise ValueError("Invalid practice preparation state.")
    if status == "missing":
        if pkg.get("questions") != [] or pkg.get("flashcards") != []:
            raise ValueError("Unprepared practice must have empty question and card lists.")
        return pkg
    return validate_assessment(pkg)


def bank_version(module):
    bank = module.get("package", {}).get("questions", [])
    return hashlib.sha256(json.dumps(bank, sort_keys=True).encode()).hexdigest()[:16]


def first_encounters(module):
    questions = {q["id"]:q for q in module.get("package", {}).get("questions", []) if q["type"] == "objective"}
    record = module.get("question_evidence", {})
    first = {qid:value for qid,value in record.get("first", {}).items() if qid in questions and type(value) is bool} if record.get("version") == bank_version(module) else {}
    for attempt in module.get("attempts", []):
        if attempt.get("bank_version") != bank_version(module):
            continue
        for result in attempt.get("results", []):
            if result.get("id") in questions:
                first.setdefault(result["id"], result.get("correct") is True)
    return first


def assessment_evidence(module):
    questions = {q["id"]:q for q in module.get("package", {}).get("questions", []) if q["type"] == "objective"}
    first = first_encounters(module)
    topics = {questions[qid].get("topic") for qid in first}
    return dict(unique=len(first), bank_size=len(questions), first_correct=sum(first.values()),
                topics=len(topics & set(module.get("topics", []))), total_topics=len(module.get("topics", [])))


def module_state(module):
    attempts = module.get("attempts", [])
    if attempts:
        recent = attempts[-3:]
        score = sum(a["correct"] for a in recent) / max(1, sum(a["total"] for a in recent))
        if score < .5:
            return "weak"
        evidence = assessment_evidence(module)
        if score >= .8 and evidence["unique"] >= 12 and evidence["first_correct"] / evidence["unique"] >= .8 and evidence["topics"] == evidence["total_topics"]:
            return "mastered"
        return "learning"
    return "learning" if module.get("read") else "unseen"


def grade(module, answers, question_ids=None):
    questions = [q for q in module.get("package", {}).get("questions", []) if q["type"] == "objective"]
    if not questions:
        raise ValueError("This module has no objective practice yet.")
    if question_ids is not None:
        valid = {q["id"] for q in questions}
        if not isinstance(question_ids, list) or not question_ids or len(question_ids) != len(set(question_ids)) or any(qid not in valid for qid in question_ids):
            raise ValueError("Choose a valid set of saved questions.")
        questions = [q for q in questions if q["id"] in question_ids]
    if not isinstance(answers, dict) or set(answers) != {q["id"] for q in questions}:
        raise ValueError("Answer each question before checking your results.")
    results = []
    for q in questions:
        answer = answers[q["id"]]
        if type(answer) is not int or not 0 <= answer < len(q["options"]):
            raise ValueError("Choose a valid option for every question.")
        results.append(dict(id=q["id"], selected=answer, correct_index=q["correct_index"],
                            correct=answer == q["correct_index"], solution=q["solution"]))
    first = first_encounters(module)
    previous = len(first)
    for result in results:
        first.setdefault(result["id"], result["correct"])
    module["question_evidence"] = dict(version=bank_version(module), first=first)
    attempt = dict(date=now(), correct=sum(r["correct"] for r in results), total=len(results), results=results, bank_version=bank_version(module))
    module.setdefault("attempts", []).append(attempt)
    module["attempts"] = module["attempts"][-30:]
    attempt["new_questions"] = assessment_evidence(module)["unique"] - previous
    return attempt


def review_card(course, module_id, index, rating):
    module = next((m for m in course["modules"] if m["id"] == module_id), None)
    if not module or not 0 <= index < len(module.get("package", {}).get("flashcards", [])):
        raise ValueError("Revision card not found.")
    if rating not in ("again", "good", "easy"):
        raise ValueError("Choose a review rating.")
    key = f"{module_id}:{index}"
    previous = course["reviews"].get(key, {})
    interval = 0 if rating == "again" else min(60, max(1, previous.get("interval", 0) * (2 if rating == "good" else 3)))
    if rating == "easy" and not previous.get("interval"):
        interval = 3
    due = datetime.now(timezone.utc) + (timedelta(minutes=10) if rating == "again" else timedelta(days=interval))
    course["reviews"][key] = dict(due=due.isoformat(), interval=interval, last_reviewed=now())
    return course["reviews"][key]
