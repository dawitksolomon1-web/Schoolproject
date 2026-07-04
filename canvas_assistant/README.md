# Canvas Academic Assistant (browser-based)

A local homework assistant that uses **your normal Canvas login in Chrome**
(via Playwright) to find upcoming assignments, gather the course materials
they need, and prepare **completed draft files locally for you to review** —
then stops. Submitting anything is always your manual step in Canvas.

## Hard rules

- **Browser-only by default.** No Canvas API token is used or needed. The
  assistant reuses the Chrome session you save once with `python main.py
  login`. (An optional read-only API client exists in `src/canvas_client.py`
  but stays dormant unless you set `CANVAS_USE_API=1` and wire it in.)
- **Read-only on Canvas.** It navigates pages, reads content, and follows
  file download links. There is no code that submits assignments, uploads
  files, posts discussions, or modifies anything on Canvas.
- **No quizzes.** Quiz functionality was removed from the workflow. Nothing
  clicks "Start Quiz", opens a quiz, or answers quiz questions.
- **Dry-run by default.** `draft` and `all` only report what they would do
  until you pass `--confirm`.

## Commands

```bash
python main.py login             # opens Chrome; log in manually (SSO/2FA fine); session is saved
python main.py dashboard         # reads your Canvas dashboard/courses, lists incoming work
python main.py sync              # downloads instructions, attachments, module/files/pages materials
python main.py draft             # DRY RUN: lists assignments that would get drafts
python main.py draft --confirm   # actually generates local draft files
python main.py all --dry-run     # shows what would be detected/downloaded/drafted (default behavior)
python main.py all --confirm     # full pipeline: sync + drafts + dashboard
```

Add `--force` to regenerate drafts that already exist.

## Workflow

1. `login` opens a real Chrome window at your Canvas URL. You log in normally
   (SSO and 2FA both work — the assistant never sees or stores your
   password). The session lives in a persistent Chrome profile under
   `data/browser_profile/` and is reused by every later command, headless.
2. `dashboard` visits your dashboard/course list, opens each course's
   assignments page, and extracts assignments (including graded discussions),
   due dates, upcoming work, and past-due work. It diffs against the previous
   run to flag new assignments and due-date changes.
3. `sync` opens each assignment page to read the instructions and download
   attachments, then collects course materials from Modules, Files, and
   Pages. Everything lands under `data/raw/<course>/...`, and readable text
   (PDF/DOCX/PPTX/pages/instructions — plus your previously generated
   drafts) is indexed into a local ChromaDB knowledge base.
4. `draft --confirm` retrieves the most relevant course material for each
   upcoming/past-due assignment and asks Claude to write a completed first
   draft, saved to `data/drafts/<course>/<assignment>/draft.md` with a
   metadata file recording confidence and whether manual review is needed.
5. Every command refreshes `data/dashboard/dashboard.md` / `.csv`:
   Course | Assignment | Due Date | Status | Draft Location | Confidence |
   Manual Review Needed.

## Setup

```bash
cd canvas_assistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium     # or use your system Chrome (tried first)
cp .env.example .env            # set CANVAS_BASE_URL (+ ANTHROPIC_API_KEY for drafts)
python main.py login
python main.py all --dry-run
```

## Folder structure after a run

```
data/
  browser_profile/                      # persistent Chrome profile (your saved session)
  raw/<course>/assignments/<name>/      # instructions.md + attachments
  raw/<course>/modules/ , files/        # downloaded course materials
  vector_store/                         # local ChromaDB knowledge base
  drafts/<course>/<assignment>/draft.md # completed drafts (review before submitting!)
  drafts/<course>/<assignment>/metadata.json
  state/tracked_state.json              # diffing between runs
  dashboard/dashboard.md / .csv         # status table
```

## Notes & limitations

- Canvas themes differ between institutions; every scraper selector is
  best-effort. If a section (e.g. Files) isn't scrapable at your school, it
  is logged and skipped — Modules and assignment attachments usually cover
  the same material.
- In browser mode the assistant doesn't read your submission history, so
  "past_due_no_draft" means *past due with no local draft*, not necessarily
  unsubmitted — check Canvas itself before panicking.
- Draft confidence and "manual review needed" come from Claude's
  self-assessment of how well the retrieved materials covered the
  assignment. Treat `low` confidence as a strong signal to rework the draft.
- The knowledge base is per-course, so one class's materials never leak into
  another class's draft.
