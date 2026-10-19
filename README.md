# Folium

A local-first course companion. Turn course PDFs into a knowledge map, detailed lessons, source-linked past papers, saved practice questions, and flashcards. Prepare once; study without further API calls.

## Run

Requires Python 3.10 or newer.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8765. The built-in sample course needs no API key. To prepare your own course, copy `.env.example` to `.env` in the same folder as `app.py`, then fill in `GEMINI_API_KEY`. Folium reads that file automatically. `GOOGLE_API_KEY` is also supported. Alternatively, use an environment variable or enter a key in Settings. Keys never enter browser storage or course backups. This is a personal local prototype: anyone with access to the computer's files can read local configuration and course files.

On this Windows computer, you can also double-click **start.bat**. It prefers a project virtual environment or the bundled Python runtime, then falls back to your system Python. Keep the server window open while using Folium. Closing it stops the app; the data remains saved.

Use `--port 8766` to choose another port, `--data-dir <path>` for another local storage folder, and `--env-file <path>` when your `.env` is elsewhere. The server binds to 127.0.0.1 only.

Settings shows whether the active key comes from the `.env` file, environment variables, or a key saved in Settings. A saved key takes precedence; otherwise `GEMINI_API_KEY` takes precedence over `GOOGLE_API_KEY`. Environment variables take precedence over the same variable in `.env`. Empty saved key fields do not mask an environment key. Saving model options does not copy an environment key into local settings.

The `.env` file is reread when configuration is needed, so changing its key does not require another server restart once this version is running. Refresh the browser to update the connection indicator. Windows user/system environment variables are also checked if the running process inherited no value.

## How a course works

1. Create a course and label uploaded PDFs as syllabus, learning material, or past papers.
2. Request an outline, review the modules/topics/prerequisites, then explicitly generate the course.
3. Preparation saves each successful stage. Resume a paused job after quota resets or a restart.
4. Read, practise, reveal solutions, review cards, and keep notes from saved content.
5. Export a course ZIP to back up or share the package. Import it into another local Folium workspace.

## Scope and limitations

- PDF text extraction is local. Image-only scans need OCR before upload; partially unreadable pages are reported.
- Only document excerpts needed for generation are sent to Gemini. There are no AI calls during study or quiz scoring.
- Citation previews render the original PDF page locally, with an extracted-text view and a link to the original file. No browser PDF plug-in is required.
- Free-tier model availability and quotas depend on your Google project. Change the model in Settings as needed. No automatic paid fallback.
- Page references point to physical PDF pages. Source-location checks do not prove that every generated claim follows from the source. AI practice and generated PYQ solutions are labeled.
- Objective questions have saved answer keys and deterministic grading. Subjective practice provides revealable solutions, without automatic marks.
- Course backups include your uploaded materials and notes; share them only with intended recipients.
- There is no account system, live tutor chat, hosted deployment, or multi-device synchronization in this version.

## Development

See [PLAN.md](PLAN.md) and [AGENTS.md](AGENTS.md). Run tests with `python -m unittest discover -s tests -v`.

See [VERIFICATION.md](VERIFICATION.md) for what was checked and the remaining live-provider validation step. Sample PDF authoring is a development-only task (`tools/create_sample.py`) requiring ReportLab; the app uses the committed originals and does not require ReportLab.
# Detailed teaching preparation

New courses use one outline request, then one teaching-plan request per unfinished module and one request per focused lesson (1–8 lessons per module). Each lesson includes its own practice and cards. Plans and completed lessons are saved independently, so resuming does not repeat successful work. Existing saved module packages are preserved; improved prompts apply to new content. See `prompts.py` for the complete teaching instructions.

Every readable material file receives a reserved outline excerpt budget, and new outlines include an explicit document-to-module map. Coverage maps are planning aids, not proof that every source statement was taught correctly. A missing module can be appended without discarding saved modules; an automatic course backup is made before extension.

Malformed PDF glyphs are normalized locally while valid mathematical Unicode is preserved. Existing extracted text is backed up before its one-time repair. Some symbols still require consulting the original PDF page; image-only scans still require OCR.

Practice progress distinguishes unique first encounters from repeated answers. Repeating a small saved bank does not establish mastery. Strong recall requires at least 12 distinct questions, topic coverage and strong first-encounter/recent results; this remains an estimate within the saved bank.

The reader supports safe Markdown and locally bundled KaTeX mathematics, with no CDN or remote font dependency. Older plain-text/Unicode formulas remain as originally saved; LaTeX typesetting is used when mathematical delimiters are present. Graph controls fit the whole map, zoom, pan, and expand it. Practice can focus on a topic, and question/option order is shuffled while server scoring keeps the original answer indices.

Reviewed source clarifications can accompany original pages and new generation. They are labeled separately from uploaded notes. `tools/apply_corrections.py` applies a reviewed local JSON patch only when the expected original question/section still matches, backs up the course first, and records the correction. This does not automatically establish factual correctness for all generated content.
