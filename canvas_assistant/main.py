"""
Canvas Academic Assistant — browser-based, read-only, draft-only.

It opens Canvas through Chrome (Playwright) with your saved login session,
finds upcoming assignments/homework, downloads instructions and course
materials, and prepares local draft files for YOU to review and submit
yourself. It never submits, uploads, posts, or modifies anything on Canvas,
and it never touches quizzes.

Commands:
    python main.py login             # open Chrome, log in manually, save the session
    python main.py dashboard         # read the Canvas dashboard, list incoming work
    python main.py sync              # download instructions/attachments/materials + build knowledge base
    python main.py draft --confirm   # generate local draft files (dry-run without --confirm)
    python main.py all [--dry-run]   # full pipeline (dry-run is the default; --confirm to run it)
"""
from __future__ import annotations

import argparse
import json
import logging

from config import DASHBOARD_DIR, DRAFTS_DIR
from src.browser_session import BrowserSession
from src.dashboard import DashboardBuilder
from src.downloader import MaterialDownloader
from src.knowledge_base import KnowledgeBase
from src.logging_config import setup_logging
from src.models import Assignment
from src.scraper import CanvasScraper
from src.tracker import TrackedWork, track

logger = setup_logging(logging.INFO)


# ---------------------------------------------------------------------------
# pipeline stages
# ---------------------------------------------------------------------------

def detect_work(scraper: CanvasScraper) -> TrackedWork:
    """Scrape courses + assignment lists and diff against the previous run."""
    courses = scraper.get_courses()
    assignments_by_course = {c.id: scraper.get_assignments(c) for c in courses}
    work = track(courses, assignments_by_course)

    for event in work.new_items:
        logger.info("[new] %s — %s", event.course_name, event.title)
    for event in work.due_date_changes:
        logger.info("[due date changed] %s — %s (%s)", event.course_name, event.title, event.detail)
    return work


def gather_materials(scraper: CanvasScraper, work: TrackedWork, dry_run: bool
                      ) -> tuple[MaterialDownloader, KnowledgeBase | None]:
    """Open each assignment page, download attachments and course materials,
    and build the knowledge base. In dry-run mode nothing is written."""
    downloader = MaterialDownloader(scraper.session, dry_run=dry_run)
    kb = None if dry_run else KnowledgeBase()

    for course in work.courses:
        # Assignment instructions + attachments
        for assignment in work.assignments.get(course.id, []):
            scraper.fill_assignment_detail(assignment)
            material = downloader.save_instructions(course, assignment)
            if kb and assignment.description.strip():
                kb.ingest_text(course.id, course.name, f"instructions: {assignment.name}",
                                "assignment_instructions", assignment.description)
            attachment_materials = downloader.download_assignment_attachments(course, assignment)
            if kb:
                for m in attachment_materials:
                    kb.ingest_material(m)

        # Module files + linked module pages
        module_files, module_page_urls = scraper.get_module_materials(course)
        for m in downloader.download_remote_files(course, module_files):
            if kb:
                kb.ingest_material(m)

        # Course Files section (best-effort)
        course_files = scraper.get_course_files(course)
        for m in downloader.download_remote_files(course, course_files):
            if kb:
                kb.ingest_material(m)

        # Course pages (text goes straight into the knowledge base)
        if dry_run:
            downloader.planned.append(f"[pages] {course.name} — course pages would be read")
        else:
            for page in scraper.get_course_pages(course, module_page_urls):
                kb.ingest_text(course.id, course.name, f"page: {page.title}",
                                "course_page", page.text)

    # Previously generated drafts also feed the knowledge base, so new drafts
    # can stay consistent with earlier work.
    if kb:
        for draft_path in DRAFTS_DIR.glob("**/draft.md"):
            meta_path = draft_path.parent / "metadata.json"
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            kb.ingest_text(meta["course_id"], meta.get("course_name", ""),
                            f"previous draft: {meta.get('assignment_name', '')}",
                            "previous_draft", draft_path.read_text())

    return downloader, kb


def _needs_draft(assignment: Assignment, force: bool) -> bool:
    from src.draft_generator import existing_draft_metadata

    if force:
        return True
    return existing_draft_metadata(assignment) is None


def generate_drafts(work: TrackedWork, kb: KnowledgeBase, force: bool) -> list[dict]:
    from src.draft_generator import DraftGenerator, existing_draft_metadata

    generator = DraftGenerator(kb)
    ready: list[dict] = []
    for assignment in work.upcoming + work.past_due:
        existing = existing_draft_metadata(assignment)
        if existing and not force:
            logger.info("Draft already exists for %s — skipping (use --force to regenerate).",
                        assignment.name)
            ready.append(existing)
            continue
        logger.info("Generating draft: %s / %s", assignment.course_name, assignment.name)
        result = generator.generate_for_assignment(assignment)
        ready.append(json.loads(result.metadata_path.read_text()))
    return ready


def write_dashboard(work: TrackedWork, to_console: bool = True) -> None:
    builder = DashboardBuilder()
    rows = builder.build(work)
    builder.write(rows)
    if to_console:
        builder.print_console(rows)
    print(f"\nDashboard files: {DASHBOARD_DIR / 'dashboard.md'} (.csv alongside)")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_login() -> None:
    with BrowserSession(headless=False) as session:
        session.interactive_login()


def cmd_dashboard() -> None:
    with BrowserSession(headless=True) as session:
        session.ensure_logged_in()
        work = detect_work(CanvasScraper(session))
    print(f"\nCourses: {len(work.courses)} | Assignments: {len(work.all_assignments())} "
          f"| Upcoming: {len(work.upcoming)} | Past due: {len(work.past_due)}")
    if work.new_items:
        print(f"New since last run: {len(work.new_items)}")
    if work.due_date_changes:
        print(f"Due-date changes: {len(work.due_date_changes)}")
    write_dashboard(work)


def cmd_sync() -> None:
    with BrowserSession(headless=True) as session:
        session.ensure_logged_in()
        scraper = CanvasScraper(session)
        work = detect_work(scraper)
        gather_materials(scraper, work, dry_run=False)
    write_dashboard(work, to_console=False)
    print("Sync complete: instructions, attachments, and course materials are under "
          "data/raw/, and the knowledge base is up to date. Nothing was sent to Canvas.")


def cmd_draft(confirm: bool, force: bool) -> None:
    with BrowserSession(headless=True) as session:
        session.ensure_logged_in()
        scraper = CanvasScraper(session)
        work = detect_work(scraper)

        targets = [a for a in work.upcoming + work.past_due if _needs_draft(a, force)]
        if not confirm:
            print("\nDRY RUN — no drafts generated. Assignments that WOULD get a draft:")
            if not targets:
                print("  (none — every upcoming/past-due assignment already has a draft)")
            for a in targets:
                print(f"  - {a.course_name} / {a.name} (due: {a.due_text or 'n/a'})")
            print("\nRe-run with --confirm to actually generate these drafts.")
            return

        _downloader, kb = gather_materials(scraper, work, dry_run=False)

    ready = generate_drafts(work, kb, force)
    write_dashboard(work, to_console=False)
    print(f"\n{len(ready)} draft(s) ready for your review under data/drafts/. "
          "Nothing was submitted to Canvas — review each draft and submit it yourself.")


def cmd_all(confirm: bool, force: bool) -> None:
    dry_run = not confirm
    with BrowserSession(headless=True) as session:
        session.ensure_logged_in()
        scraper = CanvasScraper(session)
        work = detect_work(scraper)
        downloader, kb = gather_materials(scraper, work, dry_run=dry_run)

    if dry_run:
        print("\nDRY RUN — nothing was downloaded or generated.\n")
        print(f"Detected {len(work.all_assignments())} assignment(s) across "
              f"{len(work.courses)} course(s); {len(work.upcoming)} upcoming, "
              f"{len(work.past_due)} past due.\n")
        print("Would download:")
        for line in downloader.planned or ["  (nothing new)"]:
            print(f"  {line}")
        targets = [a for a in work.upcoming + work.past_due if _needs_draft(a, force)]
        print(f"\nWould generate drafts for {len(targets)} assignment(s):")
        for a in targets:
            print(f"  - {a.course_name} / {a.name} (due: {a.due_text or 'n/a'})")
        print("\nRe-run with --confirm to download materials and generate these drafts.")
        write_dashboard(work, to_console=False)
        return

    ready = generate_drafts(work, kb, force)
    write_dashboard(work)
    print(f"\nDone. {len(ready)} draft(s) are ready for your review under data/drafts/.\n"
          "Nothing was submitted to Canvas — review everything before you submit it yourself.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browser-based Canvas homework assistant (read-only, draft-only)."
    )
    parser.add_argument(
        "command", choices=["login", "dashboard", "sync", "draft", "all"],
        help="login: save your Canvas session | dashboard: list incoming work | "
              "sync: download materials | draft: create local drafts | all: full pipeline",
    )
    parser.add_argument("--confirm", action="store_true",
                        help="Actually generate drafts (draft/all default to dry-run).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Explicitly request dry-run mode (already the default for draft/all).")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate drafts even if they already exist.")
    args = parser.parse_args()

    if args.confirm and args.dry_run:
        parser.error("--confirm and --dry-run are mutually exclusive.")

    if args.command == "login":
        cmd_login()
    elif args.command == "dashboard":
        cmd_dashboard()
    elif args.command == "sync":
        cmd_sync()
    elif args.command == "draft":
        cmd_draft(confirm=args.confirm, force=args.force)
    elif args.command == "all":
        cmd_all(confirm=args.confirm, force=args.force)


if __name__ == "__main__":
    main()
