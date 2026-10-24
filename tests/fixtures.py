"""Small synthetic fixtures; no course files or API requests are needed."""
import copy
import io
import json
from functools import lru_cache

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from core import validate_package


TEST_MODULES = [
    dict(id=f"m{i+1}", title="Complexity" if i == 0 else f"Module {i+1}",
         description="Synthetic test module.", topics=["Topic A", "Topic B"],
         prerequisites=[f"m{i}"] if i else [])
    for i in range(6)
]
SECTION_TITLES = ("Core concept", "Formal definition", "Worked example")


def scope_fixture(prompt):
    data = json.loads(prompt.split("\n")[-1])
    indexes = list(range(len(data["segments"])))
    return dict(records=[dict(title="Complexity", subtopics=["Topic A", "Topic B"], depth="Compute and explain growth rates.",
                             methods=["Compare cases"], conventions=[], uncertainties=[], segment_indexes=indexes, anchors=[])],
                segments=[dict(index=i, status="mapped", reason="") for i in indexes])


@lru_cache(maxsize=2)
def pdf_fixture(kind="notes"):
    """Build actual, renderable PDF pages in memory using a runtime dependency."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for i in range(6 if kind == "notes" else 1):
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        lines = [f"Complexity - synthetic {kind} page {i+1}", *SECTION_TITLES,
                 "Topic A and Topic B provide enough readable text for extraction tests."]
        stream = DecodedStreamObject()
        commands = ["BT /F1 12 Tf 72 760 Td"]
        for line in lines:
            commands.append(f"({line}) Tj 0 -24 Td")
        commands.append("ET")
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def lesson_fixture(spec, doc_id, page):
    """Exercise package structure, citations, diagrams, and both question types."""
    ref = dict(doc_id=doc_id, page=page)
    questions = [
        dict(type="objective", question=f"Select option {i+1}.",
             options=["First", "Second", "Third", "Fourth"], correct_index=i,
             solution=f"The requested option is {i+1}.",
             topic=spec["topics"][i % len(spec["topics"])], difficulty="Core")
        for i in range(4)
    ]
    questions.append(dict(type="subjective", question="Describe the test process.",
                          options=[], correct_index=-1, solution="Read, apply, and review.",
                          topic=spec["topics"][0], difficulty="Apply"))
    package = dict(
        overview="Synthetic lesson for persistence and validation tests.",
        objectives=["Apply the test process."],
        sections=[dict(title=title, body="Synthetic explanation for regression checks.",
                       kind=kind, sources=[dict(ref)])
                  for title, kind in zip(SECTION_TITLES, ("concept", "formula", "example"))],
        diagrams=[dict(title="Test process", nodes=["Read", "Apply", "Review"])],
        questions=questions,
        flashcards=[dict(front=f"Step {i+1}?", back=step)
                    for i, step in enumerate(("Read", "Apply", "Review"))],
        coverage_notes="", source_pages=[dict(ref)],
    )
    return validate_package(package, {(doc_id, page)})


def seed_test_course(store):
    course = store.create("Test fixture", demo=True)
    doc = store.add_pdf(course["id"], "fixture.pdf", "material", pdf_fixture())
    for i, spec in enumerate(TEST_MODULES):
        module = copy.deepcopy(spec)
        module["package"] = lesson_fixture(spec, doc["id"], i+1)
        course["modules"].append(module)
    course["status"] = "ready"
    store.save(course)
    return course
