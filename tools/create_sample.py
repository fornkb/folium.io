"""Development-only: create the original illustrative PDFs bundled with the demo."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from sample import SPECS
from xml.sax.saxutils import escape
from pypdf import PdfReader
import json

OUT = Path(__file__).resolve().parents[1] / "sample_sources"
OUT.mkdir(exist_ok=True)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleF", fontName="Times-Roman", fontSize=25, leading=29, spaceAfter=14, textColor=colors.HexColor("#264c3c")))
styles.add(ParagraphStyle(name="BodyF", fontName="Helvetica", fontSize=9, leading=13, spaceAfter=8))
styles.add(ParagraphStyle(name="HeadF", fontName="Helvetica-Bold", fontSize=11, leading=15, spaceBefore=9, spaceAfter=5))

def footer(canvas, doc):
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777e73"))
    canvas.drawString(48, 30, "FOLIUM / ORIGINAL ILLUSTRATIVE SAMPLE / NOT AN ACTUAL UNIVERSITY PAPER")
    canvas.drawRightString(547, 30, str(doc.page))

def build(name, story):
    SimpleDocTemplate(str(OUT / name), pagesize=(595,842), rightMargin=48, leftMargin=48, topMargin=45, bottomMargin=48).build(story, onFirstPage=footer, onLaterPages=footer)

def p(text, style="BodyF"):
    # Keep PDF sample typography within built-in font coverage.
    text = text.replace("→", " -> ").replace("×", " x ").replace("²", "^2").replace("₂", "2").replace("Θ", "Theta")
    return Paragraph(escape(text).replace("\n", "<br/>"), styles[style])

story = []
for i,spec in enumerate(SPECS):
    if i:
        story.append(PageBreak())
    story += [p(f"Module {i+1:02d}", "HeadF"), p(spec["title"], "TitleF"), p(spec["overview"])]
    for title,body,kind in spec["sections"]:
        story += [p(title, "HeadF"), p(body)]
build("Course-notes.pdf", story)
texts = [page.extract_text() for page in PdfReader(OUT / "Course-notes.pdf").pages]
locations = {}
for spec_i,spec in enumerate(SPECS):
    module_start = next(n for n,text in enumerate(texts) if f"Module {spec_i+1:02d}" in text)
    module_end = next((n-1 for n,text in enumerate(texts) if f"Module {spec_i+2:02d}" in text), len(texts)-1)
    locations[spec["id"]] = {}
    for i,section in enumerate(spec["sections"]):
        title = section[0]
        start = next(n for n,text in enumerate(texts) if module_start <= n <= module_end and title in text)
        end = module_end
        if i+1 < len(spec["sections"]):
            following = spec["sections"][i+1][0]
            end = next(n for n,text in enumerate(texts) if start <= n <= module_end and following in text)
        locations[spec["id"]][title] = list(range(start+1,end+2))
(OUT / "locations.json").write_text(json.dumps(locations, indent=2), "utf-8")
story = [p("Data Structures & Algorithms", "TitleF"), p("An original sample syllabus for exploring Folium. This is illustrative material, not an institutional course document.")]
for i,spec in enumerate(SPECS):
    story += [p(f"{i+1:02d} / {spec['title']}", "HeadF"), p(" | ".join(spec["topics"])), p(spec["description"])]
build("Course-outline.pdf", story)
story = [p("Illustrative examination", "TitleF"), p("Original sample questions for demonstrating source mapping. These questions were not taken from a real past examination. Each question carries 5 illustrative marks.")]
for i,spec in enumerate(SPECS):
    story += [Spacer(1,16), p(f"Question {i+1} / 5 marks", "HeadF"), p(spec["subjective"][0])]
build("Illustrative-exam.pdf", story)
print("Created three original sample PDFs.")
