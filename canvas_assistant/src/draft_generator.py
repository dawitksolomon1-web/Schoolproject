"""
Generates review-ready draft files for assignments.

IMPORTANT: this module only ever writes files under data/drafts/. It never
touches Canvas at all — no navigation, no clicks, no uploads. Every draft it
writes is explicitly labeled as a draft the student must review, edit, and
submit themselves.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, DRAFT_MODEL, DRAFTS_DIR
from src.knowledge_base import KnowledgeBase
from src.models import Assignment
from src.utils import slugify

logger = logging.getLogger("canvas_assistant.draft_generator")

SYSTEM_PROMPT = """\
You are an academic assistant that prepares DRAFT coursework for a student \
to review, edit, and personally submit. You never submit anything yourself \
and you are not producing a final answer key.

Rules:
- Treat the assignment instructions and any retrieved course-material excerpts \
as the source of truth. If the excerpts don't cover something you need, say so \
explicitly rather than inventing course-specific facts (dates, policies, \
grading rubrics, instructor names).
- Produce a genuinely useful first-pass solution/response the student can \
build on, not just an outline, unless the instructions clearly ask only for \
a plan.
- Flag any part of your draft that is a guess, is based on incomplete \
information, or should be double-checked by the student before submission.
- Never claim the work has been submitted, graded, or verified. It has not.
- Begin your reply with a fenced ```json metadata block containing exactly \
these keys: "confidence" (one of "low", "medium", "high" — your honest \
self-assessment of how complete and reliable this draft is), \
"manual_review_needed" (boolean — true unless the draft is trivial and \
directly supported by the provided materials), and "review_notes" (a short \
string describing what the student should specifically check). After that \
block, write the draft itself in Markdown.
"""


@dataclass
class DraftResult:
    course_id: int
    assignment_id: int
    assignment_name: str
    draft_path: Path
    metadata_path: Path
    confidence: str
    manual_review_needed: bool
    status: str = "ready_for_student_review"


def existing_draft_metadata(assignment: Assignment) -> Optional[dict]:
    for candidate in DRAFTS_DIR.glob(
        f"{assignment.course_id}_*/{assignment.id}_*/metadata.json"
    ):
        try:
            return json.loads(candidate.read_text())
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _extract_metadata(response_text: str) -> tuple[dict, str]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if not match:
        return {"confidence": "low", "manual_review_needed": True,
                 "review_notes": "Model did not return structured metadata; review carefully."}, response_text
    try:
        meta = json.loads(match.group(1))
    except json.JSONDecodeError:
        meta = {"confidence": "low", "manual_review_needed": True, "review_notes": "Metadata unparsable."}
    draft_body = response_text[match.end():].strip()
    return meta, draft_body


class DraftGenerator:
    def __init__(self, kb: KnowledgeBase, api_key: Optional[str] = None):
        if not (api_key or ANTHROPIC_API_KEY):
            raise RuntimeError(
                "ANTHROPIC_API_KEY must be set in .env to generate drafts."
            )
        self.kb = kb
        self.client = anthropic.Anthropic(api_key=api_key or ANTHROPIC_API_KEY)

    def generate_for_assignment(self, assignment: Assignment) -> DraftResult:
        context_chunks = self.kb.query(
            assignment.course_id, f"{assignment.name}\n{assignment.description}", n_results=6
        )
        context_text = "\n\n".join(
            f"[Source: {c['metadata'].get('source_name')}]\n{c['text']}" for c in context_chunks
        ) or "(No matching course materials were found in the knowledge base.)"

        due_str = assignment.due_text or (
            assignment.due_at.isoformat() if assignment.due_at else "No due date listed"
        )
        kind = "graded discussion" if assignment.is_discussion else "assignment"
        user_prompt = f"""\
Course: {assignment.course_name}
{kind.capitalize()}: {assignment.name}
Due: {due_str}

Assignment instructions (read from the Canvas assignment page):
{assignment.description or "(No instruction text was visible on the assignment page.)"}

Relevant course material excerpts retrieved from this course's knowledge base:
{context_text}

Prepare a draft response for the student to review before they submit it \
themselves."""

        response = self.client.messages.create(
            model=DRAFT_MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        meta, draft_body = _extract_metadata(text)

        out_dir = (
            DRAFTS_DIR
            / f"{assignment.course_id}_{slugify(assignment.course_name)}"
            / f"{assignment.id}_{slugify(assignment.name)}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        draft_path = out_dir / "draft.md"
        metadata_path = out_dir / "metadata.json"

        header = (
            f"<!--\n"
            f"DRAFT ONLY — prepared by Canvas Academic Assistant for student review.\n"
            f"This file has NOT been submitted anywhere. Review, edit, and submit it\n"
            f"yourself through Canvas.\n"
            f"Course: {assignment.course_name}\nAssignment: {assignment.name}\nDue: {due_str}\n"
            f"-->\n\n"
        )
        draft_path.write_text(header + draft_body)

        full_metadata = {
            "course_id": assignment.course_id,
            "course_name": assignment.course_name,
            "assignment_id": assignment.id,
            "assignment_name": assignment.name,
            "due_at": due_str,
            "status": "ready_for_student_review",
            "confidence": meta.get("confidence", "low"),
            "manual_review_needed": meta.get("manual_review_needed", True),
            "review_notes": meta.get("review_notes", ""),
            "draft_path": str(draft_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "auto_submitted": False,
        }
        metadata_path.write_text(json.dumps(full_metadata, indent=2))

        logger.info("Draft ready for review: %s", draft_path)
        return DraftResult(
            course_id=assignment.course_id,
            assignment_id=assignment.id,
            assignment_name=assignment.name,
            draft_path=draft_path,
            metadata_path=metadata_path,
            confidence=full_metadata["confidence"],
            manual_review_needed=full_metadata["manual_review_needed"],
        )
