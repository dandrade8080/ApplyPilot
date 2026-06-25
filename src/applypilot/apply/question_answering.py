"""LLM-backed screening Q&A with persistent knowledge-base recall and alerting."""

import logging
import re
from typing import Any

from applypilot.alerts import create_alert
from applypilot.knowledge import find_answer, save_knowledge
from applypilot.llm import get_client

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """
You are an assistant that helps fill out job application forms.
You will be given:
1. A question from a job application form (label + field type)
2. The candidate's full profile (work history, skills, education, etc.)
3. The job description (if available)

Your job: Answer the question using ONLY information from the candidate's profile.
Do NOT invent experience, skills, or credentials. If the profile doesn't
have the information to answer the question, say that honestly.

Rules:
- Answer in the same language as the question (Portuguese or English)
- Be concise but complete
- For multiple-choice questions, pick the BEST matching option
- For text questions, write 1-3 sentences
- Never fabricate

After your answer, add a line with CONFIDENCE: <0.0-1.0> indicating
how confident you are that the answer is correct based on the profile data.
"""


def _parse_confidence(answer: str) -> tuple[str, float]:
    m = re.search(r"CONFIDENCE:\s*([0-9]*\.?[0-9]+)", answer, re.IGNORECASE)
    if m:
        conf = float(m.group(1))
        clean = re.sub(r"(?i)CONFIDENCE:\s*[0-9]*\.?[0-9]+", "", answer).strip()
        return clean, min(max(conf, 0.0), 1.0)
    return answer.strip(), 0.5


def _normalize(text: str) -> str:
    if not text:
        return ""
    t = str(text).lower()
    t = re.sub(r"[áàâãä]", "a", t)
    t = re.sub(r"[éèêë]", "e", t)
    t = re.sub(r"[íìîï]", "i", t)
    t = re.sub(r"[óòôõö]", "o", t)
    t = re.sub(r"[úùûü]", "u", t)
    t = re.sub(r"[ç]", "c", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _compute_similarity(question1: str, question2: str) -> float:
    t1 = _normalize(question1)
    t2 = _normalize(question2)
    if not t1 or not t2:
        return 0.0
    keywords1 = set(t1.split())
    keywords2 = set(t2.split())
    stop = {
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos",
        "no", "na", "nos", "nas", "em", "para", "por", "com", "sem", "sob", "sobre",
        "e", "ou", "mas", "que", "qual", "quais", "quem", "como", "onde", "quando",
        "porque", "por que", "se", "voce", "você", "sua", "seu", "suas", "seus", "tem",
        "possui", "teve", "era", "sao", "estao", "sim", "nao", "não", "ja", "já",
        "ainda", "sempre", "nunca", "trabalha", "trabalhou", "atuou", "atua",
        "experiencia", "experiência",
    }
    k1 = keywords1 - stop
    k2 = keywords2 - stop
    if not k1 or not k2:
        if not t1 or not t2:
            return 0.0
        if t1 in t2 or t2 in t1:
            return 0.7
        return 0.0
    return len(k1 & k2) / len(k1 | k2)


def answer_screening_question(
    question: str,
    field_type: str,
    options: list[str],
    profile_text: str,
    resume_text: str,
    job_title: str,
    client: Any,
    job_url: str = "",
) -> str:
    try:
        matches = find_answer(question, min_similarity=0.55, min_confidence=0.6)
    except Exception as recall_exc:
        logger.debug("knowledge recall failed: %s", recall_exc)
        matches = None

    if matches:
        answer = matches.get("answer") or ""
        confidence = float(matches.get("confidence") or 0.6)
        logger.info("QA (knowledge): %s -> %s (conf=%.2f)", question[:50], answer[:80], confidence)
        if confidence >= 0.75:
            return answer
        if confidence >= 0.6 and answer:
            return answer

    options_text = ""
    if options:
        opts = "\n".join(f"  - {o}" for o in options[:50])
        options_text = f"\nAvailable options:\n{opts}\nPick the best matching option."

    prompt = (
        f"Question: {question}\n"
        f"Field type: {field_type}{options_text}\n"
        f"Job applying for: {job_title}\n\n"
        f"Candidate Profile Summary:\n{(profile_text or '')[:2000]}\n\n"
        f"Resume (key sections):\n{(resume_text or '')[:2000]}\n\n"
        f"Answer the question using only the candidate's real information above."
    )

    try:
        messages = [
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response = client.chat(messages)
        answer, confidence = _parse_confidence(response.strip())
        logger.info("QA (LLM): %s -> %s (conf=%.2f)", question[:50], answer[:80], confidence)
    except Exception as e:
        logger.warning("LLM QA failed for '%s': %s", question[:40], e)
        return ""

    try:
        save_knowledge(
            question,
            answer,
            source="llm",
            confidence=confidence,
            context_tags=f"job:{job_title[:50]}",
        )
    except Exception as save_exc:
        logger.debug("knowledge save failed: %s", save_exc)

    if confidence < 0.6 and job_url:
        try:
            alert_id = create_alert(
                job_url=job_url,
                job_title=job_title,
                field_label=question,
                question=question,
                context=f"LLM confidence was {confidence:.2f}",
                suggested_answer=answer,
            )
            logger.info("Alert created for low-confidence QA: %s", question[:40])
            # Notifica via Telegram
            from applypilot.alerts import send_telegram_message
            tg_text = (
                "🤖 <b>ApplyPilot - Preciso de ajuda</b>\n"
                f"Vaga: {job_title}\n"
                f"Alerta #{alert_id}: {question}\n"
            )
            if answer:
                tg_text += f"Sugestao: {answer}\n"
            tg_text += f"\nResponda: applypilot alerts answer {alert_id} <texto>"
            send_telegram_message(tg_text)
        except Exception as alert_exc:
            logger.debug("alert creation/notification failed: %s", alert_exc)

    return answer


def generate_standard_answer(
    question_type: str,
    profile: dict[str, Any],
) -> str:
    answers = profile.get("respostas_padrao", {})
    if question_type in answers:
        return answers[question_type]

    personal = profile.get("personal", {})
    exp = profile.get("experience", {})

    qt = question_type.lower()

    if "phone" in qt:
        return personal.get("phone", "")
    if "email" in qt:
        return personal.get("email", "")
    if "linkedin" in qt:
        return personal.get("linkedin_url", "")
    if "salary" in qt:
        sal = profile.get("compensation", {}).get("salary_expectation", "")
        cur = profile.get("compensation", {}).get("salary_currency", "BRL")
        return f"{sal} {cur}".strip() if sal else ""
    if "name" in qt:
        return personal.get("full_name", "")
    if "location" in qt or "city" in qt:
        return f"{personal.get('city', '')}, {personal.get('province_state', '')}"
    if "education" in qt:
        return exp.get("education_level", "")
    if "experience" in qt or "years" in qt:
        return exp.get("years_of_experience_total", "")

    return ""
