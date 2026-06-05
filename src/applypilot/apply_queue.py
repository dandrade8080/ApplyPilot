"""Apply queue — batch job application queuing system.

Jobs in the apply queue are processed one at a time by the background worker.
Status options: queued, processing, completed, failed, cancelled.
"""

import logging
from datetime import datetime, timezone

from applypilot.database import get_connection

logger = logging.getLogger(__name__)


def enqueue_job(job_url: str, job_title: str, job_id: str = "",
                site: str = "") -> int:
    """Add a job to the apply queue. Returns the queue entry ID."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    # Check if already queued/pending
    existing = conn.execute(
        "SELECT id FROM apply_queue WHERE job_url = ? AND status IN ('queued','processing')",
        (job_url,),
    ).fetchone()
    if existing:
        logger.info("Job %s already queued (id=%d)", job_url[:40], existing["id"])
        return existing["id"]

    conn.execute(
        "INSERT INTO apply_queue (job_url, job_title, status, "
        "created_at) VALUES (?, ?, 'queued', ?)",
        (job_url, job_title, now),
    )
    conn.commit()
    qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    logger.info("Enqueued job %s (qid=%d)", job_url[:40], qid)
    return qid


def dequeue_next() -> dict | None:
    """Get the next pending job from the queue and mark it as processing.

    Returns the queue entry dict or None if queue is empty.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM apply_queue WHERE status = 'queued' "
        "ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if not row:
        return None

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE apply_queue SET status = 'processing', started_at = ? WHERE id = ?",
        (now, row["id"]),
    )
    conn.commit()
    return dict(row)


def complete_queue_entry(qid: int, result: dict):
    """Mark a queue entry as completed or failed based on result."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    status = "completed" if result.get("status") == "applied" else "failed"
    error = result.get("error", "")
    conn.execute(
        "UPDATE apply_queue SET status = ?, error = ?, result = ?, "
        "finished_at = ? WHERE id = ?",
        (status, error, str(result), now, qid),
    )
    conn.commit()


def get_queue(limit: int = 50) -> list[dict]:
    """Get all queue entries, most recent first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM apply_queue ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_queue_counts() -> dict:
    """Get counts by status."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM apply_queue GROUP BY status"
    ).fetchall()
    counts = {r["status"]: r["cnt"] for r in rows}
    return {
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "total": sum(counts.values()),
    }


def clear_queue(status: str = "") -> int:
    """Clear queue entries. If status is given, clear only entries with that status."""
    conn = get_connection()
    if status:
        conn.execute("DELETE FROM apply_queue WHERE status = ?", (status,))
    else:
        conn.execute("DELETE FROM apply_queue")
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0]


def cancel_queue_entry(qid: int) -> bool:
    """Cancel a queued entry."""
    conn = get_connection()
    conn.execute(
        "UPDATE apply_queue SET status = 'cancelled' WHERE id = ? AND status = 'queued'",
        (qid,),
    )
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0] > 0
