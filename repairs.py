"""Explicit, backed-up corrections to saved content. No model calls."""
import copy

from core import now, validate_package


def apply_corrections(store, course_id, patch):
    """Require original wording/title matches before touching a saved artifact."""
    with store.lock:
        course = store.course(course_id)
        repair_id = patch["id"]
        if any(r.get("id") == repair_id for r in course.get("corrections", [])):
            return course
        candidate = copy.deepcopy(course)
        allowed = {(d["id"], i+1) for d in store.docs(course_id) for i in range(len(d["pages"]))}
        for change in patch.get("modules", []):
            module = next(m for m in candidate["modules"] if m["id"] == change["id"])
            package = module["package"]
            for item in change.get("questions", []):
                question = next(q for q in package["questions"] if q["id"] == item["id"])
                if question["question"] != item["expected_question"]:
                    raise ValueError("Saved question changed since this correction was prepared.")
                if set(item["updates"]) - {"question", "options", "correct_index", "solution"}:
                    raise ValueError("Invalid question correction.")
                question.update(item["updates"])
            for item in change.get("sections", []):
                section = package["sections"][item["index"]]
                if section["title"] != item["expected_title"] or section["body"] != item["expected_body"]:
                    raise ValueError("Saved lesson changed since this correction was prepared.")
                section["body"] = item["body"]
            if change.get("notice"):
                package.setdefault("corrections", []).append(dict(change["notice"], date=now()))
            validate_package(package, allowed)
        if "document_coverage" in patch:
            coverage = patch["document_coverage"]
            docs = {d["id"] for d in store.docs(course_id) if d["role"] != "pyq"}
            mids = {m["id"] for m in candidate["modules"]}
            if {r["doc_id"] for r in coverage} != docs or any(mid not in mids for r in coverage for mid in r["module_ids"]):
                raise ValueError("Invalid reviewed document coverage.")
            candidate["document_coverage"] = coverage
        if "source_annotations" in patch:
            if any((n["doc_id"],n["page"]) not in allowed for n in patch["source_annotations"]):
                raise ValueError("A source clarification points to a missing page.")
            candidate["source_annotations"] = patch["source_annotations"]
        backup = store.backup(course_id, "before-correction")
        candidate.setdefault("corrections", []).append(dict(id=repair_id, date=now(), message=patch["message"], backup=backup.name))
        store.save(candidate)
        return candidate
