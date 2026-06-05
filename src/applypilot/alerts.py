"""Alert system — pending questions that need user input.

When the apply engine encounters a question it can't answer with high
confidence, it creates an alert. The user reviews and answers these alerts
via the web UI. Answers are automatically saved to the knowledge base.
"""

import logging
from datetime import datetime, timezone

from applypilot.database import get_connection

logger = logging.getLogger(__name__)


def create_alert(job_url: str, job_title: str, field_label: str,
                 question: str, context: str = "",
                 suggested_answer: str = "") -> int:
    """Create a new alert for a question the engine couldn't answer.

    Returns the alert ID.
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO alerts (job_url, job_title, field_label, question, "
        "context, suggested_answer, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (job_url, job_title, field_label, question, context,
         suggested_answer, now),
    )
    conn.commit()
    alert_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    logger.info("Alert created (id=%d): %s", alert_id, question[:60])
    return alert_id


def answer_alert(alert_id: int, answer: str) -> bool:
    """Answer a pending alert and optionally save to knowledge base.

    Args:
        alert_id: The alert ID.
        answer: The user's answer.

    Returns:
        True if the alert was found and updated.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM alerts WHERE id = ? AND status = 'pending'",
        (alert_id,),
    ).fetchone()
    if not row:
        logger.warning("Alert %d not found or already answered", alert_id)
        return False

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE alerts SET status = 'answered', answer = ?, "
        "answered_at = ? WHERE id = ?",
        (answer, now, alert_id),
    )

    # Auto-save to knowledge base for future use
    question = row["question"]
    context = row["context"] or ""
    from applypilot.knowledge import save_knowledge
    save_knowledge(question, answer, source="user", confidence=1.0,
                   context_tags=context)

    conn.commit()
    logger.info("Alert %d answered: %s -> %s", alert_id, question[:40], answer[:40])
    return True


def get_pending_alerts(limit: int = 50) -> list[dict]:
    """Get all unanswered alerts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE status = 'pending' "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_all_alerts(limit: int = 100) -> list[dict]:
    """Get all alerts, most recent first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_alert_count() -> int:
    """Get count of pending alerts."""
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE status = 'pending'"
    ).fetchone()[0]


def dismiss_alert(alert_id: int) -> bool:
    """Dismiss an alert without answering."""
    conn = get_connection()
    conn.execute(
        "UPDATE alerts SET status = 'dismissed' WHERE id = ?",
        (alert_id,),
    )
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0] > 0
