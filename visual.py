"""Local visual triage, derived analysis PDFs, and original-page provenance.

Native text is never overwritten by model-recognized text. All PDFium work uses
the same lock as source previews, including local object inspection.
"""
from __future__ import annotations

import hashlib
import io
import ctypes
from collections import Counter

import pypdfium2 as pdfium
from PIL import ImageDraw

from pdfview import RENDER_LOCK
from scope import identity, string, strings

VISUAL_VERSION = "visual-scope-v1"
INSPECTION_VERSION = 2
MAX_BATCH_PAGES = 4
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_EDGE = 3200


def _document(source):
    return pdfium.PdfDocument(source if isinstance(source, bytes) else str(source))


def _bounds(obj, width, height):
    left, bottom, right, top = obj.get_bounds() if hasattr(obj,"get_bounds") else obj.get_pos()
    return [round(max(0, min(1, left/width)), 5), round(max(0, min(1, 1-top/height)), 5),
            round(max(0, min(1, right/width)), 5), round(max(0, min(1, 1-bottom/height)), 5)]


def _area(box):
    return max(0, box[2]-box[0]) * max(0, box[3]-box[1])


def _margin(box, edge=.18):
    # Slide decorations commonly cross the former strict 16% boundary.
    return box[3] <= edge or box[1] >= 1-edge


def _background_path(obj, box):
    """A page-sized solid fill is layout, not evidence of a diagram."""
    if _area(box) < .95 or pdfium.raw.FPDFPath_CountSegments(obj) > 5:
        return False
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    return bool(pdfium.raw.FPDFPath_GetDrawMode(obj, ctypes.byref(fill), ctypes.byref(stroke))
                and fill.value != pdfium.raw.FPDF_FILLMODE_NONE and not stroke.value)


def _visual_annotations(page, width, height):
    """Rendered stamps/free text can contain teaching absent from native extraction."""
    kinds = {pdfium.raw.FPDF_ANNOT_FREETEXT, pdfium.raw.FPDF_ANNOT_STAMP,
             pdfium.raw.FPDF_ANNOT_INK, pdfium.raw.FPDF_ANNOT_LINE,
             pdfium.raw.FPDF_ANNOT_SQUARE, pdfium.raw.FPDF_ANNOT_CIRCLE,
             pdfium.raw.FPDF_ANNOT_POLYGON, pdfium.raw.FPDF_ANNOT_POLYLINE}
    hidden = (pdfium.raw.FPDF_ANNOT_FLAG_HIDDEN | pdfium.raw.FPDF_ANNOT_FLAG_INVISIBLE |
              pdfium.raw.FPDF_ANNOT_FLAG_NOVIEW)
    for index in range(pdfium.raw.FPDFPage_GetAnnotCount(page)):
        annot = pdfium.raw.FPDFPage_GetAnnot(page, index)
        if not annot:
            continue
        try:
            if pdfium.raw.FPDFAnnot_GetSubtype(annot) not in kinds or pdfium.raw.FPDFAnnot_GetFlags(annot) & hidden:
                continue
            rect = pdfium.raw.FS_RECTF()
            if pdfium.raw.FPDFAnnot_GetRect(annot, ctypes.byref(rect)):
                box = [max(0,rect.left/width), max(0,1-rect.top/height),
                       min(1,rect.right/width), min(1,1-rect.bottom/height)]
                if _area(box) >= .002 and not _margin(box):
                    return True
        finally:
            pdfium.raw.FPDFPage_CloseAnnot(annot)
    return False


def _render(page, edge, masks=()):
    width, height = page.get_size()
    bitmap = page.render(scale=min(300/72, edge/max(width, height)))
    try:
        image = bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()
    if masks:
        draw = ImageDraw.Draw(image)
        for box in masks:
            pixels=[round(v * (image.width if i % 2 == 0 else image.height)) for i,v in enumerate(box)]
            # Cover the rasterizer's antialiased edge as well as the object bounds.
            draw.rectangle((pixels[0]-2,pixels[1]-2,pixels[2]+2,pixels[3]+2),fill="white")
    return image


def inspect_documents(docs, path_for, progress=lambda n, total: None, *, inspection_version=INSPECTION_VERSION):
    """No inference: inspect objects, repeated margin images and rendered ink.

    Geometry and repetition are heuristics, not semantic classification. The UI
    exposes every learning page for manual inclusion or exclusion.
    """
    if type(inspection_version) is not int or inspection_version not in (1, INSPECTION_VERSION):
        raise ValueError("Unsupported visual inspection version.")
    # Reproduce old metadata only when validating an existing backup. Recognition
    # manifests and render identities remain compatible across triage revisions.
    legacy = inspection_version == 1
    margin = lambda box: _margin(box, .16 if legacy else .18)
    rows = []
    total = sum(len(d["pages"]) for d in docs if d["role"] != "pyq")
    with RENDER_LOCK:
        for doc in docs:
            if doc["role"] == "pyq":
                continue
            document = _document(path_for(doc["id"]))
            try:
                for index, text in enumerate(doc["pages"]):
                    page = document[index]
                    try:
                        width, height = page.get_size()
                        images, paths = [], []
                        for number, obj in enumerate(page.get_objects(max_depth=6)):
                            if number >= 12000:
                                break
                            if obj.type not in (pdfium.raw.FPDF_PAGEOBJ_IMAGE, pdfium.raw.FPDF_PAGEOBJ_PATH):
                                continue
                            box = _bounds(obj, width, height)
                            if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                                # Small margin assets can be compared without decoding their pixels.
                                signature = hashlib.sha256(bytes(obj.get_data())).hexdigest() if _area(box) < .04 and margin(box) else None
                                images.append(dict(box=box, signature=signature))
                            else:
                                if legacy or not _background_path(obj, box):
                                    paths.append(box)
                        rows.append(dict(doc_id=doc["id"], page=index+1, digest=doc["digest"],
                                         native_characters=len(text.strip()), images=images, paths=paths))
                        if not legacy:
                            rows[-1]["visual_annotations"] = _visual_annotations(page, width, height)
                    finally:
                        page.close()
                    progress(len(rows), total)
            finally:
                document.close()
        repeats = Counter(signature for row in rows for signature in {im["signature"] for im in row["images"] if im["signature"]})
        for doc in docs:
            if doc["role"] == "pyq":
                continue
            document = _document(path_for(doc["id"]))
            try:
                for row in (r for r in rows if r["doc_id"] == doc["id"]):
                    row["masks"] = [im["box"] for im in row["images"] if im["signature"] and repeats[im["signature"]] >= 3]
                    meaningful = [im for im in row["images"] if im["box"] not in row["masks"] and
                                  not (_area(im["box"]) < .025 and margin(im["box"]))]
                    page = document[row["page"]-1]
                    try:
                        thumbnail = _render(page, 400, row["masks"])
                        histogram = thumbnail.convert("L").histogram()
                        ink = sum(histogram[:230])/max(1, thumbnail.width*thumbnail.height)
                        thumbnail.close()
                    finally:
                        page.close()
                    text = doc["pages"][row["page"]-1]
                    teaching_paths=[box for box in row["paths"] if not margin(box) and
                        (legacy or not (box[2]-box[0] > .8 and box[3]-box[1] < .01))]
                    drawing = len(teaching_paths) >= 4 and any(_area(box) > .005 for box in teaching_paths)
                    if ink < .0003 and not text.strip():
                        state, reason = "blank", "No substantial content detected in the rendered page."
                    elif meaningful:
                        state, reason = "candidate", "Scanned or text-bearing image content; review selection."
                    elif row.get("visual_annotations"):
                        state, reason = "candidate", "Visible PDF annotations may contain teaching absent from native text."
                    elif drawing:
                        state, reason = "candidate", "Vector drawing or diagram may add teaching scope."
                    elif "\ufffd" in text or (not text.strip() and ink >= .0003 and not row["images"]):
                        state, reason = "candidate", "Missing or damaged text extraction; inspect the original page."
                    elif row["images"]:
                        state, reason = "boilerplate", "Only small margin images or repeated logos detected; native text remains available."
                    else:
                        state, reason = "native", "Native text extraction is available."
                    row.update(state=state, reason=reason, selected=state == "candidate", ignored_images=len(row["images"])-len(meaningful))
                    row.pop("images"); row.pop("paths")
            finally:
                document.close()
    fingerprint = identity([VISUAL_VERSION, sorted((d["digest"], d["name"], d["role"]) for d in docs if d["role"] != "pyq")])
    result = dict(version=VISUAL_VERSION, fingerprint=fingerprint, pages=rows, batches={}, selection_reviewed=not any(r["selected"] for r in rows))
    if not legacy:
        result["inspection_version"] = inspection_version
    return result


def select_pages(visual, selected):
    if not isinstance(selected, list) or len(selected) > len(visual["pages"]):
        raise ValueError("Choose valid visual source pages.")
    if any(not isinstance(r, dict) or not isinstance(r.get("doc_id"), str) or type(r.get("page")) is not int for r in selected):
        raise ValueError("Choose actual physical PDF pages.")
    pairs = {(r["doc_id"], r["page"]) for r in selected}
    available = {(r["doc_id"], r["page"]) for r in visual["pages"]}
    if len(pairs) != len(selected) or not pairs <= available:
        raise ValueError("A selected visual page is invalid or duplicated.")
    for row in visual["pages"]:
        row["selected"] = (row["doc_id"], row["page"]) in pairs
    visual["selection_reviewed"] = True
    return visual


def render_selected(row, path, folder):
    folder.mkdir(parents=True, exist_ok=True)
    key = identity([VISUAL_VERSION, row["digest"], row["page"], row["masks"], MAX_EDGE, "jpeg92-pad2"])
    target = folder / (key + ".jpg")
    if not target.exists():
        with RENDER_LOCK:
            document = _document(path)
            try:
                page = document[row["page"]-1]
                try:
                    image = _render(page, MAX_EDGE, row["masks"])
                    try:
                        temporary=target.with_suffix(".jpg.tmp")
                        image.save(temporary, format="JPEG", quality=92)
                        temporary.replace(target)
                    finally:
                        image.close()
                finally:
                    page.close()
            finally:
                document.close()
    return target


def analysis_batches(visual, docs, path_for, folder, progress=lambda n,total:None):
    """Combine selected pages across PDFs. Exact rendered duplicates keep aliases."""
    from PIL import Image
    by_doc = {d["id"]: d for d in docs}
    unique, groups = {}, []
    total=sum(r["selected"] for r in visual["pages"]);done=0
    for row in visual["pages"]:
        if not row["selected"]:
            continue
        path = render_selected(row, path_for(row["doc_id"]), folder)
        done+=1;progress(done,total)
        image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        reference = dict(doc_id=row["doc_id"], page=row["page"], digest=row["digest"], role=by_doc[row["doc_id"]]["role"])
        if image_hash in unique:
            unique[image_hash]["aliases"].append(reference)
        else:
            item = dict(image_hash=image_hash, path=path, aliases=[reference])
            unique[image_hash] = item
            groups.append(item)
    # Stable ordering and portable IDs survive document-ID remapping on import.
    groups.sort(key=lambda item: (item["aliases"][0]["digest"], item["aliases"][0]["page"], item["image_hash"]))
    pending, results = [], []
    def write(items):
        manifest = [dict(index=i+1, image_hash=item["image_hash"], aliases=item["aliases"]) for i,item in enumerate(items)]
        key = identity([VISUAL_VERSION, [dict(image_hash=r["image_hash"], aliases=[{k:v for k,v in a.items() if k != "doc_id"} for a in r["aliases"]]) for r in manifest]])
        target = folder / (key + ".pdf")
        if not target.exists():
            images = [Image.open(item["path"]).convert("RGB") for item in items]
            try:
                temporary=target.with_suffix(".pdf.tmp")
                images[0].save(temporary, format="PDF", save_all=True, append_images=images[1:], resolution=300)
                temporary.replace(target)
            finally:
                for image in images:
                    image.close()
        if target.stat().st_size > MAX_PDF_BYTES:
            target.unlink()
            if len(items) == 1:
                raise ValueError("A visual page exceeds the analysis size limit. Upload a smaller source or clearer page export.")
            middle = len(items)//2
            write(items[:middle]); write(items[middle:])
            return
        results.append(dict(id=key, manifest=manifest, path=target))
    for item in groups:
        pending.append(item)
        if len(pending) == MAX_BATCH_PAGES:
            write(pending); pending=[]
    if pending:
        write(pending)
    return results


def validate_visual_response(value, batch):
    pages = value.get("pages") if isinstance(value, dict) else None
    expected = {r["index"]: r for r in batch["manifest"]}
    if not isinstance(pages, list) or len(pages) != len(expected) or any(not isinstance(p, dict) or type(p.get("index")) is not int for p in pages) or {p["index"] for p in pages} != set(expected):
        raise ValueError("Visual analysis must account for every combined-PDF page.")
    results, records = [], []
    for page in sorted(pages, key=lambda p:p["index"]):
        if page.get("status") not in ("mapped", "partial", "unresolved", "non_teaching"):
            raise ValueError("Invalid visual page status.")
        reason = string(page.get("reason"), 1200, empty=page["status"] == "mapped")
        recognized = string(page.get("recognized_text"), 20000, empty=True)
        description = string(page.get("visual_description"), 6000, empty=True)
        rows = page.get("records")
        if not isinstance(rows, list) or len(rows) > 24 or (page["status"] == "mapped" and not rows) or (page["status"] == "non_teaching" and rows):
            raise ValueError("Invalid visual teaching scope records.")
        clean_rows = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError("Invalid visual scope record.")
            clean = dict(title=string(row.get("title"),180), depth=string(row.get("depth")))
            for key in ("subtopics", "methods", "conventions", "uncertainties"):
                clean[key] = strings(row.get(key))
            clean_rows.append(clean)
            for alias_index, alias in enumerate(expected[page["index"]]["aliases"]):
                records.append(dict(clean, id="visual-"+batch["id"]+f"-{page['index']}-{index+1}-{alias_index+1}",
                                    doc_id=alias["doc_id"], pages=[alias["page"]], role=alias["role"],
                                    anchors=[], origin="visual_interpretation",
                                    visual_warning=reason if page["status"] in ("partial","unresolved") else ""))
        results.append(dict(index=page["index"], status=page["status"], reason=reason,
                            recognized_text=recognized, visual_description=description, records=clean_rows))
    return dict(manifest=batch["manifest"], pages=results, records=records)


def visual_records(visual):
    selected = {(r["doc_id"], r["page"]) for r in visual["pages"] if r["selected"]}
    return [dict(record) for batch in visual["batches"].values() for record in batch["records"]
            if (record["doc_id"],record["pages"][0]) in selected]


def page_results(visual):
    results = {}
    for batch in visual["batches"].values():
        for page in batch["pages"]:
            mapping = next(m for m in batch["manifest"] if m["index"] == page["index"])
            for alias in mapping["aliases"]:
                results[(alias["doc_id"],alias["page"])] = page
    return results


def visual_status(visual):
    results = page_results(visual)
    return [dict(doc_id=r["doc_id"],page=r["page"],status=results[(r["doc_id"],r["page"])]["status"],
                 reason=results[(r["doc_id"],r["page"])]["reason"]) if r["selected"] and (r["doc_id"],r["page"]) in results else
            dict(doc_id=r["doc_id"],page=r["page"],status="unresolved" if r["selected"] or r["state"]=="candidate" else "blank" if r["state"]=="blank" else "native",
                 reason="Visual content was not analyzed." if r["state"]=="candidate" else r["reason"]) for r in visual["pages"]]


def recognized_sources(docs, visual):
    """Common retrieval interface; recognized text never becomes a verified quote."""
    results = page_results(visual)
    selected = {(r["doc_id"],r["page"]) for r in visual["pages"] if r["selected"]}
    sources = []
    for doc in docs:
        result = dict(doc, pages=list(doc["pages"]), recognized_pages=[])
        for number in range(1,len(doc["pages"])+1):
            page = results.get((doc["id"],number))
            if page and (doc["id"],number) in selected:
                result["pages"][number-1] += "\n" + page["recognized_text"] + "\n" + page["visual_description"]
                result["recognized_pages"].append(number)
        sources.append(result)
    return sources


def validate_saved_visual(visual, docs, path_for):
    """Validate physical identities and schema, not recognition accuracy."""
    initial = inspect_documents(docs, path_for, inspection_version=visual.get("inspection_version",1) if isinstance(visual,dict) else 1)
    if not isinstance(visual, dict) or visual.get("version") != VISUAL_VERSION or visual.get("fingerprint") != initial["fingerprint"] or type(visual.get("selection_reviewed")) is not bool:
        raise ValueError("Invalid visual inspection in backup.")
    rows = visual.get("pages")
    if not isinstance(rows,list) or len(rows) != len(initial["pages"]):
        raise ValueError("Invalid visual page inventory.")
    expected = {(r["doc_id"],r["page"]):r for r in initial["pages"]}
    seen = set()
    for row in rows:
        pair = (row.get("doc_id"),row.get("page")) if isinstance(row,dict) else None
        if pair not in expected or pair in seen or type(row.get("selected")) is not bool or {k:v for k,v in row.items() if k != "selected"} != {k:v for k,v in expected[pair].items() if k != "selected"}:
            raise ValueError("Visual page metadata does not match the original PDFs.")
        seen.add(pair)
    batches = visual.get("batches")
    if not isinstance(batches,dict) or len(batches)>len(rows):
        raise ValueError("Invalid visual batches in backup.")
    by_doc = {d["id"]:d for d in docs}
    for key,batch in batches.items():
        manifest = batch.get("manifest") if isinstance(batch,dict) else None
        if not isinstance(manifest,list) or not 1<=len(manifest)<=MAX_BATCH_PAGES:
            raise ValueError("Invalid combined-PDF manifest.")
        aliases = set()
        for i,item in enumerate(manifest,1):
            if not isinstance(item,dict) or type(item.get("index")) is not int or item.get("index")!=i or not isinstance(item.get("image_hash"),str) or len(item["image_hash"])!=64 or not isinstance(item.get("aliases"),list) or not item["aliases"]:
                raise ValueError("Invalid combined-PDF page identity.")
            for alias in item["aliases"]:
                if not isinstance(alias,dict) or type(alias.get("page")) is not int or (alias.get("doc_id"),alias.get("page")) not in expected:
                    raise ValueError("Invalid original visual page reference.")
                pair=(alias["doc_id"],alias["page"])
                if pair in aliases or alias.get("digest")!=by_doc[alias["doc_id"]]["digest"] or alias.get("role")!=by_doc[alias["doc_id"]]["role"]:
                    raise ValueError("Invalid visual source identity.")
                aliases.add(pair)
        portable=[dict(image_hash=r["image_hash"],aliases=[{k:v for k,v in a.items() if k!="doc_id"} for a in r["aliases"]]) for r in manifest]
        if key!=identity([VISUAL_VERSION,portable]) or validate_visual_response(dict(pages=batch.get("pages")),dict(id=key,manifest=manifest))!=batch:
            raise ValueError("Invalid saved visual analysis.")
    if "model" in visual:
        import re
        if not isinstance(visual["model"],str) or not re.fullmatch(r"gemini-[a-zA-Z0-9.\-]+",visual["model"]):
            raise ValueError("Invalid visual model in backup.")
    return visual
