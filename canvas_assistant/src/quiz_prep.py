"""
Prepares study notes for quizzes.

This module never opens, starts, answers, or submits a live Canvas quiz —
it only reads quiz metadata (title, description, due/availability dates,
question count) via the read-only Canvas API and combines that with the
course's knowledge base to produce study notes and likely-topic reasoning.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, DRAFT_MODEL, DRAFTS_DIR
from src.knowledge_base import KnowledgeBase
from src.models import Course, Quiz
from src.utils import slugify

logger = logging.getLogger("canvas_assistant.quiz_prep")

SYSTEM_PROMPT = """\
You are an academic assistant preparing STUDY NOTES for a student ahead of \
a quiz. You have not seen and will not see the quiz's actual questions or \
answers — Canvas does not expose those before a student takes the quiz, and \
this tool never starts or submits a live quiz attempt on the student's \
behalf. Your job is purely preparatory:

- Summarize the topics the quiz appears to cover, based on its title, \
description, and the course material excerpts provided.
- Produce study notes: key concepts, definitions, formulas, or examples \
from the course materials that are likely relevant.
- Note the reasoning a student could use for the kinds of questions this \
topic area tends to include (e.g. "expect to distinguish X from Y").
- Be explicit that this is preparation material, not the quiz's real \
content, and that you have not taken or seen the quiz.
- Begin your reply with a fenced ```json metadata block containing exactly \
these keys: "confidence" (one of "low", "medium", "high" — how well the \
retrieved materials actually cover this quiz's likely topics) and \
"manual_review_needed" (boolean). After that block, write the study notes \
in Markdown.
"""


@dataclass
class QuizPrepResult:
    course_id: int
    quiz_id: int
    quiz_title: str
    notes_path: Path
    metadata_path: Path
    confidence: str


def _extract_metadata(response_text: str) -> tuple[dict, str]:
    import re

    match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if not match:
        return {"confidence": "low", "manual_review_needed": True}, response_text
    try:
        meta = json.loads(match.group(1))
    except json.JSONDecodeError:
        meta = {"confidence": "low", "manual_review_needed": True}
    return meta, response_text[match.end():].strip()


class QuizPrepGenerator:
    def __init__(self, kb: KnowledgeBase, api_key: Optional[str] = None):
        self.kb = kb
        self.client = anthropic.Anthropic(api_key=api_key or ANTHROPIC_API_KEY)

    def generate_for_quiz(self, course: Course, quiz: Quiz) -> QuizPrepResult:
        context_chunks = self.kb.query(course.id, f"{quiz.title}\n{quiz.description}", n_results=6)
        context_text = "\n\n".join(
            f"[Source: {c['metadata'].get('source_name')}]\n{c['text']}" for c in context_chunks
        ) or "(No matching course materials were found in the knowledge base.)"

        due_str = quiz.due_at.isoformat() if quiz.due_at else "No due date listed"
        unlock_str = quiz.unlock_at.isoformat() if quiz.unlock_at else "Not specified"

        user_prompt = f"""\
Course: {course.name}
Quiz: {quiz.title}
Available from: {unlock_str}
Due: {due_str}
Approximate question count: {quiz.question_count or "unknown"}
Points possible: {quiz.points_possible}

Quiz description (from Canvas):
{quiz.description or "(No description text was provided on Canvas.)"}

Relevant course material excerpts retrieved from this course's knowledge base:
{context_text}

Prepare study notes for the student ahead of this quiz."""

        response = self.client.messages.create(
            model=DRAFT_MODEL,
            max_tokens=3000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        meta, notes_body = _extract_metadata(text)

        out_dir = (
            DRAFTS_DIR / f"{course.id}_{slugify(course.name)}" / "quizzes" / f"{quiz.id}_{slugify(quiz.title)}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        notes_path = out_dir / "study_notes.md"
        metadata_path = out_dir / "metadata.json"

        header = (
            f"<!--\n"
            f"STUDY NOTES ONLY — no live quiz was opened, answered, or submitted.\n"
            f"Course: {course.name}\nQuiz: {quiz.title}\nDue: {due_str}\n"
            f"-->\n\n"
        )
        notes_path.write_text(header + notes_body)

        full_metadata = {
            "course_id": course.id,
            "course_name": course.name,
            "quiz_id": quiz.id,
            "quiz_title": quiz.title,
            "due_at": due_str,
            "available_from": unlock_str,
            "status": "study_notes_ready_for_review",
            "confidence": meta.get("confidence", "low"),
            "manual_review_needed": meta.get("manual_review_needed", True),
            "notes_path": str(notes_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "quiz_auto_completed": False,
        }
        metadata_path.write_text(json.dumps(full_metadata, indent=2))

        logger.info("Quiz study notes ready: %s", notes_path)
        return QuizPrepResult(
            course_id=course.id,
            quiz_id=quiz.id,
            quiz_title=quiz.title,
            notes_path=notes_path,
            metadata_path=metadata_path,
            confidence=full_metadata["confidence"],
        )
