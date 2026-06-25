"""Alert system - pending questions that need user input."""
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from applypilot.database import get_connection

logger = logging.getLogger(__name__)


def _get_tg_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _get_tg_chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_USER_ID", ""))


def create_alert(job_url: str, job_title: str, field_label: str,
                 question: str, context: str = "",
                 suggested_answer: str = "") -> int:
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO alerts (job_url, job_title, field_label, question, "
        "context, suggested_answer, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (job_url, job_title, field_label, question, context, suggested_answer, now),
    )
    conn.commit()
    alert_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    logger.info("Alert created (id=%d): %s", alert_id, question[:60])
    return alert_id


def answer_alert(alert_id: int, answer: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM alerts WHERE id = ? AND status = 'pending'", (alert_id,)
    ).fetchone()
    if not row:
        logger.warning("Alert %d not found or already answered", alert_id)
        return False
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE alerts SET status = 'answered', answer = ?, answered_at = ? WHERE id = ?",
        (answer, now, alert_id),
    )
    from applypilot.knowledge import save_knowledge
    save_knowledge(row["question"], answer, source="user", confidence=1.0,
                   context_tags=row["context"] or "")
    conn.commit()
    logger.info("Alert %d answered: %s -> %s", alert_id, row["question"][:40], answer[:40])
    return True


def get_alert(alert_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT *, answer AS user_answer FROM alerts WHERE id = ?", (alert_id,)
    ).fetchone()
    return dict(row) if row else None


def get_pending_alerts(limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_all_alerts(limit: int = 100) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_alert_count() -> int:
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE status = 'pending'"
    ).fetchone()[0]


def dismiss_alert(alert_id: int) -> bool:
    conn = get_connection()
    conn.execute("UPDATE alerts SET status = 'dismissed' WHERE id = ?", (alert_id,))
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0] > 0


def format_pending_alerts(limit: int = 50) -> str:
    rows = get_pending_alerts(limit=limit)
    if not rows:
        return "Sem alertas pendentes."
    lines = [f"Alertas pendentes ({len(rows)}):", ""]
    for r in rows:
        lines.append(f"[{r['id']}] {r['job_title']}")
        lines.append(f"   Pergunta: {r['question']}")
        if r.get("suggested_answer"):
            lines.append(f"   Sugestão: {r['suggested_answer']}")
        lines.append(f"   URL: {r['job_url']}")
        lines.append("")
    lines.append("Para responder, use: applypilot alerts answer <id> <texto>")
    return "\n".join(lines)


def dismiss_all_alerts() -> int:
    conn = get_connection()
    cur = conn.execute(
        "UPDATE alerts SET status = 'dismissed' WHERE status = 'pending'"
    )
    conn.commit()
    return cur.rowcount


def send_telegram_message(text: str, chat_id: str = "") -> bool:
    token = _get_tg_token()
    cid = chat_id or _get_tg_chat_id()
    if not token or not cid:
        logger.debug("telegram not configured (bot_token/chat_id missing)")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": cid,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, data=payload, timeout=15)
        ok = r.status_code == 200 and r.json().get("ok")
        if not ok:
            logger.debug("telegram send failed: %s %s", r.status_code, r.text[:200])
        return ok
    except Exception as exc:
        logger.debug("telegram send error: %s", exc)
        return False


def notify_pending_alerts(limit: int = 10, chat_id: str = "") -> dict:
    rows = get_pending_alerts(limit=limit)
    if not rows:
        return {"sent": 0, "message": "Sem alertas pendentes."}
    sent = 0
    for r in rows:
        text = (
            "🚨 <b>Alerta ApplyPilot</b>\n"
            f"Vaga: <a href='{r['job_url']}'>{r['job_title']}</a>\n"
            f"Pergunta: {r['question']}\n"
        )
        if r.get("suggested_answer"):
            text += f"Sugestão: {r['suggested_answer']}\n"
        text += "\nResponda: <code>applypilot alerts answer {r['id']} sua resposta</code>"
        if send_telegram_message(text, chat_id=chat_id):
            sent += 1
    return {"sent": sent, "total": len(rows)}


def notify_apply_result(status: str = "failed", *, job_title: str = "", site: str = "", url: str = "", error: str = "", chat_id: str = "") -> bool:
    if not _get_tg_token():
        return False
    try:
        text = (
            "🤖 <b>ApplyPilot</b>\n"
            f"Status: <b>{status}</b>\n"
        )
        if job_title:
            text += f"Vaga: {job_title}\n"
        if site:
            text += f"Site: {site}\n"
        if url:
            text += f"URL: {url}\n"
        if error:
            text += f"Erro: {error}\n"
        button = urllib.parse.quote_plus("applypilot alerts answer 1 sim")
        text += (
            f"\nResponda a pendência: <code>applypilot alerts answer 1 sim</code>"
        )
        return send_telegram_message(text, chat_id=chat_id)
    except Exception as exc:
        logger.debug("notify_apply_result failed: %s", exc)
        return False


def get_alert_settings() -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_USER_ID") or ""
    notify = bool(token and chat_id)
    return {
        "notify": notify,
        "token_configured": bool(token),
        "chat_id_configured": bool(chat_id),
    }