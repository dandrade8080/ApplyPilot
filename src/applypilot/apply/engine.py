"""Auto-apply engine using Patchright for stealth automation."""

import json
import logging
import os
import re
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Any

from applypilot import config
from applypilot.apply.form_detector import (
    detect_form_fields,
    detect_form_type,
    find_apply_button,
    find_submit_button,
)
from applypilot.apply.field_matcher import resolve_label, resolve_yes_no

logger = logging.getLogger(__name__)

PERSISTENT_PROFILE_DIR = config.APP_DIR / "patchright_profile"
APPLY_TIMEOUT = 120_000


def safe_evaluate(page, js_code, default=None):
    """Evaluate JS on a page, returning default on connection errors."""
    try:
        return page.evaluate(js_code)
    except Exception as exc:
        if "Connection closed" in str(exc) or "Target closed" in str(exc):
            return default
        raise


def _kill_zombie_chrome():
    """Kill Chrome processes that are not the main user browser (started recently by us)."""
    import subprocess, time
    try:
        result = subprocess.run(
            'wmic process where "name=\'chrome.exe\'" get ProcessId,CommandLine /format:csv',
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "patchright_profile" in line.lower() or "no-first-run" in line.lower():
                parts = line.split(",")
                for p in parts:
                    p = p.strip()
                    if p.isdigit():
                        subprocess.run(f"taskkill /F /PID {p} 2>nul", shell=True, capture_output=True)
                        time.sleep(0.3)
    except Exception:
        pass


def launch_browser():
    """Launch Patchright browser with persistent profile and stealth."""
    from patchright.sync_api import sync_playwright

    PERSISTENT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _kill_zombie_chrome()

    manager = sync_playwright()
    pw = manager.__enter__()
    chrome_path = config.get_chrome_path()

    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(PERSISTENT_PROFILE_DIR),
        channel="chrome" if "chrome" in chrome_path.lower() else None,
        executable_path=chrome_path,
        headless=False,
        viewport={"width": 1280, "height": 800},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        permissions=[],
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--noerrdialogs",
            "--password-store=basic",
            "--deny-permission-prompts",
            "--disable-notifications",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )

    page = context.new_page()
    page.set_default_timeout(APPLY_TIMEOUT)

    return manager, pw, context, page



def _dismiss_cookie_banners(page):
    """Try to dismiss common cookie consent banners on external ATS pages."""
    import re
    from applypilot.apply.form_detector import find_submit_button

    for selector in [
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept all')",
        "button:has-text('Accept cookies')",
        "button:has-text('Allow all')",
        "button:has-text('Permitir')",
        "button:has-text('Aceitar')",
        "button:has-text('OK')",
        "[class*='cookie'] button",
        "[id*='cookie'] button",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass


def _dismiss_overlays(page):
    """Dismiss common welcome/overlay dialogs (Gupy, etc.) with polling.
    
    Falls back to navigating directly to /curriculum URL if overlay controls
    navigation.
    """
    import time
    deadline = time.time() + 30
    texts = ["Continuar", "Continue", "Prosseguir", "Proceed"]
    while time.time() < deadline:
        for text in texts:
            try:
                clicked = page.evaluate(f"""() => {{
                    const all = document.querySelectorAll('button');
                    for (const el of all) {{
                        const t = el.textContent.trim();
                        if ((t === '{text}' || t === '{text.lower()}') && el.offsetWidth > 0 && el.offsetHeight > 0) {{
                            console.log('Dismiss: clicking', t);
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }}""")
                if clicked:
                    page.wait_for_timeout(3000)
                    if "/curriculum" in page.url:
                        return
                    # Check if the button is gone now
                    still_visible = page.evaluate(f"""() => {{
                        return Array.from(document.querySelectorAll('button')).some(b =>
                            (b.textContent.trim() === '{text}' || b.textContent.trim() === '{text.lower()}') &&
                            b.offsetWidth > 0 && b.offsetHeight > 0);
                    }}""")
                    if not still_visible:
                        return  # overlay dismissed, no navigation needed
            except Exception:
                pass
        page.wait_for_timeout(500)
    logger.info("Dismiss overlays: timeout after 30s (URL: %s)", page.url[:80])
    # Fallback: navigate directly to /curriculum
    if "/steps/" in page.url and "/curriculum" not in page.url:
        try:
            base = page.url.rstrip("/")
            page.goto(base + "/curriculum", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
        page.wait_for_timeout(500)
    # Fallback: try navigating directly to /curriculum
    if "/steps/" in page.url and "/curriculum" not in page.url:
        try:
            page.goto(page.url + "/curriculum", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
        except Exception:
            pass


def close_browser(manager, pw, context):
    """Safely close the browser and kill zombie processes."""
    import subprocess, time
    try:
        context.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass
    try:
        manager.__exit__(None, None, None)
    except Exception:
        pass
    # Kill any remaining Chrome processes launched by us
    try:
        result = subprocess.run(
            'wmic process where "name=\'chrome.exe\'" get ProcessId,CommandLine /format:csv',
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "patchright_profile" in line.lower() or "no-first-run" in line.lower():
                parts = line.split(",")
                for p in parts:
                    p = p.strip()
                    if p.isdigit():
                        subprocess.run(f"taskkill /F /PID {p} 2>nul", shell=True, capture_output=True)
                        time.sleep(0.3)
    except Exception:
        pass


def apply_to_job(job: dict, profile: dict, dry_run: bool = False) -> dict:
    """Apply to a single job. Uses AI-powered browser automation (browser-use)
    as primary method, with heuristic fallback for compatibility."""
    try:
        from applypilot.apply.ai_apply import apply_with_ai
        logger.info("AI apply: starting for '%s'", job.get("title", ""))
        return apply_with_ai(job, profile, dry_run=dry_run)
    except Exception as ai_err:
        logger.warning("AI apply failed, falling back to heuristic: %s", ai_err)
        return _legacy_apply_to_job(job, profile, dry_run=dry_run)


def _legacy_apply_to_job(job: dict, profile: dict, dry_run: bool = False) -> dict:
    """Heuristic-based apply (original method). Kept as fallback."""
    from applypilot.apply.field_matcher import resolve_label, resolve_yes_no
    from applypilot.apply.form_detector import (
        detect_form_fields,
        detect_form_type,
        find_apply_button,
        find_submit_button,
    )
    from applypilot.apply.question_answering import (
        answer_screening_question,
        generate_standard_answer,
    )
    from applypilot.llm import get_client

    url = job.get("application_url") or job["url"]
    title = job["title"]
    site = job.get("site", "unknown")

    resume_text = ""
    resume_path = job.get("tailored_resume_path") or ""
    if resume_path:
        txt = Path(resume_path).with_suffix(".txt")
        if txt.exists():
            resume_text = txt.read_text(encoding="utf-8")
    pdf_path = ""
    if resume_path:
        p = Path(resume_path).with_suffix(".pdf")
        if p.exists():
            pdf_path = str(p)

    cl_path = job.get("cover_letter_path") or ""
    cl_pdf = ""
    if cl_path:
        p = Path(cl_path).with_suffix(".pdf")
        if p.exists():
            cl_pdf = str(p)

    profile_text = _profile_to_text(profile)
    llm_client = get_client()

    manager, pw, context, page = None, None, None, None
    start = time.time()

    try:
        manager, pw, context, page = launch_browser()
        _human_delay( 0.5, 1.5)

        logger.info("Navigating to: %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        _human_delay( 0.5, 1.0)

        # Detect form type
        form_type = detect_form_type(page)
        logger.info("Detected form type: %s", form_type)

        # Handle LinkedIn Easy Apply
        if form_type == "linkedin_easy_apply":
            result = _handle_linkedin_easy_apply(
                page, profile, profile_text, resume_text, pdf_path,
                cl_pdf, title, dry_run, llm_client
            )
        elif form_type == "gupy":
            result = _handle_gupy(
                page, profile, profile_text, resume_text, pdf_path,
                cl_pdf, title, dry_run, llm_client
            )
        elif form_type == "indeed":
            result = _handle_indeed_apply(
                page, profile, profile_text, resume_text, pdf_path,
                cl_pdf, title, dry_run, llm_client
            )
        else:
            # Generic form handling
            result = _handle_generic_apply(
                page, profile, profile_text, resume_text, pdf_path,
                cl_pdf, title, form_type, dry_run, llm_client
            )

        elapsed = int((time.time() - start) * 1000)
        result["duration_ms"] = elapsed
        result["job_title"] = title
        result["site"] = site
        result["url"] = url
        return result

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        logger.exception("Apply failed for %s", title)
        return {
            "status": "failed",
            "error": str(e)[:100],
            "duration_ms": elapsed,
            "job_title": title,
            "site": site,
            "url": url,
        }
    finally:
        if not dry_run and page:
            _human_delay( 0.3, 0.8)
        if manager and pw and context:
            close_browser(manager, pw, context)


def _handle_linkedin_easy_apply(page, profile, profile_text, resume_text,
                                 pdf_path, cl_pdf, title, dry_run, llm_client):
    """Handle LinkedIn job application.

    Supports both Easy Apply (inline modal) and external redirects.
    """
    from applypilot.apply.form_detector import detect_form_type, find_apply_button

    btn = find_apply_button(page)
    if not btn:
        return {"status": "failed", "error": "apply_button_not_found"}

    is_external = page.evaluate(
        """(coords) => {
            const el = document.elementFromPoint(coords.x, coords.y);
            if (!el) return false;
            const link = el.closest('a');
            if (!link) return false;
            const href = link.getAttribute('href') || '';
            return href.includes('safety/go') || href.includes('extern');
        }""",
        {"x": btn["x"], "y": btn["y"]},
    )

    if is_external:
        raw_url = page.evaluate(
            """(coords) => {
                const el = document.elementFromPoint(coords.x, coords.y);
                const link = el.closest('a');
                return link ? link.getAttribute('href') : null;
            }""",
            {"x": btn["x"], "y": btn["y"]},
        )
        if not raw_url:
            return {"status": "failed", "error": "external_url_not_found"}

        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        direct_url = qs.get("url", [raw_url])[0]
        direct_url = urllib.parse.unquote(direct_url)

        logger.info("External apply: %s", direct_url[:100])
        page.goto(direct_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Dismiss cookie banners if present
        _dismiss_cookie_banners(page)

        # Re-detect form type after navigation
        ext_form_type = detect_form_type(page)
        if ext_form_type == "gupy":
            return _handle_gupy(
                page, profile, profile_text, resume_text,
                pdf_path, cl_pdf, title, dry_run, llm_client,
            )
        return _handle_generic_apply(
            page, profile, profile_text, resume_text,
            pdf_path, cl_pdf, title, ext_form_type,
            dry_run, llm_client,
        )
    _human_click(page, btn["x"], btn["y"])
    _human_delay(1.0, 2.0)

    steps = 0
    while steps < 15:
        if steps > 0:
            # Wait for new fields after clicking Next/Submit
            fields = wait_for_new_fields(page, timeout=8)
        else:
            fields = detect_form_fields(page)

        if not fields:
            break

        for f in fields:
            if f.get("type") in ("hidden", "submit") or not f.get("visible"):
                continue
            if f.get("tag") == "file":
                if pdf_path and _is_resume_field(f):
                    _upload_file(page, f, pdf_path)
                continue

            label = (f.get("label") or f.get("placeholder") or f.get("name") or "").strip()
            if not label:
                continue

            resolved = resolve_label(label, profile)
            if resolved and resolved["type"] == "text":
                _fill_field(page, f, resolved["value"])

        submit_btn = _find_submit_button(page)
        if not submit_btn:
            break

        btn_text = (submit_btn.get("text") or "").lower()
        _human_click(page, submit_btn["x"], submit_btn["y"])
        _human_delay( 1.0, 2.0)

        if re.search(r"(submit|enviar|concluir|finalizar)", btn_text):
            page.wait_for_timeout(5000)
            if _verify_submitted(page, "indeed"):
                return {"status": "applied"}
            page.wait_for_timeout(3000)
            if _verify_submitted(page, "indeed"):
                return {"status": "applied"}
            # Could not confirm — but this was the final submit, give benefit of doubt
            # if it was a dry run
            if dry_run:
                return {"status": "applied"}
            return {"status": "failed", "error": "submission_not_confirmed"}

        steps += 1

    return {"status": "failed", "error": "could_not_complete"}


def _find_submit_button(page, container=None):
    """Find a submit button on the page, modal-scoped first, then broad search.

    Args:
        page: Playwright page.
        container: Optional CSS selector to scope the search.

    Returns:
        Dict with x, y, text, tag or None.
    """
    from applypilot.apply.form_detector import find_submit_button
    btn = find_submit_button(page, container)
    if not btn and container:
        broad_sel = f"{container} button, {container} a[role='button'], {container} [class*='button']"
        broad_btn = page.evaluate("""(sel) => {
            const patterns = [/revisar/i, /review/i, /enviar/i, /submit/i, /concluir/i,
                              /finalizar/i, /avan\u00e7ar/i, /pr\u00f3ximo/i, /continuar/i,
                              /candidatar/i, /salvar/i, /next/i, /send/i];
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                const t = (el.textContent || el.value || '').trim();
                if (t && patterns.some(p => p.test(t)) && el.offsetWidth > 0 && el.offsetHeight > 0) {
                    const r = el.getBoundingClientRect();
                    return { tag: el.tagName, text: t.slice(0,50), x: r.left + r.width/2, y: r.top + r.height/2 };
                }
            }
            return null;
        }""", broad_sel)
        if broad_btn:
            logger.info("  Found button via modal-scoped broad search: '%s'", broad_btn["text"][:30])
            btn = broad_btn
        else:
            # Last resort: full-page fallback with FINAL submit patterns only (exclude "salvar")
            btn = page.evaluate("""() => {
                const patterns = [/enviar/i, /submit/i, /concluir/i, /finalizar/i, /candidatar/i, /send/i];
                const els = document.querySelectorAll('button, a, input[type=submit]');
                for (const el of els) {
                    const t = (el.textContent || el.value || '').trim();
                    if (t && patterns.some(p => p.test(t)) && el.offsetWidth > 0 && el.offsetHeight > 0) {
                        const r = el.getBoundingClientRect();
                        return { tag: el.tagName, text: t.slice(0,50), x: r.left + r.width/2, y: r.top + r.height/2 };
                    }
                }
                return null;
            }""")
            if btn:
                logger.info("  Found final submit button via full-page fallback: '%s'", btn["text"][:30])
    return btn


def _handle_generic_apply(page, profile, profile_text, resume_text,
                           pdf_path, cl_pdf, title, form_type, dry_run,
                           llm_client):
    """Handle generic ATS form by trying all apply buttons and waiting for fields."""
    from applypilot.apply.form_detector import (
        detect_form_fields, find_submit_button, find_all_apply_buttons,
        wait_for_new_fields, detect_linkedin_modal_fields,
    )
    from applypilot.apply.field_matcher import resolve_label, resolve_yes_no
    from applypilot.apply.question_answering import (
        answer_screening_question,
        generate_standard_answer,
    )

    # For LinkedIn Easy Apply, scope all field detection to the modal container
    # to avoid picking up global nav search bar, language selector, etc.
    container: str | None = None
    if form_type == "linkedin_easy_apply":
        for sel in [".jobs-easy-apply-modal", ".artdeco-modal--layer-fixed", "[data-test-modal]"]:
            try:
                modal = page.query_selector(sel)
                if modal:
                    container = sel
                    logger.info("Scoping field detection to modal: %s", sel)
                    break
            except Exception:
                pass

    def _detect(page, container=container):
        return detect_form_fields(page, container)

    def _find_submit(page, container=container):
        return _find_submit_button(page, container)

    def _wait_fields(page, timeout=8, prev=0, container=container):
        return wait_for_new_fields(page, timeout=timeout, previous_count=prev, container_selector=container)

    # Count initial visible fields so we can detect NEW ones after clicking
    initial_fields = _detect(page)
    previous_count = len([f for f in initial_fields if f.get("visible") and f["type"] not in ("hidden", "submit")])

    # Try all apply buttons until new fields appear
    apply_btns = find_all_apply_buttons(page)
    if apply_btns:
        logger.info("Found %d apply button(s), trying... (initial fields: %d)", len(apply_btns), previous_count)
        for i, btn in enumerate(apply_btns):
            logger.info("  Try [%d/%d]: '%s' (%s)", i+1, len(apply_btns), btn["text"], btn["tag"])
            href = btn.get("href", "")
            if btn["tag"] in ("A",) and href and href != "#" and not href.startswith("#"):
                base = page.url
                full_url = urllib.parse.urljoin(base, href)
                logger.info("  Navigating via href: %s", full_url[:80])
                page.goto(full_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                # Navigation changed page; reset previous_count
                previous_count = 0
            else:
                # Scroll into view then click
                page.evaluate("(coords) => window.scrollTo(0, coords.y - 200)", {"x": btn["x"], "y": btn["y"]})
                page.wait_for_timeout(500)
                _human_click(page, btn["x"], btn["y"])
                page.wait_for_timeout(2000)
            fields = _wait_fields(page, timeout=8, prev=previous_count)
            if fields:
                logger.info("  New fields appeared after clicking '%s'", btn["text"])
                break
    else:
        fields = initial_fields

    fields = _detect(page) if not locals().get('fields') else fields
    steps = 0
    consecutive_empty_fills = 0
    while steps < 15:
        if steps > 0 and not locals().get('skip_wait_fields'):
            fields = _wait_fields(page, timeout=8, prev=previous_count)

        if not fields:
            logger.info("  No fields detected at step %d", steps)
            break

        filled_any = False
        vis_now = [f for f in fields if f.get("visible") and f["type"] not in ("hidden", "submit")]
        logger.info("  Step %d: processing %d visible fields (total %d)", steps, len(vis_now), len(fields))
        for vf in vis_now:
            logger.info("    field: type=%s name='%s' id='%s' label='%s' group_label='%s' value='%s'", 
                vf.get("type"), vf.get("name","")[:25], vf.get("id","")[:40], vf.get("label","")[:30], vf.get("group_label","")[:30], vf.get("value","")[:15])
        # Process radio fields grouped by name or group_label
        radio_groups = {}
        radio_fields = [f for f in fields if f.get("type") == "radio"]
        for f in radio_fields:
            name = f.get("name", "")
            glabel = f.get("group_label", "")
            key = name or glabel or "__ungrouped__"
            if key not in radio_groups:
                radio_groups[key] = []
            radio_groups[key].append(f)
        logger.info("  Radio groups: %d (%s)", len(radio_groups), list(radio_groups.keys())[:3])

        for f in fields:
            if f.get("type") in ("hidden", "submit") or not f.get("visible"):
                continue
            # Skip radio fields — handled as groups below
            if f["type"] == "radio":
                continue
            if f["tag"] == "file":
                if pdf_path and _is_resume_field(f):
                    _upload_file(page, f, pdf_path)
                elif cl_pdf and _is_cover_letter_field(f):
                    _upload_file(page, f, cl_pdf)
                continue

            label = (f.get("label") or f.get("placeholder") or f.get("name") or "").strip()
            if not label:
                continue

            resolved = resolve_label(label, profile)
            logger.info("    resolve_label('%s')=%s", label[:30], resolved['value'][:30] if resolved and resolved.get("value") else None)
            if resolved and resolved["type"] == "text":
                _fill_field(page, f, resolved["value"])
                filled_any = True
            elif resolved and resolved["type"] == "resume_upload" and pdf_path:
                _upload_file(page, f, pdf_path)
                filled_any = True
            elif resolved and resolved["type"] == "cover_letter_upload" and cl_pdf:
                _upload_file(page, f, cl_pdf)
                filled_any = True
            else:
                # Try LLM for unknown questions
                yes_no = resolve_yes_no(label)
                if yes_no:
                    _fill_field(page, f, yes_no)
                    filled_any = True
                elif llm_client:
                    answer = answer_screening_question(
                        label, f["type"], f.get("options", []),
                        profile_text, resume_text, title, llm_client,
                        job_url=page.url,
                    )
                    if answer:
                        _fill_field(page, f, answer)
                        filled_any = True

        # Process radio groups using group_label (always, even if other fields filled)
        if radio_groups:
            for name, radios in radio_groups.items():
                glabel = ""
                for r in radios:
                    if r.get("group_label"):
                        glabel = r["group_label"]
                        break
                if not glabel:
                    continue
                yes_no = resolve_yes_no(glabel)
                logger.info("  Radio group '%s': resolve_yes_no=%s", glabel[:40], yes_no)
                if not yes_no:
                    continue
                target_val = "yes" if yes_no.lower() in ("yes", "sim", "y") else "no"
                handled = False
                for r in radios:
                    if r.get("value", "").lower() == target_val:
                        if r.get("checked"):
                            handled = True  # Already correctly answered
                        else:
                            _fill_field(page, r, yes_no)
                            filled_any = True
                            handled = True
                            logger.info("Radio group '%s': selected '%s' (→%s)", glabel[:40], target_val, yes_no)
                        break
                if handled:
                    filled_any = True

        if not filled_any:
            consecutive_empty_fills += 1
            if consecutive_empty_fills >= 3:
                logger.info("No fields filled in 3 consecutive attempts, giving up")
                break
        else:
            consecutive_empty_fills = 0

        submit_btn = _find_submit(page)
        if not submit_btn:
            logger.info("  No submit button at step %d", steps)
            # Before giving up, check if the application was already submitted
            page.wait_for_timeout(3000)
            if _verify_submitted(page, form_type):
                logger.info("Application already submitted (no submit button needed)")
                return {"status": "applied"}
            # Broad search for review/submit buttons (all form types)
            broad_btn = page.evaluate("""() => {
                const patterns = [/revisar/i, /review/i, /enviar/i, /submit/i, /concluir/i, /finalizar/i, /continuar/i, /candidatar/i, /salvar/i, /avan[cç]ar/i, /pr[oó]ximo/i];
                const btns = document.querySelectorAll('button, a[role="button"], .artdeco-button, [class*="button"]');
                for (const b of btns) {
                    const t = (b.textContent || b.value || '').trim();
                    if (patterns.some(p => p.test(t)) && b.offsetWidth > 0 && b.offsetHeight > 0) {
                        const r = b.getBoundingClientRect();
                        return { tag: b.tagName, text: t.slice(0,50), x: r.left + r.width/2, y: r.top + r.height/2 };
                    }
                }
                return null;
            }""")
            if broad_btn:
                logger.info("  Found review/submit button via broad search: '%s'", broad_btn["text"])
                submit_btn = broad_btn
            if not submit_btn:
                break

        btn_text = (submit_btn.get("text") or "").lower()
        logger.info("  Step %d: click '%s' filled=%s consec=%d", steps, btn_text[:30], filled_any, consecutive_empty_fills)
        _human_click(page, submit_btn["x"], submit_btn["y"])
        _human_delay( 1.0, 3.0)

        if re.search(r"(submit|enviar|concluir|finalizar|candidatar|continuar|salvar|avançar|avanç)", btn_text):
            # Wait for navigation/processing after clicking submit
            page.wait_for_timeout(5000)
            # Check for success confirmation first
            if _verify_submitted(page, form_type):
                return {"status": "applied"}
            # Check if there are more form steps
            more_fields = _detect(page)
            visible_after = [f for f in more_fields if f.get("visible") and f["type"] not in ("hidden", "submit")]
            logger.info("  After %s: %d visible fields (of %d total)", btn_text[:20], len(visible_after), len(more_fields))
            for vf in visible_after:
                logger.info("    field: type=%s name='%s' label='%s' value='%s'", vf.get("type"), vf.get("name",""), vf.get("label",""), vf.get("value","")[:20])
            if not visible_after:
                # Wait a bit more and check for success confirmation
                page.wait_for_timeout(3000)
                if _verify_submitted(page, form_type):
                    return {"status": "applied"}
                # Log current URL and page state for debugging
                after_url = page.url[:90]
                after_text_len = page.evaluate("document.body.innerText.length")
                logger.info("  Page after step: url=%s (body=%d chars)", after_url, after_text_len)
                # No fields — might be on review page with only a submit button
                # Poll for submit button in case the review page is still loading
                sub_btn = None
                for _s in range(5):
                    wait_btn = _find_submit(page)
                    if wait_btn:
                        sub_btn = wait_btn
                        logger.info("  Found submit button on page after step (try %d): '%s'", _s+1, (wait_btn.get("text") or "")[:30])
                        break
                    page.wait_for_timeout(1000)
                if sub_btn:
                    sub_text = (sub_btn.get("text") or "").lower()
                    _human_click(page, sub_btn["x"], sub_btn["y"])
                    _human_delay(1.0, 3.0)
                    page.wait_for_timeout(5000)
                    if _verify_submitted(page, form_type):
                        return {"status": "applied"}
                    page.wait_for_timeout(3000)
                    if _verify_submitted(page, form_type):
                        return {"status": "applied"}
                # Still no fields and no success — advance step counter to avoid stale state
                steps += 1
                previous_count = 0
                continue
            # Step advanced — use the new step's fields directly on next iteration
            fields = more_fields
            skip_wait_fields = True
            previous_count = 0

        steps += 1
        # Reset counter for next step
        if fields:
            previous_count = len([f for f in fields if f.get("visible") and f["type"] not in ("hidden", "submit")])

    # Check if we're on a success/thank you page
    if _verify_submitted(page, form_type):
        return {"status": "applied"}

    # Take a screenshot for debugging
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', (title or 'unknown')[:40])
        ss_path = config.APP_DIR / "screenshots" / f"fail_{safe_title}_{ts}.png"
        ss_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ss_path))
        logger.info("Screenshot saved to %s", ss_path)
    except Exception as e:
        logger.info("Screenshot save failed: %s", e)

    return {"status": "failed", "error": "could_not_complete"}


def _handle_gupy(page, profile, profile_text, resume_text,
                  pdf_path, cl_pdf, title, dry_run, llm_client):
    """Handle Gupy job application flow with auto-login support."""
    from applypilot.apply.form_detector import detect_form_fields, find_submit_button
    from applypilot.apply.field_matcher import resolve_label, resolve_yes_no

    btn = find_apply_button(page)
    if not btn:
        return {"status": "failed", "error": "apply_button_not_found"}

    click_url = page.evaluate(
        """(coords) => {
            const el = document.elementFromPoint(coords.x, coords.y);
            const link = el ? el.closest('a') : null;
            if (link) return link.getAttribute('href');
            return null;
        }""",
        {"x": btn["x"], "y": btn["y"]},
    )

    if click_url and click_url.startswith("/"):
        apply_url = urllib.parse.urljoin("https://" + urllib.parse.urlparse(page.url).netloc, click_url)
        page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
    elif click_url:
        page.goto(click_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
    else:
        _human_click(page, btn["x"], btn["y"])
        page.wait_for_timeout(3000)

    if _handle_ats_login(page, profile, "gupy"):
        logger.info("Gupy login successful (URL: %s), proceeding to apply form", page.url[:80])
        # After login, wait for redirect to steps/applications URL
        try:
            page.wait_for_url("**/steps/**", timeout=15000)
            logger.info("Gupy redirected to steps: %s", page.url[:80])
        except Exception:
            logger.info("Gupy redirect wait timeout (URL: %s)", page.url[:80])
        # Wait for spinner to finish
        try:
            page.wait_for_selector("[data-testid='spinner']", state="hidden", timeout=30000)
            logger.info("Gupy spinner done")
        except Exception:
            logger.info("Gupy spinner timeout or not found")
        # Navigate directly to the curriculum URL (bypasses welcome overlay)
        _url_before = page.url
        _has_curriculum = "/curriculum" in _url_before
        logger.info("Gupy URL check: has_curriculum=%s url=%s", _has_curriculum, _url_before[:90])
        if not _has_curriculum:
            _base = _url_before.rstrip("/")
            cur_url = urllib.parse.urljoin(_base + "/", "curriculum")
            logger.info("Gupy navigating to curriculum: %s", cur_url)
            try:
                page.goto(cur_url, wait_until="domcontentloaded", timeout=15000)
                logger.info("Gupy curriculum page loaded: %s", page.url[:80])
            except Exception as e:
                logger.info("Gupy curriculum nav failed: %s", e)
        # Dismiss welcome overlay (in case it appears on curriculum page)
        _dismiss_overlays(page)
        logger.info("After dismiss (URL: %s)", page.url[:80])
        # If dismiss navigated back to steps (no /curriculum), navigate there again
        if "/curriculum" not in page.url:
            _steps_url = page.url
            _curriculum_url = urllib.parse.urljoin(_steps_url.rstrip("/") + "/", "curriculum")
            logger.info("Gupy re-navigating to curriculum: %s", _curriculum_url)
            try:
                page.goto(_curriculum_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                logger.info("Gupy re-navigated to curriculum: %s", page.url[:80])
            except Exception as e:
                logger.info("Gupy re-navigation failed: %s", e)
        # Wait for form fields to appear
        page.wait_for_timeout(3000)
        for _ in range(20):
            fields = page.evaluate("""() => {
                const tags = ['input', 'select', 'textarea'];
                return tags.flatMap(t => Array.from(document.querySelectorAll(t)))
                    .filter(el => el.offsetWidth > 0 && el.offsetHeight > 0).length;
            }""")
            if fields > 0:
                logger.info("Gupy form fields found: %d", fields)
                break
            page.wait_for_timeout(500)
        page.wait_for_timeout(2000)
        page.wait_for_timeout(2000)
        return _handle_generic_apply(
            page, profile, profile_text, resume_text, pdf_path,
            cl_pdf, title, "gupy", dry_run, llm_client,
        )
    else:
        return {"status": "failed", "error": "ats_login_required"}


def _handle_ats_login(page, profile, ats_name: str) -> bool:
    """Detect and fill ATS login form.
    
    First tries auto-login with stored credentials.
    If that fails, waits for the user to log in manually.
    Returns True if logged in or not needed.
    """
    page_text = page.evaluate("document.body.innerText.substring(0, 2000)").lower()
    url_lower = page.url.lower()

    is_login_page = any(p in page_text or p in url_lower
                        for p in ["entrar", "acessar conta", "sign in", "login", "signin",
                                  "email ou cpf", "senha", "password"])

    if not is_login_page:
        return True  # Already logged in

    logger.info("Login required for %s", ats_name)

    creds = profile.get("ats_credentials", {}).get(ats_name)
    if creds:
        logger.info("Attempting auto-login for %s", ats_name)
        email_field = page.query_selector("input[name='username'], input#username, input[name='email'], input[type='email']")
        password_field = page.query_selector("input[type='password'], input[name='password']")

        if email_field and password_field:
            email_field.fill(creds.get("email", ""))
            _human_delay(0.3, 0.6)
            password_field.fill(creds.get("password", ""))
            _human_delay(0.3, 0.6)

            submit = page.query_selector("button[type='submit'], button:has-text('Acessar conta'), button:has-text('Entrar'), button:has-text('Sign in')")
            if submit:
                submit.click()
                page.wait_for_timeout(4000)

                url_lower2 = page.url.lower()
                if "signin" not in url_lower2 and "signup" not in url_lower2:
                    logger.info("Auto-login to %s successful", ats_name)
                    return True

    logger.info("Waiting for manual login to %s (you have 120s)...", ats_name)
    for _ in range(60):
        page.wait_for_timeout(2000)
        url_now = page.url.lower()
        if "signin" not in url_now and "signup" not in url_now:
            logger.info("Manual login detected for %s", ats_name)
            return True
        page_text_now = page.evaluate("document.body.innerText.substring(0, 500)").lower()
        if "entrar" not in page_text_now and "acessar conta" not in page_text_now[:50]:
            logger.info("Manual login detected for %s (page changed)", ats_name)
            return True

    logger.warning("Login to %s failed or timed out", ats_name)
    return False


def _fill_field(page, field: dict, value: str):
    """Fill a form field with human-like interaction.
    
    Tries standard Playwright fill first, then falls back to
    JavaScript-based filling for React-controlled fields.
    """
    try:
        tag = field["tag"]
        ftype = field["type"]

        if tag == "select":
            selector = _build_selector(field)
            if selector:
                page.select_option(selector, value)
            _human_delay( 0.1, 0.3)
            return
        elif ftype == "checkbox":
            selector = _build_selector(field)
            if selector:
                page.check(selector)
            _human_delay( 0.1, 0.2)
            return
        elif ftype == "radio":
            name = field.get("name", "")
            val = field.get("value", "")
            if name:
                selector = f"input[type='radio'][name='{name}']"
                if val:
                    selector += f"[value='{val}']"
                page.check(selector)
            else:
                _fill_field_by_label(page, field, value)
            _human_delay( 0.1, 0.2)
            return

        selector = _build_selector(field)
        logger.info("    fill: id='%s' selector='%s' -> '%s'", field.get("id","")[:40], str(selector)[:60], str(value)[:30])
        if not selector:
            _fill_field_by_label(page, field, value)
            return

        # Text-like fields: standard fill first
        try:
            _human_clear_and_type(page, selector, value)
        except Exception:
            # Fallback: JavaScript-based fill for React
            _fill_react_field(page, selector, value)
    except Exception as e:
        logger.debug("Failed to fill %s: %s", field.get("name", ""), e)


def _fill_field_by_label(page, field: dict, value: str):
    """Fill a field using JavaScript label-based lookup (for fields without name/id)."""
    safe_value = json.dumps(value)
    label = (field.get("label") or field.get("aria-label") or "").strip()
    if not label:
        return
    tag = field["tag"]
    ftype = field["type"]
    page.evaluate(
        f"""() => {{
            const labelText = {json.dumps(label)};
            // Find by explicit <label for="id">
            const labels = Array.from(document.querySelectorAll('label'));
            const matchingLabel = labels.find(l => (l.textContent || '').trim() === labelText);
            let el = null;
            if (matchingLabel && matchingLabel.getAttribute('for')) {{
                el = document.getElementById(matchingLabel.getAttribute('for'));
            }}
            if (!el) {{
                // Search all inputs for closest match: aria-label, placeholder, or parent label
                const allInputs = document.querySelectorAll('input, select, textarea');
                el = Array.from(allInputs).find(input => {{
                    const inputLabel = input.getAttribute('aria-label') || input.getAttribute('placeholder') || '';
                    if (inputLabel === labelText) return true;
                    const parentLabel = input.closest('label');
                    if (parentLabel && (parentLabel.textContent || '').trim() === labelText) return true;
                    return false;
                }});
            }}
            if (!el && matchingLabel) {{
                // Label is a sibling — find the nearest input/select/textarea
                const parent = matchingLabel.parentElement;
                if (parent) el = parent.querySelector('input, select, textarea');
            }}
            if (!el && matchingLabel) {{
                // Label is before input — traverse siblings
                let sib = matchingLabel.nextElementSibling;
                while (sib) {{
                    const inp = sib.querySelector('input, select, textarea') || (sib.matches('input, select, textarea') ? sib : null);
                    if (inp) {{ el = inp; break; }}
                    sib = sib.nextElementSibling;
                }}
            }}
            if (!el) return;
            if ('{tag}' === 'select') {{
                const opt = Array.from(el.options).find(o => o.value === {safe_value} || o.text === {safe_value});
                if (opt) {{ el.value = opt.value; el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}
            }} else if ('{ftype}' === 'checkbox') {{
                if ({safe_value} === true || {safe_value} === 'true' || {safe_value} === 'on') el.checked = true;
                else el.checked = false;
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else if ('{ftype}' === 'radio') {{
                el.click();
            }} else {{
                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                    || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
                if (nativeSetter) {{ nativeSetter.call(el, {safe_value}); }}
                else {{ el.value = {safe_value}; }}
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }}
        }}"""
    )
    _human_delay(0.1, 0.3)
    logger.info("Label-filled '%s' with '%s'", label[:30], value[:30])


def _fill_react_field(page, selector: str, value: str):
    """Fill a field using JavaScript evaluation to trigger React synthetic events."""
    import json
    safe_value = json.dumps(value)
    is_contenteditable = page.evaluate(
        f"""() => {{
            const el = document.querySelector('{selector}');
            if (!el) return 'not_found';
            if (el.getAttribute('contenteditable') === 'true') return 'contenteditable';
            return 'input';
        }}"""
    )
    if is_contenteditable == 'not_found':
        return
    if is_contenteditable == 'contenteditable':
        page.evaluate(
            f"""() => {{
                const el = document.querySelector('{selector}');
                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, {safe_value});
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}"""
        )
    else:
        page.evaluate(
            f"""() => {{
                const el = document.querySelector('{selector}');
                if (!el) return;
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                )?.set || Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                )?.set;
                if (nativeSetter) {{
                    nativeSetter.call(el, {safe_value});
                }} else {{
                    el.value = {safe_value};
                }}
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }}"""
        )
    _human_delay(0.1, 0.3)
    logger.info("React-filled %s", selector[:40])


def _upload_file(page, field: dict, file_path: str):
    """Upload a file using the file input field."""
    try:
        selector = _build_selector(field)
        if selector:
            page.set_input_files(selector, file_path)
            logger.info("Uploaded %s", Path(file_path).name)
    except Exception as e:
        logger.warning("Upload failed: %s", e)


def _build_selector(field: dict) -> str | None:
    """Build a CSS selector for a form field."""
    if field.get("id"):
        return f"#{field['id']}"
    if field.get("name"):
        return f"[name='{field['name']}']"
    label = (field.get("label") or field.get("aria-label") or "").strip()
    if label:
        safe = label.replace("'", "\\'")
        return f"[aria-label='{safe}'], [placeholder='{safe}']"
    return None


def _human_click(page, x: float, y: float):
    """Click at coordinates with human-like mouse movement."""
    try:
        page.mouse.move(x + _jitter(), y + _jitter())
        _human_delay( 0.05, 0.15)
        page.mouse.click(x + _jitter(), y + _jitter())
    except Exception:
        pass


def _human_clear_and_type(page, selector: str, text: str):
    """Type text with human-like timing."""
    try:
        page.click(selector)
        _human_delay( 0.1, 0.3)
        page.fill(selector, "")
        _human_delay( 0.05, 0.15)
        page.type(selector, str(text), delay=_jitter(40, 120))
    except Exception:
        pass


def _human_delay(min_s: float = 0.3, max_s: float = 1.0):
    """Random delay to simulate human behavior."""
    import random
    time.sleep(random.uniform(min_s, max_s))


def _jitter(min_val: float = -2, max_val: float = 2) -> float:
    """Small random offset for mouse movements."""
    import random
    return random.uniform(min_val, max_val)


def _is_resume_field(field: dict) -> bool:
    """Check if a file field is for resume upload."""
    label = (field.get("label") or field.get("placeholder") or "").lower()
    return bool(re.search(r"resume|curr[íi]culo|cv", label))


def _is_cover_letter_field(field: dict) -> bool:
    """Check if a file field is for cover letter."""
    label = (field.get("label") or field.get("placeholder") or "").lower()
    return bool(re.search(r"cover.*letter|carta.*apresenta", label))


def _verify_submitted(page, form_type: str | None) -> bool:
    """Verify that an application was actually submitted successfully.

    Uses platform-specific checks rather than loose body text matching.
    Waits up to 8 seconds for confirmation elements to appear.
    """
    import time
    deadline = time.time() + 8

    def _check_linkedin():
        """LinkedIn Easy Apply: check for confirmation modal or page state."""
        js = r"""
        () => {
            const successModal = document.querySelector('.jobs-easy-apply-modal');
            if (successModal) {
                const text = (successModal.textContent || '').toLowerCase();
                if (/candidatura\s*(enviada|recebida|concluída)/.test(text)) return true;
                if (/application\s*(sent|submitted|received)/.test(text)) return true;
                if (/thank\s*you/.test(text) && /submitted|sent/.test(text)) return true;
            }
            const banners = document.querySelectorAll('[class*="success"], [class*="confirmation"], [class*="applied"]');
            for (const b of banners) {
                if (b.offsetWidth <= 0) continue;
                const t = (b.textContent || '').toLowerCase();
                if (/candidatura\s*(enviada|recebida|concluída)/.test(t)) return true;
                if (/application\s*(sent|submitted)/.test(t)) return true;
            }
            const applyBtn = document.querySelector('button.jobs-apply-button');
            if (!applyBtn) {
                const appliedText = document.body.textContent || '';
                if (/candidatura\s*enviada/.test(appliedText.toLowerCase())) return true;
            }
            const confirmModal = document.querySelector('.artdeco-modal--confirm');
            if (confirmModal && confirmModal.offsetWidth > 0) return true;
            return false;
        }
        """
        try:
            return page.evaluate(js)
        except Exception:
            return False

    def _check_gupy():
        """Gupy: check for success URL or success elements."""
        url = page.url.lower()
        if "/success" in url or "/aplicado" in url or "/applied" in url:
            return True
        js = r"""
        () => {
            const body = (document.body.textContent || '').toLowerCase();
            if (/candidatura\s*enviada\s*com\s*sucesso/.test(body)) return true;
            if (/candidatura\s*realizada/.test(body)) return true;
            if (/thanks\s*for\s*your\s*application/.test(body)) return true;
            const alerts = document.querySelectorAll('[role="alert"], .alert, .snackbar, [class*="success"]');
            for (const a of alerts) {
                if (a.offsetWidth <= 0) continue;
                const t = (a.textContent || '').toLowerCase();
                if (/enviada|sucesso|success/.test(t)) return true;
            }
            return false;
        }
        """
        try:
            return page.evaluate(js)
        except Exception:
            return False

    def _check_indeed():
        """Indeed: check for confirmation page."""
        js = r"""
        () => {
            const body = (document.body.textContent || '').toLowerCase();
            if (/candidatura\s*enviada/.test(body)) return true;
            if (/application\s*sent/.test(body)) return true;
            if (/thank\s*you/.test(body) && /application/.test(body)) return true;
            const el = document.querySelector('.application-status, .success-message, [class*="success"]');
            if (el && el.offsetWidth > 0) return true;
            return false;
        }
        """
        try:
            return page.evaluate(js)
        except Exception:
            return False

    # Poll every 1s up to deadline
    while time.time() < deadline:
        if form_type == "linkedin_easy_apply":
            if _check_linkedin():
                logger.info("Verified LinkedIn application submission confirmed")
                return True
        elif form_type == "gupy":
            if _check_gupy():
                logger.info("Verified Gupy application submission confirmed")
                return True
        elif form_type == "indeed":
            if _check_indeed():
                logger.info("Verified Indeed application submission confirmed")
                return True
        else:
            # Generic check: look for success patterns in the page body
            try:
                text = page.inner_text("body").lower()
                if re.search(
                    r"(?:candidatura\s*(?:enviada|recebida|conclu[íi]da|realizada)|"
                    r"application\s*(?:sent|submitted|received)|"
                    r"thank\s*you\s+for\s+(?:your\s+)?application|"
                    r"(?:inscri[çc][ãa]o|candidatura).*(?:sucesso|confirmada|recebida)|"
                    r"sucesso.*(?:inscri[çc][ãa]o|candidatura))",
                    text
                ):
                    logger.info("Verified generic application submission confirmed")
                    return True
            except Exception:
                pass
        time.sleep(1)

    logger.info("Could not verify application submission for form_type=%s", form_type)
    return False


def _profile_to_text(profile: dict) -> str:
    """Convert profile to a compact text summary for LLM context."""
    lines = []
    p = profile.get("personal", {})
    lines.append(f"Name: {p.get('full_name', '')}")
    lines.append(f"Email: {p.get('email', '')}")
    lines.append(f"Location: {p.get('city', '')}, {p.get('province_state', '')}")
    lines.append(f"LinkedIn: {p.get('linkedin_url', '')}")

    exp = profile.get("experience", {})
    lines.append(f"Years Exp: {exp.get('years_of_experience_total', '')}")
    lines.append(f"Education: {exp.get('education_level', '')}")
    lines.append(f"Current: {exp.get('current_title', '')} @ {exp.get('current_company', '')}")

    skills = profile.get("skills_boundary", {})
    for cat, items in skills.items():
        if items:
            lines.append(f"{cat.replace('_', ' ').title()}: {', '.join(items[:8])}")

    projetos = profile.get("projetos", [])
    if projetos:
        lines.append("Projects:")
        for pr in projetos[:3]:
            lines.append(f"  - {pr.get('nome', '')}: {pr.get('descricao', '')[:100]}")

    return "\n".join(lines)
