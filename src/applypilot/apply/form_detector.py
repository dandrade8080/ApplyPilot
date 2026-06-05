"""Detects form fields on a page and categorizes them."""

import re
from typing import Any

FIELD_TYPES = {
    "text": "text",
    "email": "email",
    "tel": "tel",
    "number": "number",
    "url": "url",
    "textarea": "textarea",
    "select": "select",
    "checkbox": "checkbox",
    "radio": "radio",
    "file": "file",
    "date": "date",
    "hidden": "hidden",
}


def detect_form_fields(page, container_selector: str | None = None) -> list[dict[str, Any]]:
    """Extract all form fields from a page using JavaScript evaluation.

    Args:
        page: The Playwright page.
        container_selector: Optional CSS selector to scope field detection (e.g. modal).

    Returns a list of dicts with: tag, type, name, id, label, placeholder,
    required, visible, rect, options (for select), checked (for checkbox/radio).
    """
    try:
        fields = page.evaluate(_SCAN_FORM_JS, container_selector or "")
        return fields
    except Exception as exc:
        if "Connection closed" in str(exc) or "Target closed" in str(exc):
            return []
        raise


def detect_linkedin_modal_fields(page) -> list[dict[str, Any]]:
    """Detect fields only within the LinkedIn Easy Apply modal.

    Falls back to full-page scan if no modal is found.
    """
    for sel in [".jobs-easy-apply-modal", ".artdeco-modal--layer-fixed", "[data-test-modal]"]:
        modal = page.query_selector(sel)
        if modal:
            return detect_form_fields(page, sel)
    return detect_form_fields(page)


def detect_form_type(page) -> str | None:
    """Detect which ATS/form type is on the current page."""
    try:
        url = page.url.lower()
        html = page.content()
    except Exception as exc:
        if "Connection closed" in str(exc) or "Target closed" in str(exc):
            return None
        raise

    if "linkedin.com" in url and ("easyapply" in html.lower() or "jobs/view" in url):
        return "linkedin_easy_apply"
    if "greenhouse.io" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    if "myworkdayjobs.com" in url or "wd5.myworkdayjobs.com" in url:
        return "workday"
    if "ashbyhq.com" in url:
        return "ashby"
    if "gupy.io" in url:
        return "gupy"
    if "jobs.recruitee.com" in url or "recruitee.com" in url:
        return "recruitee"
    if "breezy.hr" in url:
        return "breezy"
    if "icims.com" in url:
        return "icims"
    if "taleo.net" in url:
        return "taleo"
    if "smartrecruiters.com" in url:
        return "smartrecruiters"
    if "indeed.com" in url:
        return "indeed"
    if "jobs.smartrecruiters.com" in url:
        return "smartrecruiters"

    return None


def find_apply_button(page) -> dict | None:
    """Find the Apply button on a job page."""
    try:
        button = page.evaluate(_FIND_APPLY_BUTTON_JS)
        return button
    except Exception as exc:
        if "Connection closed" in str(exc) or "Target closed" in str(exc):
            return None
        raise


def find_all_apply_buttons(page) -> list[dict]:
    """Find ALL apply buttons on a page, ordered by specificity.
    
    Returns a list of dicts with tag, text, x, y. The most specific
    (button/link elements) come first; generic span/div fallbacks last.
    """
    try:
        return page.evaluate(_FIND_ALL_APPLY_BUTTONS_JS)
    except Exception as exc:
        if "Connection closed" in str(exc) or "Target closed" in str(exc):
            return []
        raise


def find_submit_button(page, container_selector: str | None = None) -> dict | None:
    """Find the Submit/Next button in an application form.

    Args:
        page: The Playwright page.
        container_selector: Optional CSS selector to scope search (e.g. modal).
    """
    try:
        button = page.evaluate(_FIND_SUBMIT_BUTTON_JS, container_selector or "")
        return button
    except Exception as exc:
        if "Connection closed" in str(exc) or "Target closed" in str(exc):
            return None
        raise


def wait_for_new_fields(page, timeout: float = 15.0, previous_count: int = 0,
                        container_selector: str | None = None) -> list[dict]:
    """Wait for new form fields to appear (e.g. after clicking Apply).
    
    Polls every 1s until more visible fields exist than previous_count or timeout.
    """
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        fields = detect_form_fields(page, container_selector)
        visible = [f for f in fields if f.get("visible") and f["type"] not in ("hidden", "submit")]
        if len(visible) > previous_count:
            return fields
        page.wait_for_timeout(1000)
    return []


_SCAN_FORM_JS = """
(containerSelector = '') => {
    const root = containerSelector ? document.querySelector(containerSelector) : document;
    if (!root) return [];

    const fields = [];
    const labels = root.querySelectorAll('label');
    const labelMap = {};
    labels.forEach(l => {
        const forId = l.getAttribute('for');
        const text = (l.textContent || '').trim();
        if (forId) labelMap[forId] = text;
    });

    // Known non-form field selectors to always exclude
    const NON_FORM_SELECTORS = [
        '#global-nav-search', '#global-nav-typeahead',
        '[data-search-bar]', '.search-global-typeahead',
        '.nav-search-bar', 'header nav input',
        'footer select', 'footer input',
        'select[aria-label*="idioma" i], select[aria-label*="language" i]',
        'input[aria-label*="Pesquisar" i], input[placeholder*="Pesquisar" i]',
        'input[aria-label*="search" i], input[placeholder*="search" i]',
        'input[aria-label*="Search" i]',
        '#ember-context-menu',
    ];

    function isNonForm(el) {
        for (const sel of NON_FORM_SELECTORS) {
            if (el.matches(sel)) return true;
            if (el.closest(sel)) return true;
        }
        // Exclude footer elements
        if (el.closest('footer')) return true;
        // Exclude elements clearly outside the modal (when modal is present)
        const modal = document.querySelector('.jobs-easy-apply-modal, .artdeco-modal--layer-fixed, [data-test-modal]');
        if (modal && !modal.contains(el) && !el.closest('.jobs-easy-apply-modal, .artdeco-modal--layer-fixed, [data-test-modal]')) {
            return true;
        }
        return false;
    }

    function extractLabel(el) {
        let label = '';
        const id = el.getAttribute('id') || '';
        if (id && labelMap[id]) return labelMap[id];
        const parent = el.closest('div, fieldset, section, li, label');
        if (parent) {
            const parentLabel = parent.querySelector('label');
            if (parentLabel) label = (parentLabel.textContent || '').trim();
            if (!label && parent.tagName === 'LABEL') label = (parent.textContent || '').trim();
        }
        if (!label) label = el.getAttribute('placeholder') || '';
        if (!label) label = el.getAttribute('aria-label') || '';
        if (!label) label = el.getAttribute('name') || '';
        return label;
    }

    function extractGroupLabel(el) {
        const ftype = el.getAttribute('type') || '';
        if (ftype !== 'radio' && ftype !== 'checkbox') return '';
        let walk = el.parentElement;
        for (let i = 0; i < 10 && walk; i++) {
            if (walk.tagName === 'FIELDSET') {
                const legend = walk.querySelector('legend');
                if (legend) { const t = (legend.textContent || '').trim(); if (t) return t; }
            }
            const legend = walk.querySelector('legend');
            if (legend) { const t = (legend.textContent || '').trim(); if (t.length > 3) return t; }
            const h = walk.querySelector('h1, h2, h3, h4, h5, h6, p, span, div, label');
            if (h && !h.contains(el)) {
                const t = (h.textContent || '').trim();
                if (t.length > 3 && !t.match(/^(sim|não|yes|no)$/i)) return t;
            }
            const ownText = (walk.childNodes && Array.from(walk.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => (n.textContent || '').trim())
                .join(' ')).trim();
            if (ownText.length > 10) return ownText;
            const prev = walk.previousElementSibling;
            if (prev && prev !== el) {
                const t = (prev.textContent || '').trim();
                if (t.length > 3 && !t.match(/^(sim|não|yes|no)$/i)) return t;
            }
            walk = walk.parentElement;
        }
        return '';
    }

    function pushField(el, tag, type, frameSrc) {
        if (isNonForm(el)) return;
        const rect = el.getBoundingClientRect();
        const visible = rect.width > 0 && rect.height > 0;
        const label = extractLabel(el);
        const opts = tag === 'select' ? Array.from(el.querySelectorAll('option')).map(o => ({ value: o.getAttribute('value') || o.textContent, text: o.textContent.trim() })) : [];
        fields.push({
            tag: tag, type: type,
            name: el.getAttribute('name') || '',
            id: el.getAttribute('id') || '',
            value: el.getAttribute('value') || '',
            label: label,
            group_label: extractGroupLabel(el),
            placeholder: el.getAttribute('placeholder') || '',
            required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true',
            visible: visible,
            rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
            options: opts,
            checked: el.checked || false,
            frame: frameSrc || '',
        });
    }

    // 1. Standard form elements
    root.querySelectorAll('input, select, textarea').forEach(el => pushField(el, el.tagName.toLowerCase(), el.getAttribute('type') || el.tagName.toLowerCase(), ''));

    // 2. contenteditable elements (React rich text editors)
    root.querySelectorAll('[contenteditable="true"]').forEach(el => pushField(el, el.tagName.toLowerCase(), 'textarea', ''));

    // 3. ARIA textbox/combobox roles
    root.querySelectorAll('[role="textbox"], [role="combobox"], [role="listbox"], [role="spinbutton"], [role="slider"]').forEach(el => {
        if (!el.matches('input, select, textarea, [contenteditable="true"]')) {
            pushField(el, el.tagName.toLowerCase(), 'text', '');
        }
    });

    // 4. Same-origin iframes
    root.querySelectorAll('iframe').forEach(iframe => {
        try {
            const doc = iframe.contentDocument || iframe.contentWindow.document;
            if (!doc) return;
            doc.querySelectorAll('input, select, textarea').forEach(el => pushField(el, el.tagName.toLowerCase(), el.getAttribute('type') || el.tagName.toLowerCase(), iframe.src));
            doc.querySelectorAll('[contenteditable="true"]').forEach(el => pushField(el, el.tagName.toLowerCase(), 'textarea', iframe.src));
        } catch(e) {}
    });

    return fields;
}
"""

_FIND_APPLY_BUTTON_JS = """
() => {
    const patterns = [/apply/i, /candidat/i, /inscrev/i, /candidate-se/i, /inscri/i];
    // First, try easy-apply-specific selectors (LinkedIn)
    const easyApply = document.querySelector('button.jobs-apply-button, button[data-control-name="apply"], a.jobs-apply-button');
    if (easyApply && easyApply.offsetWidth > 0 && easyApply.offsetHeight > 0) {
        const rect = easyApply.getBoundingClientRect();
        return { tag: easyApply.tagName, text: (easyApply.textContent || '').trim().slice(0, 50), x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
    }
    // Next, try buttons and links with matching text
    const candidates = document.querySelectorAll('button, a, input[type=button], input[type=submit]');
    for (const el of candidates) {
        const text = (el.textContent || el.value || '').trim();
        if (patterns.some(p => p.test(text)) && el.offsetWidth > 0 && el.offsetHeight > 0) {
            const rect = el.getBoundingClientRect();
            return { tag: el.tagName, text: text.slice(0, 50), x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
        }
    }
    // Fallback: broad scan including spans/divs with short matching text
    const fallbacks = document.querySelectorAll('span, div');
    for (const el of fallbacks) {
        const text = (el.textContent || '').trim();
        if (patterns.some(p => p.test(text)) && el.offsetWidth > 0 && el.offsetHeight > 0 && text.length < 60) {
            const rect = el.getBoundingClientRect();
            return { tag: el.tagName, text: text.slice(0, 50), x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
        }
    }
    return null;
}
"""

_FIND_ALL_APPLY_BUTTONS_JS = """
() => {
    const patterns = [/^apply/i, /^candidat/i, /^inscrev/i, /^candidate-se/i, /^inscri/i];
    const results = [];
    const seen = new Set();
    const isVisible = (el) => {
        if (el.offsetWidth <= 0 || el.offsetHeight <= 0) return false;
        const r = el.getBoundingClientRect();
        return r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
    };

    // Priority 1: LinkedIn-specific
    for (const el of document.querySelectorAll('button.jobs-apply-button, button[data-control-name="apply"], a.jobs-apply-button')) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (!isVisible(el)) continue;
        const rect = el.getBoundingClientRect();
        results.push({ tag: el.tagName, text: (el.textContent || '').trim().slice(0,50), x: rect.left + rect.width/2, y: rect.top + rect.height/2, href: el.getAttribute('href') || '' });
    }

    // Priority 2: buttons, links, inputs (interactive elements only)
    for (const el of document.querySelectorAll('button, a, input[type=button], input[type=submit]')) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (!isVisible(el)) continue;
        const text = (el.textContent || el.value || '').trim();
        if (!text || text.length > 60) continue;
        if (!patterns.some(p => p.test(text))) continue;
        const rect = el.getBoundingClientRect();
        results.push({ tag: el.tagName, text: text.slice(0,50), x: rect.left + rect.width/2, y: rect.top + rect.height/2, href: el.getAttribute('href') || '' });
    }

    // Priority 3: short spans with apply text (only if no button/link found)
    if (results.length === 0) {
        for (const el of document.querySelectorAll('span')) {
            if (seen.has(el)) continue;
            if (!isVisible(el)) continue;
            const text = (el.textContent || '').trim();
            if (!text || text.length > 30) continue;
            if (!patterns.some(p => p.test(text))) continue;
            if (el.closest('button, a, input')) continue;
            const rect = el.getBoundingClientRect();
            results.push({ tag: el.tagName, text: text.slice(0,50), x: rect.left + rect.width/2, y: rect.top + rect.height/2, href: '' });
        }
    }

    return results;
}
"""

_FIND_SUBMIT_BUTTON_JS = """
(containerSelector = '') => {
    const root = containerSelector ? document.querySelector(containerSelector) : document;
    if (!root) return null;
    const candidates = root.querySelectorAll('button, a, input[type=submit], input[type=button]');
    const patterns = [/submit/i, /next/i, /continue/i, /review/i, /send/i, /enviar/i, /avançar/i, /avançar/i, /pr[oó]ximo/i, /concluir/i, /finalizar/i, /salvar/i, /candidatar/i];
    for (const el of candidates) {
        const text = (el.textContent || el.value || '').trim();
        if (patterns.some(p => p.test(text)) && el.offsetWidth > 0 && el.offsetHeight > 0) {
            const rect = el.getBoundingClientRect();
            return { tag: el.tagName, text: text.slice(0, 50), x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
        }
    }
    return null;
}
"""
