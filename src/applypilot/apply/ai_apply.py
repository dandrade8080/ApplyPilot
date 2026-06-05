"""
AI-powered job application using browser-use + LLM.

Browser-use uses an LLM to understand web pages and perform actions.
This module wraps it for our job application pipeline.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from browser_use import Agent, Browser
from langchain_openai import ChatOpenAI
from pydantic import Field


class _CompatChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass with browser-use-compatible provider field."""
    provider: str = Field(default="openai")

from applypilot.config import APP_DIR, get_chrome_path, load_env

logger = logging.getLogger(__name__)

PERSISTENT_PROFILE_DIR = APP_DIR / "patchright_profile"


def _build_llm() -> _CompatChatOpenAI:
    """Build LangChain OpenAI-compatible LLM from our env config."""
    load_env()

    api_key = (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or ""
    )
    base_url = "https://api.deepseek.com/v1"
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    if os.environ.get("OPENAI_API_KEY"):
        base_url = "https://api.openai.com/v1"
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    elif os.environ.get("GEMINI_API_KEY"):
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")

    return _CompatChatOpenAI(model=model, api_key=api_key, base_url=base_url)


def _profile_to_task_context(profile: dict) -> str:
    """Convert profile to a compact text summary for the AI task."""
    parts = []
    personal = profile.get("personal", {})
    parts.append(f"Nome: {personal.get('full_name', '')}")
    parts.append(f"Email: {personal.get('email', '')}")
    parts.append(f"Telefone: {personal.get('phone', '')}")
    parts.append(f"Cidade: {personal.get('city', '')}")
    parts.append(f"LinkedIn: {personal.get('linkedin_url', '')}")

    exp = profile.get("experience", {})
    parts.append(f"Cargo atual: {exp.get('current_job_title', '')}")
    parts.append(f"Empresa atual: {exp.get('current_company', '')}")
    parts.append(f"Anos de experiência: {exp.get('years_of_experience_total', '')}")
    parts.append(f"Nível de educação: {exp.get('education_level', '')}")

    comp = profile.get("compensation", {})
    parts.append(f"Pretensão salarial: {comp.get('salary_expectation', '')}")

    skills = profile.get("skills_boundary", {})
    if skills:
        parts.append(f"Habilidades: {', '.join(skills.values())}")

    about = profile.get("about_resumo", "")
    if about:
        parts.append(f"Sobre: {about[:500]}")

    return "\n".join(parts)


def apply_with_ai(
    job: dict[str, Any],
    profile: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply to a job using AI-powered browser automation (browser-use).

    Runs the browser-use Agent in an async event loop on a background thread.
    """
    url = job.get("application_url") or job["url"]
    title = job["title"]
    site = job.get("site", "unknown")
    start = time.time()

    profile_text = _profile_to_task_context(profile)

    resume_path = job.get("tailored_resume_path") or ""
    resume_pdf = ""
    if resume_path:
        p = Path(resume_path).with_suffix(".pdf")
        if p.exists():
            resume_pdf = str(p)

    cover_path = job.get("cover_letter_path") or ""
    cover_pdf = ""
    if cover_path:
        p = Path(cover_path).with_suffix(".pdf")
        if p.exists():
            cover_pdf = str(p)

    task = f"""Você está em uma página de candidatura de emprego para '{title}'.

INFORMAÇÕES DO CANDIDATO:
{profile_text}

ARQUIVOS DISPONÍVEIS:
{'- Currículo: ' + resume_pdf if resume_pdf else '- Sem currículo'}
{'- Carta de apresentação: ' + cover_pdf if cover_pdf else '- Sem carta de apresentação'}

INSTRUÇÕES:
1. Navegue até a URL de candidatura
2. Preencha todos os campos do formulário com as informações do candidato
3. Faça upload do currículo quando houver campo apropriado
4. Faça upload da carta de apresentação quando houver campo apropriado
5. Responda a quaisquer perguntas de triagem (screening questions)
6. {"NÃO envie o formulário - pare antes de enviar" if dry_run else "Clique no botão de enviar/finalizar para submeter a candidatura"}
7. Confirme se a candidatura foi submetida com sucesso"""

    try:
        result = asyncio.run(_run_agent(task, url, dry_run))
        elapsed = int((time.time() - start) * 1000)
        return {
            "status": result.get("status", "unknown"),
            "message": result.get("message", ""),
            "duration_ms": elapsed,
            "job_title": title,
            "site": site,
            "url": url,
        }
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        logger.exception("AI apply failed for %s", title)
        return {
            "status": "failed",
            "error": str(e)[:200],
            "duration_ms": elapsed,
            "job_title": title,
            "site": site,
            "url": url,
        }


async def _run_agent(task: str, url: str, dry_run: bool) -> dict[str, Any]:
    """Run browser-use agent asynchronously."""
    chrome_path = get_chrome_path()

    browser = Browser(
        headless=False,
        user_data_dir=str(PERSISTENT_PROFILE_DIR),
        executable_path=chrome_path,
        channel="chrome" if "chrome" in chrome_path.lower() else None,
        viewport={"width": 1280, "height": 800},
        disable_security=True,
    )

    llm = _build_llm()

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        max_actions_per_step=5,
        max_failures=3,
    )

    try:
        history = await agent.run(max_steps=80)

        if history.is_successful():
            return {"status": "applied", "message": "Candidatura submetida com sucesso"}
        elif dry_run:
            return {"status": "filled", "message": "Formulário preenchido (dry run)"}
        else:
            return {
                "status": "failed",
                "message": "Agente não conseguiu concluir a candidatura",
            }
    finally:
        await browser.close()
