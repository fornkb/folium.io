# Folium

A local-first study companion that turns your course PDFs into a connected course map, detailed lessons, source-linked past questions, practice quizzes, and flashcards. Prepare a course once, then study its saved content without further AI calls.

## Features

- Review and edit an AI-proposed syllabus before preparing lessons.
- Explore modules and prerequisites on a course map with zoom, pan, and progress indicators.
- Study focused lessons with worked examples and offline mathematical typesetting.
- Open citations at the original PDF page, with both image and extracted-text views.
- Prepare practice and revision cards separately from saved teaching, then study them offline.
- Practise objective questions with instant scoring, or reveal solutions for subjective questions.
- Keep personal notes, review spaced-repetition cards, and track recall separately from reading completion.
- Export and import complete course backups, including the original PDFs and saved progress.

## Run locally

Requires **Python 3.10 or newer**. No frontend build or package installation is needed for the browser interface.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open [Folium](http://127.0.0.1:8765) in your browser. On Windows, you can also use `start.bat` after installing the dependencies. Keep the server running while using the app. Closing it leaves your saved courses on disk.

A fresh installation starts with an empty library. Sample courses and personal course materials are not distributed in the repository.

### Connect Gemini

Create a `.env` file beside `app.py`, using `.env.example` as a template. Add your key locally:

```dotenv
GEMINI_API_KEY=your_key_here
```

You can configure up to three keys in the app's Settings. For `.env` or environment configuration, use `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, and `GEMINI_API_KEY_3`; corresponding `GOOGLE_API_KEY` names are also supported. The extra slots are optional. Select a Gemini model available to your project in Settings. Folium has no automatic paid-model fallback; model access and free-tier quotas depend on your Google project.

Lesson writing defaults to `gemini-3.8-flash` (`GEMINI_MODEL`). Scope discovery and merging, outlines, lesson planning, assessments, cards, and past-paper extraction/mapping default to `gemini-3.5-flash-lite` (`GEMINI_TASK_MODEL`). Settings exposes both choices. Legacy unfinished combined teaching/practice lessons still use the lesson-writing model. Model changes apply to missing work; saved artifacts are reused, and response caches distinguish models.

`GEMINI_VISION_MODEL` optionally selects the model for explicitly requested visual scope analysis of learning PDFs. A vision model saved in Settings takes precedence; otherwise the environment/file value is used, falling back to the other-task model when unset (`gemini-3.5-flash-lite` by default). Changes apply to missing visual batches, preserving completed recognition. This does not enable scanned past-paper transcription.

A key saved in Settings takes precedence over environment configuration for that slot. Otherwise, process environment variables take precedence over `.env`; the `GEMINI_API_KEY` name takes precedence over the corresponding `GOOGLE_API_KEY` name. Leave a field blank to preserve its current key. Removing a saved key restores that slot's environment fallback, if present. The app rereads `.env` when configuration is needed. Refresh the browser after editing it to update the connection indicators.

Outgoing Gemini requests rotate through distinct configured keys in slot order, then repeat. Empty slots are skipped and duplicate keys are used once. Cached results make no request and do not advance the rotation. Rotation is shared across course jobs in the running server and starts at the first available slot after a restart or a key change. The request interval still applies globally. A quota/rate-limit response (HTTP 429) consumes its turn and tries the remaining distinct configured keys once, respecting the global interval. If all are exhausted, preparation pauses for explicit resume. Other provider failures still pause immediately; there is no endless retry loop. Keys belonging to the same Google project share its quotas, so rotation does not increase that project's allowance.

Keys stay on the server and are excluded from course exports. Configuration and course files are stored locally, so other users with access to those files can read them. Never commit a real key.

### Optional startup settings

```powershell
python app.py --port 8766
python app.py --data-dir "C:\path\to\folium-data"
python app.py --env-file "C:\path\to\.env"
```

The server listens on `127.0.0.1` only. The default port is `8765`; `FOLIUM_PORT` can also set it.

## Prepare and study a course

1. Create a course and upload PDFs, identifying each as a syllabus, learning material, or past paper.
2. Inspect visual pages locally. Review the suggested scan/diagram selection and explicitly analyze it, or exclude it. Then prepare scope and outline; review topics, depth, conventions, unresolved pages, exclusions, prerequisites, and physical PDF source ranges.
3. Start lesson preparation. Successful teaching plans and individual lessons are saved as they finish. Once a module is saved, choose **Explore ready modules** to read it while the remaining modules generate. Keep the local server running; navigation and reading do not start another AI request.
4. Open a module to study. When wanted, explicitly choose **Generate practice & cards** from Practice or Flashcards. Uploaded past papers have their own explicit preparation action in Past papers.
5. Export a course ZIP when you want a portable backup. Import it into another local installation to restore it.

The ready-module map has its own saved URL and survives browser reloads. Unfinished modules lead to preparation; a progress notice shows background work and provides a way back to setup. New module arrivals and completion update the reader's status without replacing its teaching or notes editor.

**Delete course** is available on library cards and course pages. Confirming deletion first saves a complete recovery ZIP in `data/backups`, then removes the course, document records, study state, summaries, original workspace PDFs, and derived previews. The deletion notice links to the recovery download; restore it with **Import course**. Deletion is blocked while a preparation job is active, and a failed recovery backup leaves the course intact. Existing backups and the shared provider-response cache remain local; deletion removes the active workspace rather than erasing every historical copy.

New outlines treat modules as broad course units and lessons as their focused subdivisions. The outline prompt chooses the smallest coherent set, combines overlapping native/visual accounts, and consolidates overlapping goals and example-only or supporting modules before returning. Definitions, notation, rule structure and worked applications of the same idea stay together, with their required depth preserved. No fixed module count is imposed across subjects. Outline requests use their own prompt version, so refining structure does not invalidate other stages' response caches. Lesson counts follow the module's distinct learning goals; a single lesson can cover several related topics. Teaching uses a natural nonempty section list, with detailed central reasoning and proportionate supporting definitions. These are generation instructions, not a guarantee of a particular module count or improved content quality. Saved outlines, plans, and lessons remain unchanged when prompts are updated.

For new courses, preparation first processes all readable learning text into saved scope records. Batches are bounded to 24,000 text characters and 24 segments, prefer available section boundaries, split dense pages without dropping their tails, remove exact repeated boundary boilerplate, and share analysis of exact duplicate pages while retaining every physical location. Empty and damaged-text pages remain visibly unresolved. PYQs use a separate path.

Scope records retain subtopics, expected depth, methods, conventions, uncertainty, physical locations, and optional exact source anchors. Large catalogues are merged in saved stages with explicit input-to-output lineage. The outline must assign every scope record to a module or give an exclusion reason. Source ranges are derived on the server and editable; they can span multiple PDFs. Review and save the outline before explicitly starting lessons, acknowledging unresolved pages where present. Per-module clarifications let you correct expected scope/depth without altering extracted text.

During scope discovery, an optional quotation that fails exact whitespace-normalized matching is omitted and shown as a scope-review warning instead of pausing the entire batch. Its wording is never treated as verified or used as an exact anchor; source locations and the remaining scope still require review. Backup validation continues to reject invalid saved quotations. PDF extraction can join words or lose symbols, so a readable page is not a guarantee of faithful notation. The known pypdf invalid-object-reference warnings are grouped into one console summary per PDF read; other parser warnings and errors remain visible.

Teaching uses one plan request per unfinished module and one request per focused lesson (one to eight lessons per module). Plans use approved scope instead of repeating raw PDFs; each lesson receives its assigned scope records and up to 12,000 characters of selected original passages/anchors from approved module ranges. Retrieval excludes zero-match filler and can find text beyond the start of a page. Exact source anchors get priority. Retrieval uses overlapping passages with natural boundaries and merges only adjacent/overlapping intervals from the same page, so quotations are not broken solely by a fixed window edge. Legacy planning is bounded to 24,000 source characters and each legacy lesson to 12,000. Every approved scope record must be assigned to a lesson. Oversized module packets ask you to split the module before starting generation.

New teaching requests contain only explanations, worked examples, learning objectives, and coverage notes. The short teaching prompt asks for approachable language, detailed central reasoning, useful concrete examples, and course-appropriate scope and notation. Bounded extracts of earlier saved lessons and available prerequisite teaching provide continuity; these extracts are incomplete context, not a guarantee of consistent notation. No diagrams are requested in the new teaching schema. Previously saved diagrams remain readable.

Practice and cards are optional and use a separate prompt and schema: one request per saved lesson, with its complete teaching text as input. They are generated together in that later stage, with no additional PDF retrieval or teaching regeneration. Successful practice batches are saved independently; a pause, restart, or course backup/import resumes only unfinished lessons. Each batch is tied to the saved teaching by a content hash. Structural validation enforces four distinct objective options, valid answer keys, and coverage of assigned topics; it does not establish answer correctness. Uploaded-paper mapping is also separate, using a request per readable paper page. It sends the module/topic map and concise reviewed conventions, not a dump of generated lessons. The full readable page is sent up to a 30,000-character safety limit; oversized pages pause with a clear message instead of silently dropping the tail. Past-paper coverage lists unreadable/sparse/damaged pages and links to their originals. Scans still require a searchable replacement; there is no automatic OCR fallback. Questions spanning pages may remain missing.

This initial scope pass may require more requests than the former sampled outline. Total savings depend on course size, repeated lesson context, output length, and provider quotas. No cost or completeness guarantee is made. Successful raw provider responses and available usage metadata are cached locally before validation; validated batches, merges, plans, and lessons resume independently. Backups preserve scope stages, source mappings, review state, and unfinished generation.

On explicit resume, a complete saved raw response is checked with the current validator before making another request. It is reused only if validation succeeds. Truncated, blocked, malformed, or still-invalid responses require a fresh request; there is no automatic retry loop. Provider-cache recovery is local to the workspace and is not included in course ZIPs.

If preparation pauses because of a quota, connection failure, or restart, resume it explicitly. Completed stages are reused. Existing saved lessons are preserved when prompts change; improved prompts apply to newly generated content. Unfinished legacy jobs retain their combined-package schema and reuse their completed lessons. Reading, navigation, quizzes, solution reveals, notes, and card reviews make **no AI requests**.

## Data and privacy

By default, SQLite records, uploaded PDFs, provider-response caches, settings, and backups live under `data/`. They are excluded from Git, along with `.env`, local demo assets, temporary output, and development notes. Only the root README is tracked as Markdown. Tests generate small synthetic documents at runtime and need no sample PDFs or API key.

Notes, reading flags, bookmarks, attempts, and card schedules are stored in separate per-module study rows. Normal study actions do not rewrite saved lesson/scope JSON and return only a small state update. Older databases remain readable: embedded study state is overlaid with newer study rows, and backups export the combined current state. The library uses a persisted compact course index (including saved cards for offline revision), and full teaching loads when opening a course. Job polling uses compact status responses and fetches full content when saved artifacts or completion state change. PDF page counts and text-availability counts are stored separately, with an index on document course ownership.

Text extraction, local visual inspection and PDF previews run on your computer. Explicit visual analysis sends only selected derived page images and bounded surrounding text to Gemini. Preparing the outline sends usable learning text in bounded scope batches, followed by scope records and selected excerpts for planning and teaching. Course ZIPs include your uploaded materials, recognition and notes, but exclude API credentials; share them only with intended recipients.

## Limitations

- Readable and scanned PDFs are accepted. Visual recognition uses the separately selected Gemini vision model after explicit page-selection review. A standalone local OCR engine and searchable-PDF export are not included. Scanned PYQ transcription remains separate, unimplemented work; image-only paper pages are saved but not automatically converted into questions.
- Citations use physical PDF page numbers. Valid source locations and coverage maps do not establish that every AI-generated statement is correct or every source detail is covered.
- Processing every extracted segment is not proof of semantic completeness. Diagrams, tables, reading order, and damaged notation can need manual review even on pages with usable text. Model uncertainty is a review signal, not a calibrated confidence score. Human topic-recall and cost/latency benchmarks remain outstanding.
- Scope-based lessons label generated teaching separately from exact original-text excerpts. Topic-location links identify where topics occur, not evidence verifying expanded explanations. Stored legacy courses and unfinished legacy jobs retain their existing source selection; saved lessons are never silently regenerated or migrated.
- AI-generated practice and past-paper solutions are labeled. Uploaded-paper frequency reflects the papers you provided and does not predict future exams.
- Objective answers use saved answer keys and deterministic scoring. Subjective questions provide solutions for self-review, without automatic grading.
- Recall estimates depend on distinct answered questions, topic coverage, and first-encounter/recent results. Repeating a small question bank does not establish mastery.
- This local prototype has no accounts, live tutor chat, cloud synchronization, or hosted multi-user service.

## Development

### Scope-driven teaching and visual recognition

The PDFs and reviewed syllabus should define what the course teaches, its depth, and its notation. Gemini may explain those topics using its general knowledge, derivations, and generated examples, without reproducing the notes or requiring an excerpt for every explanation. Source-specific claims and original past-paper wording still need faithful extraction. Links that locate a topic in the materials must be distinguished from citations supporting a particular claim.

Scope-driven teaching supports new readable, scanned, and mixed courses. Local PDFium inspection checks rendered ink, image placement, repeated small margin assets, damaged text, vector drawings, and visible teaching annotations such as stamps and free text. It tolerates slide decorations crossing the header/footer boundary and excludes solid page backgrounds and thin page-wide rules from diagram evidence. These are selection heuristics, not semantic proof: manually include a missed page or exclude an irrelevant one before analysis. Repeated small header/footer images are masked only in derived recognition copies; native text and original PDF bytes are preserved. Small margin images alone do not trigger recognition.

Inspection is deterministic, so uploading identical PDFs again normally produces the same suggestions. Before scope preparation, **Re-inspect pages** runs local inspection again instead of returning the cached inventory; it refreshes unreviewed suggestions while preserving already-reviewed selections and successful analysis batches. Existing backups retain their original inspection rules during validation, so revised suggestions do not invalidate saved recognition. Re-inspection makes no AI request.

Selected pages from all learning PDFs are combined into derived analysis PDFs, with at most four unique rendered pages and 8 MB per batch. Exact rendered duplicates share analysis while retaining their original document/page aliases. Recognition renders are capped at 3200 pixels on their longest edge; tiny notation and poor scans may remain unreadable. Each combined-PDF index maps back to originals on the server. The vision response supplies bounded recognized text, visual descriptions, page status, and scope records. Successful results are saved independently and reused after quota pauses, restarts, and backup restoration. Raw model responses and usage metadata use the same local provider cache and key rotation as teaching. There is no automatic model escalation or paid fallback.

Visual scope records join native-text scope records before outline generation; already analyzed visual content does not require another scope-extraction request. Subsequent module/lesson planning uses the same reviewed scope pipeline. A common retrieval interface adds saved recognition to native text without overwriting it. Recognition and visual interpretations are explicitly unverified and cannot be labeled as verified original-text quotations. Partial, skipped, and unresolved teaching visuals remain visible for scope review. Page selection locks once scope preparation starts, preserving existing outlines and lessons; create a new course to add new visual analysis to a saved legacy course.

Saved combined PDFs can be opened from course setup and reconstructed locally after import, without model requests. Derived renders/PDFs are disposable caches rather than additional ZIP entries: original PDFs, inspection/selection metadata, batch manifests, recognition, and scope records are all preserved in backups. Local Tesseract/OCRmyPDF integration, handwritten/notation accuracy benchmarks, and empirical cost/latency evaluation remain future work. Recognition cannot recover detail that is absent from the original scan.

The backend uses Python's HTTP server, SQLite, pypdf, PDFium, and Pillow. The frontend is buildless HTML, CSS, and JavaScript with locally bundled KaTeX.

| File | Purpose |
| --- | --- |
| `app.py` | Local HTTP server and API routes |
| `core.py` | Persistence, validation, backups, and practice scoring |
| `configuration.py` | Environment and local configuration loading |
| `generation.py` | Gemini requests, retrieval, caching, and resumable jobs |
| `scope.py` | Full-text batching, scope validation, coverage, review, and portable lineage |
| `visual.py` | Local page triage, logo filtering, combined analysis PDFs, and unverified recognition |
| `prompts.py` | Outline and teaching instructions |
| `pdfview.py` | Local PDF page previews |
| `repairs.py` | Reviewed corrections with backups |
| `web/` | Course map, study reader, practice, and settings interface |
| `tests/` | Backend and reader regression checks |

Run backend checks with the Python dependencies installed:

```powershell
python -m unittest discover -s tests -v
```

Run reader checks with Node.js installed; no npm dependencies are required:

```powershell
node tests/test_reader.mjs
node tests/test_notes.mjs
```

The notes regression controls network completion order to check that a slower earlier save cannot overwrite a newer edit. Reader checks include mathematics late in long wrapped paragraphs. Original paper extraction and answer-option validation preserve case-sensitive notation such as `A` versus `a`; textual distinctness does not establish that options are mathematically inequivalent.

### Teaching prompt evaluation

Export a small synthetic comparison suite without reading personal courses, loading keys, or making provider requests:

```powershell
python tools/teaching_evaluation.py --output tmp/teaching-evaluation.json
```

The five cases cover a derivation, a conceptual explanation, a procedure, sparse notes, and an ambiguous convention. The export contains the current prompt, schema, expected features, and a human scoring rubric. Record the selected model, prompt version, token/request counts, failures, and human judgments when testing variants. Review the rendered lessons as well as their text. Automated persistence and formatting checks do not establish teaching quality; no real-model comparison or reduction in error rate has yet been measured for this change.

The provider leaves sampling parameters at the model defaults, following Google's current guidance. Raw output, available usage metadata, and finish reasons are retained for interrupted responses, but truncated text is never accepted as a complete lesson or silently repaired.

The prompt design follows Google's [clear instructions and task decomposition guidance](https://ai.google.dev/gemini-api/docs/prompting-strategies) and [sequential prompting guidance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/prompts/break-down-prompts). Concrete examples and worked explanations are informed by the IES [instruction and study practice guide](https://ies.ed.gov/ncee/wwc/PracticeGuide/1). These sources motivate the design; they do not validate a particular generated lesson.

## Third-party attribution

[KaTeX](https://katex.org/) 0.19.0 is bundled from its official npm distribution for offline math rendering. Its MIT license is retained in [web/vendor/katex/LICENSE](web/vendor/katex/LICENSE). The browser script, stylesheet, and required fonts are served locally without a runtime CDN.
