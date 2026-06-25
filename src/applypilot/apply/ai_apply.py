"""
AI-powered job application using Playwright CDP + Gemini.

Abordagem: conecta ao Chrome JA ABERTO via porta de debug (CDP).
Voce abre o Chrome normalmente, faz login nos sites, e o agente
se conecta e trabalha na sessao existente.

Como usar:
1. Abra o Chrome com debug habilitado (script launch_chrome.bat)
2. Faca login no LinkedIn, Gupy, etc
3. O agente se conecta e preenche os formularios
4. Quando nao souber uma resposta, cria alerta e pausa
5. Voce responde na UI e o agente continua
"""

import asyncio
import json
import logging
import os
import re
import time
import threading
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR, get_chrome_path, load_env

logger = logging.getLogger(__name__)

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"

# Eventos de pausa: alert_id -> threading.Event
_alert_events: dict[int, threading.Event] = {}
_alert_lock = threading.Lock()


def signal_alert_answered(alert_id: int) -> None:
    """Sinaliza que o usuario respondeu um alerta. Chamado pelo routes.py."""
    with _alert_lock:
        event = _alert_events.get(alert_id)
    if event:
        event.set()
        logger.info("Alert #%d answered - agent resuming", alert_id)


def _wait_for_answer(alert_id: int, timeout: int = 300) -> str | None:
    """Pausa o agente ate o usuario responder ou timeout."""
    event = threading.Event()
    with _alert_lock:
        _alert_events[alert_id] = event

    logger.info("PAUSADO aguardando resposta do alerta #%d (max %ds)...", alert_id, timeout)
    answered = event.wait(timeout=timeout)

    with _alert_lock:
        _alert_events.pop(alert_id, None)

    if not answered:
        logger.info("Alerta #%d: timeout sem resposta", alert_id)
        return None

    try:
        from applypilot.alerts import get_alert
        alert = get_alert(alert_id)
        if alert and alert.get("status") == "answered":
            return alert.get("user_answer", "")
    except Exception as e:
        logger.warning("Erro ao buscar resposta do alerta #%d: %s", alert_id, e)
    return None


def _ask_user(question: str, job_url: str, job_title: str,
              suggested: str = "", options: list | None = None,
              timeout: int = 300) -> str | None:
    """Consulta KB, se nao encontrar cria alerta e pausa."""
    # 1) Checa Knowledge Base
    try:
        from applypilot.knowledge import find_answer
        kb = find_answer(question, min_similarity=0.75, min_confidence=0.7)
        if kb:
            logger.info("KB: '%s' -> '%s'", question[:50], kb["answer"][:50])
            return kb["answer"]
    except Exception:
        pass

    # 2) Cria alerta, notifica Telegram e pausa
    try:
        from applypilot.alerts import create_alert, send_telegram_message
        context = f"Options: {options}" if options else "Campo de texto livre"
        alert_id = create_alert(
            job_url=job_url, job_title=job_title,
            field_label=question, question=question,
            context=context, suggested_answer=suggested,
        )
        logger.info("Alerta #%d criado para: '%s'", alert_id, question[:60])
        # Notifica via Telegram
        tg_text = (
            "🤖 <b>ApplyPilot - Preciso de ajuda</b>\n"
            f"Vaga: {job_title}\n"
            f"Alerta #{alert_id}: {question}\n"
        )
        if suggested:
            tg_text += f"Sugestao: {suggested}\n"
        tg_text += f"\nResponda: applypilot alerts answer {alert_id} <texto>"
        send_telegram_message(tg_text)
    except Exception as e:
        logger.warning("Erro ao criar alerta: %s", e)
        return None

    answer = _wait_for_answer(alert_id, timeout=timeout)

    if answer:
        try:
            from applypilot.knowledge import save_knowledge
            save_knowledge(question, answer, source="user", confidence=1.0,
                           context_tags=f"job:{job_title[:50]}")
        except Exception:
            pass
        return answer

    return None


def _launch_chrome_with_debug():
    """Abre o Chrome com porta de debug se ainda nao estiver aberto."""
    import subprocess, time, urllib.request

    # Checa se ja esta rodando
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
        logger.info("Chrome CDP ja esta rodando na porta %d", CDP_PORT)
        return True
    except Exception:
        pass

    chrome_path = get_chrome_path()
    # Use o mesmo perfil persistente do heuristic para preservar login (LinkedIn, Gupy)
    from applypilot.apply.engine import PERSISTENT_PROFILE_DIR
    profile_dir = PERSISTENT_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
    ]
    logger.info("Abrindo Chrome com debug: %s", " ".join(cmd[:3]))
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Aguarda Chrome iniciar
    for i in range(15):
        time.sleep(1)
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
            logger.info("Chrome CDP pronto na porta %d", CDP_PORT)
            return True
        except Exception:
            pass

    logger.error("Chrome nao iniciou na porta %d", CDP_PORT)
    return False


async def _run_agent(task: str, job_url: str, job: dict,
                     profile: dict, dry_run: bool) -> dict[str, Any]:
    """Executa o agente conectando ao Chrome via CDP."""
    from playwright.async_api import async_playwright

    job_title = job.get("title", "")
    job_site = job.get("site", "unknown")

    async with async_playwright() as p:
        # Conecta ao Chrome ja aberto
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            logger.info("Conectado ao Chrome via CDP")
        except Exception as e:
            logger.error("Falha ao conectar ao Chrome CDP: %s", e)
            return {"status": "failed", "error": f"Chrome nao acessivel em {CDP_URL}. Abra o Chrome com debug habilitado."}

        # Usa contexto existente ou cria novo
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            logger.info("Usando contexto existente do Chrome")
        else:
            context = await browser.new_context()

        # Navega para a URL da vaga
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = await context.new_page()

        try:
            logger.info("Navegando para: %s", job_url)
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            logger.warning("Erro ao navegar: %s", e)

        # Executa o preenchimento com LLM
        result = await _fill_form_with_llm(page, task, job, profile, dry_run)

        # Nao fecha o browser - apenas desconecta
        await browser.close()
        return result


async def _fill_form_with_llm(page, task: str, job: dict,
                               profile: dict, dry_run: bool) -> dict[str, Any]:
    """Usa LLM para analisar a pagina e preencher campos."""
    import base64

    job_title = job.get("title", "")
    job_url = page.url

    llm = _build_llm()
    max_steps = 20
    step = 0

    while step < max_steps:
        step += 1
        logger.info("Step %d/%d - URL: %s", step, max_steps, page.url[:80])

        # Tira screenshot da pagina atual
        try:
            screenshot = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(screenshot).decode()
        except Exception as e:
            logger.warning("Screenshot falhou: %s", e)
            screenshot_b64 = None

        # Extrai texto da pagina para contexto adicional
        try:
            page_text = await page.evaluate("""() => {
                const body = document.body.innerText || '';
                return body.substring(0, 3000);
            }""")
        except Exception:
            page_text = ""

        # Extrai campos do formulario
        try:
            form_fields = await page.evaluate("""() => {
                const fields = [];
                document.querySelectorAll('input, select, textarea, [role="combobox"]').forEach(el => {
                    if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                        const label = el.getAttribute('aria-label') ||
                            el.getAttribute('placeholder') ||
                            el.getAttribute('name') ||
                            document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() || '';
                        fields.push({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || el.tagName.toLowerCase(),
                            id: el.id || '',
                            name: el.name || '',
                            label: label,
                            value: el.value || '',
                            required: el.required || false,
                        });
                    }
                });
                return fields.slice(0, 30);
            }""")
        except Exception:
            form_fields = []

        # Monta prompt para o LLM
        fields_text = json.dumps(form_fields, ensure_ascii=False, indent=2) if form_fields else "Nenhum campo encontrado"

        prompt = f"""Voce esta preenchendo um formulario de candidatura.

TAREFA ORIGINAL:
{task}

PAGINA ATUAL:
URL: {page.url}
Texto visivel: {page_text[:1000]}

CAMPOS DO FORMULARIO:
{fields_text}

INSTRUCOES:
Analise a pagina e retorne um JSON com as acoes a executar.
Formato:
{{
  "status": "in_progress" | "completed" | "failed" | "need_info",
  "message": "descricao do que esta fazendo",
  "actions": [
    {{"type": "fill", "selector": "#campo_id", "value": "valor"}},
    {{"type": "select", "selector": "#select_id", "value": "opcao"}},
    {{"type": "click", "selector": "button:has-text('Continuar')"}},
    {{"type": "upload", "selector": "input[type=file]", "path": "caminho/arquivo.pdf"}},
    {{"type": "ask_user", "question": "pergunta exata do campo", "suggested": "sugestao de resposta"}}
  ]
}}

Se o formulario foi submetido com sucesso, use status "completed".
Se nao ha mais campos para preencher e nao e possivel avancar, use status "failed".
Se precisar de informacao que nao esta no perfil, use action "ask_user".
{'Se status=completed, NAO envie ainda - apenas confirme que esta pronto.' if dry_run else ''}

Responda APENAS com o JSON, sem texto adicional."""

        # Chama o LLM
        try:
            messages = [{"role": "user", "content": prompt}]
            if screenshot_b64:
                # Usa visao se disponivel
                try:
                    response_text = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: llm.invoke([
                            {"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"
                                }}
                            ]}
                        ]).content
                    )
                except Exception:
                    response_text = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: llm.invoke(prompt).content
                    )
            else:
                response_text = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: llm.invoke(prompt).content
                )
        except Exception as e:
            logger.error("LLM falhou: %s", e)
            return {"status": "failed", "error": f"LLM error: {e}"}

        # Parse da resposta
        try:
            # Remove markdown se presente
            clean = re.sub(r'```json\s*|\s*```', '', response_text).strip()
            decision = json.loads(clean)
        except Exception as e:
            logger.warning("JSON parse falhou: %s | resposta: %s", e, response_text[:200])
            decision = {"status": "in_progress", "actions": [], "message": "parse error"}

        logger.info("LLM decision: status=%s msg=%s actions=%d",
                    decision.get("status"), decision.get("message","")[:60],
                    len(decision.get("actions", [])))

        # Verifica status
        if decision.get("status") == "completed":
            if dry_run:
                return {"status": "applied", "message": "Formulario preenchido (dry run)"}
            return {"status": "applied", "message": decision.get("message", "Candidatura enviada")}

        if decision.get("status") == "failed":
            return {"status": "failed", "error": decision.get("message", "Agente nao conseguiu completar")}

        # Executa acoes
        actions = decision.get("actions", [])
        if not actions:
            logger.info("Nenhuma acao retornada, aguardando...")
            await page.wait_for_timeout(2000)
            continue

        for action in actions:
            atype = action.get("type", "")
            selector = action.get("selector", "")

            try:
                if atype == "fill":
                    value = str(action.get("value", ""))
                    if selector:
                        await page.fill(selector, value)
                        logger.info("  fill: %s = '%s'", selector[:50], value[:30])
                    await page.wait_for_timeout(300)

                elif atype == "select":
                    value = str(action.get("value", ""))
                    if selector:
                        try:
                            await page.select_option(selector, label=value)
                        except Exception:
                            try:
                                await page.select_option(selector, value=value)
                            except Exception:
                                # Match parcial
                                await page.evaluate(f"""([sel, val]) => {{
                                    const el = document.querySelector(sel);
                                    if (!el) return;
                                    const opt = Array.from(el.options).find(
                                        o => o.text.toLowerCase().includes(val.toLowerCase())
                                    );
                                    if (opt) {{
                                        el.value = opt.value;
                                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    }}
                                }}""", [selector, value])
                        logger.info("  select: %s = '%s'", selector[:50], value[:30])
                    await page.wait_for_timeout(300)

                elif atype == "click":
                    if selector:
                        await page.click(selector, timeout=5000)
                        logger.info("  click: %s", selector[:60])
                    await page.wait_for_timeout(2000)

                elif atype == "upload":
                    file_path = action.get("path", "")
                    if selector and file_path and Path(file_path).exists():
                        await page.set_input_files(selector, file_path)
                        logger.info("  upload: %s -> %s", selector[:40], Path(file_path).name)
                    await page.wait_for_timeout(500)

                elif atype == "ask_user":
                    question = action.get("question", "")
                    suggested = action.get("suggested", "")
                    if question:
                        logger.info("  ask_user: '%s'", question[:60])
                        answer = _ask_user(
                            question=question,
                            job_url=job_url,
                            job_title=job.get("title", ""),
                            suggested=suggested,
                            timeout=300,
                        )
                        if answer:
                            # Re-analisa a pagina com a nova informacao
                            # Injeta no contexto do proximo step
                            task_extra = f"\nResposta do usuario para '{question}': {answer}"
                            task = task + task_extra
                            logger.info("  resposta recebida: '%s'", answer[:50])
                        else:
                            logger.info("  sem resposta para '%s' - pulando campo", question[:40])

                elif atype == "scroll":
                    await page.evaluate("window.scrollBy(0, 300)")
                    await page.wait_for_timeout(500)

            except Exception as e:
                logger.warning("  Acao '%s' falhou em '%s': %s", atype, selector[:40], e)

        await page.wait_for_timeout(1000)

    return {"status": "failed", "error": "max_steps_reached"}


def _build_llm():
    """Constroi LLM com suporte a visao."""
    load_env()

    if os.environ.get("GEMINI_API_KEY"):
        from langchain_openai import ChatOpenAI
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        logger.info("Usando Gemini: %s", model)
        return ChatOpenAI(
            model=model,
            api_key=os.environ["GEMINI_API_KEY"],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )

    if os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        model = os.environ.get("LLM_MODEL", "gpt-4o")
        logger.info("Usando OpenAI: %s", model)
        return ChatOpenAI(model=model, api_key=os.environ["OPENAI_API_KEY"])

    if os.environ.get("DEEPSEEK_API_KEY"):
        from langchain_openai import ChatOpenAI
        model = os.environ.get("LLM_MODEL", "deepseek-chat")
        logger.info("Usando DeepSeek: %s", model)
        return ChatOpenAI(
            model=model,
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com/v1",
        )

    raise ValueError("Nenhuma API key encontrada no .env")


def _profile_to_task_context(profile: dict) -> str:
    """Converte perfil em texto para o LLM."""
    parts = []
    p = profile.get("personal", {})
    parts.append(f"Nome completo: {p.get('full_name', '')}")
    parts.append(f"Email: {p.get('email', '')}")
    parts.append(f"Telefone: {p.get('phone', '')}")
    parts.append(f"Cidade: {p.get('city', '')}, {p.get('province_state', '')}")
    parts.append(f"Pais: {p.get('country', 'Brasil')}")
    parts.append(f"LinkedIn: {p.get('linkedin_url', '')}")
    parts.append(f"CPF: {p.get('cpf', '')}")

    exp = profile.get("experience", {})
    parts.append(f"Cargo atual: {exp.get('current_job_title', '')}")
    parts.append(f"Empresa atual: {exp.get('current_company', '')}")
    parts.append(f"Anos de experiencia: {exp.get('years_of_experience_total', '')}")
    parts.append(f"Educacao: {exp.get('education_level', '')}")

    comp = profile.get("compensation", {})
    parts.append(f"Pretensao salarial: {comp.get('salary_expectation', '')} {comp.get('salary_currency', 'BRL')}")
    parts.append(f"Disponibilidade: {comp.get('availability', 'imediata')}")

    defaults = profile.get("respostas_padrao", {})
    if defaults:
        parts.append("\nRESPOSTAS PADRAO:")
        for k, v in list(defaults.items())[:15]:
            parts.append(f"  {k}: {v}")

    skills = profile.get("skills_boundary", {})
    all_skills = []
    for v in skills.values():
        if isinstance(v, list):
            all_skills.extend(v)
        elif isinstance(v, str) and v:
            all_skills.append(v)
    if all_skills:
        parts.append(f"Habilidades: {', '.join(all_skills[:20])}")

    about = profile.get("about_resumo", "") or profile.get("summary", "")
    if about:
        parts.append(f"\nSobre: {about[:600]}")

    return "\n".join(parts)


def apply_with_ai(job: dict[str, Any], profile: dict[str, Any],
                  dry_run: bool = False) -> dict[str, Any]:
    """Candidata a uma vaga usando o Chrome aberto via CDP."""
    url = job.get("application_url") or job["url"]
    title = job["title"]
    site = job.get("site", "unknown")
    start = time.time()

    # Garante que o Chrome esta aberto com debug
    if not _launch_chrome_with_debug():
        return {
            "status": "failed",
            "error": "Chrome nao esta acessivel. Execute launch_chrome.bat primeiro.",
            "job_title": title, "site": site, "url": url,
        }

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

    task = f"""Voce esta preenchendo uma candidatura para a vaga '{title}'.
URL: {url}

=== DADOS DO CANDIDATO ===
{profile_text}

=== ARQUIVOS ===
{f'Curriculo PDF: {resume_pdf}' if resume_pdf else 'Sem curriculo PDF'}
{f'Carta de apresentacao: {cover_pdf}' if cover_pdf else 'Sem carta de apresentacao'}

=== REGRAS ===
- Use APENAS informacoes reais do perfil acima
- Se um campo nao tiver informacao no perfil, use action "ask_user"
- NAO invente dados, empresas, datas ou qualificacoes
- Campos opcionais sem informacao: deixe em branco
- {'NAO submeta o formulario - preencha mas nao clique em enviar final' if dry_run else 'Submeta o formulario clicando no botao de envio final'}
"""

    try:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                _run_agent(task, url, job, profile, dry_run)
            )
        finally:
            loop.close()

        elapsed = int((time.time() - start) * 1000)
        result.update({"duration_ms": elapsed, "job_title": title, "site": site, "url": url})
        return result

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        logger.exception("apply_with_ai falhou para %s", title)
        return {"status": "failed", "error": str(e)[:200],
                "duration_ms": elapsed, "job_title": title, "site": site, "url": url}
