"""Knowledge base — persistent Q&A memory for screening questions.

Stores question/answer pairs learned during applications and reuses them
for similar questions in future applications. Uses simple keyword matching
for similarity search (no vector DB dependency).
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection

logger = logging.getLogger(__name__)

NORMALIZE_PATTERNS = [
    (r"[áàâãä]", "a"),
    (r"[éèêë]", "e"),
    (r"[íìîï]", "i"),
    (r"[óòôõö]", "o"),
    (r"[úùûü]", "u"),
    (r"[ç]", "c"),
    (r"[ñ]", "n"),
    (r"[^a-z0-9\s]", ""),
    (r"\s+", " "),
]


def _normalize(text: str) -> str:
    """Normalize text: lowercase, remove accents, collapse whitespace."""
    t = text.lower().strip()
    for pattern, repl in NORMALIZE_PATTERNS:
        t = re.sub(pattern, repl, t)
    return t.strip()


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from a question."""
    t = _normalize(text)
    stopwords = {
        "o", "a", "os", "as", "um", "uma", "uns", "umas",
        "de", "da", "do", "das", "dos", "no", "na", "nos", "nas",
        "em", "para", "por", "com", "sem", "sob", "sobre",
        "e", "ou", "mas", "que", "qual", "quais", "quem",
        "como", "onde", "quando", "porque", "por que",
        "se", "voce", "você", "sua", "seu", "suas", "seus",
        "tem", "possui", "possuiu", "teve", "era", "sao", "estao",
        "sim", "nao", "não", "talvez",
        "ja", "já", "ainda", "sempre", "nunca",
        "trabalha", "trabalhou", "atuou", "atua",
        "experiencia", "experiência",
    }
    keywords = {w for w in t.split() if len(w) > 2 and w not in stopwords}
    return keywords


def _compute_similarity(question1: str, question2: str) -> float:
    """Compute similarity between two questions using keyword overlap."""
    kw1 = _extract_keywords(question1)
    kw2 = _extract_keywords(question2)
    if not kw1 or not kw2:
        return 0.0
    intersection = kw1 & kw2
    union = kw1 | kw2
    return len(intersection) / len(union)


def save_knowledge(question: str, answer: str, source: str = "llm",
                   confidence: float = 1.0, context_tags: str = "") -> int:
    """Save a Q&A pair to the knowledge base.

    If a similar question already exists (>70% overlap), updates it instead.
    Returns the knowledge entry ID.
    """
    conn = get_connection()
    normalized = _normalize(question)
    now = datetime.now(timezone.utc).isoformat()

    # Check for existing similar question
    existing = conn.execute(
        "SELECT id, question, answer, used_count FROM knowledge"
    ).fetchall()

    for row in existing:
        sim = _compute_similarity(normalized, _normalize(row["question"]))
        if sim >= 0.7:
            conn.execute(
                "UPDATE knowledge SET answer = ?, confidence = ?, "
                "source = ?, context_tags = ?, updated_at = ?, "
                "used_count = used_count + 1 WHERE id = ?",
                (answer, confidence, source, context_tags, now, row["id"]),
            )
            conn.commit()
            logger.info("Knowledge updated (id=%d, sim=%.2f, question='%s')",
                        row["id"], sim, question[:40])
            return row["id"]

    conn.execute(
        "INSERT INTO knowledge (question, answer, source, confidence, "
        "context_tags, used_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (question, answer, source, confidence, context_tags, now, now),
    )
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    logger.info("Knowledge saved (id=%d, question='%s')", new_id, question[:40])
    return new_id


def find_answer(question: str, min_similarity: float = 0.5,
                min_confidence: float = 0.0) -> dict | None:
    """Find the best matching answer for a question in the knowledge base.

    Args:
        question: The question text to search for.
        min_similarity: Minimum keyword overlap (0.0-1.0) to consider a match.
        min_confidence: Minimum stored confidence threshold.

    Returns:
        Dict with keys: id, question, answer, confidence, similarity, source
        or None if no match found.
    """
    conn = get_connection()
    normalized = _normalize(question)
    rows = conn.execute(
        "SELECT id, question, answer, confidence, source, used_count "
        "FROM knowledge"
    ).fetchall()

    best = None
    best_sim = 0.0

    for row in rows:
        if row["confidence"] < min_confidence:
            continue
        sim = _compute_similarity(normalized, _normalize(row["question"]))
        if sim > best_sim and sim >= min_similarity:
            best_sim = sim
            best = {
                "id": row["id"],
                "question": row["question"],
                "answer": row["answer"],
                "confidence": row["confidence"],
                "similarity": sim,
                "source": row["source"],
            }

    if best:
        # Increment used_count
        conn.execute(
            "UPDATE knowledge SET used_count = used_count + 1, "
            "updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), best["id"]),
        )
        conn.commit()

    return best


def get_all_knowledge(limit: int = 100) -> list[dict]:
    """Return all knowledge entries, most recently updated first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM knowledge ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def search_knowledge(query: str, limit: int = 10) -> list[dict]:
    """Search knowledge base by keyword similarity."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM knowledge ORDER BY used_count DESC LIMIT ?",
        (limit * 5,),
    ).fetchall()
    scored = []
    for row in rows:
        sim = _compute_similarity(query, row["question"])
        if sim >= 0.3:
            d = dict(row)
            d["similarity"] = sim
            scored.append(d)
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


def delete_knowledge(knowledge_id: int) -> bool:
    """Delete a knowledge entry by ID."""
    conn = get_connection()
    conn.execute("DELETE FROM knowledge WHERE id = ?", (knowledge_id,))
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0] > 0
