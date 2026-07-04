# Canvas Academic Assistant

A local assistant that connects to Canvas, tracks your coursework, downloads
and indexes your course materials, and prepares **draft** solutions, study
notes, reminders, and a status dashboard — all for you to review before you
personally submit anything.

## Hard rule: it never submits anything

Every Canvas API call this project makes is a `GET` request. There is no
code path anywhere in this repo that calls a Canvas submission, quiz-attempt,
or discussion-post endpoint. Draft files are written under `data/drafts/`
and explicitly labeled "ready for student review" — turning them in is
always a manual step you take yourself in Canvas.

## Architecture

```
Canvas API (read-only)
      │
      ▼
canvas_client.py  ──►  tracker.py (deadlines, new/changed items, missing work)
      │                        │
      ▼                        ▼
downloader.py          reminders.py + dashboard.py
      │
      ▼
knowledge_base.py (chromadb, local, per-course retrieval)
      │
      ▼
draft_generator.py / quiz_prep.py  (Claude, retrieval-augmented)
      │
      ▼
data/drafts/<course>/<assignment|quiz>/  (review-ready files only)
```

- **Connection**: `src/canvas_client.py` uses the Canvas REST API with a
  personal access token (`CANVAS_API_TOKEN`). If your institution blocks
  token issuance, `src/browser_login.py` is an optional, explicitly
  read-only Playwright fallback (login + file download only — no form
  submission code exists in it).
- **Tracking**: `src/tracker.py` fetches assignments, quizzes, discussions,
  and announcements per course, diffs them against `data/state/` from the
  last run, and flags new items, due-date changes, and missing work.
- **Materials**: `src/downloader.py` pulls course files, module attachments,
  and assignment attachments into `data/raw/<course>/...`.
- **Knowledge base**: `src/knowledge_base.py` extracts text from PDFs,
  DOCX, PPTX, and plain text files and stores chunk embeddings in a local
  ChromaDB store (`data/vector_store/`) for per-course retrieval.
- **Drafting**: `src/draft_generator.py` retrieves relevant course-material
  chunks for each assignment and asks Claude to prepare a draft response,
  along with a confidence rating and review notes. `src/quiz_prep.py` does
  the same for quizzes but only ever produces study notes — it never opens,
  answers, or submits a live quiz.
- **Reminders & dashboard**: `src/reminders.py` and `src/dashboard.py` turn
  all of the above into a reminder feed (`data/state/reminders.json`) and a
  single status table (`data/dashboard/dashboard.md` / `.csv`).

## Setup

```bash
cd canvas_assistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in CANVAS_BASE_URL, CANVAS_API_TOKEN, ANTHROPIC_API_KEY
```

Get a Canvas API token from **Account → Settings → New Access Token**.

## Usage

```bash
python main.py sync        # detect courses/deadlines, download + index materials
python main.py draft       # generate draft solutions for open assignments
python main.py quizzes     # generate study notes for upcoming quizzes
python main.py dashboard   # rebuild the summary dashboard
python main.py all         # run the full pipeline
```

Add `--force` to any command that generates drafts/notes to regenerate ones
that already exist.

## Folder structure after a run

```
data/
  raw/<course>/{files,modules,assignments}/...   # downloaded course materials
  vector_store/                                   # local ChromaDB index
  drafts/<course>/<assignment>/draft.md           # draft solutions
  drafts/<course>/<assignment>/metadata.json      # status/confidence/review flag
  drafts/<course>/quizzes/<quiz>/study_notes.md   # quiz study notes
  state/tracked_state.json                        # for diffing between runs
  state/reminders.json                            # latest reminder feed
  dashboard/dashboard.md / dashboard.csv           # status table
```

## Dashboard columns

Course, Assignment/Quiz, Due Date, Status, Draft File Location, Confidence,
Manual Review Needed — one row per assignment/quiz across all your courses.

## Notes

- Draft confidence and "manual review needed" come from Claude's own
  self-assessment of how well the retrieved course materials covered the
  assignment — treat `low` confidence or `manual_review_needed: true` as a
  strong signal to read the draft closely before using it.
- The knowledge base is per-course (queries are filtered by `course_id`), so
  material from one class is never used to answer another class's
  assignment.
- Nothing here reads or writes Canvas grades, submissions, or quiz
  attempts — only assignment/quiz/discussion/announcement metadata and
  course files.
