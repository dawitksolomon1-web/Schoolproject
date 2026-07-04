"""
Canvas Academic Assistant — CLI entry point.

This tool connects to Canvas read-only, tracks deadlines and coursework,
downloads and indexes course materials, and prepares draft
solutions/summaries for you to review. It never submits anything to Canvas.

Usage:
    python main.py sync        # detect courses/deadlines, download + index materials
    python main.py draft       # generate draft solutions for open assignments
    python main.py quizzes     # generate study notes for upcoming quizzes
    python main.py dashboard   # rebuild the summary dashboard
    python main.py all         # run the full pipeline
"""
from __future__ import annotations

import argparse
import json
import logging

from config import DASHBOARD_DIR, DRAFTS_DIR
from src.canvas_client import CanvasClient
from src.dashboard import DashboardBuilder
from src.downloader import FileDownloader
from src.draft_generator import DraftGenerator
from src.knowledge_base import KnowledgeBase
from src.logging_config import setup_logging
from src.quiz_prep import QuizPrepGenerator
from src.reminders import ReminderEngine
from src.tracker import DeadlineTracker, SyncResult

logger = setup_logging(logging.INFO)

SKIP_SUBMISSION_TYPES = {"online_quiz", "none", "not_graded", "on_paper", "external_tool"}


def do_sync(client: CanvasClient) -> tuple[SyncResult, KnowledgeBase]:
    logger.info("Detecting enrolled courses and coursework (read-only)...")
    tracker = DeadlineTracker(client)
    sync_result = tracker.sync()
    logger.info("Found %d course(s).", len(sync_result.courses))

    logger.info("Downloading course materials...")
    downloader = FileDownloader(client)
    materials = downloader.download_all(sync_result.courses, sync_result.assignments)
    logger.info("Downloaded/verified %d material file(s).", len(materials))

    logger.info("Building local knowledge base...")
    kb = KnowledgeBase()
    for m in materials:
        kb.ingest_material(m)

    return sync_result, kb


def do_draft(sync_result: SyncResult, kb: KnowledgeBase, force: bool = False) -> list[dict]:
    generator = DraftGenerator(kb)
    ready: list[dict] = []
    for course in sync_result.courses:
        for assignment in sync_result.assignments.get(course.id, []):
            if assignment.has_submitted_submissions:
                continue
            if set(assignment.submission_types) & SKIP_SUBMISSION_TYPES and assignment.submission_types:
                continue
            metadata_path = None
            for candidate in DRAFTS_DIR.glob(f"{course.id}_*/{assignment.id}_*/metadata.json"):
                metadata_path = candidate
                break
            if metadata_path and not force:
                logger.info("Draft already exists for %s, skipping (use --force to regenerate)",
                            assignment.name)
                ready.append(json.loads(metadata_path.read_text()))
                continue
            logger.info("Generating draft for: %s / %s", course.name, assignment.name)
            result = generator.generate_for_assignment(course, assignment)
            ready.append(json.loads(result.metadata_path.read_text()))
    return ready


def do_quizzes(sync_result: SyncResult, kb: KnowledgeBase, force: bool = False) -> list[dict]:
    generator = QuizPrepGenerator(kb)
    ready: list[dict] = []
    for course in sync_result.courses:
        for quiz in sync_result.quizzes.get(course.id, []):
            metadata_path = None
            for candidate in DRAFTS_DIR.glob(f"{course.id}_*/quizzes/{quiz.id}_*/metadata.json"):
                metadata_path = candidate
                break
            if metadata_path and not force:
                logger.info("Study notes already exist for %s, skipping", quiz.title)
                ready.append(json.loads(metadata_path.read_text()))
                continue
            logger.info("Generating study notes for: %s / %s", course.name, quiz.title)
            result = generator.generate_for_quiz(course, quiz)
            ready.append(json.loads(result.metadata_path.read_text()))
    return ready


def do_dashboard(sync_result: SyncResult) -> None:
    builder = DashboardBuilder()
    rows = builder.build(sync_result)
    builder.write(rows)


def do_reminders(sync_result: SyncResult, ready_items: list[dict]) -> None:
    engine = ReminderEngine()
    reminders = engine.build(sync_result, ready_items)
    engine.save(reminders)
    for r in reminders:
        logger.info("[%s] %s — %s (%s)", r.category, r.course_name, r.title, r.detail)


def main() -> None:
    parser = argparse.ArgumentParser(description="Canvas Academic Assistant")
    parser.add_argument(
        "command",
        choices=["sync", "draft", "quizzes", "dashboard", "all"],
        help="Which stage of the pipeline to run",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate drafts/notes even if they already exist")
    args = parser.parse_args()

    client = CanvasClient()

    if args.command == "sync":
        do_sync(client)
        print("Sync complete. Nothing was submitted to Canvas.")
        return

    if args.command == "dashboard":
        sync_result, _kb = do_sync(client)
        do_dashboard(sync_result)
        print(f"Dashboard written to {DASHBOARD_DIR}")
        return

    if args.command == "draft":
        sync_result, kb = do_sync(client)
        ready = do_draft(sync_result, kb, force=args.force)
        do_reminders(sync_result, ready)
        do_dashboard(sync_result)
        print(f"{len(ready)} assignment draft(s) ready for your review under data/drafts/.")
        return

    if args.command == "quizzes":
        sync_result, kb = do_sync(client)
        ready = do_quizzes(sync_result, kb, force=args.force)
        do_dashboard(sync_result)
        print(f"{len(ready)} quiz study-note set(s) ready under data/drafts/.")
        return

    if args.command == "all":
        sync_result, kb = do_sync(client)
        ready_assignments = do_draft(sync_result, kb, force=args.force)
        ready_quizzes = do_quizzes(sync_result, kb, force=args.force)
        do_reminders(sync_result, ready_assignments + ready_quizzes)
        do_dashboard(sync_result)
        print(
            f"Done. {len(ready_assignments)} assignment draft(s) and "
            f"{len(ready_quizzes)} quiz study-note set(s) are ready for your review.\n"
            f"Dashboard: {DASHBOARD_DIR / 'dashboard.md'}\n"
            "Nothing was submitted to Canvas — review everything before you submit it yourself."
        )
        return


if __name__ == "__main__":
    main()
