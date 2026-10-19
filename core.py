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


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex[:16]


def clean(value, limit=1000):
    return str(value or "").strip()[:limit]


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
        """)
        self.db.commit()

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
            self.db.execute("INSERT OR REPLACE INTO courses VALUES (?,?)",
                            (course["id"], json.dumps(course, ensure_ascii=False)))

    def course(self, course_id):
        with self.lock:
            row = self.db.execute("SELECT data FROM courses WHERE id=?", (course_id,)).fetchone()
        if not row:
            raise ValueError("Course not found.")
        return json.loads(row[0])

    def update(self, course_id, mutate):
        with self.lock:
            course = self.course(course_id)
            result = mutate(course)
            self.save(course)
            return result if result is not None else course

    def courses(self):
        with self.lock:
            rows = self.db.execute("SELECT data FROM courses ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def docs(self, course_id):
        with self.lock:
            rows = self.db.execute("SELECT id,name,role,pages,digest FROM documents WHERE course_id=? ORDER BY rowid",
                                   (course_id,)).fetchall()
        return [dict(id=r[0], name=r[1], role=r[2], pages=json.loads(r[3]), digest=r[4]) for r in rows]

    def public(self, course_id):
        course = self.course(course_id)
        course["documents"] = [dict(id=d["id"], name=d["name"], role=d["role"],
                                   page_count=len(d["pages"]),
                                   readable_pages=sum(bool(p.strip()) for p in d["pages"]))
                               for d in self.docs(course_id)]
        return course

    def add_pdf(self, course_id, name, role, content):
        if role not in ("material", "syllabus", "pyq"):
            raise ValueError("Choose a valid document type.")
        if not content.startswith(b"%PDF-") or len(content) > 25 * 1024 * 1024:
            raise ValueError("Upload a valid PDF smaller than 25 MB.")
        digest = hashlib.sha256(content).hexdigest()
        for doc in self.docs(course_id):
            if doc["digest"] == digest:
                return doc
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("This PDF is password protected. Upload an unlocked copy.")
            if len(reader.pages) > 600:
                raise ValueError("Use PDFs with 600 pages or fewer for this prototype.")
            pages = [(p.extract_text() or "").strip() for p in reader.pages]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("This PDF could not be read. Try exporting it as a new PDF.") from exc
        if sum(len(p) for p in pages) > 3_000_000:
            raise ValueError("This PDF contains too much text. Split it into smaller files.")
        if sum(len(p) for p in pages) < 60:
            raise ValueError("No usable text was found. Image-only scans need OCR before upload.")
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
            z.writestr("folium.json", json.dumps(dict(version=1, course=course, documents=docs), ensure_ascii=False))
            for doc in docs:
                z.write(self.document(doc["id"])[0], "documents/" + doc["id"] + ".pdf")
        return stream.getvalue()

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
                modules = validate_outline(original.get("modules", []))
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
                    pages = [(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(raw)).pages]
                    if not 1 <= len(pages) <= 600 or sum(map(len, pages)) > 3_000_000:
                        raise ValueError("Invalid page count in backup.")
                    new_id = uid()
                    id_map[doc["id"]] = new_id
                    prepared.append((dict(id=new_id, name=clean(Path(doc["name"].replace("\\", "/")).name, 180),
                                          role=doc["role"] if doc["role"] in ("material", "syllabus", "pyq") else "material",
                                          pages=pages, digest=hashlib.sha256(raw).hexdigest()), raw))
                allowed = {(old, p + 1) for old, d in original_docs.items()
                           for p in range(len(next(n[0]["pages"] for n in prepared if n[0]["id"] == id_map[old])))}
                for module in modules:
                    pkg = original["modules"][next(i for i,m in enumerate(original["modules"]) if m["id"] == module["id"])].get("package")
                    if pkg:
                        validate_package(pkg, allowed)
                        module["package"] = pkg
                module_ids = {m["id"] for m in modules}
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
                for module, old in zip(course["modules"], original["modules"]):
                    for field in ("read", "bookmarked", "notes", "attempts"):
                        if field in old:
                            module[field] = old[field]
                course["status"] = "ready" if original.get("status") == "ready" and all(m.get("package") for m in modules) else "outline"
                # Preserve PYQ-stage completion when resuming an imported course.
                course["pyq_batches"] = [id_map.get(x.split(":")[0], x.split(":")[0]) + ":" + x.split(":", 1)[1]
                                         for x in original.get("pyq_batches", []) if ":" in x]
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


def validate_package(pkg, allowed):
    if not isinstance(pkg, dict) or not clean(pkg.get("overview")):
        raise ValueError("The generated lesson is incomplete. Resume to retry this module.")
    if not isinstance(pkg.get("sections"), list) or len(pkg["sections"]) < 3:
        raise ValueError("The generated lesson needs at least three teaching sections.")
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
        if not clean(sec.get("title")) or not clean(sec.get("body")):
            raise ValueError("The generated lesson has an empty section.")
        for ref in sec.get("sources", []):
            if (ref.get("doc_id"), ref.get("page")) not in allowed:
                raise ValueError("A generated citation did not match a supplied source page. Resume to retry.")
    questions = pkg.get("questions", [])
    if not isinstance(questions, list) or not questions:
        raise ValueError("No practice questions were generated.")
    for i, q in enumerate(questions):
        q["id"] = f"q{i+1}"
        if q.get("type") not in ("objective", "subjective") or not clean(q.get("question")) or not clean(q.get("solution")):
            raise ValueError("A generated practice question is incomplete.")
        if q["type"] == "objective":
            opts = q.get("options", [])
            answer = q.get("correct_index")
            if not isinstance(opts, list) or not 2 <= len(opts) <= 6 or type(answer) is not int or not 0 <= answer < len(opts):
                raise ValueError("A practice question has an invalid answer key.")
    if not any(q["type"] == "objective" for q in questions):
        raise ValueError("The question bank needs objective questions.")
    if not isinstance(pkg.get("flashcards"), list) or not pkg["flashcards"]:
        raise ValueError("No revision cards were generated.")
    for card in pkg["flashcards"]:
        if not clean(card.get("front")) or not clean(card.get("back")):
            raise ValueError("A revision card is incomplete.")
    return pkg


def module_state(module):
    attempts = module.get("attempts", [])
    if attempts:
        recent = attempts[-3:]
        score = sum(a["correct"] for a in recent) / max(1, sum(a["total"] for a in recent))
        if score < .5:
            return "weak"
        if score >= .8 and len(attempts) >= 2 and sum(a["total"] for a in recent) >= 5:
            return "mastered"
        return "learning"
    return "learning" if module.get("read") else "unseen"


def grade(module, answers):
    questions = [q for q in module.get("package", {}).get("questions", []) if q["type"] == "objective"]
    if not questions:
        raise ValueError("This module has no objective practice yet.")
    if not isinstance(answers, dict) or any(q["id"] not in answers for q in questions):
        raise ValueError("Answer each question before checking your results.")
    results = []
    for q in questions:
        answer = answers[q["id"]]
        if type(answer) is not int or not 0 <= answer < len(q["options"]):
            raise ValueError("Choose a valid option for every question.")
        results.append(dict(id=q["id"], selected=answer, correct_index=q["correct_index"],
                            correct=answer == q["correct_index"], solution=q["solution"]))
    attempt = dict(date=now(), correct=sum(r["correct"] for r in results), total=len(results), results=results)
    module.setdefault("attempts", []).append(attempt)
    module["attempts"] = module["attempts"][-30:]
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
