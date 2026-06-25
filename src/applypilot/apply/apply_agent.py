"""
ApplyAgent -- browser-use 0.1.40 AI agent with self-learning knowledge base
and interactive Telegram notifications.

Flow:
1. Task received --- check knowledge base for known field mappings
2. Run browser-use Agent with persistent Chrome profile
3. If agent needs info --- check KB --- create alert --- notify Telegram
4. User responds via Telegram (or CLI) --- save to KB --- agent continues
5. On success --- save successful strategy as a 'skill'
"""

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from applypilot import config
from applypilot.alerts import create_alert, send_telegram_message, get_alert
from applypilot.knowledge import find_answer, save_knowledge

logger = logging.getLogger(__name__)

PERSISTENT_PROFILE_DIR = config.APP_DIR / 'patchright_profile'

_alert_events: dict[int, threading.Event] = {}
_alert_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Alert signalling (called from webhook / CLI when user answers)
# ---------------------------------------------------------------------------

def signal_alert_answered(alert_id: int) -> None:
    with _alert_lock:
        event = _alert_events.get(alert_id)
    if event:
        event.set()
        logger.info('Alert #%d answered - agent resuming', alert_id)


def _wait_for_answer(alert_id: int, timeout: int = 600) -> str | None:
    event = threading.Event()
    with _alert_lock:
        _alert_events[alert_id] = event
    logger.info(
        'PAUSADO aguardando resposta do alerta #%d (max %ds)...',
        alert_id, timeout,
    )
    answered = event.wait(timeout=timeout)
    with _alert_lock:
        _alert_events.pop(alert_id, None)
    if not answered:
        logger.info('Alerta #%d: timeout sem resposta', alert_id)
        return None
    try:
        alert = get_alert(alert_id)
        if alert and alert.get('status') == 'answered':
            return alert.get('user_answer', '')
    except Exception as e:
        logger.warning('Erro ao buscar resposta do alerta #%d: %s', alert_id, e)
    return None


# ---------------------------------------------------------------------------
# Ask user --- knowledge-base lookup -> alert -> Telegram -> wait -> save
# ---------------------------------------------------------------------------

def _ask_user(
    question: str,
    job_url: str = '',
    job_title: str = '',
    suggested: str = '',
    options: list | None = None,
    timeout: int = 600,
) -> str | None:
    kb = find_answer(question, min_similarity=0.75, min_confidence=0.7)
    if kb:
        logger.info('KB auto-resposta: \'%s\' -> \'%s\'', question[:50], kb['answer'][:50])
        return kb['answer']

    try:
        context = f'Options: {options}' if options else 'Campo de texto livre'
        alert_id = create_alert(
            job_url=job_url,
            job_title=job_title,
            field_label=question,
            question=question,
            context=context,
            suggested_answer=suggested,
        )
        logger.info('Alerta #%d criado para: \'%s\'', alert_id, question[:60])
        tg_text = (
            '\U0001f916 <b>ApplyPilot - Preciso de ajuda</b>\n'
            f'Vaga: <a href=\'{job_url}\'>{job_title}</a>\n'
            f'Alerta #{alert_id}: {question}\n'
        )
        if suggested:
            tg_text += f'Sugestao: {suggested}\n'
        tg_text += (
            '\nResponda neste chat:\n'
            f'<code>/answer {alert_id} sua resposta aqui</code>'
        )
        send_telegram_message(tg_text)
    except Exception as e:
        logger.warning('Erro ao criar alerta: %s', e)
        return None

    answer = _wait_for_answer(alert_id, timeout=timeout)
    if answer:
        try:
            save_knowledge(
                question,
                answer,
                source='user',
                confidence=1.0,
                context_tags=f'job:{job_title[:50]}',
            )
            logger.info('Knowledge saved: \'%s\' -> \'%s\'', question[:40], answer[:40])
        except Exception:
            pass
        return answer
    return None


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _build_llm() -> Any:
    config.load_env()

    # Try Gemini if user explicitly configured it (uncommented env var)
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key:
        from browser_use.llm.google.chat import ChatGoogle
        return ChatGoogle(model='gemini-2.0-flash', api_key=gemini_key, temperature=0.2)

    # Default: use ChatDeepSeek natively (handles JSON function-calling correctly)
    from browser_use.llm.deepseek.chat import ChatDeepSeek
    api_key = (
        os.environ.get('DEEPSEEK_API_KEY')
        or os.environ.get('OPENAI_API_KEY')
        or ''
    )
    base_url = 'https://api.deepseek.com/v1'
    model = os.environ.get('LLM_MODEL', 'deepseek-chat')
    if os.environ.get('OPENAI_API_KEY'):
        base_url = 'https://api.openai.com/v1'
        model = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model, api_key=api_key, base_url=base_url,
            temperature=0.2, max_completion_tokens=8192,
        )

    return ChatDeepSeek(model=model, api_key=api_key, base_url=base_url)


# ---------------------------------------------------------------------------
# Profile -> task context text
# ---------------------------------------------------------------------------

def _profile_to_task_context(profile: dict) -> str:
    parts: list[str] = []
    personal = profile.get('personal', {})
    parts.append(f"Nome: {personal.get('full_name', '')}")
    parts.append(f"CPF: {personal.get('cpf', '')}")
    parts.append(f"Email: {personal.get('email', '')}")
    parts.append(f"Telefone: {personal.get('phone', '')}")
    parts.append(f"Data nascimento: {personal.get('birth_date', '')}")
    parts.append(f"Genero: {personal.get('gender', '')}")
    parts.append(f"Cidade: {personal.get('city', '')}/{personal.get('province_state', '')}")
    parts.append(f"Endereco: {personal.get('address', '')}, {personal.get('neighborhood', '')}, CEP {personal.get('postal_code', '')}")
    parts.append(f"LinkedIn: {personal.get('linkedin_url', '')}")
    parts.append(f"Portfolio: {personal.get('portfolio_url', '')}")

    exp = profile.get('experience', {})
    parts.append(f"Cargo atual: {exp.get('current_job_title', '')}")
    parts.append(f"Empresa atual: {exp.get('current_company', '')}")
    parts.append(f"Anos de experiencia: {exp.get('years_of_experience_total', '')}")
    parts.append(f"Nivel de educacao: {exp.get('education_level', '')}")

    comp = profile.get('compensation', {})
    parts.append(
        f"Pretensao salarial: {comp.get('salary_expectation', '')} "
        f"{comp.get('salary_currency', '')}"
    )

    wa = profile.get('work_authorization', {})
    if wa.get('legally_authorized_to_work') == 'Yes':
        parts.append('Autorizado a trabalhar no Brasil: Sim')
    if wa.get('require_sponsorship') == 'No':
        parts.append('Nao precisa de sponsorship')

    skills = profile.get('skills_boundary', {})
    all_skills: list[str] = []
    for v in skills.values():
        if isinstance(v, list):
            all_skills.extend(str(s) for s in v if s)
        elif isinstance(v, str) and v:
            all_skills.append(v)
    if all_skills:
        parts.append(f"Habilidades: {', '.join(all_skills[:20])}")

    respostas = profile.get('respostas_padrao', {})
    if respostas:
        parts.append('\n--- Respostas padrao ---')
        for k, v in respostas.items():
            if v:
                label = k.replace('_', ' ').title()
                parts.append(f'{label}: {v}')

    about = profile.get('about_resumo', '') or profile.get('summary', '')
    if about:
        parts.append(f'\nSobre: {about[:600]}')

    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Browser-use Agent runner
# ---------------------------------------------------------------------------

async def _run_agent(
    task: str,
    url: str,
    profile: dict,
    dry_run: bool,
    job_title: str,
    sensitive_data: dict[str, str] | None = None,
    available_file_paths: list[str] | None = None,
) -> dict[str, Any]:
    from browser_use import Agent, Controller, ActionResult, BrowserProfile, BrowserSession

    chrome_path = config.get_chrome_path()
    llm = _build_llm()

    # Register custom ask_user tool for the LLM
    controller = Controller()

    @controller.action(
        'Ask the user for missing information. '
        'Use this when you need data NOT present in the profile or resume. '
        'Parameter "question" is the question to ask the user in Portuguese.'
    )
    def ask_user(question: str):
        response = _ask_user(
            question=question,
            job_url=url,
            job_title=job_title,
            timeout=600,
        )
        if response is None:
            return ActionResult(extracted_content='No response received from user within timeout.')
        return ActionResult(extracted_content=f'User response: {response}')

    # Configure persistent browser profile
    browser_profile = BrowserProfile(
        user_data_dir=str(PERSISTENT_PROFILE_DIR),
        executable_path=chrome_path,
        headless=False,
        highlight_elements=True,
    )

    agent = Agent(
        task=task,
        llm=llm,
        controller=controller,
        browser_profile=browser_profile,
        sensitive_data=sensitive_data,
        available_file_paths=available_file_paths,
        use_vision=False,
        use_thinking=True,
        generate_gif=False,
        max_actions_per_step=5,
        max_failures=5,
        step_timeout=900,
    )

    history = await agent.run(max_steps=100)
    if history.is_successful():
        result = {
            'status': 'applied',
            'message': 'Candidatura submetida com sucesso',
        }
    elif dry_run:
        result = {
            'status': 'filled',
            'message': 'Formulario preenchido (dry run)',
        }
    else:
        result = {
            'status': 'failed',
            'message': 'Agente nao conseguiu concluir',
        }
    return result


# ---------------------------------------------------------------------------
# Public entry point (synchronous, called from launcher)
# ---------------------------------------------------------------------------

def apply_with_agent(
    job: dict[str, Any],
    profile: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    url = job.get('application_url') or job['url']
    title = job['title']
    site = job.get('site', 'unknown')
    start = time.time()

    profile_text = _profile_to_task_context(profile)

    resume_path = job.get('tailored_resume_path') or ''
    resume_pdf = ''
    if resume_path:
        p = Path(resume_path).with_suffix('.pdf')
        if p.exists():
            resume_pdf = str(p)

    cover_path = job.get('cover_letter_path') or ''
    cover_pdf = ''
    if cover_path:
        p = Path(cover_path).with_suffix('.pdf')
        if p.exists():
            cover_pdf = str(p)

    sensitive = {}
    pwd = profile.get('personal', {}).get('password', '')
    if pwd:
        sensitive['SENHA'] = pwd
    pwd2 = profile.get('personal', {}).get('password_fallback', '')
    if pwd2:
        sensitive['SENHA_FALLBACK'] = pwd2

    _pdf_resume = f"Curriculo PDF: {resume_pdf}" if resume_pdf else "Sem curriculo PDF"
    _pdf_cover = f"Carta de apresentacao: {cover_pdf}" if cover_pdf else "Sem carta de apresentacao"
    _submit_inst = "NAO envie o formulario - apenas preencha" if dry_run else "Submeta o formulario apos preencher tudo"

    task = (
        f"Voce esta preenchendo uma candidatura para a vaga '{title}'.\n"
        f"URL da vaga: {url}\n"
        "\n"
        "=== DADOS DO CANDIDATO ===\n"
        f"{profile_text}\n"
        "\n"
        "=== ARQUIVOS ===\n"
        f"{_pdf_resume}\n"
        f"{_pdf_cover}\n"
        "\n"
        "=== INSTRUCOES ===\n"
        "1. Navegue ate a URL da vaga\n"
        "2. Clique no botao de candidatura (Candidatar-se, Easy Apply, etc.)\n"
        "3. Preencha todos os campos do formulario com os dados do candidato\n"
        "4. Se o formulario pedir login e voce nao estiver logado:\n"
        "   a) PRIMEIRO: tente 'Entrar com LinkedIn' se disponivel\n"
        "   b) SEGUNDO: tente 'Entrar com Google' se disponivel\n"
        "   c) TERCEIRO: preencha email e senha manualmente (use SENHA)\n"
        "5. Faca upload do curriculo e carta de apresentacao nos campos apropriados\n"
        "6. Responda as perguntas de triagem com os dados do perfil\n"
        f"7. {_submit_inst}\n"
        "8. Confirme se a candidatura foi submetida com sucesso\n"
        "\n"
        "=== REGRAS IMPORTANTES ===\n"
        "- Use APENAS informacoes reais do perfil acima\n"
        "- Se faltar informacao para um campo, use a funcao ask_user\n"
        "- Para campos de senha, use SENHA (ou SENHA_FALLBACK se a primeira nao funcionar)\n"
        "- NAO invente dados\n"
        "- Para perguntas de selecao, use as respostas padrao do perfil\n"
        "- Se encontrar reCAPTCHA, Cloudflare Turnstile ou qualquer verificacao humana,\n"
        "  use ask_user para notificar o usuario imediatamente\n"
        "- Nao passe por CAPTCHAs sozinho - sempre avise o usuario\n"
        "- Se um banner de cookies aparecer e estiver bloqueando o formulario, feche-o\n"
        "  imediatamente (clique em 'Rejeitar', 'Recusar', 'Fechar', ou no X).\n"
        "  Se nao conseguir fechar apos 3 tentativas, use ask_user para avisar."
    )

    available_files = [p for p in [resume_pdf, cover_pdf] if p]

    try:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                _run_agent(task, url, profile, dry_run, title, sensitive, available_files),
            )
        finally:
            loop.close()

        elapsed = int((time.time() - start) * 1000)
        result.update({
            'duration_ms': elapsed,
            'job_title': title,
            'site': site,
            'url': url,
        })
        return result

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        logger.exception('apply_with_agent falhou para %s', title)
        return {
            'status': 'failed',
            'error': str(e)[:200],
            'duration_ms': elapsed,
            'job_title': title,
            'site': site,
            'url': url,
        }
