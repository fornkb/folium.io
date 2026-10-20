"""Explicit, sequential, resumable Gemini preparation with page-aware local retrieval."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

from core import clean, now, safe_text, validate_outline, validate_package
from configuration import Settings
from prompts import VERSION, SYSTEM, OUTLINE_INSTRUCTIONS, PLAN_INSTRUCTIONS, LESSON_INSTRUCTIONS


S = {"type": "STRING"}
I = {"type": "INTEGER"}
def array(item):
    return {"type": "ARRAY", "items": item}
def obj(props):
    return {"type": "OBJECT", "properties": props, "required": list(props)}

REF = obj(dict(doc_id=S, page=I))
OUTLINE = obj(dict(description=S, modules=array(obj(dict(id=S, title=S, description=S,
    topics=array(S), prerequisites=array(S)))), document_coverage=array(obj(dict(doc_id=S, module_ids=array(S), notes=S)))))
TEACHING_PLAN = obj(dict(overview=S, objectives=array(S), lessons=array(obj(dict(
    id=S, title=S, topics=array(S), concepts=array(S), gaps=array(S))))))
PACKAGE = obj(dict(overview=S, objectives=array(S), sections=array(obj(dict(title=S, body=S,
                  kind={"type": "STRING", "enum": ["concept", "example", "formula", "pitfall", "recap"]}, sources=array(REF)))),
                  diagrams=array(obj(dict(title=S, nodes=array(S), layout={"type":"STRING", "enum":["flow","cycle","comparison"]}))),
                  questions=array(obj(dict(type={"type":"STRING", "enum":["objective","subjective"]},
                          question=S, options=array(S), correct_index=I, solution=S, topic=S, difficulty=S))),
                  flashcards=array(obj(dict(front=S, back=S))), coverage_notes=S))
PYQ_SCHEMA = obj(dict(questions=array(obj(dict(question=S, module_ids=array(S), year=S,
                                             number=S, marks=S, solution=S)))))


class ProviderError(Exception):
    pass


class Gemini:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.lock = threading.Lock()
        self.last_call = 0
        self.key_pool = ()
        self.next_key = 0

    def generate(self, prompt, schema, validator=lambda x: x):
        settings = self.settings.get()
        cache_key = hashlib.sha256(json.dumps([VERSION, settings["model"], SYSTEM, prompt, schema], sort_keys=True).encode()).hexdigest()
        cached = self.store.cached(cache_key)
        if cached is not None:
            return validator(cached)
        payload = dict(contents=[dict(role="user", parts=[dict(text=prompt)])],
                       systemInstruction=dict(parts=[dict(text=SYSTEM)]),
                       generationConfig=dict(temperature=.3, maxOutputTokens=24000,
                                             responseMimeType="application/json", responseSchema=schema))
        with self.lock:
            time.sleep(max(0, settings["interval"] - (time.monotonic() - self.last_call)))
            # A waiting job must not reuse a key removed while it was queued.
            keys = tuple(self.settings.get()["api_keys"])
            if not keys:
                raise ProviderError("Add a Gemini API key in Settings, then resume preparation.")
            if keys != self.key_pool:
                self.key_pool, self.next_key = keys, 0
            req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/" + settings["model"] + ":generateContent",
                                         data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type":"application/json", "x-goog-api-key": keys[self.next_key]})
            # Only outgoing attempts consume a turn, including failed attempts.
            self.next_key = (self.next_key + 1) % len(keys)
            try:
                self.last_call = time.monotonic()
                with urllib.request.urlopen(req, timeout=240) as response:
                    result = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code in (500, 502, 503, 504):
                    raise ProviderError("Gemini is temporarily busy or unavailable. Completed lessons are saved. Wait a moment, then select Resume.") from None
                if exc.code == 429:
                    raise ProviderError("Gemini's free quota or rate limit was reached. Completed work is saved. Wait for your quota to reset, then select Resume.") from None
                if exc.code in (401, 403):
                    raise ProviderError("Gemini rejected a configured key or model access. Check your keys and the free-tier model in Settings.") from None
                if exc.code == 404:
                    raise ProviderError("This Gemini model is unavailable. Choose a model available to your project in Settings.") from None
                raise ProviderError(f"Gemini returned HTTP {exc.code}. Completed work is saved; resume to retry.") from None
            except (TimeoutError, OSError):
                raise ProviderError("Gemini could not be reached. Check your connection, then resume. Completed work is saved.") from None
        try:
            candidate = result["candidates"][0]
            if candidate.get("finishReason") not in (None, "STOP"):
                raise ValueError("The response was interrupted or blocked.")
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
            value = validator(json.loads(text))
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ValueError("Gemini did not return a usable study package. Resume to retry this unfinished stage.") from exc
        self.store.cache(cache_key, value)
        return value


STOP = set("the and of to in a an for with is are on from by as at this that into it its module topic introduction".split())
def words(text):
    return [w for w in re.findall(r"[a-zA-Z0-9]{2,}", text.lower()) if w not in STOP]


def source_pages(docs, query=None, budget=65000):
    pages = [dict(doc_id=d["id"], name=d["name"], page=i+1, text=p)
             for d in docs if d["role"] != "pyq" for i,p in enumerate(d["pages"]) if p.strip()]
    if query:
        terms = Counter(words(query))
        def relevance(p):
            counts = Counter(words(p["text"]))
            title_terms = set(words(p["name"]))
            return (sum(min(5, counts[t]) * weight for t,weight in terms.items()) + sum(4 * w for t,w in terms.items() if t in title_terms)) / max(1, len(p["text"]) / 4000) ** .3
        pages.sort(key=relevance, reverse=True)
    else:
        # Reserve a fair share for EVERY readable file, independently of upload order.
        groups = []
        for d in sorted(docs, key=lambda d: d["id"]):
            dp = [p for p in pages if p["doc_id"] == d["id"]]
            if not dp:
                continue
            count = min(len(dp), 18)
            indexes = sorted({round(i * (len(dp)-1) / max(1, count-1)) for i in range(count)})
            groups.append((d, [dp[i] for i in indexes]))
        weight = sum(2 if d["role"] == "syllabus" else 1 for d,_ in groups)
        selected = []
        remaining = budget
        for index, (doc, sample) in enumerate(groups):
            share = min(remaining, budget * (2 if doc["role"] == "syllabus" else 1) // max(1, weight))
            # Allocate across the full document rather than spend its share on page one.
            per_page = share // len(sample)
            for p in sample:
                excerpt = safe_text(p["text"])[:min(9000, per_page)]
                if excerpt:
                    selected.append({**p, "text": excerpt})
                    remaining -= len(excerpt)
        return selected
    selected, used = [], 0
    for p in pages:
        if used >= budget:
            break
        excerpt = safe_text(p["text"])[:min(9000, budget-used)]
        selected.append({**p, "text": excerpt})
        used += len(excerpt)
    return selected


def format_pages(pages):
    return "\n\n".join(f"[SOURCE doc_id={p['doc_id']} page={p['page']} file={p['name']}]\n{p['text']}\n[/SOURCE]" for p in pages)


def document_inventory(docs):
    inventory = []
    for d in docs:
        if d["role"] == "pyq":
            continue
        headings = []
        # A bounded heading inventory gives every file a voice even outside excerpts.
        step = max(1, len(d["pages"]) // 16)
        for i in range(0, len(d["pages"]), step):
            lines = [safe_text(s).strip() for s in d["pages"][i].splitlines() if len(s.strip()) > 3]
            if lines:
                headings.append(dict(page=i+1, heading=" / ".join(lines[:2])[:180]))
            if len(headings) == 16:
                break
        inventory.append(dict(doc_id=d["id"], file=d["name"], role=d["role"], pages=len(d["pages"]), headings=headings))
    return json.dumps(inventory, ensure_ascii=True)


def validate_plan(value, topics):
    lessons = value.get("lessons", [])
    if not isinstance(lessons, list) or not 1 <= len(lessons) <= 8:
        raise ValueError("The teaching plan needs 1–8 focused lessons. Resume to retry planning.")
    assigned = []
    ids = set()
    for lesson in lessons:
        lid = lesson.get("id")
        if not isinstance(lid, str) or not re.fullmatch(r"l[1-8]", lid) or lid in ids or not clean(lesson.get("title")):
            raise ValueError("The teaching plan contains an invalid lesson.")
        ids.add(lid)
        for key in ("topics", "concepts", "gaps"):
            if not isinstance(lesson.get(key), list) or not all(isinstance(x, str) and x.strip() for x in lesson[key]):
                raise ValueError("The teaching plan has an invalid coverage checklist.")
        if not lesson["topics"] or not lesson["concepts"]:
            raise ValueError("Every lesson needs topics and a concept checklist.")
        assigned.extend(lesson["topics"])
    if Counter(assigned) != Counter(topics):
        raise ValueError("The teaching plan omitted or duplicated a required topic. Resume to retry.")
    if not clean(value.get("overview")) or not isinstance(value.get("objectives"), list) or not value["objectives"]:
        raise ValueError("The teaching plan needs an overview and objectives.")
    return value


def course_context(course):
    return json.dumps([dict(title=m["title"], topics=m["topics"]) for m in course["modules"]])


def reviewed_notes(course, module):
    notes = [n for n in course.get("source_annotations", []) if module["id"] in n.get("module_ids", [])]
    return "\nREVIEWED SOURCE CLARIFICATIONS (local audit; distinguish these from the original notes and flag the source conflict):\n" + json.dumps(notes) if notes else ""


class Jobs:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.active = set()
        self.lock = threading.Lock()
        for c in store.courses():
            if c.get("job", {}) and c["job"].get("state") == "running":
                c["job"].update(state="paused", message="Preparation was interrupted. Resume to continue saved work.")
                store.save(c)

    def start(self, course_id, action):
        course = self.store.course(course_id)
        if course.get("demo"):
            raise ValueError("The sample course is already prepared.")
        if action not in ("outline", "generate"):
            raise ValueError("Unknown preparation stage.")
        if not self.store.docs(course_id):
            raise ValueError("Upload course PDFs first.")
        if action == "generate" and not course["modules"]:
            raise ValueError("Prepare and review the outline first.")
        if action == "generate" and course["status"] == "ready":
            return course
        if action == "outline" and course["modules"]:
            return course
        with self.lock:
            if course_id in self.active:
                return course
            self.active.add(course_id)
        self._status(course_id, "running", "outline" if action == "outline" else "lessons", "Preparing your course…")
        threading.Thread(target=self._run, args=(course_id, action), daemon=True).start()
        return self.store.course(course_id)

    def _status(self, cid, state, stage, message, done=0, total=1):
        def update(c):
            c["job"] = dict(state=state, stage=stage, message=message, done=done, total=total, updated=now())
        self.store.update(cid, update)

    def _run(self, cid, action):
        try:
            if action == "outline":
                self._outline(cid)
            else:
                self._packages(cid)
            self._status(cid, "complete", action, "Your outline is ready to review." if action == "outline" else "Your course is ready. Everything is saved locally.", 1, 1)
        except (ProviderError, ValueError) as exc:
            current = self.store.course(cid).get("job") or {}
            self._status(cid, "paused", current.get("stage", action), str(exc), current.get("done", 0), current.get("total", 1))
        except Exception:
            self._status(cid, "paused", action, "Preparation stopped unexpectedly. Your completed work is safe. Resume to retry.")
        finally:
            with self.lock:
                self.active.discard(cid)

    def _outline(self, cid):
        course = self.store.course(cid)
        docs = self.store.docs(cid)
        pages = source_pages(docs)
        if not pages:
            raise ValueError("Upload readable learning materials or a syllabus, not only exam papers.")
        prompt = OUTLINE_INSTRUCTIONS.format(title=course["title"]) + "\nDOCUMENT INVENTORY\n" + document_inventory(docs) + "\n\n" + format_pages(pages)
        def validate(value):
            value["modules"] = validate_outline(value.get("modules"))
            value["description"] = clean(value.get("description"), 500)
            ids = {m["id"] for m in value["modules"]}
            coverage = value.get("document_coverage", [])
            expected = {d["id"] for d in docs if d["role"] != "pyq"}
            if not isinstance(coverage, list) or len(coverage) != len(expected) or {r.get("doc_id") for r in coverage} != expected:
                raise ValueError("The outline did not account for every document. Resume to retry.")
            for row in coverage:
                if not isinstance(row.get("module_ids"), list) or any(mid not in ids for mid in row["module_ids"]) or (not row["module_ids"] and not clean(row.get("notes"))):
                    raise ValueError("The outline needs a valid document coverage map.")
                row["supplied_pages"] = [p["page"] for p in pages if p["doc_id"] == row["doc_id"]]
            return value
        result = self.provider.generate(prompt, OUTLINE, validate)
        def save(c):
            c.update(modules=result["modules"], description=result["description"], status="outline", document_coverage=result["document_coverage"], generation_version=VERSION)
        self.store.update(cid, save)

    def _packages(self, cid):
        course = self.store.course(cid)
        docs = self.store.docs(cid)
        missing = sum(not m.get("package") for m in course["modules"])
        done = len(course["modules"]) - missing
        total = len(course["modules"])
        for module in course["modules"]:
            if module.get("package"):
                continue
            self._status(cid, "running", "planning", "Planning " + module["title"], done, total)
            pages = source_pages(docs, module["title"] + " " + " ".join(module["topics"]))
            if not pages:
                raise ValueError("No readable learning material is available for this module.")
            preparation = module.get("preparation") or dict(version=VERSION, lessons={})
            if not preparation.get("plan"):
                prompt = PLAN_INSTRUCTIONS.format(module=module["title"], topics=json.dumps(module["topics"]), context=course_context(course)) + reviewed_notes(course,module) + "\n" + format_pages(pages)
                preparation["plan"] = self.provider.generate(prompt, TEACHING_PLAN, lambda x: validate_plan(x, module["topics"]))
                self.store.update(cid, lambda c: next(m for m in c["modules"] if m["id"] == module["id"]).update(preparation=preparation))
            plan = preparation["plan"]
            for index, lesson in enumerate(plan["lessons"]):
                if lesson["id"] in preparation["lessons"]:
                    continue
                self._status(cid, "running", "lessons", f"{module['title']} · lesson {index+1}/{len(plan['lessons'])}: {lesson['title']}", done, total)
                lesson_pages = source_pages(docs, module["title"] + " " + " ".join(lesson["topics"] + lesson["concepts"]))
                allowed = {(p["doc_id"], p["page"]) for p in lesson_pages}
                prompt = LESSON_INSTRUCTIONS.format(module=module["title"], lesson=lesson["title"], topics=json.dumps(lesson["topics"]), concepts=json.dumps(lesson["concepts"]), gaps=json.dumps(lesson["gaps"]), plan=json.dumps(plan), context=course_context(course)) + reviewed_notes(course,module) + "\n\n" + format_pages(lesson_pages)
                def validate(value):
                    value = validate_package(value, allowed)
                    if any(q.get("topic") not in lesson["topics"] for q in value["questions"]):
                        raise ValueError("A practice question was not mapped to an assigned topic. Resume to retry this lesson.")
                    for topic in lesson["topics"]:
                        if not any(q["type"] == "objective" and q["topic"] == topic for q in value["questions"]):
                            raise ValueError("A lesson is missing practice for a required topic. Resume to retry.")
                    if any(not s.get("sources") for s in value["sections"] if s["kind"] != "recap" and not (s["kind"] == "pitfall" and value.get("coverage_notes"))):
                        raise ValueError("A teaching section needs a supplied source citation. Resume to retry.")
                    return value
                lesson_pkg = self.provider.generate(prompt, PACKAGE, validate)
                lesson_pkg["source_pages"] = [dict(doc_id=p["doc_id"], page=p["page"]) for p in lesson_pages]
                preparation["lessons"][lesson["id"]] = lesson_pkg
                self.store.update(cid, lambda c: next(m for m in c["modules"] if m["id"] == module["id"]).update(preparation=preparation))
            pkg = dict(overview=plan["overview"], objectives=plan["objectives"], teaching_plan=plan, sections=[], diagrams=[], questions=[], flashcards=[], source_pages=[], coverage_notes="", coverage_map=[], generation_version=VERSION)
            gaps = []
            for lesson in plan["lessons"]:
                part = preparation["lessons"][lesson["id"]]
                start = len(pkg["sections"])
                pkg["sections"].extend(dict(s, lesson_id=lesson["id"], lesson_title=lesson["title"]) for s in part["sections"])
                pkg["diagrams"].extend(dict(d, lesson_id=lesson["id"]) for d in part.get("diagrams", []))
                for key in ("questions", "flashcards", "source_pages"):
                    pkg[key].extend(part.get(key, []))
                if part.get("coverage_notes"):
                    gaps.append(part["coverage_notes"])
                gaps.extend(lesson["gaps"])
                pkg["coverage_map"].extend(dict(topic=t, lesson=lesson["title"], section=start) for t in lesson["topics"])
            pkg["coverage_notes"] = "\n\n".join(dict.fromkeys(gaps))
            annotations = [n for n in course.get("source_annotations", []) if module["id"] in n.get("module_ids", [])]
            if annotations:
                pkg["corrections"] = [dict(message=n["message"], url=n.get("url", "")) for n in annotations]
            pkg["source_pages"] = [dict(doc_id=doc, page=page) for doc,page in sorted({(r["doc_id"], r["page"]) for r in pkg["source_pages"]})]
            validate_package(pkg, {(p["doc_id"],p["page"]) for p in pkg["source_pages"]})
            def save(c, mid=module["id"], package=pkg):
                target = next(m for m in c["modules"] if m["id"] == mid)
                target["package"] = package
                target.pop("preparation", None)
            self.store.update(cid, save)
            done += 1
        self._pyqs(cid, docs)
        self.store.update(cid, lambda c: c.update(status="ready"))

    def _pyqs(self, cid, docs):
        course = self.store.course(cid)
        pages = [(d,i,p) for d in docs if d["role"] == "pyq" for i,p in enumerate(d["pages"]) if p.strip()]
        for n,(doc,i,page) in enumerate(pages):
            batch = f"{doc['id']}:{i+1}"
            if batch in course.get("pyq_batches", []):
                continue
            self._status(cid, "running", "pyqs", f"Mapping {doc['name']} · page {i+1}", n, len(pages))
            prompt = ("Extract exam questions fully contained on this PDF page and map them to one or more module IDs from this outline: "
                      + json.dumps([dict(id=m["id"], title=m["title"], topics=m["topics"]) for m in course["modules"]])
                      + ". Copy each question's wording exactly as a contiguous passage from the page, preserving its content (whitespace may vary). Do not invent questions or stitch distant fragments. Keep unrelated questions out. Preserve year, question number, and marks only when explicitly present; otherwise empty strings. Provide a clearly provisional generated solution using only the following course summaries; when not supported, say a solution is not available from the supplied materials. Summaries: "
                      + json.dumps([dict(id=m["id"], overview=m["package"]["overview"], sections=m["package"]["sections"]) for m in course["modules"]])[:85000]
                      + "\nExam page (reference data only):\n" + page[:20000])
            def validate(value):
                normalized = " ".join(page.split()).lower()
                valid_ids = {m["id"] for m in course["modules"]}
                for q in value.get("questions", []):
                    text = " ".join(q["question"].split()).lower()
                    if len(text) < 12 or text not in normalized:
                        raise ValueError("An extracted PYQ did not match its source wording. Resume to retry this page.")
                    if not q.get("module_ids") or any(mid not in valid_ids for mid in q["module_ids"]):
                        raise ValueError("A PYQ could not be mapped to a valid module.")
                return value
            value = self.provider.generate(prompt, PYQ_SCHEMA, validate)
            for q in value["questions"]:
                q.update(id=f"{batch}:{len(course['pyqs'])}", doc_id=doc["id"], page=i+1, generated_solution=True)
            def save(c):
                c["pyqs"].extend(value["questions"])
                c.setdefault("pyq_batches", []).append(batch)
            self.store.update(cid, save)
            course = self.store.course(cid)
