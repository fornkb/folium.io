# Folium development instructions

This is the local-first Folium study app. The parent project's `sources/` and synced files are read-only. Work only in this repository.

## Product contract
- A course is created from the user's PDFs, not a hardcoded subject.
- Review the editable syllabus before explicitly starting full generation.
- Persist uploaded PDFs, extracted page text, outlines, lessons, questions, PYQs, notes, attempts, and revision state on disk.
- Reading, navigating, taking saved quizzes, revealing solutions, and reviewing flashcards must never call an AI API.
- Generate only missing artifacts. Persist every successful AI response and stage before continuing. Failed/quota-limited jobs must be resumable without repeating completed work.
- Never silently regenerate saved material. Keep model keys server-side, exclude them from Git and exports, and never log them.
- Distinguish uploaded PYQs from AI practice, original solutions from generated solutions, reading completion from assessed mastery, and missing evidence from supported explanations.
- Citations must resolve to stored document IDs and actual PDF page numbers. Never invent source references.
- The sample course is explicitly labeled and requires no key.

## Implementation
- Python 3.10+ local server, SQLite, local files, pypdf, PDFium/Pillow page previews, and buildless HTML/CSS/JavaScript. Bind to loopback only.
- Do not introduce hosted services, paid APIs, telemetry, remote fonts, or runtime CDN dependencies.
- Accessible keyboard navigation, responsive layouts, readable lessons, restrained colors, and clear loading/error/empty states.
- Validate model JSON on the server and escape all generated/user text in the browser. Do not render arbitrary AI HTML.
- Keep source selection bounded and page-aware; identify incomplete coverage. No promise that every generated answer is verified.

## Checkpoints and verification
- Commit after each major completed checkpoint with a descriptive message.
- Update PLAN.md as checkpoints land and document material limitations in README.md.
- Run `python -m unittest discover -s tests -v` for backend changes, plus browser checks for major user flows.
- Meaningful tests should cover persistent caching/resumption, citation validation, upload validation, quiz scoring, and backup round trips.
- Do not commit runtime data, API credentials, local logs, or personal course materials.
