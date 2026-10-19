# Folium

A local-first course companion. Turn course PDFs into a knowledge map, detailed lessons, source-linked past papers, saved practice questions, and flashcards. Prepare once; study without further API calls.

## Run

Requires Python 3.10 or newer.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8765. The built-in sample course needs no API key. Add your Gemini key in Settings when you want to prepare your own course. The key stays on the local server in ignored runtime settings, never in browser storage or backups. This is a personal local prototype: anyone with access to the computer's data folder can read those settings and course files.

On this Windows computer, you can also double-click **start.bat**. It prefers a project virtual environment or the bundled Python runtime, then falls back to your system Python. Keep the server window open while using Folium. Closing it stops the app; the data remains saved.

Use `--port 8766` to choose another port, and `--data-dir <path>` for another local storage folder. The server binds to 127.0.0.1 only. It does not load `.env` automatically; set environment variables in your shell or use Settings.

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
