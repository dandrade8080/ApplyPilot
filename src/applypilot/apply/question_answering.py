"""LLM-powered question answering for screening questions.

Integrated with:
- Knowledge base: checks past answers before calling LLM
- Alert system: creates user alerts when LLM can't answer confidently
"""

import json
import logging
from typing import Any

from applypilot.knowledge import find_answer, save_knowledge
from applypilot.alerts import create_alert

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """You are an assistant that helps fill out job application forms.
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
how confident you are that the answer is correct based on the profile data."""


def _parse_confidence(answer: str) -> tuple[str, float]:
    """Extract confidence from LLM response."""
    import re
    m = re.search(r"CONFIDENCE:\s*([0-9]*\.?[0-9]+)", answer, re.IGNORECASE)
    if m:
        conf = float(m.group(1))
        clean = re.sub(r"(?i)CONFIDENCE:\s*[0-9]*\.?[0-9]+", "", answer).strip()
        return clean, min(max(conf, 0.0), 1.0)
    return answer.strip(), 0.5  # default confidence


def answer_screening_question(
    question: str,
    field_type: str,
    options: list[str],
    profile_text: str,
    resume_text: str,
    job_title: str,
    client,
    job_url: str = "",
) -> str:
    """Answer a screening question using knowledge base first, LLM as fallback.

    1. Check knowledge base for similar questions
    2. If high-confidence match found, reuse it
    3. Otherwise, call LLM
    4. If LLM confidence is low, create an alert
    5. Save answer to knowledge base for future use
    """
    # Step 1: Check knowledge base
    kb_match = find_answer(question, min_similarity=0.5, min_confidence=0.6)
    if kb_match:
        logger.info("QA (knowledge): %s -> %s (sim=%.2f, conf=%.2f)",
                     question[:50], str(kb_match["answer"])[:80],
                     kb_match["similarity"], kb_match["confidence"])
        return kb_match["answer"]

    # Step 2: Call LLM
    options_text = ""
    if options:
        opts = "\n".join(f"  - {o}" for o in options[:50])
        options_text = f"\nAvailable options:\n{opts}\n\nPick the best matching option."

    prompt = f"""Question: {question}
Field type: {field_type}{options_text}
Job applying for: {job_title}

Candidate Profile Summary:
{profile_text[:2000]}

Resume (key sections):
{resume_text[:2000]}

Answer the question using only the candidate's real information above."""

    try:
        messages = [
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response = client.chat(messages)
        answer, confidence = _parse_confidence(response.strip())
        logger.info("QA (LLM): %s -> %s (conf=%.2f)",
                     question[:50], answer[:80], confidence)

        # Step 3: Save to knowledge base
        save_knowledge(question, answer, source="llm",
                       confidence=confidence,
                       context_tags=f"job:{job_title[:50]}")

        # Step 4: Alert if low confidence
        if confidence < 0.6 and job_url:
            create_alert(
                job_url=job_url,
                job_title=job_title,
                field_label=question,
                question=question,
                context=f"LLM confidence was {confidence:.2f}",
                suggested_answer=answer,
            )
            logger.info("Alert created for low-confidence QA: %s", question[:40])

        return answer
    except Exception as e:
        logger.warning("LLM QA failed for '%s': %s", question[:40], e)
        return ""


def generate_standard_answer(
    question_type: str,
    profile: dict[str, Any],
) -> str:
    """Generate answer for common question types without calling LLM."""
    answers = profile.get("respostas_padrao", {})
    if question_type in answers:
        return answers[question_type]

    personal = profile.get("personal", {})
    exp = profile.get("experience", {})

    qt_lower = question_type.lower()

    if "phone" in qt_lower:
        return personal.get("phone", "")
    if "email" in qt_lower:
        return personal.get("email", "")
    if "linkedin" in qt_lower:
        return personal.get("linkedin_url", "")
    if "salary" in qt_lower:
        sal = profile.get("compensation", {}).get("salary_expectation", "")
        cur = profile.get("compensation", {}).get("salary_currency", "BRL")
        return f"{sal} {cur}" if sal else ""
    if "name" in qt_lower:
        return personal.get("full_name", "")
    if "location" in qt_lower or "city" in qt_lower:
        return f"{personal.get('city', '')}, {personal.get('province_state', '')}"
    if "education" in qt_lower:
        return exp.get("education_level", "")
    if "experience" in qt_lower or "years" in qt_lower:
        return exp.get("years_of_experience_total", "")

    return ""
