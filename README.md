# Folium

A local-first study companion that turns your course PDFs into a connected course map, detailed lessons, source-linked past questions, practice quizzes, and flashcards. Prepare a course once, then study its saved content without further AI calls.

## Features

- Review and edit an AI-proposed syllabus before preparing lessons.
- Explore modules and prerequisites on a course map with zoom, pan, and progress indicators.
- Study focused lessons with worked examples, simple flow diagrams, and offline mathematical typesetting.
- Open citations at the original PDF page, with both image and extracted-text views.
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

You can also configure a key in the app's Settings or through `GEMINI_API_KEY` / `GOOGLE_API_KEY` environment variables. Select a Gemini model available to your project in Settings. Folium has no automatic paid-model fallback; model access and free-tier quotas depend on your Google project.

A key saved in Settings takes precedence over environment configuration. Otherwise, process environment variables take precedence over `.env`; `GEMINI_API_KEY` takes precedence over `GOOGLE_API_KEY`. The app rereads `.env` when configuration is needed. Refresh the browser after editing it to update the connection indicator.

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
2. Prepare an outline, then review its modules, topics, prerequisites, and document coverage.
3. Start lesson preparation. Successful teaching plans and individual lessons are saved as they finish.
4. Open a module from the course map to study, practise, view mapped past questions, or review cards.
5. Export a course ZIP when you want a portable backup. Import it into another local installation to restore it.

Preparation uses one request for the outline, then one teaching-plan request per unfinished module and one request per focused lesson (one to eight lessons per module). Past-paper mapping uses a request per readable paper page. Each lesson also supplies its practice questions and cards.

If preparation pauses because of a quota, connection failure, or restart, resume it explicitly. Completed stages are reused. Existing saved lessons are preserved when prompts change; improved prompts apply to newly generated content. Reading, navigation, quizzes, solution reveals, notes, and card reviews make **no AI requests**.

## Data and privacy

By default, SQLite records, uploaded PDFs, provider-response caches, settings, and backups live under `data/`. They are excluded from Git, along with `.env`, local demo assets, temporary output, and development notes. Only the root README is tracked as Markdown. Tests generate small synthetic documents at runtime and need no sample PDFs or API key.

Text extraction and PDF previews run locally. Source excerpts selected for preparation are sent to Gemini. Course ZIPs include your uploaded materials and notes, but exclude API credentials; share them only with intended recipients.

## Limitations

- Uploads currently support text-readable PDFs. Image-only scans need OCR before upload; uncertain extracted symbols should be checked against the original page.
- Citations use physical PDF page numbers. Valid source locations and coverage maps do not establish that every AI-generated statement is correct or every source detail is covered.
- AI-generated practice and past-paper solutions are labeled. Uploaded-paper frequency reflects the papers you provided and does not predict future exams.
- Objective answers use saved answer keys and deterministic scoring. Subjective questions provide solutions for self-review, without automatic grading.
- Recall estimates depend on distinct answered questions, topic coverage, and first-encounter/recent results. Repeating a small question bank does not establish mastery.
- This local prototype has no accounts, live tutor chat, cloud synchronization, or hosted multi-user service.

## Development

### Planned direction: scope-driven teaching and scanned PDFs

The PDFs and reviewed syllabus should define what the course teaches, its depth, and its notation. Gemini may explain those topics using its general knowledge, derivations, and generated examples, without reproducing the notes or requiring an excerpt for every explanation. Source-specific claims and original past-paper wording still need faithful extraction. Links that locate a topic in the materials must be distinguished from citations supporting a particular claim.

The proposed scan workflow keeps local text extraction for readable pages and uses an explicitly requested Gemini visual pass on pages needing it to build a saved, page-aware scope map. Unreadable pages and uncertain notation remain visible for review. Optional local OCR can provide searchable text. This is a planned change: the current app still requires text-readable PDFs and uses excerpt-grounded lesson prompts. Scan processing and scope-driven generation have not been implemented or benchmarked.

The backend uses Python's HTTP server, SQLite, pypdf, PDFium, and Pillow. The frontend is buildless HTML, CSS, and JavaScript with locally bundled KaTeX.

| File | Purpose |
| --- | --- |
| `app.py` | Local HTTP server and API routes |
| `core.py` | Persistence, validation, backups, and practice scoring |
| `configuration.py` | Environment and local configuration loading |
| `generation.py` | Gemini requests, retrieval, caching, and resumable jobs |
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
```

## Third-party attribution

[KaTeX](https://katex.org/) 0.19.0 is bundled from its official npm distribution for offline math rendering. Its MIT license is retained in [web/vendor/katex/LICENSE](web/vendor/katex/LICENSE). The browser script, stylesheet, and required fonts are served locally without a runtime CDN.
