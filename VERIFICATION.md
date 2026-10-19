# Verification record

## Automated checks
Run: `python -m unittest discover -s tests -v`.

Latest result: **46 Python tests passed**, plus the Node reader suite. The teaching-depth checkpoint adds order-independent document sampling, Unicode recovery with a pre-migration database backup, required-topic plan validation, independent lesson resumption (including backup/import), preserved packages on course extension, unique-question assessment evidence, atomic/idempotent content corrections, and a numerical check of the teleportation correction orders.

The reader suite checks Markdown headings, mixed lists, tables, step spacing, offline fraction/matrix typesetting, escaping of HTML/script payloads, rejection of unsafe math links, and canonical answer indices under shuffled presentation.

Follow-up browser checks use an isolated copy of the real course: full-map fit, real long module titles, source page 5's formerly broken Unicode text, shuffled options, topic filtering, correct subset scoring and first-encounter tracking, backed-up course extension, and the reader at 390 pixels without horizontal overflow. No browser warnings/errors were observed in these flows. The user's course history is untouched by QA.

The suite covers local PDF extraction, upload deduplication and rollback, prerequisite validation, source-page validation, practice answer keys and scoring, reading versus mastery, flashcard schedules, durable provider caching after reopening storage, quota handling, interrupted-job recovery, generation resumption without repeating completed modules, backup export/import and state validation, secret exclusion, and cross-origin write rejection.

The integration flow uploads a real local PDF, prepares an outline using a simulated provider, saves the reviewed outline, prepares a module, verifies that requesting preparation again makes no provider call, retrieves extracted page text, and renders the original PDF page to PNG.

JavaScript modules are syntax-checked with `node --check`.

Configuration checks cover `.env` parsing, quotes/comments/BOM, live file rereading, environment precedence, both key variable names, blank saved settings, explicit overrides, safe removal, credential-free public metadata, and avoiding duplicate credential storage. The user's copied app's actual `.env` was checked for key presence without printing or transmitting the key.

## Browser checks
Performed in a separate local test workspace so the primary workspace's courses and progress remain untouched.

- Library, course graph, outline, and module navigation.
- Objective choices, complete-answer submission, a 100% result, and saved explanations.
- Subjective solution reveal and mapped paper solution reveal.
- Reading status, bookmarks, and search by topic name.
- Notes saved and preserved after a full reload.
- Flashcard reveal/rating, advancing the card and reducing the due count.
- Multi-PDF upload, document-role inference, saved materials, and a clear resumable missing-key pause.
- Outline title editing, adding/removing a module, and persistence after reload. The outline fixture is seeded locally; the test does not pretend a live AI call occurred.
- ZIP download and reimport through the browser, preserving study progress.
- Original source page rendered locally, with a physical page selector and extracted-text alternative.
- Desktop layout and 390-pixel mobile navigation/lesson layout; no document-level horizontal overflow in the lesson.
- Light and dark appearance. No browser error/warning logs during the tested flows.
- Keyboard skip-to-content keeps the current module open; the source page selector updates its rendered image as the page number changes.

## Remaining validation
The initial build used controlled provider responses. The real-course follow-up exercised the configured Gemini connection: one missing module was prepared as a saved plan and six focused lessons, with seven successful cached responses. A temporary 503 on the final lesson paused preparation; resuming reused the plan and five saved lessons and completed only the unfinished lesson. No existing module was regenerated. The configured model remains editable in Settings.

Source checks verify file/page identity and supplied-page membership. They do not establish factual entailment, prove numerical correctness, or turn generated solutions into an official mark scheme. Image-only PDF scans require OCR before upload in this version.

The final assessment regression retains first-encounter outcomes beyond the 30-attempt display/history limit, including export/import. A numerical check confirms the reviewed teleportation correction. The isolated browser fixture typeset inline equations and a fraction/matrix, rendered a Markdown table and focused lesson navigation, with no math fallback.

## Completed real-course follow-up

- All eight modules are ready. The added module contains six focused lessons, 41 teaching sections, roughly 10,400 teaching words, 21 objective questions, seven written problems, and 42 cards.
- All 653 mathematical expressions in the new lesson sections typeset without fallback. Twelve diagrams are associated with their own lessons.
- Existing study history and original PDF hashes were checked before/after repairs. Original packages are retained in automatic local backups; corrections are recorded separately.
- An actual completed-course ZIP was exported and restored into isolated storage. All eight modules, eight PDFs, the teaching plan, annotations, and remapped citations survived restoration.
- Browser checks confirm the completed eight-node expanded map fits its viewport; the source viewer shows reviewed clarifications beside original pages; and the full new reader has six lesson links, 41 sections, and no horizontal overflow. Tablet contents navigation was verified after constraining its scroll height.
- Local corrections clarify the known ambiguous physics assessment and balance verbose choices. No claim is made that every answer is independently verified. Improved teaching prompts apply to new content; existing guides were preserved.
