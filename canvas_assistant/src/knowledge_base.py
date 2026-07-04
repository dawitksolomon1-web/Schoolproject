"""
Local, per-install vector knowledge base built from downloaded course
materials. Backed by chromadb's persistent client so everything stays on
disk under data/vector_store — nothing is sent anywhere except the local
embedding model chromadb loads on first use.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import chromadb

from config import VECTOR_STORE_DIR
from src.downloader import DownloadedMaterial
from src.text_extraction import extract_text

logger = logging.getLogger("canvas_assistant.knowledge_base")

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
COLLECTION_NAME = "course_materials"


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _chunk_id(course_id: int, source_name: str, chunk_index: int) -> str:
    key = f"{course_id}::{source_name}::{chunk_index}"
    return hashlib.sha256(key.encode()).hexdigest()


class KnowledgeBase:
    def __init__(self, persist_dir: Path = VECTOR_STORE_DIR):
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(COLLECTION_NAME)

    def ingest_material(self, material: DownloadedMaterial) -> int:
        text = extract_text(material.path)
        if not text.strip():
            return 0
        return self.ingest_text(
            course_id=material.course_id,
            course_name=material.course_name,
            source_name=material.source_name,
            category=material.category,
            text=text,
        )

    def ingest_text(
        self, course_id: int, course_name: str, source_name: str, category: str, text: str
    ) -> int:
        chunks = _chunk_text(text)
        if not chunks:
            return 0
        ids = [_chunk_id(course_id, source_name, i) for i in range(len(chunks))]
        metadatas = [
            {
                "course_id": course_id,
                "course_name": course_name,
                "source_name": source_name,
                "category": category,
                "chunk_index": i,
            }
            for i in range(len(chunks))
        ]
        self._collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        logger.info("Ingested %d chunk(s) from %s (%s)", len(chunks), source_name, course_name)
        return len(chunks)

    def query(self, course_id: int, query_text: str, n_results: int = 5) -> list[dict]:
        if self._collection.count() == 0:
            return []
        result = self._collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where={"course_id": course_id},
        )
        matches = []
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            matches.append({"text": doc, "metadata": meta, "distance": dist})
        return matches

    def course_has_materials(self, course_id: int) -> bool:
        if self._collection.count() == 0:
            return False
        result = self._collection.get(where={"course_id": course_id}, limit=1)
        return bool(result.get("ids"))
