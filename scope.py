"""Local, durable scope preparation. No network or study-time inference lives here."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

SCOPE_VERSION = "scope-v1"
BATCH_CHARS = 24000
CATALOGUE_CHARS = 60000


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def prepare_sources(docs, budget=BATCH_CHARS):
    """Visit every native-text character; splitting a dense page never drops its tail.

    Only exact repeated boundary lines are removed. Empty pages remain unresolved:
    without inspecting the image we cannot call them blank. Duplicate pages retain
    their own physical identity and share the representative page's scope records.
    """
    inventory, batches = [], []
    for doc in sorted((d for d in docs if d["role"] != "pyq"), key=lambda d: d["id"]):
        lines = [p.splitlines() for p in doc["pages"]]
        boundary = Counter(line.strip() for rows in lines for line in set(rows[:1] + rows[-1:])
                           if line.strip() and len(line.strip()) < 160)
        repeated = {line for line, count in boundary.items() if count >= max(3, (len(lines) + 1) // 2)}
        seen, segments, page_rows = {}, [], []
        for number, text in enumerate(doc["pages"], 1):
            rows = text.splitlines()
            kept = [line for i, line in enumerate(rows)
                    if not (i in (0, len(rows)-1) and line.strip() in repeated)]
            cleaned = "\n".join(kept).strip()
            # Do not erase a page consisting solely of a repeated heading.
            cleaned = cleaned or text.strip()
            signature = identity(cleaned)
            duplicate = seen.get(signature) if cleaned else None
            state = "unresolved" if not cleaned else "suspect" if "\ufffd" in cleaned else "readable"
            page_rows.append(dict(page=number, state=state, characters=len(cleaned),
                                  duplicate_of=duplicate, headings=[s.strip()[:180] for s in kept[:2] if s.strip()]))
            if not cleaned or duplicate:
                continue
            seen[signature] = number
            # Prefer paragraph/line boundaries; retain every character between splits.
            start = 0
            while start < len(cleaned):
                end = min(start + budget, len(cleaned))
                if end < len(cleaned):
                    boundary_at = cleaned.rfind("\n", start + budget // 2, end)
                    if boundary_at > start:
                        end = boundary_at + 1
                segments.append(dict(page=number, start=start, end=end, text=cleaned[start:end]))
                start = end
        pending, used = [], 0
        def flush():
            if not pending:
                return
            key = identity([SCOPE_VERSION, doc["digest"], doc["name"], doc["role"], pending])
            batches.append(dict(id=key, doc_id=doc["id"], name=doc["name"], role=doc["role"],
                                segments=list(pending)))
        for segment in segments:
            heading = segment["text"].lstrip().splitlines()[0] if segment["text"].strip() else ""
            section_start = bool(re.match(r"^(chapter|unit|module|\d+\.\d+)\s", heading, re.I))
            if pending and (len(pending) >= 24 or used + len(segment["text"]) > budget or (section_start and used > budget // 2)):
                flush()
                pending, used = [], 0
            pending.append(segment)
            used += len(segment["text"])
        flush()
        for page in page_rows:
            page["expected_segments"] = sum(s["page"] == page["page"] for s in segments)
        inventory.append(dict(doc_id=doc["id"], name=doc["name"], role=doc["role"], pages=page_rows))
    fingerprint = identity([SCOPE_VERSION, sorted(b["id"] for b in batches),
                            sorted((d["digest"], d["role"], d["name"]) for d in docs if d["role"] != "pyq")])
    return dict(version=SCOPE_VERSION, fingerprint=fingerprint, inventory=inventory,
                batches={}, merges={}, complete=False), batches


def string(value, maximum=1200, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError("A scope record has missing or oversized text. Resume to retry.")
    return value.strip()


def strings(value, maximum=20):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("A scope checklist is invalid. Resume to retry.")
    return [string(v, 500) for v in value]


def anchor_warning(page):
    return (f"An optional source quotation could not be matched to the extracted text on physical page "
            f"{page}; it was omitted. Check important notation against the original PDF.")


def validate_batch(value, batch, *, strict_anchors=True):
    if not isinstance(value, dict) or not isinstance(value.get("records"), list) or len(value["records"]) > 24:
        raise ValueError("The scope response needs bounded topic records.")
    expected = set(range(len(batch["segments"])))
    decisions = value.get("segments")
    if not isinstance(decisions, list) or len(decisions) != len(expected):
        raise ValueError("The scope response omitted a source segment. Resume to retry.")
    indexes = [r.get("index") for r in decisions if isinstance(r, dict)]
    if any(type(i) is not int for i in indexes) or set(indexes) != expected:
        raise ValueError("The scope response has an invalid segment index.")
    records = []
    for index, record in enumerate(value["records"]):
        if not isinstance(record, dict):
            raise ValueError("Invalid scope record.")
        refs = record.get("segment_indexes")
        if not isinstance(refs, list) or not refs or any(type(i) is not int or i not in expected for i in refs):
            raise ValueError("A scope location is outside the supplied batch.")
        result = dict(id=batch["id"] + "-" + str(index+1), title=string(record.get("title"), 180),
                      depth=string(record.get("depth"), 1200), doc_id=batch["doc_id"],
                      pages=sorted({batch["segments"][i]["page"] for i in refs}), segment_indexes=sorted(set(refs)))
        for key in ("subtopics", "methods", "conventions", "uncertainties"):
            result[key] = strings(record.get(key))
        # This metadata is created locally, never supplied by the discovery model.
        warnings = record.get("anchor_warnings", []) if strict_anchors else []
        if (not isinstance(warnings, list) or len(warnings) > 6 or
                any(not isinstance(w, dict) or type(w.get("page")) is not int or w["page"] not in result["pages"]
                    or w != dict(page=w["page"], reason=anchor_warning(w["page"])) for w in warnings)):
            raise ValueError("Invalid saved scope anchor warning.")
        warnings = list(warnings)
        # Optional anchors must never become invented quotes. During discovery a
        # failed quote is omitted and flagged for review; imports remain strict.
        anchors = record.get("anchors")
        if not isinstance(anchors, list) or len(anchors) > 6:
            raise ValueError("Invalid scope source anchors.")
        result["anchors"] = []
        for anchor in anchors:
            if not isinstance(anchor, dict) or type(anchor.get("segment_index")) is not int or anchor["segment_index"] not in refs:
                raise ValueError("Invalid scope anchor location.")
            quote = string(anchor.get("quote"), 600)
            segment = batch["segments"][anchor["segment_index"]]
            if " ".join(quote.split()) not in " ".join(segment["text"].split()):
                if strict_anchors:
                    raise ValueError("A scope anchor did not match the original text.")
                warning = dict(page=segment["page"], reason=anchor_warning(segment["page"]))
                if warning not in warnings:
                    warnings.append(warning)
                continue
            result["anchors"].append(dict(page=segment["page"], quote=quote))
        if warnings:
            result["anchor_warnings"] = warnings
        records.append(result)
    for row in decisions:
        status = row.get("status")
        if status not in ("mapped", "non_teaching", "unresolved"):
            raise ValueError("Invalid scope segment status.")
        row["reason"] = string(row.get("reason"), 600, empty=status == "mapped")
        has_record = any(row["index"] in r["segment_indexes"] for r in records)
        if status == "mapped" and not has_record:
            raise ValueError("A mapped segment has no scope record.")
        if status == "non_teaching" and has_record:
            raise ValueError("A segment cannot be both excluded and mapped.")
    return dict(records=records, segments=decisions)


def records_for(scope):
    records = []
    for key, batch in sorted(scope.get("batches", {}).items()):
        for record in batch["records"]:
            record = dict(record)
            doc = next((d for d in scope["inventory"] if d["doc_id"] == record["doc_id"]), None)
            aliases = [p["page"] for p in doc["pages"] if p.get("duplicate_of") in record["pages"]] if doc else []
            record["pages"] = sorted(set(record["pages"] + aliases))
            records.append(record)
    return records + [dict(r) for r in scope.get("visual_records", [])]


def catalogue_record(record):
    result = {k: record[k] for k in ("id", "title", "subtopics", "depth", "methods", "conventions", "uncertainties")}
    if record.get("anchor_warnings"):
        result["uncertainties"] = result["uncertainties"] + [w["reason"] for w in record["anchor_warnings"]]
    for key in ("doc_id", "role", "source_roles", "origin", "visual_warning"):
        if key in record:
            result[key] = record[key]
    return result


def catalogue(records):
    return json.dumps([catalogue_record(r) for r in records], ensure_ascii=False)


def merge_identity(records):
    # Document IDs change on backup import; scope record IDs and content do not.
    portable = [{k: v for k, v in catalogue_record(r).items() if k != "doc_id"} for r in records]
    return identity([portable, [r.get("leaf_ids", [r["id"]]) for r in records]])


def validate_merge(value, inputs, key):
    rows = value.get("records") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not rows or len(rows) > 24:
        raise ValueError("Invalid merged scope catalogue.")
    by_id = {r["id"]: r for r in inputs}
    assigned, results = [], []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Invalid merged scope record.")
        ids = row.get("record_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(rid, str) or rid not in by_id for rid in ids):
            raise ValueError("A merged scope record has an unknown input.")
        assigned.extend(ids)
        result = dict(id="merge-" + key + "-" + str(i+1), title=string(row.get("title"), 180),
                      depth=string(row.get("depth")), record_ids=list(ids),
                      leaf_ids=sorted({leaf for rid in ids for leaf in by_id[rid].get("leaf_ids", [rid])}))
        result["source_roles"] = sorted({role for rid in ids for role in by_id[rid].get("source_roles", [by_id[rid].get("role", "material")])})
        for field in ("subtopics", "methods", "conventions", "uncertainties"):
            result[field] = strings(row.get(field))
        results.append(result)
    if Counter(assigned) != Counter(by_id.keys()):
        raise ValueError("A scope merge omitted or duplicated an input record.")
    if len(catalogue(results)) >= len(catalogue(inputs)) * .85:
        raise ValueError("The scope merge did not reduce its size. Resume to retry.")
    return results


def ranges_for(records):
    pairs = sorted({(r["doc_id"], p) for r in records for p in r["pages"]})
    ranges = []
    for doc_id, page in pairs:
        if ranges and ranges[-1]["doc_id"] == doc_id and ranges[-1]["end_page"] == page-1:
            ranges[-1]["end_page"] = page
        else:
            ranges.append(dict(doc_id=doc_id, start_page=page, end_page=page))
    return ranges


def validate_ranges(ranges, docs):
    lengths = {d["id"]: len(d["pages"]) for d in docs if d["role"] != "pyq"}
    if not isinstance(ranges, list) or len(ranges) > 2000:
        raise ValueError("Invalid module source ranges.")
    result = []
    for row in ranges:
        if not isinstance(row, dict) or row.get("doc_id") not in lengths or type(row.get("start_page")) is not int or type(row.get("end_page")) is not int or not 1 <= row["start_page"] <= row["end_page"] <= lengths[row["doc_id"]]:
            raise ValueError("A module range must use actual learning-PDF pages.")
        result.append({k: row[k] for k in ("doc_id", "start_page", "end_page")})
    return result


def review_outline(course, modules, exclusions, docs):
    """Validate the saved review without making any inference request."""
    records = {r["id"]: r for r in records_for(course["scope"])}
    mapped = set()
    for module in modules:
        ids = module.get("scope_ids")
        if not isinstance(ids, list) or any(not isinstance(rid, str) or rid not in records for rid in ids):
            raise ValueError("Select valid scope records for every module.")
        module["scope_ids"] = list(dict.fromkeys(ids))
        module["source_ranges"] = validate_ranges(module.get("source_ranges"), docs)
        if not ids or not module["source_ranges"]:
            raise ValueError("Every module needs scope records and source ranges before generation.")
        for rid in ids:
            record = records[rid]
            if not all(any(row["doc_id"] == record["doc_id"] and row["start_page"] <= p <= row["end_page"] for row in module["source_ranges"]) for p in record["pages"]):
                raise ValueError("Module ranges must include the selected scope records' pages.")
        mapped.update(ids)
        module["scope_notes"] = string(module.get("scope_notes", ""), 12000, empty=True)
    if not isinstance(exclusions, list):
        raise ValueError("Scope exclusions need a reason.")
    excluded = []
    for row in exclusions:
        if not isinstance(row, dict) or row.get("scope_id") not in records or row["scope_id"] in excluded or row["scope_id"] in mapped:
            raise ValueError("A scope record must be mapped or excluded, not both.")
        string(row.get("reason"), 1200)
        excluded.append(row["scope_id"])
    if mapped | set(excluded) != set(records):
        raise ValueError("Some scope records are unmapped. Assign them to a module or explain their exclusion.")
    return modules


def review_signature(modules, exclusions, fingerprint):
    return identity([fingerprint, [{k: m.get(k) for k in ("id", "title", "topics", "prerequisites", "scope_ids", "source_ranges", "scope_notes")} for m in modules], exclusions])


def module_packet(course, module, lesson_ids=None):
    ids = set(module.get("scope_ids", []) if lesson_ids is None else lesson_ids)
    records = [r for r in records_for(course["scope"]) if r["id"] in ids]
    packet = dict(module=module["title"], topics=module["topics"], reviewed_notes=module.get("scope_notes", ""),
                  records=[catalogue_record(r) for r in records],
                  source_ranges=module["source_ranges"] if lesson_ids is None else ranges_for(records))
    # Do not silently truncate a packet that cannot fit the planning budget.
    if len(json.dumps(packet)) > 90000:
        raise ValueError("This module has too much scope for one plan. Split it into smaller modules in the outline.")
    return packet


def coverage(scope):
    pages = [p for d in scope["inventory"] for p in d["pages"]]
    processed = Counter((b["doc_id"], s["page"]) for b in scope["batches"].values() for s in b.get("manifest", []))
    unresolved = []
    visual = {(r["doc_id"],r["page"]):r for r in scope.get("visual_status",[])}
    for doc in scope["inventory"]:
        for page in doc["pages"]:
            representative = page.get("duplicate_of") or page["page"]
            issues = [row["reason"] for b in scope["batches"].values() if b["doc_id"] == doc["doc_id"]
                      for row in b["segments"] if row["status"] == "unresolved"
                      and b["manifest"][row["index"]]["page"] == representative]
            issues += [issue for b in scope["batches"].values() if b["doc_id"] == doc["doc_id"]
                       for r in b["records"] if representative in r["pages"] for issue in r["uncertainties"]]
            issues += [w["reason"] for b in scope["batches"].values() if b["doc_id"] == doc["doc_id"]
                       for r in b["records"] for w in r.get("anchor_warnings", []) if w["page"] == representative]
            v=visual.get((doc["doc_id"],page["page"]))
            visual_done = v and v["status"] in ("mapped","non_teaching","blank")
            if v and v["status"] in ("partial","unresolved"):
                issues.append(v["reason"] or "Visual content is unresolved.")
            if (page["state"] in ("unresolved", "suspect") and not visual_done) or issues:
                unresolved.append(dict(doc_id=doc["doc_id"], page=page["page"], reason="; ".join(issues) or
                                       ("No extracted text; page may be blank, scanned, or visual." if page["state"] == "unresolved" else "Extraction contains damaged symbols.")))
    done = 0
    for doc in scope["inventory"]:
        by_page = {p["page"]: p for p in doc["pages"]}
        for page in doc["pages"]:
            representative = by_page[page.get("duplicate_of") or page["page"]]
            expected = representative["expected_segments"]
            v=visual.get((doc["doc_id"],page["page"]))
            done += bool((expected and processed[(doc["doc_id"], representative["page"])] == expected) or (v and v["status"] in ("mapped","partial","non_teaching","blank")))
    non_teaching = [dict(doc_id=b["doc_id"], page=b["manifest"][row["index"]]["page"], reason=row["reason"])
                    for b in scope["batches"].values() for row in b["segments"] if row["status"] == "non_teaching"]
    return dict(total_pages=len(pages), processed_pages=done, unresolved=unresolved, non_teaching=non_teaching,
                records=len(records_for(scope)), complete=scope.get("complete", False))


def validate_saved_scope(scope, docs):
    """Validate portable batch manifests against the actual PDF bytes on import."""
    initial, batches = prepare_sources(docs)
    if not isinstance(scope, dict) or scope.get("version") != initial["version"] or scope.get("fingerprint") != initial["fingerprint"] or sorted(scope.get("inventory", []), key=lambda d: d["doc_id"]) != initial["inventory"]:
        raise ValueError("The backup scope does not match its PDFs.")
    expected = {b["id"]: b for b in batches}
    saved = scope.get("batches")
    if not isinstance(saved, dict) or any(key not in expected for key in saved):
        raise ValueError("Invalid scope batches in backup.")
    for key, result in saved.items():
        batch = expected[key]
        manifest = [{k: s[k] for k in ("page", "start", "end")} for s in batch["segments"]]
        if not isinstance(result, dict) or result.get("doc_id") != batch["doc_id"] or result.get("manifest") != manifest:
            raise ValueError("Invalid scope page manifest in backup.")
        raw_records = []
        for r in result.get("records", []):
            if not isinstance(r, dict) or not isinstance(r.get("segment_indexes"), list) or any(type(i) is not int or not 0 <= i < len(batch["segments"]) for i in r["segment_indexes"]):
                raise ValueError("Invalid saved scope segment index.")
            raw = dict(r)
            raw["anchors"] = []
            for anchor in r.get("anchors", []):
                index = next((i for i in r["segment_indexes"] if batch["segments"][i]["page"] == anchor["page"]
                              and " ".join(anchor["quote"].split()) in " ".join(batch["segments"][i]["text"].split())), None)
                if index is None:
                    raise ValueError("Invalid saved scope anchor.")
                raw["anchors"].append(dict(segment_index=index, quote=anchor["quote"]))
            raw_records.append(raw)
        validated = validate_batch(dict(records=raw_records, segments=result.get("segments")), batch)
        for record in validated["records"]:
            record["role"] = batch["role"]
        if validated["records"] != result["records"]:
            raise ValueError("Invalid saved scope locations or records.")
    if type(scope.get("complete")) is not bool or scope["complete"] != (len(saved) == len(expected)):
        # A pause after the final batch can precede the complete marker.
        if scope.get("complete") is not False:
            raise ValueError("Invalid scope completion state.")
    known = {r["id"]: r for r in records_for(scope)}
    merges = scope.get("merges")
    if not isinstance(merges, dict) or len(merges) > 10000:
        raise ValueError("Invalid scope merges in backup.")
    pending = dict(merges)
    while pending:
        progress = False
        for key, rows in list(pending.items()):
            if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or not isinstance(r.get("record_ids"), list) for r in rows):
                raise ValueError("Invalid saved scope merge.")
            ids = list(dict.fromkeys(rid for r in rows for rid in r["record_ids"]))
            if any(rid not in known for rid in ids):
                continue
            inputs = [known[rid] for rid in ids]
            # Reconstruct original input order (record order may differ after merging).
            ordered = sorted(inputs, key=lambda r: r["id"])
            expected_key = merge_identity(ordered)
            if key != expected_key or validate_merge(dict(records=rows), ordered, key) != rows:
                raise ValueError("Invalid saved scope merge lineage.")
            known.update({r["id"]: r for r in rows})
            del pending[key]
            progress = True
        if not progress:
            raise ValueError("Unknown or cyclic scope merge lineage.")
    return scope
