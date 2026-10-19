# Folium implementation plan

## Agreed outcome
A premium, minimal local web application that turns uploaded course PDFs into a saved, source-linked learning package. Generate once, study repeatedly without further AI calls. Gemini free-tier limits pause preparation gracefully. This prototype is a personal workspace, with export/import for sharing courses; it is not a multi-user hosted service.

## Checkpoints
1. [x] Product scope, architecture, repository instructions, and acceptance criteria.
2. [x] Persistent backend: courses, PDF ingestion, editable outline, Gemini generation, resumable jobs, citations, scoring, notes, flashcards, backup.
3. [x] Complete interface: library, graph/outline, lesson reader, practice, PYQs, revision, saved items, settings, upload/review flow.
4. [x] Integration and polish: sample course with real local sources, automated verification, browser verification, responsive/accessibility fixes, launch instructions.

## Data model
- Course records hold metadata, editable modules/topics/prerequisites, stage, errors, and provenance.
- Documents store original PDF bytes and extracted text per physical PDF page. Content hashes prevent duplicate uploads within a course.
- Each generated module package holds detailed lesson sections, bounded flow diagrams, objective and subjective questions, flashcards, source references, and coverage notes.
- A per-prompt response cache survives interruption between a provider response and later processing.
- Study progress, quiz attempts, notes, bookmarks, and card schedules are persistent user state separate from generated course content.
- ZIP backups contain a versioned course manifest and source PDFs; credentials are never included.

## Generation flow
Upload -> extract local PDF text -> explicitly request outline -> review/edit outline -> explicitly generate packages -> map PYQ pages -> ready.

Outline generation uses the syllabus first, or representative learning pages when no syllabus is provided. Module generation retrieves relevant pages locally and uses a constrained JSON response schema. Stored citations are accepted only if their source page was included in that request. Diagram nodes contain text only. PYQ mapping retains exact extracted question text and source metadata. Jobs run sequentially with a configurable interval; transient quota errors pause with a retry hint. Restarting the server marks unfinished jobs as paused. Resume skips persisted outputs.

## UI direction
Warm ivory background, forest-green accents, ink text, serif display typography, system sans-serif body, fine borders, ample whitespace, and compact purposeful motion. Main navigation: My courses, Revision, Saved, Settings. Module click opens a dedicated full-page learning workspace. No marketing landing page or decorative AI chat panel.

## Acceptance criteria
- Sample course works end to end without a key or internet access.
- Uploaded text PDFs persist and can be opened to their cited physical page.
- Outline is editable before generation, and prerequisites cannot form cycles.
- Completed content is reused on reload/resume; studying and scoring use no provider calls.
- Objective grading is deterministic on the server; subjective questions offer saved solutions without automated marking.
- Errors explain missing keys, unreadable scans, bad provider output, quota exhaustion, and interrupted jobs.
- Export/import preserves content and study state without importing paths or credentials.
- Core flows work with a keyboard and at desktop/mobile widths.

## Deliberate first-version limits
Text-based PDFs first; image-only scans require OCR before upload. No live tutor chat, automatic subjective marks, native PPT ingestion, full exam prediction, collaboration accounts, or cloud hosting. Generated material is study assistance; validation checks source locations and structure, not mathematical truth or semantic entailment.

## Checkpoint evidence
- Backend: 19 passing unit/integration checks cover persistent provider caching, resume without regenerated modules, PDF text extraction/deduplication, citation validation, quiz grading, mastery separation, revision scheduling, safe backup round trips, loopback request protection, and no provider calls during study.
- The sample course includes original illustrative PDF sources with verified physical page mappings. It is not a real past examination.
- Interface checkpoint: complete local library, prerequisite graph, outline and source library, lesson reader with flow diagrams, question interfaces, saved modules, notes, revision, connection settings, and upload/outline editing. PDF page previews render locally to avoid browser plug-in dependence. All 24 backend/integration checks pass, including upload-to-study with a simulated provider and actual PDF rendering.
- Final checkpoint: 25 automated checks pass; JavaScript syntax and whitespace checks pass. Browser checks cover upload, outline editing, study/practice, notes/reload, cards, search/bookmarks, source image/text/page navigation, backup round trips, dark appearance, keyboard skip navigation, and a 390-pixel lesson layout. See VERIFICATION.md. Live Gemini inference remains untested because no real key was supplied.

## Follow-up: environment configuration
- Fixed automatic loading of the `.env` beside the running app, including when the repository is copied to another folder.
- Added both Gemini key variable names, source labels in Settings, blank-setting fallback, Windows persisted-variable detection, and an explicit `--env-file` option.
- Environment keys are not copied into settings when saving other preferences, and never appear in public configuration responses.
- All 33 automated checks pass, including eight configuration regressions. The user's real key was detected locally without making an inference call.

## Follow-up: teaching depth and real-course audit
- [x] Fair document sampling, document-to-module coverage, safe Unicode extraction, and detailed coverage-first prompts.
- [x] Persist a module teaching plan and each focused lesson independently; resume without repeating saved lessons. Preserve existing packages.
- [x] Safe Markdown and offline mathematical typesetting, compact citations, lesson navigation, and responsive graph/reader layouts.
- [x] Shuffled assessment presentation, topic drills, unique-question evidence, and transparent corrections of identified content errors.
- [x] Back up and repair the live course; add only the missing Quantum Error Correction module. Test, synchronize the running copy, and document results.

Completed follow-up: 46 backend tests and the reader suite pass. The running copy is updated; all eight modules are ready. The new module demonstrates the six-lesson teaching flow. Existing guides were preserved, local corrections were backed up, and an actual complete-course backup round trip passed.
